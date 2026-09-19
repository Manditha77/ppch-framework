# Phase II Bootstrap Validation (RQ2)

Out-of-sample bootstrap validation, 1000 requested iterations, on 62 rows. Answers: *what accuracy can supervised ML achieve in predicting smelly/complex PRs at submission time?*

A-priori target: AUC > 0.8

| Model | Valid iterations | Mean AUC | Median AUC | Std | 95% CI |
|---|---:|---:|---:|---:|---|
| random_forest | 1000/1000 | 0.721 | 0.726 | 0.104 | [0.493, 0.905] |
| xgboost | 1000/1000 | 0.682 | 0.690 | 0.116 | [0.437, 0.898] |

Bootstrap validation on a 62-row dataset. The a-priori target AUC > 0.80 (Methodology §3.5.1) is a pipeline-validation checkpoint here, not a dissertation-level claim - scale the Sense-phase sample before reporting these figures as final.

SMOTE was NOT applied inside each bootstrap iteration (some bags would have too few minority examples for it to run reliably); iterations with a single-class bag or out-of-bag set are skipped and counted separately.
