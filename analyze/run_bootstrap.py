"""Phase II — Out-of-sample bootstrap validation (Methodology §3.5.1, answers RQ2).

For each of 1000 iterations: draw a bootstrap sample (with replacement) of the
full dataset as the training "bag"; the rows NOT drawn ("out-of-bag", OOB) form
that iteration's held-out test set. This is the standard out-of-bag bootstrap
validation protocol and gives a distribution of AUC estimates rather than a
single point estimate from one train/test split - directly answering how
reliable the Analyze layer's predictive performance is (RQ2), and giving a
confidence interval rather than a single fragile number from 19 test rows.

Design note: unlike analyze/train_models.py, this script does NOT apply SMOTE
inside each bootstrap iteration. With only 62 rows, some bootstrap bags would
have too few minority-class examples for SMOTE's k-nearest-neighbor step to
run reliably every time; iterations where a bag or its OOB set ends up with
only one class are skipped (not counted) rather than crashing or producing a
misleading degenerate AUC.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.naive_bayes import MultinomialNB
from xgboost import XGBClassifier

from feature_utils import apply_log_transform

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
EVALUATION_DIR = ROOT / "evaluation"

# Real BERT + Word2Vec embeddings (PCA-reduced to 5 dims each, MinMax-scaled
# non-negative for MultinomialNB) - see sense/scripts/05_compute_textual_embeddings.py
TEXTUAL_EMBEDDING_FEATURES = [f"bert_embed_{i}" for i in range(5)] + [f"w2v_embed_{i}" for i in range(5)]

FEATURES = [
    "additions", "deletions", "changed_files", "changed_java_files", "commits",
    "comments", "review_comments", "body_character_count", "title_word_count",
    *TEXTUAL_EMBEDDING_FEATURES,
    "contributor_prior_pr_count", "contributor_prior_acceptance_rate",
    "contributor_tenure_days", "contributor_follower_count",
    "complexity_before",
    # See train_models.py's own comment on this feature (added 2026-09-22 to
    # close the "brand-new file invisible to complexity_before" gap).
    "max_touched_method_complexity",
]
LABEL = "exceeds_significant_complexity_increase"
N_ITERATIONS = 1000


def load_dataset() -> pd.DataFrame:
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in PROCESSED_DIR.glob("pr_*/feature_table.json")
    ]
    return apply_log_transform(pd.DataFrame(rows).reset_index(drop=True))


def make_model(name: str, seed: int):
    if name == "random_forest":
        return RandomForestClassifier(n_estimators=100, random_state=seed, n_jobs=-1, class_weight="balanced")
    if name == "xgboost":
        return XGBClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.05,
            subsample=0.9, colsample_bytree=0.9,
            objective="binary:logistic", eval_metric="logloss",
            random_state=seed, n_jobs=1,
        )
    if name == "naive_bayes":
        # No random_state - MultinomialNB's fit is deterministic given data.
        return MultinomialNB()
    if name == "logistic_regression":
        return LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)
    raise ValueError(f"Unknown model name: {name}")


def bootstrap_validate(frame: pd.DataFrame, model_name: str, n_iterations: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = len(frame)
    aucs = []
    skipped = 0

    for i in range(n_iterations):
        bag_idx = rng.integers(0, n, size=n)
        oob_idx = np.setdiff1d(np.arange(n), np.unique(bag_idx))
        if len(oob_idx) == 0:
            skipped += 1
            continue
        y_bag = frame.iloc[bag_idx][LABEL]
        y_oob = frame.iloc[oob_idx][LABEL]
        if len(set(y_bag)) < 2 or len(set(y_oob)) < 2:
            skipped += 1
            continue
        model = make_model(model_name, seed=i)
        model.fit(frame.iloc[bag_idx][FEATURES], y_bag)
        proba = model.predict_proba(frame.iloc[oob_idx][FEATURES])[:, 1]
        aucs.append(roc_auc_score(y_oob, proba))

    aucs = np.array(aucs)
    return {
        "requested_iterations": n_iterations,
        "valid_iterations": int(len(aucs)),
        "skipped_iterations": int(skipped),
        "skip_reason": "bag or out-of-bag set contained only one class",
        "mean_auc": float(aucs.mean()) if len(aucs) else None,
        "median_auc": float(np.median(aucs)) if len(aucs) else None,
        "std_auc": float(aucs.std()) if len(aucs) else None,
        "ci_95_low": float(np.percentile(aucs, 2.5)) if len(aucs) else None,
        "ci_95_high": float(np.percentile(aucs, 97.5)) if len(aucs) else None,
    }


def main() -> None:
    frame = load_dataset()
    if frame[FEATURES + [LABEL]].isnull().any().any():
        raise ValueError("Dataset contains null values in features or label")
    assert (frame[FEATURES] >= 0).all().all(), "MultinomialNB requires non-negative features"

    results = {
        "phase": "II_ANALYZE",
        "study": "out_of_sample_bootstrap_validation",
        "warning": (
            f"Bootstrap validation on a {len(frame)}-row dataset. The a-priori target "
            "AUC > 0.80 (Methodology §3.5.1) is a pipeline-validation checkpoint here, "
            "not a dissertation-level claim - scale the Sense-phase sample before "
            "reporting these figures as final."
        ),
        "row_count": len(frame),
        "n_iterations_requested": N_ITERATIONS,
        "target_auc": 0.80,
        "models": {},
    }
    for model_name in ["random_forest", "xgboost", "naive_bayes", "logistic_regression"]:
        results["models"][model_name] = bootstrap_validate(frame, model_name, N_ITERATIONS, seed=42)

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "bootstrap_results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Phase II Bootstrap Validation (RQ2)",
        "",
        f"Out-of-sample bootstrap validation, {N_ITERATIONS} requested iterations, "
        f"on {results['row_count']} rows. Answers: *what accuracy can supervised ML "
        "achieve in predicting smelly/complex PRs at submission time?*",
        "",
        f"A-priori target: AUC > {results['target_auc']}",
        "",
        "| Model | Valid iterations | Mean AUC | Median AUC | Std | 95% CI |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name, r in results["models"].items():
        if r["mean_auc"] is None:
            lines.append(f"| {name} | {r['valid_iterations']}/{N_ITERATIONS} | n/a | n/a | n/a | n/a |")
        else:
            lines.append(
                f"| {name} | {r['valid_iterations']}/{N_ITERATIONS} | {r['mean_auc']:.3f} | "
                f"{r['median_auc']:.3f} | {r['std_auc']:.3f} | "
                f"[{r['ci_95_low']:.3f}, {r['ci_95_high']:.3f}] |"
            )
    lines += [
        "",
        results["warning"],
        "",
        "SMOTE was NOT applied inside each bootstrap iteration (some bags would have "
        "too few minority examples for it to run reliably); iterations with a "
        "single-class bag or out-of-bag set are skipped and counted separately.",
        "",
        "Four baselines compared: Random Forest, XGBoost, Multinomial Naive Bayes, and "
        "Logistic Regression (all named in Methodology §3.4.2). GCN/CNN/RNN "
        "deep-learning baselines are also named there but require genuinely new "
        "infrastructure (AST-to-graph construction, a torch training pipeline) and are "
        "explicitly out of scope given the dissertation timeline.",
    ]
    (EVALUATION_DIR / "bootstrap_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"\nWrote {EVALUATION_DIR / 'bootstrap_results.json'}")
    print(f"Wrote {EVALUATION_DIR / 'bootstrap_results.md'}")


if __name__ == "__main__":
    main()