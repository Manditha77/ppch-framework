# Phase II Pilot Training Results (SMOTE-balanced)

Temporal holdout pilot results on a small (62-row) dataset — a pipeline
validation, not a final dissertation claim. SMOTE was applied to the
TRAINING partition only; the test partition is the real, untouched
class distribution.

- Rows: 62
- Training rows: 43 (before SMOTE: {'0': 32, '1': 11}, after: {'0': 32, '1': 32})
- Test rows: 19 (positive=7, negative=12, true positive rate=0.368)

| Model | ROC AUC | Accuracy | Precision | Recall | F1 | Predicted-positive rate |
|---|---:|---:|---:|---:|---:|---:|
| random_forest | 0.893 | 0.789 | 0.800 | 0.571 | 0.667 | 0.263 |
| xgboost | 0.917 | 0.789 | 0.800 | 0.571 | 0.667 | 0.263 |

**Confusion matrices** (rows=actual, cols=predicted):

- **random_forest**: TN=11, FP=1, FN=3, TP=4
- **xgboost**: TN=11, FP=1, FN=3, TP=4

Post-submission complexity measurements (after/delta) were excluded from the
predictor matrix; complexity_before was correctly INCLUDED since it reflects
the target branch's state prior to the PR and is genuinely available at
submission time.

**Interpretation note:** Feature importance is reasonably distributed across the feature set in both models (top feature per model: random_forest: additions (0.21), xgboost: changed_files (0.21)), consistent with genuine multi-feature prediction rather than a single dominant signal.

A predicted-positive rate close to the test set's true positive rate (0.368) indicates the model is discriminating between classes rather than defaulting to the majority class — check this figure before trusting accuracy/precision/recall on an imbalanced set like this one.
