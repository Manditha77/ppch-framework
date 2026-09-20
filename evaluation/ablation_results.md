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

Full-model AUC: **0.657**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.686 | +0.029 |
| structural_size | 0.589 | -0.068 |
| process | 0.692 | +0.035 |
| textual_semantic | 0.695 | +0.038 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.553 |
| structural_size | 0.692 |
| process | 0.506 |
| textual_semantic | 0.589 |

## xgboost

Full-model AUC: **0.705**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.682 | -0.023 |
| structural_size | 0.574 | -0.131 |
| process | 0.687 | -0.018 |
| textual_semantic | 0.745 | +0.040 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.560 |
| structural_size | 0.695 |
| process | 0.585 |
| textual_semantic | 0.525 |

## naive_bayes

Full-model AUC: **0.691**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.702 | +0.011 |
| structural_size | 0.664 | -0.027 |
| process | 0.599 | -0.092 |
| textual_semantic | 0.595 | -0.096 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.500 |
| structural_size | 0.695 |
| process | 0.513 |
| textual_semantic | 0.487 |

## logistic_regression

Full-model AUC: **0.739**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.735 | -0.004 |
| structural_size | 0.729 | -0.010 |
| process | 0.722 | -0.017 |
| textual_semantic | 0.720 | -0.019 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.576 |
| structural_size | 0.678 |
| process | 0.683 |
| textual_semantic | 0.580 |

**Reading this table:** a large negative Δ when a family is removed means that
family is essential; Δ near 0 means the model doesn't need it (often because
another family, or `baseline_complexity` in particular, already captures the
same signal). A family's standalone AUC shows how much it can predict on its own.

Four baselines compared: Random Forest, XGBoost, Multinomial Naive Bayes, and Logistic Regression (all named in Methodology §3.4.2). GCN/CNN/RNN deep-learning baselines are also named there but require genuinely new infrastructure (AST-to-graph construction, a torch training pipeline) and are explicitly out of scope given the dissertation timeline.
