"""Standalone, PR-independent Act-layer entry point.

Give it ANY Java file (or a directory of .java files) and it identifies
every method whose cognitive complexity exceeds a threshold and refactors
it using the same ILP Extract-Method engine used throughout the framework
(act/ilp-engine/) - no PR data, no GitHub, no ML risk prediction involved.

This is deliberately separate from act/github-action/pipeline.py, which IS
PR/prediction-driven per the dissertation's Sense-Analyze-Act architecture
(the Act layer there is triggered by the Analyze layer's risk_score, and
its post_hoc_validation section is scoped to historical PR data). This
module answers a different, narrower question: "does the Act layer's
refactoring mechanism work well on its own, for any complex Java code,
independent of the PR pipeline?" - useful for demonstrating the mechanism
directly, and for spot-checking it against code the historical PR sample
doesn't happen to cover.

Iterates per method: try an extraction, reparse, check if still over
threshold, try again - up to --max-iterations. One extraction is often not
enough on its own (both worked dissertation examples - PricingEngine.java
and ShippingCalculator.java - needed this), so a single pass would
under-sell what the mechanism can actually do.

By default measures complexity via the framework's own Campbell-rule
reproduction (java_statement_extractor.py) - the SAME numbers the ILP
solver itself optimizes against - so this runs anywhere with just Python,
no SonarQube/Docker setup required to demo it to someone. Pass
--verify-sonarqube to additionally confirm the before/after numbers
against a real SonarQube scan of an isolated copy of just the target file
(requires SONAR_TOKEN/SONAR_HOST_URL in .env and sonar-scanner on PATH,
same setup as the rest of this project).

Usage:
    python act/refactor_file.py path/to/File.java
    python act/refactor_file.py path/to/src/ --threshold 15
    python act/refactor_file.py path/to/File.java --dry-run
    python act/refactor_file.py path/to/File.java --verify-sonarqube
"""

import argparse
import json
import sys
from pathlib import Path

import javalang

THIS_FILE = Path(__file__).resolve()
ROOT = THIS_FILE.parents[1]  # ppch-framework/
sys.path.insert(0, str(THIS_FILE.parent / "ilp-engine"))
sys.path.insert(0, str(ROOT / "refactor"))

from extract_method import solve_extract_method  # noqa: E402
from java_statement_extractor import all_methods_by_complexity, render_extraction_suggestion  # noqa: E402
from apply_extraction import apply_extraction_to_text  # noqa: E402
from sonarqube_verify import verify_with_sonarqube  # noqa: E402

DEFAULT_THRESHOLD = 15.0
DEFAULT_MAX_ITERATIONS = 8


def _existing_method_names(source_text: str) -> set:
    tree = javalang.parse.parse(source_text)
    return {node.name for _, node in tree.filter(javalang.tree.MethodDeclaration)}


def _disambiguate_suggestion(suggestion: dict, existing_names: set) -> dict:
    """A method extracted from twice across iterations (common - see
    module docstring) would otherwise get the SAME generated name both
    times (`{method}Extracted`), colliding with the helper the first
    extraction already inserted - a duplicate-method compile error. Append
    a numeric suffix until the name is free, rewriting the three
    already-rendered text fields that embed it."""
    base_name = suggestion["suggested_method_name"]
    name = base_name
    counter = 2
    while name in existing_names:
        name = f"{base_name}{counter}"
        counter += 1
    if name == base_name:
        return suggestion
    suggestion = dict(suggestion)
    suggestion["suggested_method_name"] = name
    suggestion["suggested_signature"] = suggestion["suggested_signature"].replace(base_name, name, 1)
    suggestion["full_snippet"] = suggestion["full_snippet"].replace(base_name, name, 1)
    suggestion["call_site_replacement"] = suggestion["call_site_replacement"].replace(base_name, name, 1)
    return suggestion


