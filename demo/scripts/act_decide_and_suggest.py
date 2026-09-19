"""Demo Act layer — reuses the ACTUAL, fixed research components directly:
  - act/ilp-engine/java_statement_extractor.py (Campbell-rule approximation,
    deep variable detection, brace-balancing snippet rendering)
  - act/ilp-engine/extract_method.py (the real PuLP ILP solver, with the
    smallest-sufficient-extraction tie-breaker)
This is NOT a separate simplified demo reimplementation — it is the same
code that produced the validated PR #1719 result, run against a local file
instead of one fetched from GitHub (no network fetch needed here, since the
demo file already exists locally).

Runs when EITHER of two independent signals fires:
  1. analyze_predict.py's ML prediction requested a refactoring suggestion
     (risk_score >= WARNING_THRESHOLD) — same gating as the real pipeline
     (Methodology §3.4.3: "refactoring proposals were generated only when
     the classifier's predicted probability exceeded a configurable
     threshold").
  2. The MEASURED complexity_before already exceeds the Act layer's own
     per-method ceiling (matches SonarQube's own S3776 rule, 15) - i.e.
     the code is deterministically over the line regardless of what any
     predictive model estimates.
These are deliberately kept separate rather than collapsed into one gate:
Analyze's prediction is the model's genuine best estimate given ITS
training distribution (real historical PRs, where the typical touched
file already carries ~180 points of pre-existing complexity - see
sense/scripts/03_build_feature_table.py's docstring); this demo's single
freshly-written method sits at a very different scale, and a synthetic
"brand new file" PR has no real pre-existing target-branch baseline for
complexity_before to represent in the first place. A model correctly NOT
flagging that scenario as unusually risky is not a bug - it's an honest
reflection of what the model learned. But "the model didn't rate this as
unusually risky relative to its training data" and "this method needs
refactoring" are two different questions, and the second one already has
a deterministic, SonarQube-grounded answer independent of any prediction.
The result records WHICH signal(s) fired (see "trigger_reasons") so this
distinction stays visible rather than being silently collapsed.

Since this is a brand-new file (the whole demo "PR" is new code), every line
is treated as part of the diff — so the method-selection logic correctly
reports was_touched_by_pr=True, same honest flagging as the main pipeline,
here trivially true rather than requiring an actual base/head diff.

Usage:
    python act_decide_and_suggest.py --version before
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPTS_DIR.parent
ROOT = DEMO_DIR.parent  # ppch-framework/
ILP_ENGINE_DIR = ROOT / "act" / "ilp-engine"
sys.path.insert(0, str(ILP_ENGINE_DIR))

from extract_method import solve_extract_method  # noqa: E402
from java_statement_extractor import most_complex_method, render_extraction_suggestion  # noqa: E402

# Matches SonarQube's own S3776 per-method cognitive-complexity rule - the
# same real, deterministic ceiling used throughout act/ (extract_method.py's
# default complexity_threshold, act/refactor_file.py's default --threshold).
ACT_LAYER_COMPLEXITY_THRESHOLD = 15.0


def project_dir_for(version: str) -> Path:
    return DEMO_DIR / f"java_project_{version}"


def generate_suggestion(version: str, target_file: str = "PricingEngine.java") -> dict:
    analyze_result_path = DEMO_DIR / "results" / version / "analyze_result.json"
    if not analyze_result_path.exists():
        raise RuntimeError(f"{analyze_result_path} not found — run analyze_predict.py --version {version} first.")
    analyze_result = json.loads(analyze_result_path.read_text(encoding="utf-8"))

    complexity_before = analyze_result["features"]["complexity_before"]
    ml_triggered = analyze_result["refactoring_suggestion_requested"]
    complexity_triggered = complexity_before > ACT_LAYER_COMPLEXITY_THRESHOLD

    trigger_reasons = []
    if ml_triggered:
        trigger_reasons.append(
            f"Analyze layer: risk_score {analyze_result['risk_score']:.3f} >= warning threshold"
        )
    if complexity_triggered:
        trigger_reasons.append(
            f"Act layer: measured complexity_before {complexity_before:.1f} > "
            f"per-method threshold {ACT_LAYER_COMPLEXITY_THRESHOLD}"
        )

    if not trigger_reasons:
        return {
            "status": "not_requested",
            "reason": (
                f"risk_score {analyze_result['risk_score']:.3f} below warning threshold, and "
                f"complexity_before {complexity_before:.1f} at or under the Act layer's own "
                f"per-method threshold ({ACT_LAYER_COMPLEXITY_THRESHOLD})"
            ),
        }

    file_path = project_dir_for(version) / target_file
    source_text = file_path.read_text(encoding="utf-8")

    # This entire file is new code (the demo "PR" adds it), so every line
    # counts as part of the diff - same honest was_touched_by_pr flagging as
    # the main pipeline, just trivially true here rather than requiring an
    # actual base/head fetch and comparison.
    all_lines_changed = set(range(1, len(source_text.splitlines()) + 1))

    result = most_complex_method(source_text, all_lines_changed)
    if result is None:
        return {"status": "extraction_failed", "reason": "no_parseable_methods_found"}

    method_name, statements, total_complexity, meta, method_start_line, was_touched, type_map = result

    solver_result = solve_extract_method(statements)
    solver_result["source_file"] = target_file
    solver_result["method_name"] = method_name
    solver_result["method_start_line"] = method_start_line
    solver_result["was_touched_by_pr"] = was_touched
    solver_result["approximate_method_complexity"] = total_complexity
    solver_result["trigger_reasons"] = trigger_reasons
    solver_result["note"] = (
        "approximate_method_complexity is this framework's own reproduction of "
        "Campbell's (2018) rules, not SonarQube's proprietary engine — the "
        "complexity_before figure used for the risk PREDICTION above is the real "
        "SonarQube measurement; this number is only used to select and score the "
        "extraction candidate."
    )

    for reason in trigger_reasons:
        print(f"Triggered by: {reason}")

    if solver_result.get("status") in ("optimal", "threshold_unreachable"):
        suggestion = render_extraction_suggestion(
            source_text, method_name, statements, meta,
            solver_result["selected_statement_indices"], type_map,
        )
        solver_result["suggestion"] = suggestion
        if solver_result["status"] == "threshold_unreachable":
            print(f"NOTE: no extraction got remaining complexity under the "
                  f"{solver_result.get('complexity_threshold')} threshold — showing the best-effort suggestion.")
        print(f"Target method: {method_name} (approx. complexity {total_complexity:.1f})")
        print(f"Selected {len(solver_result['selected_statement_indices'])} statements for extraction")
        print(f"Remaining complexity after extraction: {solver_result['remaining_complexity']:.1f}")
        if suggestion.get("rendered"):
            lo, hi = suggestion["source_line_range"]
            print(f"Suggested extraction: lines {lo}-{hi}, parameters: {suggestion['inferred_parameters']}")
            print(f"Return-value handling: {suggestion['return_analysis']['status']}")
            print(f"Safe to auto-apply: {suggestion['safe_to_auto_apply']}")
    else:
        print(f"ILP status: {solver_result.get('status')}")

    return solver_result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["before", "after"], default="before")
    parser.add_argument("--target-file", default="PricingEngine.java")
    args = parser.parse_args()

    result = generate_suggestion(args.version, args.target_file)

    results_dir = DEMO_DIR / "results" / args.version
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "act_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {results_dir / 'act_result.json'}")


if __name__ == "__main__":
    main()
