"""Survey all usable PRs' predicted-high-risk cases through the real ILP
refactoring pipeline, to find:
  (a) genuinely clean demo candidates - localized complexity, small extraction
  (b) cases like PR #1719 - complexity spread broadly across the method,
      where any sufficient extraction necessarily covers most of it

This is exploratory/diagnostic, not part of the core pipeline: it reuses
generate_refactoring_suggestion() from pipeline.py directly rather than
duplicating logic, and reports an "extraction_ratio" (selected statements /
total statements in the method) as a rough cleanliness signal - lower is a
more localized, more classically "Extract Method"-shaped suggestion.

Usage:
    python act/github-action/explore_candidates.py
"""

import json
import sys
from pathlib import Path

import joblib
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
sys.path.insert(0, str(THIS_DIR.parent / "ilp-engine"))

from pipeline import (  # noqa: E402
    FEATURES, MODEL_DIR, PROCESSED_DIR, NOTICE_THRESHOLD,
    generate_refactoring_suggestion,
)

EVALUATION_DIR = THIS_DIR.parents[1] / "evaluation"
sys.path.insert(0, str(THIS_DIR.parents[1] / "analyze"))
from feature_utils import apply_log_transform  # noqa: E402


def load_models() -> dict:
    return {
        "random_forest": joblib.load(MODEL_DIR / "random_forest.joblib"),
        "xgboost": joblib.load(MODEL_DIR / "xgboost.joblib"),
    }


def predict_risk(models: dict, feature_row: dict) -> float:
    # MUST match analyze/train_models.py's load_dataset() exactly, or
    # predictions silently skew (see analyze/feature_utils.py).
    x = apply_log_transform(pd.DataFrame([{f: feature_row[f] for f in FEATURES}]))
    probs = [model.predict_proba(x)[0, 1] for model in models.values()]
    return sum(probs) / len(probs)


