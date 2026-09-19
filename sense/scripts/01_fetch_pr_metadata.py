"""
Phase I.2 — Data Extraction (Methodology 3.3.2)

Fetches historical Pull Request metadata for the target ASF Java project(s) using the
GitHub REST API (via PyGithub), and writes one JSON-Lines file per project to
sense/data/raw/<owner>_<repo>_prs.jsonl.

Design notes:
- Both accepted AND rejected/closed PRs are retained (state="all"), per methodology 3.3.1 —
  "no PR was excluded on the grounds of its outcome".
- Every field pulled here reflects information about the PR's lifecycle; it is the
  FEATURE-ENGINEERING step (01.x -> 06_build_feature_table.py, written later) that is
  responsible for separating "visible at submission time" fields from "post-submission"
  fields, per the leakage-prevention rule in methodology 3.3.2.
- Resumable: if the output file already has N lines, extraction picks up after the
  N-th PR number seen, so a rate-limit interruption doesn't force a restart from zero.
- Rate-limit aware: checks remaining quota before each page and sleeps until reset if
  the buffer gets low, rather than crashing.

Usage:
    python 01_fetch_pr_metadata.py --target pilot
    python 01_fetch_pr_metadata.py --target full_sample
    python 01_fetch_pr_metadata.py --owner apache --repo commons-lang   # single repo
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from github import Github, Auth
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]  # ppch-framework/
RAW_DIR = ROOT / "sense" / "data" / "raw"
PROJECT_LIST_PATH = RAW_DIR / "project_list.json"


def get_client() -> Github:
    load_dotenv(ROOT / ".env")
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN not found. Copy .env.example to .env in the project root "
            "and paste your personal access token in."
        )
    return Github(auth=Auth.Token(token), per_page=100)


def wait_for_rate_limit(gh: Github, buffer: int = 50):
    """Sleep until quota resets if remaining calls drop below `buffer`."""
    core = gh.get_rate_limit().core
    if core.remaining < buffer:
        reset_ts = core.reset.replace(tzinfo=timezone.utc).timestamp()
        sleep_for = max(0, reset_ts - datetime.now(timezone.utc).timestamp()) + 5
        print(f"\n[rate limit] {core.remaining} calls left — sleeping {sleep_for:.0f}s until reset...")
        time.sleep(sleep_for)


def pr_to_record(pr) -> dict:
    """Extract the fields we need from a PyGithub PullRequest object."""
    return {
        "number": pr.number,
        "title": pr.title,
        "body": pr.body or "",
        "state": pr.state,                      # open / closed
        "merged": pr.merged,
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
        "closed_at": pr.closed_at.isoformat() if pr.closed_at else None,
        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
        "user_login": pr.user.login if pr.user else None,
        "base_sha": pr.base.sha if pr.base else None,
        "head_sha": pr.head.sha if pr.head else None,
        "base_ref": pr.base.ref if pr.base else None,
        "additions": pr.additions,
        "deletions": pr.deletions,
        "changed_files": pr.changed_files,
        "commits": pr.commits,
        "comments": pr.comments,                 # issue-style discussion comments
        "review_comments": pr.review_comments,   # inline code review comments
        "labels": [l.name for l in pr.labels],
    }


def resume_point(out_path: Path) -> set:
    """Return the set of PR numbers already saved, so we can skip them."""
    if not out_path.exists():
        return set()
    seen = set()
    with open(out_path, "r") as f:
        for line in f:
            try:
                seen.add(json.loads(line)["number"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def fetch_project(gh: Github, owner: str, repo_name: str, domain: str):
    full_name = f"{owner}/{repo_name}"
    out_path = RAW_DIR / f"{owner}_{repo_name}_prs.jsonl"
    already_have = resume_point(out_path)

    print(f"\n=== {full_name} ({domain}) ===")
    if already_have:
        print(f"Resuming — {len(already_have)} PRs already saved to {out_path.name}")

    repo = gh.get_repo(full_name)
    pulls = repo.get_pulls(state="all", sort="created", direction="asc")
    total = pulls.totalCount
    print(f"Total PRs on GitHub: {total}")

    with open(out_path, "a") as f:
        for pr in tqdm(pulls, total=total, desc=full_name):
            if pr.number in already_have:
                continue
            wait_for_rate_limit(gh)
            try:
                record = pr_to_record(pr)
                record["domain"] = domain
                f.write(json.dumps(record) + "\n")
                f.flush()
            except Exception as e:
                print(f"\n[warn] Skipped PR #{pr.number} in {full_name}: {e}")
                continue


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["pilot", "full_sample"], help="Named group from project_list.json")
    parser.add_argument("--owner", help="Single repo owner, e.g. apache")
    parser.add_argument("--repo", help="Single repo name, e.g. commons-lang")
    parser.add_argument("--domain", default="unspecified", help="Domain tag for a single --owner/--repo run")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    gh = get_client()

    if args.owner and args.repo:
        projects = [{"owner": args.owner, "repo": args.repo, "domain": args.domain}]
    else:
        target = args.target or "pilot"
        with open(PROJECT_LIST_PATH) as f:
            projects = json.load(f)[target]

    for p in projects:
        fetch_project(gh, p["owner"], p["repo"], p["domain"])

    print("\nDone. Raw PR metadata written to sense/data/raw/*.jsonl")


if __name__ == "__main__":
    main()
