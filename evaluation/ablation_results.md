# Phase II Ablation Study (RQ1)

Answers: *what are the most reliable predictors of cognitive-complexity
spikes in Java Pull Requests?* Same temporal train/test split as the main
training run.

**Feature-family caveat:** `textual_proxy` here is `body_character_count` and
`title_word_count` — placeholders for the BERT/Word2Vec embeddings specified
in Methodology §3.3.3, which are not yet implemented.

## random_forest

Full-model AUC: **0.911**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.911 | +0.000 |
| structural_size | 0.625 | -0.286 |
| process | 0.893 | -0.018 |
| textual_proxy | 0.869 | -0.042 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.726 |
| structural_size | 0.732 |
| process | 0.405 |
| textual_proxy | 0.738 |

## xgboost

Full-model AUC: **0.917**

| Family removed | AUC without family | Δ vs full |
|---|---:|---:|
| baseline_complexity | 0.929 | +0.012 |
| structural_size | 0.750 | -0.167 |
| process | 0.869 | -0.048 |
| textual_proxy | 0.881 | -0.036 |

| Family alone | Standalone AUC |
|---|---:|
| baseline_complexity | 0.732 |
| structural_size | 0.815 |
| process | 0.411 |
| textual_proxy | 0.655 |

**Reading this table:** a large negative Δ when a family is removed means that
family is essential; Δ near 0 means the model doesn't need it (often because
another family, or `baseline_complexity` in particular, already captures the
same signal). A family's standalone AUC shows how much it can predict on its own.
