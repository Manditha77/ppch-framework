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
    load_scan_result,
)
from fetch_source import fetch_file_at_commit  # noqa: E402
from sonarqube_verify import verify_with_sonarqube  # noqa: E402
from refactor_file import refactor_source  # noqa: E402


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
    try:
        head_source = fetch_file_at_commit(GITHUB_OWNER, GITHUB_REPO, scan_record["head_sha"], file_path)
    except Exception as exc:  # noqa: BLE001
        result["status"] = "fetch_failed"
        result["error"] = str(exc)
        return result

    refactor_result = refactor_source(head_source, threshold=15.0, max_iterations=8, safety_margin=2.0)
    extractions = [step for step in refactor_result["log"] if step["outcome"] == "extracted"]

    result["status"] = "verified"
    result["method_name"] = ilp.get("method_name")
    result["extractions_applied"] = len(extractions)
    result["still_over_threshold_after"] = refactor_result["still_over_threshold"]
    result["sonarqube"] = verify_with_sonarqube(Path(file_path).name, head_source, refactor_result["final_text"])
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
        all_results.append(result)
        out_dir = PROCESSED_DIR / f"pr_{number}"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "suggestion_verification.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )

    summary_path = ROOT / "evaluation" / "pr_suggestion_verification_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(all_results, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {summary_path}")


if __name__ == "__main__":
    main()
