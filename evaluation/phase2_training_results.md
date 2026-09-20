# Phase II Training Results (SMOTE-balanced)

Temporal holdout results on a 334-row dataset (single-project, apache/commons-lang). SMOTE was applied to the TRAINING partition only; the test partition is the real, untouched class distribution. Four baselines are compared: Random Forest, XGBoost, Multinomial Naive Bayes, and Logistic Regression (all named in Methodology §3.4.2). GCN/CNN/RNN deep-learning baselines are also named there but require genuinely new infrastructure (AST-to-graph construction, a torch training pipeline) and are explicitly out of scope given the dissertation timeline.

- Rows: 334
- Training rows: 233 (before SMOTE: {'0': 164, '1': 69}, after: {'1': 164, '0': 164})
- Test rows: 101 (positive=33, negative=68, true positive rate=0.327)

| Model | ROC AUC | Accuracy | Precision | Recall | F1 | Predicted-positive rate |
|---|---:|---:|---:|---:|---:|---:|
| random_forest | 0.652 | 0.703 | 0.636 | 0.212 | 0.318 | 0.109 |
| xgboost | 0.690 | 0.673 | 0.500 | 0.152 | 0.233 | 0.099 |
| naive_bayes | 0.638 | 0.713 | 0.643 | 0.273 | 0.383 | 0.139 |
| logistic_regression | 0.722 | 0.663 | 0.486 | 0.545 | 0.514 | 0.366 |

**Confusion matrices** (rows=actual, cols=predicted):

- **random_forest**: TN=64, FP=4, FN=26, TP=7
- **xgboost**: TN=63, FP=5, FN=28, TP=5
- **naive_bayes**: TN=63, FP=5, FN=24, TP=9
- **logistic_regression**: TN=49, FP=19, FN=15, TP=18

Post-submission complexity measurements (after/delta) were excluded from the
predictor matrix; complexity_before was correctly INCLUDED since it reflects
the target branch's state prior to the PR and is genuinely available at
submission time.

**Interpretation note:** Feature importance is reasonably distributed across the feature set in both models (top feature per model: random_forest: additions (0.21), xgboost: additions (0.18)), consistent with genuine multi-feature prediction rather than a single dominant signal.

A predicted-positive rate close to the test set's true positive rate (0.327) indicates the model is discriminating between classes rather than defaulting to the majority class — check this figure before trusting accuracy/precision/recall on an imbalanced set like this one.