def main() -> None:
    models = load_models()
    rows = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in PROCESSED_DIR.glob("pr_*/feature_table.json")
    ]
    print(f"Loaded {len(rows)} usable PRs. Computing risk scores...")

    candidates = []
    for row in rows:
        risk = predict_risk(models, row)
        if risk >= NOTICE_THRESHOLD:
            candidates.append((row["pr_number"], risk))
    candidates.sort(key=lambda c: -c[1])
    print(f"{len(candidates)} PRs at or above NOTICE_THRESHOLD ({NOTICE_THRESHOLD}). "
          f"Running the real ILP pipeline on each (this fetches real source over the network)...\n")

    survey = []
    for i, (pr_number, risk) in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] PR #{pr_number} (risk={risk:.3f})...", end=" ")
        try:
            result = generate_refactoring_suggestion(pr_number)
        except Exception as exc:
            print(f"ERROR: {exc}")
            survey.append({"pr_number": pr_number, "risk_score": risk, "status": "error", "error": str(exc)})
            continue

        if result.get("status") not in ("optimal", "threshold_unreachable"):
            print(f"status={result.get('status')} ({result.get('reason', '')})")
            survey.append({
                "pr_number": pr_number, "risk_score": risk,
                "status": result.get("status"), "reason": result.get("reason"),
            })
            continue

        selected = result.get("selected_statement_indices", [])
        # total statement count isn't directly in the result; re-derive it from
        # the fact that indices are 0-based and contiguous over the method
        total_statements = None
        suggestion = result.get("suggestion", {})
        line_span = None
        if suggestion.get("rendered"):
            lo, hi = suggestion["source_line_range"]
            line_span = hi - lo + 1

        entry = {
            "pr_number": pr_number,
            "risk_score": round(risk, 3),
            "status": result.get("status"),
            "method_name": result.get("method_name"),
            "source_file": result.get("source_file"),
            "was_touched_by_pr": result.get("was_touched_by_pr"),
            "original_complexity": result.get("original_complexity"),
            "remaining_complexity": result.get("remaining_complexity"),
            "selected_statement_count": len(selected),
            "line_span": line_span,
            "brace_balanced": suggestion.get("brace_balanced"),
            "inferred_parameter_count": len(suggestion.get("inferred_parameters", [])),
            # "status": "optimal" only means the ILP SOLVER found a
            # mathematically valid extraction - it says nothing about
            # whether the RENDERED code is safe to apply (e.g. a `return`
            # statement inside the extracted block makes it unsafe
            # regardless of how clean the ILP solution looks). Surfaced
            # explicitly so a reader of this table doesn't conflate "the
            # solver succeeded" with "this is ready to auto-apply" - see
            # act/github-action/verify_pr_suggestion.py for the real,
            # SonarQube-checked outcome on a candidate-by-candidate basis.
            "safe_to_auto_apply": suggestion.get("safe_to_auto_apply"),
        }
        survey.append(entry)
        print(f"method={entry['method_name']}, touched_by_pr={entry['was_touched_by_pr']}, "
              f"selected={entry['selected_statement_count']} stmts, line_span={line_span}, "
              f"safe_to_auto_apply={entry['safe_to_auto_apply']}")

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "refactoring_candidates_survey.json").write_text(
        json.dumps(survey, indent=2) + "\n", encoding="utf-8"
    )

    optimal = [s for s in survey if s.get("status") in ("optimal", "threshold_unreachable") and s.get("line_span")]
    optimal.sort(key=lambda s: (not s.get("was_touched_by_pr"), s["line_span"]))

    lines = [
        "# Refactoring Candidate Survey",
        "",
        f"Ran the real ILP pipeline across {len(candidates)} PRs at/above the notice threshold "
        f"({NOTICE_THRESHOLD}). Sorted first by whether the target method was confirmed as part "
        "of the PR's actual diff (trustworthy candidates first), then by line_span (smaller = "
        "more localized, more classically \"Extract Method\"-shaped suggestion).",
        "",
        "| PR | Risk | Method | Touched by PR? | Selected stmts | Line span | Remaining complexity | Balanced | Safe to auto-apply |",
        "|---|---:|---|---|---:|---:|---:|---|---|",
    ]
    for s in optimal:
        touched = "✅" if s.get("was_touched_by_pr") else "⚠️ NO"
        safe = "✅" if s.get("safe_to_auto_apply") else "⚠️ NO"
        lines.append(
            f"| #{s['pr_number']} | {s['risk_score']:.3f} | `{s['method_name']}` | {touched} | "
            f"{s['selected_statement_count']} | {s['line_span']} | {s['remaining_complexity']:.1f} | "
            f"{s['brace_balanced']} | {safe} |"
        )
    untrusted_count = sum(1 for s in optimal if not s.get("was_touched_by_pr"))
    if untrusted_count:
        lines += ["", f"**{untrusted_count} of {len(optimal)} candidates could not be confirmed as "
                       "touching the reported method** - these fell back to the file's globally "
                       "most complex method, which may be unrelated to what the PR actually "
                       "changed. Prefer ✅-marked rows for any dissertation demo or claim."]
    unreachable_count = sum(1 for s in optimal if s.get("status") == "threshold_unreachable")
    if unreachable_count:
        lines += ["", f"**{unreachable_count} of {len(optimal)} candidates could not get remaining "
                       f"complexity under the target threshold with a single extraction** - shown as "
                       "best-effort suggestions; these methods likely need more than one extraction "
                       "to fully resolve."]
    unsafe_count = sum(1 for s in optimal if not s.get("safe_to_auto_apply"))
    if unsafe_count:
        lines += ["", f"**{unsafe_count} of {len(optimal)} candidates are NOT safe to auto-apply** "
                       "(most commonly: the extracted block contains a `return` statement that isn't "
                       "safely forwardable - either mixed with genuine fall-through, or a sequence of "
                       "separate sibling `if` guard clauses rather than a single `if/else-if/.../else` "
                       "chain with a terminal `else`. That specific chained-else shape IS now safely "
                       "handled via return-forwarding - see java_statement_extractor.py's "
                       "render_extraction_suggestion docstring - but as of this survey, zero real "
                       "candidates in this corpus happen to have that shape) - the ILP still found a "
                       "mathematically valid extraction, but applying it as-is risks incorrect code. "
                       "These need manual restructuring, not automatic application. See "
                       "act/github-action/verify_pr_suggestion.py for confirmed, SonarQube-checked "
                       "outcomes on specific PRs."]
    non_optimal = [s for s in survey if s.get("status") not in ("optimal", "threshold_unreachable")]
    if non_optimal:
        lines += ["", f"{len(non_optimal)} candidates did not produce an optimal suggestion "
                       "(skipped, extraction_failed, or error) — see the JSON for details."]
    (EVALUATION_DIR / "refactoring_candidates_survey.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {EVALUATION_DIR / 'refactoring_candidates_survey.json'}")
    print(f"Wrote {EVALUATION_DIR / 'refactoring_candidates_survey.md'}")
    if optimal:
        print(f"\nSmallest, cleanest candidate: PR #{optimal[0]['pr_number']} "
              f"({optimal[0]['method_name']}, line_span={optimal[0]['line_span']})")


if __name__ == "__main__":
    main()