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

**Reading this table:** a large negative Δ when a family is removed means that
family is essential; Δ near 0 means the model doesn't need it (often because
another family, or `baseline_complexity` in particular, already captures the
same signal). A family's standalone AUC shows how much it can predict on its own.
