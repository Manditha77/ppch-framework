"""Real per-method SonarQube verification for the Act layer's PR-level
advisory suggestions.

pipeline.py deliberately never applies its own suggestions or re-scans -
it's advisory-only by design (see its own module docstring: "This report
... does not modify source code"). This is a SEPARATE, opt-in step that
answers a different question: "if a developer HAD applied this suggestion
at PR submission time, would it have actually worked?" - fetching the same
real historical PR source pipeline.py already generates a suggestion for,
applying that suggestion in memory (refactor/apply_extraction.py's pure-
text core), and checking the result against a REAL SonarQube scan's own
per-method S3776 rule (act/sonarqube_verify.py) - not just this
framework's own Campbell-rule approximation, and not just a file-level
aggregate (see sense/scripts/03_build_feature_table.py's docstring for why
file-level aggregates are misleading once a file has more than one
method).

This is the rigorous half of the "Hybrid" approach: the bulk 500-PR
Analyze-layer training uses the faster delta-based label (no per-method
re-scan needed for 500 PRs - that would roughly double the Sense-phase
scan budget), while these specific Act-layer case-study PRs get fully
verified against real SonarQube per-method measurements.

Usage:
    python act/github-action/verify_pr_suggestion.py
    python act/github-action/verify_pr_suggestion.py --pr-number 1719
"""

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[1]  # ppch-framework/
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(ROOT / "act" / "ilp-engine"))
sys.path.insert(0, str(ROOT / "act"))
sys.path.insert(0, str(ROOT / "refactor"))

from pipeline import (  # noqa: E402
    PROCESSED_DIR, GITHUB_OWNER, GITHUB_REPO,
    load_models, predict_risk, build_intervention, generate_refactoring_suggestion,
    load_scan_result, is_test_file,
)
from fetch_source import fetch_file_at_commit  # noqa: E402
from sonarqube_verify import verify_with_sonarqube  # noqa: E402
from multi_file_refactor import refactor_all_files  # noqa: E402


