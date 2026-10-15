# PPCH Framework

**Predictive and Proactive Code Health** — a Sense → Analyze → Act framework that predicts
when a Java pull request will increase cognitive complexity, and proposes a verified,
automated refactoring before it merges. Final-year dissertation research, IM/2021/028,
University of Kelaniya.

Trained and evaluated on a real, 334-PR dataset built from `apache/commons-lang`'s PR
history, and deployed as a working, installable GitHub Action.

## Why

Cognitive complexity accumulates quietly in a codebase, one merged PR at a time, and is
normally only caught *after* the fact — a nightly or CI static-analysis scan flags it once
it's already in `master`. This framework moves detection to the moment a PR is opened,
and pairs it with an automated refactoring engine that proposes a fix a reviewer can
inspect immediately, rather than leaving complexity-reduction entirely to manual
intervention later.

## How it works

**Sense** — mines PR history through the GitHub REST API and runs SonarScanner on
isolated before/after snapshots of each PR's base and head commits, building a
leakage-safe dataset of 334 real PRs (structural, process, textual, and complexity
features — nothing derived from information only available after the PR was reviewed).

**Analyze** — four supervised classifiers (Random Forest, XGBoost, Multinomial Naive
Bayes, Logistic Regression) are trained on a temporal split (233 chronologically earliest
PRs for training, 101 most recent held out for testing) to predict, at submission time,
whether an incoming PR is likely to significantly increase complexity. The deployed
GitHub Action currently runs Random Forest + XGBoost as a live ensemble.

**Act** — when either the predictive model or a direct structural check flags a PR, an
ILP-based Extract Method engine (else-if flattening → branch-split → iterative extraction)
proposes a refactoring, gated behind four safety checks (return-forwarding,
break/continue, independent-variable-mutation, and a non-productive-extraction guard).
Every applied suggestion is independently re-verified against a real SonarQube scan — not
the framework's own internal complexity estimate.

## Results

| Metric | Result | Source |
|---|---:|---|
| Training dataset | 334 real PRs (from 1,767 scraped, 497 scanned) | `evaluation/phase2_training_results.md` |
| Best model (bootstrap mean AUC) | **Logistic Regression — 0.780** (95% CI [0.709, 0.847]) | `evaluation/bootstrap_results.md` |
| Other models (bootstrap mean AUC) | Random Forest 0.746, XGBoost 0.750, Naive Bayes 0.660 | `evaluation/bootstrap_results.md` |
| Dominant predictive feature family | `structural_size` | `evaluation/ablation_results.md` |
| Mean detection-time improvement vs. a reactive scanner | **82.4 hours** (median 12.9h), across 52 real merged, complexity-increasing PRs | `evaluation/mttd_mttr_benchmark.md` |
| Realistic pre-merge catch rate | **42.3%** (22 of 52) — the model's actual accuracy, not an assumed 100% | `evaluation/mttd_mttr_benchmark.md` |
| Refactoring safety (historical + live cases) | 10 applied, all independently confirmed safe by SonarQube re-scan; 4 correctly declined by the return-forwarding safety check; 0 unsafe applications | `evaluation/pr_suggestion_verification_summary.json` |

Every number above is reproducible from its source file or by re-running the generating
script in `evaluation/`.

## Live deployment

Installed as a GitHub Action on a real fork (`Manditha77/commons-text`), triggered on
`pull_request` events, posting a real PR comment end-to-end — not a replay of historical
data. Two live demonstrations: a single-file PR where a method's complexity was reduced
from 83 to under 15 across four successive extractions, and a multi-file PR demonstrating
independent, per-file complexity reporting and resolution.

### Installing it on your own repository

```yaml
# .github/workflows/ppch.yml
on: pull_request

jobs:
  ppch:
    runs-on: self-hosted   # or a hosted runner with a reachable SonarQube instance
    steps:
      - uses: actions/checkout@v4
      - uses: Manditha77/ppch-framework@main
        with:
          sonar-token: ${{ secrets.SONAR_TOKEN }}
          sonar-host-url: "http://localhost:9000"
          post-comment: "true"   # defaults to false; a local report is always written
```

A JSON/Markdown prediction report is always written as a build artifact
(`evaluation/live_action_runs/`), independent of comment-posting. The Action is idempotent
— it edits its own previous comment on a PR rather than posting a new one per commit.

**Scope caveat:** the trained models were fit only on `apache/commons-lang` PR data.
Running the Action on a different repository is mechanically supported — every feature is
computed fresh, live — but the resulting `risk_score` is out-of-distribution for the
model and should be treated as illustrative, not calibrated, until retrained on that
repository's own history.

## Project structure

```
sense/      PR-history mining, SonarQube scanning, feature-table construction
analyze/    Model training, bootstrap validation, ablation study
act/        ILP refactoring engine, safety checks, live GitHub Action entrypoint
evaluation/ Generated results (bootstrap/ablation/MTTD reports, safety-verification data)
docs/       Full dissertation chapters and supporting material
action.yml  The packaged, installable GitHub Action definition
```

## Setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv311
. .\.venv311\Scripts\Activate.ps1

# 2. Install dependencies
python -m pip install -r requirements.txt

# 3. Add your GitHub token
Copy-Item .env.example .env
# then open .env and paste your token after GITHUB_TOKEN=
```

Reproducing the full pipeline, in order:

```bash
python sense/scripts/01_fetch_pr_metadata.py --target pilot   # mine PR history
python sense/scripts/02_scan_pilot_batch.py                   # SonarQube before/after scans
python sense/scripts/03_build_feature_table.py --all          # build the labeled dataset
python sense/scripts/04_enrich_process_features.py            # contributor history features
python sense/scripts/05_compute_textual_embeddings.py         # BERT + Word2Vec embeddings
python analyze/train_models.py                                # train the deployed models
python analyze/run_bootstrap.py                                # bootstrap validation
python analyze/run_ablation.py                                 # feature-family ablation
python evaluation/run_mttd_mttr_benchmark.py                   # RQ3 benchmark
```

Each step is resumable — if interrupted (rate limit, network, Ctrl+C), re-run the same
command to pick up where it left off.

## Limitations

- Validated on a single repository (`apache/commons-lang`); live deployment on a
  different repository is mechanically supported but out-of-distribution for the model.
- The safety-verification evidence base (14 cases) demonstrates the safety mechanism
  functions correctly, but is not large enough to support a population-level safety-rate
  claim.
- Cognitive complexity (SSCC) is the sole complexity metric used; slice-based metrics
  from the original research proposal remain unimplemented.
- The live GitHub Action's deployed ensemble (Random Forest + XGBoost) predates the
  later-added Naive Bayes/Logistic Regression comparison; integrating the
  best-performing model (Logistic Regression) into the live path is a identified next
  step, not yet completed.

See the full dissertation (`docs/`) for the complete methodology, related work, and
discussion.
