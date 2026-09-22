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
sys.path.insert(0, str(ROOT / "act" / "ilp-engine"))
sys.path.insert(0, str(ROOT / "act" / "github-action"))
from feature_utils import apply_log_transform  # noqa: E402
from java_statement_extractor import max_complexity_across_sources  # noqa: E402
from pipeline import decide_intervention  # noqa: E402 - same shared decision logic as the real pipeline/live paths
from live_predict import compute_live_textual_embeddings  # noqa: E402 - same fitted PCA/Word2Vec/BERT models

# Must exactly match analyze/train_models.py's FEATURES set (sklearn
# validates by NAME, not position, so ordering here doesn't have to match -
# every name the model was fit with must simply be present).
TEXTUAL_EMBEDDING_FEATURES = [f"bert_embed_{i}" for i in range(5)] + [f"w2v_embed_{i}" for i in range(5)]

FEATURES = [
    "additions", "deletions", "changed_files", "changed_java_files", "commits",
    "comments", "review_comments", "body_character_count", "title_word_count",
    *TEXTUAL_EMBEDDING_FEATURES,
    "contributor_prior_pr_count", "contributor_prior_acceptance_rate",
    "contributor_tenure_days", "contributor_follower_count",
    "complexity_before",
    "max_touched_method_complexity",
]

# Thresholds/action-decision logic now imported directly from
# act/github-action/pipeline.py's decide_intervention - guarantees this demo
# can never silently drift from the real pipeline/live paths' thresholds.


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

    # max_touched_method_complexity: same AST-based measurement used live/
    # historically (see java_statement_extractor.py::max_complexity_across_
    # sources), computed here from this scenario's own local
    # java_project_{version}/ files - the demo's local stand-in for "this
    # PR's own HEAD content" (see sense_scan.py's own docstring on why the
    # demo uses plain local folders instead of a git checkout).
    project_dir = DEMO_DIR / f"java_project_{version}"
    java_sources = [
        p.read_text(encoding="utf-8") for p in project_dir.glob("*.java")
    ]
    max_touched_method_complexity = max_complexity_across_sources(java_sources)

    # bert_embed_*/w2v_embed_*: same fitted PCA/Word2Vec/BERT models used
    # live (see live_predict.py::compute_live_textual_embeddings's own
    # docstring on why these must never be refit per call).
    embeddings = compute_live_textual_embeddings(pr_meta["title"], pr_meta["body"])

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
        **embeddings,
        "contributor_prior_pr_count": pr_meta["contributor_prior_pr_count"],
        "contributor_prior_acceptance_rate": pr_meta["contributor_prior_acceptance_rate"],
        "contributor_tenure_days": pr_meta["contributor_tenure_days"],
        "contributor_follower_count": pr_meta["contributor_follower_count"],
        "complexity_before": sense_result["cognitive_complexity"],
        "max_touched_method_complexity": max_touched_method_complexity,
    }


def predict(version: str) -> dict:
    models = load_models()
    feature_row = build_feature_row(version)
    # MUST match analyze/train_models.py's load_dataset() exactly, or
    # predictions silently skew (see feature_utils.py).
    x = apply_log_transform(pd.DataFrame([feature_row]))[FEATURES]

    probabilities = {name: float(model.predict_proba(x)[0, 1]) for name, model in models.items()}
    risk_score = sum(probabilities.values()) / len(probabilities)
    decision = decide_intervention(risk_score, feature_row["max_touched_method_complexity"])

    result = {
        "version": version,
        "features": feature_row,
        "model_probabilities": probabilities,
        "risk_score": risk_score,
        "predicted_label": int(risk_score >= 0.5),
        **decision,
    }
    print(f"complexity_before = {feature_row['complexity_before']}")
    print(f"max_touched_method_complexity = {feature_row['max_touched_method_complexity']}")
    print(f"Random Forest probability: {probabilities['random_forest']:.3f}")
    print(f"XGBoost probability:      {probabilities['xgboost']:.3f}")
    print(f"Risk score: {risk_score:.3f}  ->  action: {decision['action']} ({decision['trigger_reason']})")
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
