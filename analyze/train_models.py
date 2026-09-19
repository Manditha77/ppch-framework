"""Phase II — Temporal pilot training for Random Forest and XGBoost, SMOTE-balanced.

FIX (see docs — class-imbalance finding): the previous version of this script
trained on a 34-positive / 9-negative partition with no imbalance handling.
Both models degenerated to near-constant "positive" predictions, which scored
misleadingly high on accuracy/precision/recall while carrying almost no real
signal. This version:

  1. Applies SMOTE to the TRAINING partition only (never the test partition —
     the test set must stay a real, untouched class distribution or its
     metrics become meaningless), matching Methodology §3.3.4's stated design.
  2. Reports a confusion matrix and the predicted-positive rate for each
     model, alongside accuracy/precision/recall/F1, so a degenerate
     "always-predict-majority" model is visible in the output rather than
     hidden behind a high-looking score.
  3. Keeps everything else unchanged: temporal (chronological) train/test
     split, post-submission complexity fields excluded from the predictor
     matrix, models saved to analyze/models/.
"""

import json
from pathlib import Path

import joblib
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
MODEL_DIR = ROOT / "analyze" / "models"
EVALUATION_DIR = ROOT / "evaluation"

FEATURES = [
    "additions", "deletions", "changed_files", "changed_java_files", "commits",
    "comments", "review_comments", "body_character_count", "title_word_count",
    # complexity_before reflects the TARGET BRANCH's state before the PR's
    # changes are applied — it is genuinely available at PR-submission time (a
    # real deployment could scan the base branch independently of any incoming
    # PR, even continuously). It is NOT the same as complexity_after/delta/the
    # label itself, which only exist after the PR's changes are known and must
    # stay excluded.
    #
    # HISTORY: under an EARLIER, since-replaced label definition
    # (exceeds_complexity_threshold_after = file-total-after > 15 — see
    # sense/scripts/03_build_feature_table.py's docstring for the full story),
    # complexity_before separated the two classes almost perfectly on its own,
    # and omitting it caused a degenerate "always predict positive" model. The
    # CURRENT label (exceeds_significant_complexity_increase, delta-based) does
    # NOT have this property — the ablation study (evaluation/ablation_results.md)
    # shows removing complexity_before barely changes AUC (and slightly IMPROVES
    # XGBoost's), since structural_size features now carry the dominant signal.
    # It stays in FEATURES because it's still a legitimate, leakage-free
    # pre-submission signal — not because it's load-bearing anymore.
    "complexity_before",
]
LABEL = "exceeds_significant_complexity_increase"


def load_dataset() -> pd.DataFrame:
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in PROCESSED_DIR.glob("pr_*/feature_table.json")
    ]
    if not rows:
        raise RuntimeError("No feature-table rows found")
    frame = pd.DataFrame(rows).sort_values("created_at").reset_index(drop=True)
    if frame[FEATURES + [LABEL]].isnull().any().any():
        raise ValueError("Training features or labels contain null values")
    return frame


def metrics(model, x_test: pd.DataFrame, y_test: pd.Series) -> dict:
    predictions = model.predict(x_test)
    probabilities = model.predict_proba(x_test)[:, 1]
    cm = confusion_matrix(y_test, predictions, labels=[0, 1])
    result = {
        "accuracy": accuracy_score(y_test, predictions),
        "precision": precision_score(y_test, predictions, zero_division=0),
        "recall": recall_score(y_test, predictions, zero_division=0),
        "f1": f1_score(y_test, predictions, zero_division=0),
        "predicted_positive_rate": float(predictions.mean()),
        "confusion_matrix": {
            "true_negative": int(cm[0][0]),
            "false_positive": int(cm[0][1]),
            "false_negative": int(cm[1][0]),
            "true_positive": int(cm[1][1]),
        },
    }
    result["roc_auc"] = roc_auc_score(y_test, probabilities) if len(set(y_test)) == 2 else None
    return result