def refactor_source(source_text: str, threshold: float, max_iterations: int, safety_margin: float = 2.0) -> dict:
    """Iteratively refactor `source_text` until no method exceeds
    `threshold` or no further safe progress can be made.

    `safety_margin`: the framework's own Campbell-rule complexity
    reproduction is an APPROXIMATION of SonarQube's actual computation (see
    java_statement_extractor.py's module docstring) - verified in practice
    to be off by a point or two on real code (a method this tool measured
    at exactly 15.0 was independently confirmed by SonarQube's own S3776
    rule to actually be 16). Targeting `threshold - safety_margin`
    internally (default margin 2.0) means the tool keeps refactoring until
    it has enough headroom that the gap is very unlikely to leave the
    REAL, SonarQube-measured complexity still over the user's actual
    threshold. Use --verify-sonarqube for a real check rather than relying
    on the margin alone."""
    effective_threshold = threshold - safety_margin
    stuck_methods = set()
    log = []

    # Minimum genuine reduction (in complexity points) the newly created
    # method's own complexity must fall below the original method's
    # complexity to count as "productive" - see the non-productive-
    # extraction guard below. 0.5 tolerates float noise while still catching
    # "effectively zero improvement" (Campbell/SonarQube complexity
    # accumulates in +1 increments, so any REAL improvement is at least ~1.0).
    MIN_PRODUCTIVE_REDUCTION = 0.5

    for iteration in range(max_iterations):
        methods = all_methods_by_complexity(source_text)
        candidates = [m for m in methods if m[2] > effective_threshold and m[0] not in stuck_methods]
        if not candidates:
            break

        name, statements, total, meta, start_line, type_map = candidates[0]
        solver_result = solve_extract_method(statements, complexity_threshold=effective_threshold)

        if solver_result["status"] == "infeasible" or not solver_result.get("selected_statement_indices"):
            stuck_methods.add(name)
            log.append({
                "iteration": iteration, "method": name, "outcome": "no_extraction_found",
                "complexity_before": total,
            })
            continue

        suggestion = render_extraction_suggestion(
            source_text, name, statements, meta, solver_result["selected_statement_indices"], type_map,
        )
        if not suggestion.get("rendered") or not suggestion.get("safe_to_auto_apply"):
            stuck_methods.add(name)
            log.append({
                "iteration": iteration, "method": name, "outcome": "unsafe_suggestion",
                "complexity_before": total,
                "reason": suggestion.get("caveat") or suggestion.get("reason"),
            })
            continue

        suggestion = _disambiguate_suggestion(suggestion, _existing_method_names(source_text))
        act_result = {
            "status": solver_result["status"],
            "method_start_line": start_line,
            "suggestion": suggestion,
        }
        try:
            new_text, info = apply_extraction_to_text(source_text, act_result)
        except RuntimeError as exc:
            stuck_methods.add(name)
            log.append({"iteration": iteration, "method": name, "outcome": "apply_failed", "error": str(exc)})
            continue

        # Non-productive-extraction guard: a VALID, "optimal"-status
        # extraction can still fail to genuinely reduce complexity - it
        # happens when a method's complexity comes from several separate,
        # FLAT sibling constructs (guard-clause sequences) rather than one
        # deep nested tree. The ILP's "at most one independent root"
        # constraint (a deliberate fix for an earlier invalid-extraction
        # bug - see extract_method.py) then has no choice but to move the
        # WHOLE flat sibling group as one lump, and that lump - having the
        # same internal shape - measures at essentially the SAME complexity
        # once it's independently re-parsed as its own method. Nothing was
        # actually reduced, just relocated under a new name - and left
        # unchecked, this repeats identically every iteration until the
        # iteration cap, producing a chain of pointless single-line
        # delegating wrapper methods (confirmed on a real PR: `random` in
        # RandomStringUtils.java chained 6 levels deep, 40.0 complexity
        # measured identically at every level).
        #
        # NOT the right metric here: FILE-WIDE total complexity before vs.
        # after. A first attempt at this guard used that and immediately
        # broke a genuinely-working, previously-verified case
        # (getCanonicalName in PR #1422): SonarQube's rule flags complexity
        # PER METHOD, not as a file-wide sum - splitting one over-threshold
        # method into two methods that are EACH individually under the
        # ceiling is a completely valid win even when the file-wide total
        # doesn't move at all (the complexity didn't vanish, it just landed
        # somewhere that's no longer flagged). Checking the file total would
        # reject that real, already-SonarQube-confirmed win.
        #
        # The metric that actually distinguishes the two cases: compare the
        # NEWLY CREATED method's own complexity against what the ORIGINAL
        # method (the one being extracted FROM) measured at, just before
        # this step. A genuine partial extraction, or one that benefits from
        # nesting-depth reduction, always leaves the new method with
        # NOTICEABLY LESS complexity than the original had (nesting inside a
        # fresh top-level method resets, and/or only part of the original
        # was moved). A flat/wide structure with no nesting to shed and
        # nothing left worth keeping behind hands the ENTIRE original
        # complexity to the new method essentially unchanged - THAT's the
        # signal to catch, not the file-wide total.
        new_method_name = info["suggested_method_name"]
        new_method_complexity = next(
            (m[2] for m in all_methods_by_complexity(new_text) if m[0] == new_method_name),
            None,
        )
        if new_method_complexity is not None and new_method_complexity >= total - MIN_PRODUCTIVE_REDUCTION:
            stuck_methods.add(name)
            log.append({
                "iteration": iteration, "method": name, "outcome": "non_productive_extraction",
                "complexity_before": total,
                "new_method": new_method_name,
                "new_method_complexity": new_method_complexity,
                "reason": (
                    "This extraction is valid Java but did not genuinely reduce complexity - "
                    f"the newly created method ({new_method_name}, complexity "
                    f"{new_method_complexity:.1f}) inherited essentially the SAME complexity "
                    f"the original method had ({total:.1f}), meaning a flat sequence of "
                    "sibling constructs (not a deep nested tree) was relocated wholesale, "
                    "not genuinely reduced. Discarded rather than applied."
                ),
            })
            continue

        source_text = new_text
        log.append({
            "iteration": iteration, "method": name, "outcome": "extracted",
            "complexity_before": total,
            "remaining_complexity": solver_result["remaining_complexity"],
            "solver_status": solver_result["status"],
            "new_method": info["suggested_method_name"],
        })

    final_methods = all_methods_by_complexity(source_text)
    still_over = [{"method": m[0], "complexity": m[2]} for m in final_methods if m[2] > effective_threshold]
    return {"final_text": source_text, "log": log, "still_over_threshold": still_over}


