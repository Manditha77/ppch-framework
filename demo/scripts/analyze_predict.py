"""Demo Analyze layer — builds the exact same 10-feature vector the real
pipeline uses (see analyze/train_models.py's FEATURES list), combining:
  - REAL complexity_before, from sense_scan.py's actual SonarScanner run
  - Demo PR metadata (structural counts are real, derived from the actual
    demo files; process/text fields are clearly-labeled illustrative
    placeholders — see demo_pr_metadata.json's "_note")
and predicts risk using the SAME trained Random Forest / XGBoost models used
throughout the real research pipeline (analyze/models/*.joblib) — not a
separate demo-only model.

Usage:
    python analyze_predict.py --version before
    python analyze_predict.py --version after
"""

import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPTS_DIR.parent
ROOT = DEMO_DIR.parent  # ppch-framework/
MODEL_DIR = ROOT / "analyze" / "models"
sys.path.insert(0, str(ROOT / "analyze"))
from feature_utils import apply_log_transform  # noqa: E402

# Must exactly match analyze/train_models.py's FEATURES list and order.
FEATURES = [
    "additions", "deletions", "changed_files", "changed_java_files", "commits",
    "comments", "review_comments", "body_character_count", "title_word_count",
    "contributor_prior_pr_count", "contributor_prior_acceptance_rate",
    "contributor_tenure_days", "contributor_follower_count",
    "complexity_before",
]

# Same thresholds as act/github-action/pipeline.py, for a consistent demo narrative.
WARNING_THRESHOLD = 0.7
NOTICE_THRESHOLD = 0.4


def load_models() -> dict:
    return {
        "random_forest": joblib.load(MODEL_DIR / "random_forest.joblib"),
        "xgboost": joblib.load(MODEL_DIR / "xgboost.joblib"),
    }


def build_feature_row(version: str) -> dict:
    pr_meta = json.loads((DEMO_DIR / "demo_pr_metadata.json").read_text(encoding="utf-8"))
    sense_result_path = DEMO_DIR / "results" / version / "sense_result.json"
    if not sense_result_path.exists():
        raise RuntimeError(f"{sense_result_path} not found — run sense_scan.py --version {version} first.")
    sense_result = json.loads(sense_result_path.read_text(encoding="utf-8"))

    return {
        "additions": pr_meta["additions"],
        "deletions": pr_meta["deletions"],
        "changed_files": pr_meta["changed_files"],
        "changed_java_files": pr_meta["changed_java_files"],
        "commits": pr_meta["commits"],
        "comments": pr_meta["comments"],
        "review_comments": pr_meta["review_comments"],
        "body_character_count": len(pr_meta["body"]),
        "title_word_count": len(pr_meta["title"].split()),
        "contributor_prior_pr_count": pr_meta["contributor_prior_pr_count"],
        "contributor_prior_acceptance_rate": pr_meta["contributor_prior_acceptance_rate"],
        "contributor_tenure_days": pr_meta["contributor_tenure_days"],
        "contributor_follower_count": pr_meta["contributor_follower_count"],
        "complexity_before": sense_result["cognitive_complexity"],
    }


def predict(version: str) -> dict:
    models = load_models()
    feature_row = build_feature_row(version)
    # MUST match analyze/train_models.py's load_dataset() exactly, or
    # predictions silently skew (see feature_utils.py).
    x = apply_log_transform(pd.DataFrame([feature_row]))[FEATURES]

    probabilities = {name: float(model.predict_proba(x)[0, 1]) for name, model in models.items()}
    risk_score = sum(probabilities.values()) / len(probabilities)

    if risk_score >= WARNING_THRESHOLD:
        action = "complexity_warning_and_refactoring_review"
    elif risk_score >= NOTICE_THRESHOLD:
        action = "complexity_increase_notice"
    else:
        action = "no_intervention"

    result = {
        "version": version,
        "features": feature_row,
        "model_probabilities": probabilities,
        "risk_score": risk_score,
        "predicted_label": int(risk_score >= 0.5),
        "action": action,
        "refactoring_suggestion_requested": risk_score >= WARNING_THRESHOLD,
    }
    print(f"complexity_before = {feature_row['complexity_before']}")
    print(f"Random Forest probability: {probabilities['random_forest']:.3f}")
    print(f"XGBoost probability:      {probabilities['xgboost']:.3f}")
    print(f"Risk score: {risk_score:.3f}  ->  action: {action}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["before", "after"], required=True)
    args = parser.parse_args()

    result = predict(args.version)

    results_dir = DEMO_DIR / "results" / args.version
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "analyze_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {results_dir / 'analyze_result.json'}")


if __name__ == "__main__":
    main()
