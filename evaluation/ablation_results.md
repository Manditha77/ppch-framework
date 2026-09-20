# Phase II Ablation Study (RQ1)

Answers: *what are the most reliable predictors of cognitive-complexity
spikes in Java Pull Requests?* Same temporal train/test split as the main
training run.

**Feature-family caveat:** `textual_proxy` here is `body_character_count` and
`title_word_count` — placeholders for the BERT/Word2Vec embeddings specified
in Methodology §3.3.3, which are not yet implemented.

## random_forest

Full-model AUC: **0.679**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.659 | -0.020 |
| structural_size | 0.550 | -0.129 |
| process | 0.710 | +0.032 |
| textual_proxy | 0.695 | +0.017 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.553 |
| structural_size | 0.692 |
| process | 0.506 |
| textual_proxy | 0.511 |

## xgboost

Full-model AUC: **0.711**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.702 | -0.009 |
| structural_size | 0.598 | -0.113 |
| process | 0.706 | -0.005 |
| textual_proxy | 0.745 | +0.034 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.560 |
| structural_size | 0.695 |
| process | 0.585 |
| textual_proxy | 0.479 |

## naive_bayes

Full-model AUC: **0.649**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.668 | +0.020 |
| structural_size | 0.655 | +0.006 |
| process | 0.584 | -0.065 |
| textual_proxy | 0.595 | -0.054 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.500 |
| structural_size | 0.695 |
| process | 0.513 |
| textual_proxy | 0.470 |

## logistic_regression

Full-model AUC: **0.720**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.707 | -0.013 |
| structural_size | 0.720 | +0.000 |
| process | 0.701 | -0.019 |
| textual_proxy | 0.720 | +0.000 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.576 |
| structural_size | 0.678 |
| process | 0.683 |
| textual_proxy | 0.541 |

**Reading this table:** a large negative Δ when a family is removed means that
family is essential; Δ near 0 means the model doesn't need it (often because
another family, or `baseline_complexity` in particular, already captures the
same signal). A family's standalone AUC shows how much it can predict on its own.

Four baselines compared: Random Forest, XGBoost, Multinomial Naive Bayes, and Logistic Regression (all named in Methodology §3.4.2). GCN/CNN/RNN deep-learning baselines are also named there but require genuinely new infrastructure (AST-to-graph construction, a torch training pipeline) and are explicitly out of scope given the dissertation timeline.