def refactor_file(path: Path, threshold: float, max_iterations: int,
                   output: Path = None, dry_run: bool = False, safety_margin: float = 2.0) -> dict:
    source_text = path.read_text(encoding="utf-8")
    before_methods = all_methods_by_complexity(source_text)
    before_report = [{"method": m[0], "complexity": m[2]} for m in before_methods]

    result = refactor_source(source_text, threshold, max_iterations, safety_margin=safety_margin)

    report = {
        "file": str(path),
        "threshold": threshold,
        "before": before_report,
        "iterations": result["log"],
        "still_over_threshold_after": result["still_over_threshold"],
        "changed": result["final_text"] != source_text,
        "final_text": result["final_text"],
    }

    if report["changed"] and not dry_run:
        out_path = output or path.with_name(f"{path.stem}.refactored{path.suffix}")
        out_path.write_text(result["final_text"], encoding="utf-8")
        report["output_file"] = str(out_path)

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="A .java file, or a directory to scan recursively for .java files")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--safety-margin", type=float, default=2.0,
                         help="Internally target threshold minus this margin, to compensate for "
                              "this tool's complexity estimate running ~1-2 points below SonarQube's "
                              "own measurement on real code (verified empirically - see refactor_source's "
                              "docstring). Use --verify-sonarqube for a real check rather than the margin alone.")
    parser.add_argument("--output", help="Output path (single-file mode only). "
                                          "Defaults to <name>.refactored.java next to the input.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would change without writing any file.")
    parser.add_argument("--verify-sonarqube", action="store_true",
                         help="Also confirm before/after complexity with a real SonarQube scan.")
    args = parser.parse_args()

    input_path = Path(args.path)
    java_files = [input_path] if input_path.is_file() else sorted(input_path.rglob("*.java"))
    if not java_files:
        print(f"No .java files found at {input_path}")
        return

    all_reports = []
    for java_file in java_files:
        print(f"\n=== {java_file} ===")
        try:
            report = refactor_file(
                java_file, args.threshold, args.max_iterations,
                output=Path(args.output) if args.output and len(java_files) == 1 else None,
                dry_run=args.dry_run, safety_margin=args.safety_margin,
            )
        except Exception as exc:
            print(f"  ERROR: {exc}")
            all_reports.append({"file": str(java_file), "error": str(exc)})
            continue

        for entry in report["before"]:
            flag = " <-- over threshold" if entry["complexity"] > args.threshold else ""
            print(f"  {entry['method']}: complexity {entry['complexity']:.1f}{flag}")

        for step in report["iterations"]:
            if step["outcome"] == "extracted":
                print(f"    -> extracted from {step['method']}: "
                      f"{step['complexity_before']:.1f} -> ~{step['remaining_complexity']:.1f} remaining "
                      f"(new method: {step['new_method']}, solver status: {step['solver_status']})")
            else:
                print(f"    -> {step['method']}: gave up ({step['outcome']})")

        if report["still_over_threshold_after"]:
            names = ", ".join(f"{e['method']} ({e['complexity']:.1f})" for e in report["still_over_threshold_after"])
            print(f"  Still over threshold after refactoring: {names}")
        elif report["before"]:
            print("  All methods now at or under threshold.")

        if report.get("output_file"):
            print(f"  Wrote {report['output_file']}")
        elif report["changed"] and args.dry_run:
            print("  (dry run - no file written)")
        elif not report["changed"]:
            print("  No changes needed.")

        if args.verify_sonarqube and report["changed"]:
            original_text = java_file.read_text(encoding="utf-8")
            verify_with_sonarqube(java_file.name, original_text, report["final_text"])

        report.pop("final_text", None)
        all_reports.append(report)

    if len(java_files) > 1:
        summary_path = input_path / "refactor_file_report.json"
        summary_path.write_text(json.dumps(all_reports, indent=2) + "\n", encoding="utf-8")
        print(f"\nWrote {summary_path}")


if __name__ == "__main__":
    main()
