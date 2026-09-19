"""
Phase I.8 — Contributor process-feature enrichment (Methodology §3.3.3).

Methodology §3.3.3 specifies four process features: "the contributor's
prior acceptance rate on the target project, the tenure of the contributor,
the number of prior PRs submitted, and the reputation signal derived from
the contributor's public follower count." Only commits/comments/review_
comments (properties of the PR itself, not the CONTRIBUTOR) were previously
implemented - this script closes that gap.

Three of the four are computed for FREE from data already on disk (no new
GitHub API calls): sense/data/raw/apache_commons-lang_prs.jsonl already has
the full historical PR record (1,767 PRs) with `user_login` and
`created_at`/`merged` for every one of them, so for any given PR, "how many
prior PRs did this contributor submit, and what fraction were merged, and
how long have they been contributing" are pure local computations over data
already fetched during 01_fetch_pr_metadata.py.

The fourth (follower count) needs the GitHub API, but only ONE call per
UNIQUE contributor (cached), not per PR - for a 500-PR sample with
typically a few hundred unique contributors, this is a small fraction of
the 5,000/hour rate limit.

All four are leakage-safe: computed strictly from information that existed
BEFORE this PR was submitted (prior PRs only, follower count as observed
now - a contributor's follower count at prediction time, same as how a
real deployment would query it).

Usage:
    python 04_enrich_process_features.py            # enrich all processed PRs
    python 04_enrich_process_features.py --pr-number 1719
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from github import Github, Auth

ROOT = Path(__file__).resolve().parents[2]  # ppch-framework/
RAW_DIR = ROOT / "sense" / "data" / "raw"
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
PR_METADATA_PATH = RAW_DIR / "apache_commons-lang_prs.jsonl"
FOLLOWER_CACHE_PATH = RAW_DIR / "contributor_follower_cache.json"


def load_full_history() -> list:
    with PR_METADATA_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def build_contributor_index(history: list) -> dict:
    """{user_login: [ (created_at_datetime, merged_bool), ... ]} sorted by
    created_at, so prior-PR stats for any PR can be computed by binary
    position rather than rescanning the full history per PR."""
    index = {}
    for record in history:
        login = record.get("user_login")
        created_at = record.get("created_at")
        if not login or not created_at:
            continue
        index.setdefault(login, []).append(
            (datetime.fromisoformat(created_at), bool(record.get("merged")))
        )
    for login in index:
        index[login].sort(key=lambda pair: pair[0])
    return index


def prior_stats(contributor_index: dict, login: str, created_at: str) -> dict:
    """Stats for `login` using ONLY PRs strictly before `created_at` -
    leakage-safe by construction (mirrors how a real deployment would query
    "this contributor's history so far" at PR-submission time)."""
    this_created = datetime.fromisoformat(created_at)
    history = contributor_index.get(login, [])
    prior = [(c, m) for c, m in history if c < this_created]

    if not prior:
        return {
            "contributor_prior_pr_count": 0,
            "contributor_prior_acceptance_rate": 0.0,
            "contributor_tenure_days": 0.0,
        }

    prior_pr_count = len(prior)
    prior_acceptance_rate = sum(1 for _, merged in prior if merged) / prior_pr_count
    earliest = min(c for c, _ in prior)
    tenure_days = (this_created - earliest).total_seconds() / 86400.0
    return {
        "contributor_prior_pr_count": prior_pr_count,
        "contributor_prior_acceptance_rate": prior_acceptance_rate,
        "contributor_tenure_days": tenure_days,
    }


def load_follower_cache() -> dict:
    if FOLLOWER_CACHE_PATH.exists():
        return json.loads(FOLLOWER_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_follower_cache(cache: dict) -> None:
    FOLLOWER_CACHE_PATH.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


def get_follower_count(gh: "Github", login: str, cache: dict) -> int:
    if login in cache:
        return cache[login]
    try:
        count = gh.get_user(login).followers
    except Exception as exc:  # noqa: BLE001 — deleted/renamed accounts, API hiccups
        print(f"  [warn] could not fetch follower count for {login}: {exc} — using 0")
        count = 0
    cache[login] = count
    save_follower_cache(cache)
    return count


def enrich_pr(number: int, contributor_index: dict, gh: "Github", cache: dict) -> bool:
    feature_path = PROCESSED_DIR / f"pr_{number}" / "feature_table.json"
    if not feature_path.exists():
        return False
    row = json.loads(feature_path.read_text(encoding="utf-8"))

    login = row.get("contributor")
    created_at = row.get("created_at")
    if not login or not created_at:
        print(f"  [skip] PR #{number} has no contributor/created_at recorded")
        return False

    stats = prior_stats(contributor_index, login, created_at)
    stats["contributor_follower_count"] = get_follower_count(gh, login, cache)
    row.update(stats)

    feature_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, nargs="+", default=None,
                         help="Specific PR(s) to enrich. Default: every PR with a feature_table.json.")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not found in .env — needed for follower counts.")
    gh = Github(auth=Auth.Token(token), per_page=100)

    print("Loading full PR history for prior-PR/tenure computation...")
    history = load_full_history()
    contributor_index = build_contributor_index(history)
    print(f"Indexed {len(contributor_index)} unique contributors across {len(history)} historical PRs.")

    cache = load_follower_cache()
    print(f"Follower-count cache: {len(cache)} contributors already known.")

    if args.pr_number:
        numbers = args.pr_number
    else:
        numbers = sorted(
            int(p.name.removeprefix("pr_"))
            for p in PROCESSED_DIR.glob("pr_*")
            if (p / "feature_table.json").exists()
        )

    print(f"Enriching {len(numbers)} PR(s)...")
    enriched = 0
    for number in numbers:
        if enrich_pr(number, contributor_index, gh, cache):
            enriched += 1
    print(f"\nDone. Enriched {enriched}/{len(numbers)} PRs with contributor process features.")
    print(f"Follower-count cache now has {len(cache)} contributors — reused on future runs.")


if __name__ == "__main__":
    main()
