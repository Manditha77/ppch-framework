# Phase II Ablation Study (RQ1)

Answers: *what are the most reliable predictors of cognitive-complexity
spikes in Java Pull Requests?* Same temporal train/test split as the main
training run.

**Feature-family caveat:** `textual_proxy` here is `body_character_count` and
`title_word_count` — placeholders for the BERT/Word2Vec embeddings specified
in Methodology §3.3.3, which are not yet implemented.

## random_forest

Full-model AUC: **0.798**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.726 | -0.071 |
| structural_size | 0.702 | -0.095 |
| process | 0.893 | +0.095 |
| textual_proxy | 0.774 | -0.024 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.726 |
| structural_size | 0.738 |
| process | 0.667 |
| textual_proxy | 0.714 |

## xgboost

Full-model AUC: **0.786**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.679 | -0.107 |
| structural_size | 0.726 | -0.059 |
| process | 0.869 | +0.083 |
| textual_proxy | 0.762 | -0.024 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.732 |
| structural_size | 0.815 |
| process | 0.565 |
| textual_proxy | 0.655 |

**Reading this table:** a large negative Δ when a family is removed means that
family is essential; Δ near 0 means the model doesn't need it (often because
another family, or `baseline_complexity` in particular, already captures the
same signal). A family's standalone AUC shows how much it can predict on its own.
