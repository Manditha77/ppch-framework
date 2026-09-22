# Phase II Bootstrap Validation (RQ2)

Out-of-sample bootstrap validation, 1000 requested iterations, on 334 rows. Answers: *what accuracy can supervised ML achieve in predicting smelly/complex PRs at submission time?*

A-priori target: AUC > 0.8

| Model | Valid iterations | Mean AUC | Median AUC | Std | 95% CI |
|---|---:|---:|---:|---:|---|
| random_forest | 1000/1000 | 0.746 | 0.747 | 0.039 | [0.666, 0.818] |
| xgboost | 1000/1000 | 0.750 | 0.752 | 0.037 | [0.675, 0.817] |
| naive_bayes | 1000/1000 | 0.660 | 0.666 | 0.066 | [0.518, 0.770] |
| logistic_regression | 1000/1000 | 0.780 | 0.781 | 0.036 | [0.709, 0.847] |

Bootstrap validation on a 334-row dataset. The a-priori target AUC > 0.80 (Methodology §3.5.1) is a pipeline-validation checkpoint here, not a dissertation-level claim - scale the Sense-phase sample before reporting these figures as final.

SMOTE was NOT applied inside each bootstrap iteration (some bags would have too few minority examples for it to run reliably); iterations with a single-class bag or out-of-bag set are skipped and counted separately.

Four baselines compared: Random Forest, XGBoost, Multinomial Naive Bayes, and Logistic Regression (all named in Methodology §3.4.2). GCN/CNN/RNN deep-learning baselines are also named there but require genuinely new infrastructure (AST-to-graph construction, a torch training pipeline) and are explicitly out of scope given the dissertation timeline.
