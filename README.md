# PPCH Framework — Implementation

Predictive and Proactive Code Health framework for Java Pull Requests.
IM/2021/028 · See `docs/00_implementation_plan.md` for the full phased plan.

## Setup (do this first, in VS Code's integrated PowerShell terminal)

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv311
. .\.venv311\Scripts\Activate.ps1

# 2. Install Phase I dependencies
python -m pip install -r requirements.txt

# 3. Add your GitHub token
Copy-Item .env.example .env
# then open .env and paste your token after GITHUB_TOKEN=
```

## Run the pilot extraction (Phase I.2)

```bash
python sense/scripts/01_fetch_pr_metadata.py --target pilot
```

This fetches all historical PRs (open, closed, merged — every outcome retained) from
`apache/commons-lang` and writes them to `sense/data/raw/apache_commons-lang_prs.jsonl`,
one JSON object per line. It's resumable — if it gets interrupted (rate limit, network,
Ctrl+C), just re-run the same command and it picks up where it left off.

**Expect this to take a while** — `commons-lang` has 2,000+ historical PRs and GitHub's
REST API is rate-limited to 5,000 authenticated requests/hour. The script sleeps
automatically when the quota runs low rather than failing.

## What's next

Once `apache_commons-lang_prs.jsonl` has data in it, we move to:
- **1.3–1.5**: checking out base/head commits per PR and running SonarScanner + srcSlice
- **1.6–1.8**: feature engineering and leakage-safe train/test split

Each step gets its own script in `sense/scripts/`, numbered in build order.
