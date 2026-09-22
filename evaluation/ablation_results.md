# Phase II Ablation Study (RQ1)

Answers: *what are the most reliable predictors of cognitive-complexity
spikes in Java Pull Requests?* Same temporal train/test split as the main
training run.

**Feature-family note:** `textual_semantic` now includes real BERT
(sentence-transformers/all-MiniLM-L6-v2) and Word2Vec (trained on this
project's own PR corpus) embeddings, PCA-reduced to 5 dims each, alongside
the original `body_character_count`/`title_word_count` — closing the gap an
earlier version of this report flagged here (see
sense/scripts/05_compute_textual_embeddings.py).

## random_forest

Full-model AUC: **0.674**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.686 | +0.012 |
| structural_size | 0.612 | -0.062 |
| process | 0.695 | +0.022 |
| textual_semantic | 0.708 | +0.034 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.603 |
| structural_size | 0.692 |
| process | 0.506 |
| textual_semantic | 0.589 |

## xgboost

Full-model AUC: **0.703**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.682 | -0.021 |
| structural_size | 0.582 | -0.120 |
| process | 0.699 | -0.004 |
| textual_semantic | 0.724 | +0.021 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.623 |
| structural_size | 0.695 |
| process | 0.585 |
| textual_semantic | 0.525 |

## naive_bayes

Full-model AUC: **0.698**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.702 | +0.004 |
| structural_size | 0.672 | -0.026 |
| process | 0.612 | -0.086 |
| textual_semantic | 0.584 | -0.114 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.606 |
| structural_size | 0.695 |
| process | 0.513 |
| textual_semantic | 0.487 |

## logistic_regression

Full-model AUC: **0.753**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.735 | -0.018 |
| structural_size | 0.712 | -0.041 |
| process | 0.738 | -0.015 |
| textual_semantic | 0.744 | -0.009 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.628 |
| structural_size | 0.678 |
| process | 0.683 |
| textual_semantic | 0.580 |

**Reading this table:** a large negative Δ when a family is removed means that
family is essential; Δ near 0 means the model doesn't need it (often because
another family, or `baseline_complexity` in particular, already captures the
same signal). A family's standalone AUC shows how much it can predict on its own.

Four baselines compared: Random Forest, XGBoost, Multinomial Naive Bayes, and Logistic Regression (all named in Methodology §3.4.2). GCN/CNN/RNN deep-learning baselines are also named there but require genuinely new infrastructure (AST-to-graph construction, a torch training pipeline) and are explicitly out of scope given the dissertation timeline.
