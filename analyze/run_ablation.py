"""Phase II — Ablation study (Methodology §3.5.2, answers RQ1).

Isolates the contribution of each feature family to predictive performance by:
  1. Training the full model (all families) as a baseline AUC.
  2. Leave-one-family-out: drop each family in turn, retrain, record the AUC drop.
  3. Family-alone: train using ONLY each family, to see its standalone power.

Family definitions here reflect what is actually implemented in the current
feature table (see docs — textual-semantic features are still a crude proxy,
not the BERT/Word2Vec embeddings specified in Methodology §3.3.3; this should
be stated as a limitation until that gap is closed):

  - baseline_complexity: complexity_before (the target file's pre-existing
    complexity — legitimate pre-submission signal, NOT a leakage field)
  - structural_size: additions, deletions, changed_files, changed_java_files
  - process: commits, comments, review_comments
  - textual_proxy: body_character_count, title_word_count (placeholders for
    the specified BERT/Word2Vec embeddings, not the real thing yet)

Uses the SAME temporal train/test split as analyze/train_models.py so results
are directly comparable to the main reported metrics.
"""

import json
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

from feature_utils import apply_log_transform

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
EVALUATION_DIR = ROOT / "evaluation"

FAMILIES = {
    "baseline_complexity": ["complexity_before"],
    "structural_size": ["additions", "deletions", "changed_files", "changed_java_files"],
    # "process" now includes the PR's own activity (commits/comments/review_
    # comments) AND the contributor-level process features Methodology §3.3.3
    # specifies (prior acceptance rate, tenure, prior PR count, follower
    # count) — added via sense/scripts/04_enrich_process_features.py.
    "process": [
        "commits", "comments", "review_comments",
        "contributor_prior_pr_count", "contributor_prior_acceptance_rate",
        "contributor_tenure_days", "contributor_follower_count",
    ],
    "textual_proxy": ["body_character_count", "title_word_count"],
}
ALL_FEATURES = [f for group in FAMILIES.values() for f in group]
LABEL = "exceeds_significant_complexity_increase"


def load_split():
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in PROCESSED_DIR.glob("pr_*/feature_table.json")
    ]
    frame = apply_log_transform(pd.DataFrame(rows).sort_values("created_at").reset_index(drop=True))
    split_index = max(1, int(len(frame) * 0.7))
    return frame.iloc[:split_index], frame.iloc[split_index:]


def make_models():
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=300, random_state=42, n_jobs=-1, class_weight="balanced"
        ),
        "xgboost": XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.9, colsample_bytree=0.9,
            objective="binary:logistic", eval_metric="logloss",
            random_state=42, n_jobs=1,
        ),
    }


def auc_for(features, train, test, model_name):
    if len(set(train[LABEL])) < 2 or not features:
        return None
    model = make_models()[model_name]
    model.fit(train[features], train[LABEL])
    proba = model.predict_proba(test[features])[:, 1]
    if len(set(test[LABEL])) < 2:
        return None
    return float(roc_auc_score(test[LABEL], proba))


def main() -> None:
    train, test = load_split()
    results = {"phase": "II_ANALYZE", "study": "ablation", "row_count": len(train) + len(test)}

    for model_name in ["random_forest", "xgboost"]:
        full_auc = auc_for(ALL_FEATURES, train, test, model_name)
        leave_one_out = {}
        for family, feats in FAMILIES.items():
            remaining = [f for f in ALL_FEATURES if f not in feats]
            auc = auc_for(remaining, train, test, model_name)
            leave_one_out[family] = {
                "auc_without_family": auc,
                "delta_vs_full": None if auc is None else round(auc - full_auc, 4),
            }
        family_alone = {
            family: auc_for(feats, train, test, model_name)
            for family, feats in FAMILIES.items()
        }
        results[model_name] = {
            "full_model_auc": full_auc,
            "leave_one_family_out": leave_one_out,
            "family_alone": family_alone,
        }

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "ablation_results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Phase II Ablation Study (RQ1)",
        "",
        "Answers: *what are the most reliable predictors of cognitive-complexity",
        "spikes in Java Pull Requests?* Same temporal train/test split as the main",
        "training run.",
        "",
        "**Feature-family caveat:** `textual_proxy` here is `body_character_count` and",
        "`title_word_count` — placeholders for the BERT/Word2Vec embeddings specified",
        "in Methodology §3.3.3, which are not yet implemented.",
        "",
    ]
    for model_name in ["random_forest", "xgboost"]:
        r = results[model_name]
        lines += [
            f"## {model_name}",
            "",
            f"Full-model AUC: **{r['full_model_auc']:.3f}**" if r["full_model_auc"] is not None else "Full-model AUC: n/a",
            "",
            "| Family removed | AUC without family | Δ vs full |",
            "|---|---:|---:|",
        ]
        for family, res in r["leave_one_family_out"].items():
            auc = res["auc_without_family"]
            delta = res["delta_vs_full"]
            lines.append(
                f"| {family} | {auc:.3f} | {delta:+.3f} |" if auc is not None
                else f"| {family} | n/a | n/a |"
            )
        lines += ["", "| Family alone | Standalone AUC |", "|---|---:|"]
        for family, auc in r["family_alone"].items():
            lines.append(f"| {family} | {auc:.3f} |" if auc is not None else f"| {family} | n/a |")
        lines.append("")

    lines += [
        "**Reading this table:** a large negative Δ when a family is removed means that",
        "family is essential; Δ near 0 means the model doesn't need it (often because",
        "another family, or `baseline_complexity` in particular, already captures the",
        "same signal). A family's standalone AUC shows how much it can predict on its own.",
    ]
    (EVALUATION_DIR / "ablation_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"\nWrote {EVALUATION_DIR / 'ablation_results.json'}")
    print(f"Wrote {EVALUATION_DIR / 'ablation_results.md'}")


if __name__ == "__main__":
    main()