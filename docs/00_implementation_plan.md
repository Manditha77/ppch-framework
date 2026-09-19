# PPCH Framework — Implementation Plan
**Predictive Analysis and Proactive Intervention for Mitigating Cognitive Complexity Accumulation in Java Pull Requests**
IM/2021/028 · Manditha Madushanka · Supervisor: Prof. Janaka Wijayanayake

This document translates Chapter 3 (Methodology) of the dissertation into a concrete, buildable
implementation plan. Each phase below maps 1:1 onto a section of the methodology so progress here
can be reported directly against the written proposal.

---

## 0. Project Structure

```
ppch-framework/
├── docs/                     # This plan + phase-by-phase build logs (for supervisor review)
├── sense/
│   ├── scripts/               # GitHub API extraction, SonarScanner runner, srcSlice runner
│   └── data/
│       ├── raw/                # Raw PR JSON, diffs, commit metadata
│       └── processed/          # Cleaned, feature-engineered dataset (train/test ready)
├── analyze/
│   ├── notebooks/              # EDA, model training, ablation studies
│   └── models/                 # Serialized trained models (RF, XGBoost, baselines)
├── act/
│   ├── github-action/          # The packaged GitHub Action (Sense+Analyze+Act at runtime)
│   └── ilp-engine/             # Integer Linear Programming "Extract Method" refactoring engine
├── evaluation/                 # Bootstrap validation, ablation, MTTD/MTTR benchmark, SUS results
└── tests/
```

---

## Phase I — SENSE: Data Acquisition & Feature Engineering
*(Methodology §3.3, §3.4.1 Sense layer)*

**Goal:** produce a leakage-free, labeled, multi-dimensional dataset of historical Java PRs.

| Step | Task | Output |
|---|---|---|
| 1.1 | Select target ASF Java projects (purposive sample: data-processing, web framework, infra library) | `sense/data/raw/project_list.json` |
| 1.2 | Extract PR metadata via GitHub REST/GraphQL (title, body, diff, files, timestamps, contributor history, review discussion) | `sense/data/raw/*_prs.jsonl` |
| 1.3 | Reconstruct pre-PR and post-PR codebase snapshots per PR (checkout base/head commit) | local git worktrees (not stored) |
| 1.4 | Run SonarScanner on both snapshots → method/class-level SSCC deltas + code smells (God Class, Long Method) | `sense/data/raw/sonar_*.json` |
| 1.5 | Run srcSlice on the same snapshots → sliceSize, sliceIdentifier, sliceSpatial | `sense/data/raw/slice_*.json` |
| 1.6 | Feature engineering: structural (LOC±, files changed, max nesting delta, ΔSSCC/method), process (tenure, prior acceptance rate, follower count), textual (BERT/Word2Vec embeddings of title+body) — **computed strictly from pre-submission state** | `sense/data/processed/features.parquet` |
| 1.7 | Label construction: does the PR's resulting SSCC exceed the repo threshold (default 15)? | `label` column in processed dataset |
| 1.8 | Data cleaning: log-transform heavy-tailed features; class-imbalance handling (SMOTE + VAE) on **training partition only** | `sense/data/processed/train.parquet`, `test.parquet` |

**Decision needed before coding starts:** which ASF repos, how many PRs, and whether you already have a GitHub token / rate-limit budget. See questions below.

---

## Phase II — ANALYZE: Predictive Modelling
*(Methodology §3.4.2, §3.5.1, §3.5.2)*

| Step | Task | Output |
|---|---|---|
| 2.1 | Train/test split with strict temporal ordering (avoid future leakage across PR history) | split indices |
| 2.2 | Train candidate models: Random Forest, XGBoost, Multinomial Naïve Bayes baseline, (optionally GCN/DL baseline) | `analyze/models/*.pkl` |
| 2.3 | Hyperparameter tuning via grid search | tuned model configs |
| 2.4 | Out-of-sample bootstrap validation, 1000 repeats → AUC, precision, recall, F1, calibration (target AUC > 0.80) — **answers RQ2** | `evaluation/bootstrap_results.json` |
| 2.5 | Ablation study: drop each feature family (structural / process / textual), retrain, record AUC drop — **answers RQ1** | `evaluation/ablation_results.json` |
| 2.6 | Feature-importance explanation (e.g. SHAP) for the "contributing features" shown in interventions | `analyze/models/explainer.pkl` |

---

## Phase III — ACT: Proactive Intervention Engine
*(Methodology §3.4.3, §3.4.4)*

| Step | Task | Output |
|---|---|---|
| 3.1 | Implement the ILP "Extract Method" formulation (objective: minimize SSCC subject to data-dependence/nesting/local-variable constraints) | `act/ilp-engine/extract_method.py` |
| 3.2 | Wrap Sense+Analyze+Act as a single inference pipeline callable at PR-submission time | `act/github-action/pipeline.py` |
| 3.3 | Package as a GitHub Action (`action.yml`) triggered on `pull_request: opened/synchronize` | `act/github-action/action.yml` |
| 3.4 | Idempotent PR comment logic (update existing bot comment rather than duplicate) | comment-management code |
| 3.5 | Two intervention types: predictive complexity warning (always) / ILP refactoring suggestion (only above configurable probability threshold) | — |

---

## Phase IV — EVALUATION
*(Methodology §3.5.3, §3.5.4, §3.5.5)*

| Step | Task | Output | RQ |
|---|---|---|---|
| 4.1 | Run same PR corpus through PPCH vs a reactive SonarQube-only baseline; compute MTTD, MTTR, % complex code merged | `evaluation/mttd_mttr.json` | RQ3 |
| 4.2 | Developer usability study (SUS questionnaire) on realistic PR scenarios | `evaluation/sus_results.csv` | RQ4 |
| 4.3 | Threats-to-validity write-up (construct/internal/external/conclusion) | `docs/threats_to_validity.md` | — |

---

## Immediate Next Step

Phase I, Steps 1.1–1.2 (target selection + GitHub extraction script) is the right place to start —
everything downstream depends on this dataset. Before writing code I need a few decisions from you
(see the questions in chat). Once confirmed, I'll build the extraction script in
`sense/scripts/` and we validate it on one small repo before scaling to the full sample.
