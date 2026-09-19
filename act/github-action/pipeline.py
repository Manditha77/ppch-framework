"""Phase III — Prediction-driven Act-layer demonstration for selected PRs.

FIX vs. the previous version: the intervention decision here is driven by the
ANALYZE layer's PREDICTED probability, computed only from pre-submission
features — exactly what would be available in real use, at the moment a PR
is opened, before its actual complexity is known.

The previously measured, post-submission complexity values (from the Sense
layer's SonarQube scan) are still loaded, but strictly as POST-HOC VALIDATION
evidence: after the prediction and intervention decision are made, we check
whether the prediction matched what SonarQube actually measured. This mirrors
how the framework would behave in real deployment (predict blind, validate
after merge) and is what makes this a genuine test of the predict-then-
intervene design, not just a report of already-known facts.
"""

import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ilp-engine"))
from extract_method import solve_extract_method
from java_statement_extractor import most_complex_method, render_extraction_suggestion
from fetch_source import fetch_file_at_commit
from diff_utils import changed_line_numbers

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
MODEL_DIR = ROOT / "analyze" / "models"
SCAN_RESULTS_PATH = ROOT / "sense" / "data" / "raw" / "pilot_scan_results.jsonl"

# TODO: parameterize once Kafka/Dubbo are added to the Sense-phase sample.
GITHUB_OWNER = "apache"
GITHUB_REPO = "commons-lang"

FEATURES = [
    "additions", "deletions", "changed_files", "changed_java_files", "commits",
    "comments", "review_comments", "body_character_count", "title_word_count",
    # Legitimate pre-submission signal: the TARGET BRANCH's complexity before this
    # PR's changes are applied. In real use this comes from scanning the base
    # branch independently of the incoming PR (even continuously) - it is not
    # derived from this PR's outcome, unlike complexity_after/delta below.
    "complexity_before",
]

# Risk-score bands for the intervention decision. risk_score is the average of
# the two models' predicted probabilities of exceeding the complexity threshold.
WARNING_THRESHOLD = 0.7
NOTICE_THRESHOLD = 0.4


