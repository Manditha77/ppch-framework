# Phase II Pilot Training Results (SMOTE-balanced)

Temporal holdout pilot results on a small (62-row) dataset — a pipeline
validation, not a final dissertation claim. SMOTE was applied to the
TRAINING partition only; the test partition is the real, untouched
class distribution.

- Rows: 334
- Training rows: 233 (before SMOTE: {'0': 164, '1': 69}, after: {'1': 164, '0': 164})
- Test rows: 101 (positive=33, negative=68, true positive rate=0.327)

| Model | ROC AUC | Accuracy | Precision | Recall | F1 | Predicted-positive rate |
|---|---:|---:|---:|---:|---:|---:|
| random_forest | 0.652 | 0.703 | 0.636 | 0.212 | 0.318 | 0.109 |
| xgboost | 0.690 | 0.673 | 0.500 | 0.152 | 0.233 | 0.099 |

**Confusion matrices** (rows=actual, cols=predicted):

- **random_forest**: TN=64, FP=4, FN=26, TP=7
- **xgboost**: TN=63, FP=5, FN=28, TP=5

Post-submission complexity measurements (after/delta) were excluded from the
predictor matrix; complexity_before was correctly INCLUDED since it reflects
the target branch's state prior to the PR and is genuinely available at
submission time.

**Interpretation note:** Feature importance is reasonably distributed across the feature set in both models (top feature per model: random_forest: additions (0.21), xgboost: additions (0.18)), consistent with genuine multi-feature prediction rather than a single dominant signal.

A predicted-positive rate close to the test set's true positive rate (0.327) indicates the model is discriminating between classes rather than defaulting to the majority class — check this figure before trusting accuracy/precision/recall on an imbalanced set like this one.