def main() -> None:
    frame = load_dataset()
    split_index = max(1, int(len(frame) * 0.7))
    train = frame.iloc[:split_index]
    test = frame.iloc[split_index:]
    x_train, y_train = train[FEATURES], train[LABEL]
    x_test, y_test = test[FEATURES], test[LABEL]

    if len(set(y_train)) < 2:
        raise RuntimeError("Temporal training partition contains only one class")

    pre_smote_counts = {str(k): int(v) for k, v in y_train.value_counts().to_dict().items()}
    minority_count = min(y_train.value_counts())
    # SMOTE requires k_neighbors < minority class size; cap at 5 (sklearn default) or
    # smaller if the minority class itself is tiny, rather than crashing on small data.
    k_neighbors = max(1, min(5, minority_count - 1))

    smote = SMOTE(random_state=42, k_neighbors=k_neighbors)
    x_train_bal, y_train_bal = smote.fit_resample(x_train, y_train)
    post_smote_counts = {str(k): int(v) for k, v in y_train_bal.value_counts().to_dict().items()}

    models = {
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            random_state=42,
            n_jobs=-1,
        ),
        "xgboost": XGBClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
            n_jobs=1,
        ),
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    evaluation = {
        "phase": "II_ANALYZE",
        "status": "pilot_evaluation_smote_balanced",
        "warning": (
            "Pilot metrics on a 62-row dataset are a pipeline validation, not a "
            "final dissertation claim. Scale the Sense-phase sample (more "
            "commons-lang PRs, then Kafka/Dubbo) before reporting dissertation-"
            "level results."
        ),
        "row_count": len(frame),
        "feature_fields": FEATURES,
        "excluded_post_submission_fields": [
            "complexity_after", "complexity_delta",
            "complexity_increased", LABEL, "complexity_threshold",
        ],
        "label_field": LABEL,
        "temporal_split": {
            "train_fraction": 0.7,
            "train_count": len(train),
            "test_count": len(test),
            "train_pr_numbers": train["pr_number"].tolist(),
            "test_pr_numbers": test["pr_number"].tolist(),
        },
        "class_balance": {
            "train_before_smote": pre_smote_counts,
            "train_after_smote": post_smote_counts,
            "smote_k_neighbors": k_neighbors,
            "test_positive": int(y_test.sum()),
            "test_negative": int((y_test == 0).sum()),
            "test_true_positive_rate": float(y_test.mean()),
        },
        "models": {},
    }
    predictions = test[["pr_number", "created_at", LABEL]].copy()

    for name, model in models.items():
        model.fit(x_train_bal, y_train_bal)
        joblib.dump(model, MODEL_DIR / f"{name}.joblib")
        evaluation["models"][name] = metrics(model, x_test, y_test)
        if hasattr(model, "feature_importances_"):
            evaluation["models"][name]["feature_importances"] = {
                feature: float(importance)
                for feature, importance in sorted(
                    zip(FEATURES, model.feature_importances_), key=lambda pair: -pair[1]
                )
            }
        predictions[f"{name}_prediction"] = model.predict(x_test)
        predictions[f"{name}_probability"] = model.predict_proba(x_test)[:, 1]

    # Computed AFTER fitting, from the ACTUAL importances - not a hardcoded
    # claim, since which feature (if any) dominates depends on the label
    # definition and can change (e.g. this was previously always
    # complexity_before, back when the label was a near-constant function
    # of it - see 03_build_feature_table.py's docstring for that history).
    top_features = {
        name: max(result["feature_importances"].items(), key=lambda kv: kv[1])
        for name, result in evaluation["models"].items()
        if "feature_importances" in result
    }
    max_share = max((share for _, share in top_features.values()), default=0.0)
    if max_share > 0.5:
        dominant = ", ".join(f"{name} ({feat}={share:.2f})" for name, (feat, share) in top_features.items())
        evaluation["interpretation_note"] = (
            f"One feature dominates importance in at least one model ({dominant}) - check "
            "whether this reflects genuine predictive signal or a near-tautological "
            "relationship (e.g. a feature that trivially determines the label) before "
            "trusting the headline AUC."
        )
    else:
        top_desc = ", ".join(f"{name}: {feat} ({share:.2f})" for name, (feat, share) in top_features.items())
        evaluation["interpretation_note"] = (
            f"Feature importance is reasonably distributed across the feature set in both "
            f"models (top feature per model: {top_desc}), consistent with genuine "
            "multi-feature prediction rather than a single dominant signal."
        )

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "phase2_training_results.json").write_text(
        json.dumps(evaluation, indent=2) + "\n", encoding="utf-8"
    )
    predictions.to_csv(EVALUATION_DIR / "phase2_test_predictions.csv", index=False)

    lines = [
        "# Phase II Pilot Training Results (SMOTE-balanced)",
        "",
        "Temporal holdout pilot results on a small (62-row) dataset — a pipeline",
        "validation, not a final dissertation claim. SMOTE was applied to the",
        "TRAINING partition only; the test partition is the real, untouched",
        "class distribution.",
        "",
        f"- Rows: {len(frame)}",
        f"- Training rows: {len(train)} (before SMOTE: {pre_smote_counts}, after: {post_smote_counts})",
        f"- Test rows: {len(test)} (positive={evaluation['class_balance']['test_positive']}, "
        f"negative={evaluation['class_balance']['test_negative']}, "
        f"true positive rate={evaluation['class_balance']['test_true_positive_rate']:.3f})",
        "",
        "| Model | ROC AUC | Accuracy | Precision | Recall | F1 | Predicted-positive rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in evaluation["models"].items():
        auc = f"{result['roc_auc']:.3f}" if result["roc_auc"] is not None else "n/a"
        lines.append(
            f"| {name} | {auc} | {result['accuracy']:.3f} | "
            f"{result['precision']:.3f} | {result['recall']:.3f} | {result['f1']:.3f} | "
            f"{result['predicted_positive_rate']:.3f} |"
        )
    lines.extend(["", "**Confusion matrices** (rows=actual, cols=predicted):", ""])
    for name, result in evaluation["models"].items():
        cm = result["confusion_matrix"]
        lines.append(
            f"- **{name}**: TN={cm['true_negative']}, FP={cm['false_positive']}, "
            f"FN={cm['false_negative']}, TP={cm['true_positive']}"
        )
    lines.extend([
        "",
        "Post-submission complexity measurements (after/delta) were excluded from the",
        "predictor matrix; complexity_before was correctly INCLUDED since it reflects",
        "the target branch's state prior to the PR and is genuinely available at",
        "submission time.",
        "",
        f"**Interpretation note:** {evaluation['interpretation_note']}",
        "",
        "A predicted-positive rate close to the test set's true positive rate "
        f"({evaluation['class_balance']['test_true_positive_rate']:.3f}) indicates the "
        "model is discriminating between classes rather than defaulting to the majority "
        "class — check this figure before trusting accuracy/precision/recall on an "
        "imbalanced set like this one.",
    ])
    (EVALUATION_DIR / "phase2_training_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(evaluation, indent=2))


if __name__ == "__main__":
    main()