def load_scan_result(pr_number: int) -> dict | None:
    """Look up a PR's changed_java_files (the actual list of paths, not just
    the count) and head_sha from the Sense layer's raw scan results."""
    if not SCAN_RESULTS_PATH.exists():
        return None
    with open(SCAN_RESULTS_PATH, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            if record.get("number") == pr_number:
                return record
    return None


def is_test_file(path: str) -> bool:
    return "/test/" in path or path.startswith("test/")


def generate_refactoring_suggestion(pr_number: int) -> dict:
    """Fetch the real source of the PR's touched production files, find the
    method this PR actually modified with the highest complexity (falling
    back to the file's single most complex method only if no touched method
    can be identified - see java_statement_extractor.most_complex_method's
    diff-scoping fix), and run the ILP Extract Method solver on it. Falls
    back to a clear diagnostic status on any failure (network, parse error,
    no suitable file) rather than crashing the whole pipeline."""
    scan_record = load_scan_result(pr_number)
    if scan_record is None:
        return {"status": "skipped", "reason": "no_scan_record_found_for_pr"}

    candidate_files = [f for f in scan_record.get("changed_java_files", []) if not is_test_file(f)]
    if not candidate_files:
        return {"status": "skipped", "reason": "no_non_test_java_files_changed"}

    base_sha = scan_record["base_sha"]
    head_sha = scan_record["head_sha"]
    # (file_path, method_name, statements, total_complexity, meta, source_text, was_touched_by_pr)
    touched_best = None
    fallback_best = None
    fetch_errors = []

    for file_path in candidate_files:
        try:
            head_source = fetch_file_at_commit(GITHUB_OWNER, GITHUB_REPO, head_sha, file_path)
        except Exception as exc:  # network error, file doesn't exist at this commit, etc.
            fetch_errors.append({"file": file_path, "error": str(exc)})
            continue

        changed_lines = None
        try:
            base_source = fetch_file_at_commit(GITHUB_OWNER, GITHUB_REPO, base_sha, file_path)
            changed_lines = changed_line_numbers(base_source, head_source)
        except Exception as exc:
            # File may be new in this PR (no base version) or base fetch failed -
            # not fatal, we just can't scope to the diff for this file and fall
            # back to file-wide selection, clearly flagged via was_touched_by_pr.
            fetch_errors.append({"file": file_path, "error": f"base fetch failed: {exc}"})

        try:
            result = most_complex_method(head_source, changed_lines)
        except Exception as exc:
            fetch_errors.append({"file": file_path, "error": f"parse failed: {exc}"})
            continue
        if result is None:
            continue

        method_name, statements, total_complexity, meta, method_start_line, was_touched, type_map = result
        entry = (file_path, method_name, statements, total_complexity, meta, head_source, was_touched,
                 type_map, method_start_line)

        if was_touched:
            if touched_best is None or total_complexity > touched_best[3]:
                touched_best = entry
        else:
            if fallback_best is None or total_complexity > fallback_best[3]:
                fallback_best = entry

    # Prefer ANY method the PR actually touched over an untouched-but-more-complex
    # one elsewhere in the file - relevance matters more than raw complexity here.
    best = touched_best if touched_best is not None else fallback_best

    if best is None:
        return {
            "status": "extraction_failed",
            "reason": "could_not_parse_any_candidate_file",
            "fetch_errors": fetch_errors,
        }

    file_path, method_name, statements, total_complexity, meta, source_text, was_touched, type_map, \
        method_start_line = best
    solver_result = solve_extract_method(statements)
    solver_result["source_file"] = file_path
    solver_result["method_name"] = method_name
    solver_result["method_start_line"] = method_start_line
    solver_result["was_touched_by_pr"] = was_touched
    solver_result["approximate_method_complexity"] = total_complexity
    solver_result["note"] = (
        "approximate_method_complexity is computed by this framework's own "
        "reproduction of Campbell's (2018) rules, not SonarQube's proprietary "
        "engine — see java_statement_extractor.py for the approximation caveat."
    )
    if not was_touched:
        solver_result["note"] += (
            " WARNING: this method could not be confirmed as part of the PR's actual "
            "diff (base-version fetch or diff comparison failed) - this is the file's "
            "most complex method overall, which may be UNRELATED to what this PR "
            "changed. Treat this suggestion with reduced confidence."
        )

    if solver_result.get("status") in ("optimal", "threshold_unreachable"):
        suggestion = render_extraction_suggestion(
            source_text, method_name, statements, meta,
            solver_result["selected_statement_indices"], type_map,
        )
        solver_result["suggestion"] = suggestion

    return solver_result


def load_models() -> dict:
    return {
        "random_forest": joblib.load(MODEL_DIR / "random_forest.joblib"),
        "xgboost": joblib.load(MODEL_DIR / "xgboost.joblib"),
    }


def predict_risk(models: dict, feature_row: dict) -> dict:
    x = pd.DataFrame([{field: feature_row[field] for field in FEATURES}])
    probabilities = {name: float(model.predict_proba(x)[0, 1]) for name, model in models.items()}
    risk_score = sum(probabilities.values()) / len(probabilities)
    return {"model_probabilities": probabilities, "risk_score": risk_score}


def build_intervention(feature_row: dict, prediction: dict) -> dict:
    risk_score = prediction["risk_score"]

    if risk_score >= WARNING_THRESHOLD:
        action = "complexity_warning_and_refactoring_review"
        message = (
            "PREDICTED high risk of exceeding the cognitive-complexity threshold; "
            "review an Extract Method refactoring before merge."
        )
    elif risk_score >= NOTICE_THRESHOLD:
        action = "complexity_increase_notice"
        message = (
            "PREDICTED moderate risk of a cognitive-complexity increase; "
            "review the modified logic before merging."
        )
    else:
        action = "no_intervention"
        message = "PREDICTED low risk of a cognitive-complexity increase."

    predicted_label = int(risk_score >= 0.5)
    actual_label = feature_row["exceeds_significant_complexity_increase"]

    return {
        "pr_number": feature_row["pr_number"],
        "stage": "predicted_at_submission_time",
        "action": action,
        "message": message,
        "risk_score": risk_score,
        "model_probabilities": prediction["model_probabilities"],
        "warning_threshold": WARNING_THRESHOLD,
        "notice_threshold": NOTICE_THRESHOLD,
        "refactoring_suggestion_requested": risk_score >= WARNING_THRESHOLD,
        "predicted_label": predicted_label,
        "evidence_pre_submission_features": {f: feature_row[f] for f in FEATURES},
        "post_hoc_validation": {
            "note": (
                "The fields below were measured AFTER the PR was scanned by SonarQube "
                "and are used ONLY to check the prediction retrospectively. They were "
                "NOT available to the model at prediction time."
            ),
            "actual_complexity_before": feature_row["complexity_before"],
            "actual_complexity_after": feature_row["complexity_after"],
            "actual_complexity_delta": feature_row["complexity_delta"],
            "actual_label_exceeds_threshold": actual_label,
            "prediction_matched_actual": predicted_label == actual_label,
        },
    }


def write_outputs(payload: dict) -> None:
    output_dir = PROCESSED_DIR / f"pr_{payload['pr_number']}"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_dir / "intervention"
    stem.with_suffix(".json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    pv = payload["post_hoc_validation"]
    match_text = "matched" if pv["prediction_matched_actual"] else "did NOT match"
    ilp = payload["ilp"]
    ilp_lines = [f"- ILP status: `{ilp['status']}`"]
    suggestion_block = []
    if ilp.get("status") in ("optimal", "threshold_unreachable"):
        touched_flag = "yes — confirmed in this PR's diff" if ilp.get("was_touched_by_pr") else \
            "**NO — could not confirm this method is part of the PR's diff, treat with caution**"
        ilp_lines += [
            f"- Target method: `{ilp.get('method_name')}` in `{ilp.get('source_file')}`",
            f"- Method confirmed touched by this PR: {touched_flag}",
            f"- Approximate method complexity: {ilp.get('approximate_method_complexity'):.1f}",
            f"- Suggested extraction: statements {ilp.get('selected_statement_indices')}",
            f"- Remaining complexity after extraction: {ilp.get('remaining_complexity'):.1f} "
            f"(from {ilp.get('original_complexity'):.1f})",
        ]
        suggestion = ilp.get("suggestion")
        if suggestion and suggestion.get("rendered"):
            safe = suggestion.get("safe_to_auto_apply", True)
            safe_flag = "✅ yes" if safe else "⚠️ NO — see caveat below, manual restructuring needed"
            suggestion_block = [
                "",
                "### Suggested extraction (advisory — review before applying)",
                "",
                f"- Source lines {suggestion['source_line_range'][0]}–{suggestion['source_line_range'][1]} "
                f"of `{ilp.get('source_file')}`",
                f"- Return-value handling: `{suggestion['return_analysis']['status']}`",
                f"- Safe to auto-apply: {safe_flag}",
                "",
                "**Ready-to-paste new method:**",
                "",
                "```java",
                suggestion["full_snippet"],
                "```",
                "",
                "**Replace the extracted lines in the original method with:**",
                "",
                "```java",
                suggestion["call_site_replacement"],
                "```",
                "",
                f"*{suggestion['caveat']}*",
            ]
        elif suggestion:
            suggestion_block = ["", f"*Could not render a concrete snippet: {suggestion.get('reason')}*"]
    elif ilp.get("reason"):
        ilp_lines.append(f"- Reason: `{ilp['reason']}`")

    report = [
        f"# PPCH Act Demonstration: PR #{payload['pr_number']}",
        "",
        f"**Stage:** `{payload['stage']}`  ",
        f"**Action:** `{payload['action']}`",
        "",
        payload["message"],
        "",
        "## Prediction (computed from pre-submission features only)",
        "",
        f"- Risk score (average of model probabilities): {payload['risk_score']:.3f}",
        f"- Random Forest probability: {payload['model_probabilities']['random_forest']:.3f}",
        f"- XGBoost probability: {payload['model_probabilities']['xgboost']:.3f}",
        f"- Predicted label (risk_score >= 0.5 -> 1): {payload['predicted_label']}",
        f"- Refactoring suggestion requested: `{payload['refactoring_suggestion_requested']}`",
        *ilp_lines,
        *suggestion_block,
        "",
        "## Post-hoc validation (NOT used in the decision above)",
        "",
        f"- Actual complexity: {pv['actual_complexity_before']} -> {pv['actual_complexity_after']} "
        f"(delta {pv['actual_complexity_delta']:+.1f})",
        f"- Actual label: {pv['actual_label_exceeds_threshold']}",
        f"- Prediction {match_text} the actual outcome.",
        "",
        "This report is an advisory Act-layer output driven by the Analyze layer's "
        "prediction. It does not modify source code.",
    ]
    stem.with_suffix(".md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote {stem.with_suffix('.json')}")
    print(f"Wrote {stem.with_suffix('.md')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pr-number", type=int, nargs="+", default=[1525, 1324, 1719],
        help="Default set: 1525 (no increase, true negative), 1324 (borderline, +1.0), "
             "1719 (clear increase, +16.0) — a deliberately varied demonstration set.",
    )
    args = parser.parse_args()
    models = load_models()
    for number in args.pr_number:
        feature_path = PROCESSED_DIR / f"pr_{number}" / "feature_table.json"
        feature_row = json.loads(feature_path.read_text(encoding="utf-8"))
        prediction = predict_risk(models, feature_row)
        payload = build_intervention(feature_row, prediction)
        payload["ilp"] = (
            generate_refactoring_suggestion(number) if payload["refactoring_suggestion_requested"]
            else {"status": "not_requested"}
        )
        write_outputs(payload)
        print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()