def verify_pr(number: int) -> dict:
    feature_path = PROCESSED_DIR / f"pr_{number}" / "feature_table.json"
    if not feature_path.exists():
        return {"pr_number": number, "status": "skipped", "reason": "no_feature_table"}
    feature_row = json.loads(feature_path.read_text(encoding="utf-8"))

    models = load_models()
    prediction = predict_risk(models, feature_row)
    intervention = build_intervention(feature_row, prediction)

    result = {
        "pr_number": number,
        "risk_score": intervention["risk_score"],
        "action": intervention["action"],
        "refactoring_suggestion_requested": intervention["refactoring_suggestion_requested"],
    }
    if not intervention["refactoring_suggestion_requested"]:
        result["status"] = "not_requested"
        return result

    # generate_refactoring_suggestion() is still used here to identify WHICH
    # file/method the Act layer would target first (matching pipeline.py's
    # own advisory report) and to confirm a safe suggestion exists at all -
    # but the actual apply+verify step below uses refactor_source (the same
    # iterative engine act/refactor_file.py uses standalone), since a single
    # extraction pass is often nowhere near enough for real legacy methods
    # (some real commons-lang methods flagged here run to 50-80+ complexity -
    # matches what the demo files (PricingEngine, ShippingCalculator) also
    # needed multiple passes for, just at a larger scale).
    ilp = generate_refactoring_suggestion(number)
    result["ilp_status"] = ilp.get("status")
    if ilp.get("status") not in ("optimal", "threshold_unreachable"):
        result["status"] = "no_suggestion"
        result["reason"] = ilp.get("reason")
        return result

    suggestion = ilp.get("suggestion")
    if not suggestion or not suggestion.get("rendered") or not suggestion.get("safe_to_auto_apply"):
        result["status"] = "unsafe_suggestion"
        result["caveat"] = (suggestion or {}).get("caveat")
        return result

    scan_record = load_scan_result(number)
    file_path = ilp["source_file"]

    # Multi-file coverage (added 2026-09-23 - see multi_file_refactor.py's
    # own module docstring for the full motivation): the PRIMARY file
    # (file_path, what the code below always treated as "the" file) is
    # always processed FIRST and always included, so its own result is
    # unchanged from before this change - regression-verified, not just
    # true by construction. Every OTHER non-test Java file this PR also
    # touched now gets the SAME real refactor + real SonarQube verification,
    # instead of being silently never looked at.
    candidate_files = [f for f in scan_record.get("changed_java_files", []) if not is_test_file(f)]

    def fetch_fn(fp: str) -> str:
        return fetch_file_at_commit(GITHUB_OWNER, GITHUB_REPO, scan_record["head_sha"], fp)

    try:
        multi = refactor_all_files(candidate_files, file_path, fetch_fn,
                                    threshold=15.0, max_iterations=8, safety_margin=2.0)
    except Exception as exc:  # noqa: BLE001 — primary-file fetch failure, same as the old code's behavior
        result["status"] = "fetch_failed"
        result["error"] = str(exc)
        return result

    primary = multi["per_file"].get(file_path)
    if primary is None or primary.get("status") != "ok":
        result["status"] = "fetch_failed"
        result["error"] = (primary or {}).get("error", "primary file not processed")
        return result

    # --- Fields below are UNCHANGED in meaning from before this change:
    # they describe the PRIMARY file only, exactly as they always did. ---
    extractions = [
        step for step in primary["log"]
        if step["outcome"] in ("extracted", "branch_split_applied")
    ]
    result["status"] = "verified"
    result["method_name"] = ilp.get("method_name")
    result["extractions_applied"] = len(extractions)
    result["still_over_threshold_after"] = primary["still_over_threshold"]
    result["sonarqube"] = verify_with_sonarqube(Path(file_path).name, primary["before_text"], primary["after_text"])
    result["_original_source"] = primary["before_text"]
    result["_refactored_source"] = primary["after_text"]
    result["_filename"] = Path(file_path).name

    # --- NEW: every additional file, real SonarQube-verified the same way. ---
    additional_results = []
    additional_file_texts = {}  # file_path -> (before, after, filename) for main() to write out
    for fp in multi["files_analyzed"]:
        if fp == file_path:
            continue
        entry = multi["per_file"].get(fp)
        if not entry or entry.get("status") != "ok" or entry.get("extractions_applied", 0) == 0:
            continue  # nothing genuinely applied to this file - no point re-scanning it
        sq = verify_with_sonarqube(Path(fp).name, entry["before_text"], entry["after_text"], quiet=True)
        additional_results.append({
            "file": fp,
            "extractions_applied": entry["extractions_applied"],
            "still_over_threshold_after": entry["still_over_threshold"],
            "sonarqube": sq,
        })
        additional_file_texts[fp] = (entry["before_text"], entry["after_text"], Path(fp).name)

    result["additional_files_refactored"] = additional_results
    result["total_extractions_applied_all_files"] = (
        result["extractions_applied"] + sum(r["extractions_applied"] for r in additional_results)
    )
    result["files_touched_by_pr"] = len(candidate_files)
    result["files_analyzed"] = multi["files_analyzed"]
    result["files_skipped_due_to_cap"] = multi["files_skipped_due_to_cap"]
    result["_additional_file_texts"] = additional_file_texts
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr-number", type=int, nargs="+", default=[1525, 1324, 1719])
    args = parser.parse_args()

    all_results = []
    for number in args.pr_number:
        print(f"\n=== PR #{number} ===")
        result = verify_pr(number)
        print(f"  status: {result['status']}")
        if result["status"] == "verified":
            sq = result["sonarqube"]
            print(f"  target method: {result['method_name']} "
                  f"({result['extractions_applied']} extraction(s) applied)")
            if sq.get("before") is not None and sq.get("after") is not None:
                print(f"  SonarQube file-total: {sq['before']} -> {sq['after']}")
                if sq.get("after_issues"):
                    print(f"  STILL flagged over-complexity after refactoring: {len(sq['after_issues'])} method(s)")
                    for issue in sq["after_issues"]:
                        print(f"    - line {issue['line']}: {issue['message']}")
                else:
                    print("  SonarQube confirms: clean after refactoring.")
            print(f"  PR touched {result['files_touched_by_pr']} non-test Java file(s); "
                  f"{len(result['files_analyzed'])} analyzed"
                  + (f", {len(result['files_skipped_due_to_cap'])} skipped (cap)"
                     if result['files_skipped_due_to_cap'] else ""))
            for extra in result["additional_files_refactored"]:
                esq = extra["sonarqube"]
                line = f"  + {extra['file']}: {extra['extractions_applied']} extraction(s)"
                if esq.get("before") is not None and esq.get("after") is not None:
                    line += f", SonarQube {esq['before']} -> {esq['after']}"
                print(line)
            print(f"  TOTAL extractions applied across all analyzed files: "
                  f"{result['total_extractions_applied_all_files']}")
        out_dir = PROCESSED_DIR / f"pr_{number}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Pop the source blobs out before writing the JSON (they'd bloat it
        # and duplicate what's now in the .java files below) - written to
        # real, openable files instead.
        original_source = result.pop("_original_source", None)
        refactored_source = result.pop("_refactored_source", None)
        filename = result.pop("_filename", None)
        additional_texts = result.pop("_additional_file_texts", {})
        if original_source is not None:
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            original_path = out_dir / f"{stem}_before{suffix}"
            refactored_path = out_dir / f"{stem}_after{suffix}"
            original_path.write_text(original_source, encoding="utf-8")
            refactored_path.write_text(refactored_source, encoding="utf-8")
            result["original_file"] = str(original_path)
            result["refactored_file"] = str(refactored_path)
            print(f"  Wrote {original_path}")
            print(f"  Wrote {refactored_path}")

        # Same, for every additional file that had a real extraction applied.
        for fp, (before_text, after_text, fname) in additional_texts.items():
            stem = Path(fname).stem
            suffix = Path(fname).suffix
            before_path = out_dir / f"{stem}_before{suffix}"
            after_path = out_dir / f"{stem}_after{suffix}"
            before_path.write_text(before_text, encoding="utf-8")
            after_path.write_text(after_text, encoding="utf-8")
            print(f"  Wrote {before_path}")
            print(f"  Wrote {after_path}")

        all_results.append(result)
        (out_dir / "suggestion_verification.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

    summary_path = ROOT / "evaluation" / "pr_suggestion_verification_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(all_results, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {summary_path}")


if __name__ == "__main__":
    main()
