"""
Phase I.9 — max_touched_method_complexity backfill.

Closes a real gap found via a live self-hosted-runner test (2026-09-22, see
act/ilp-engine/java_statement_extractor.py::max_complexity_across_sources'
own docstring for the full story): the Analyze layer's only complexity
feature, complexity_before, is computed from a file's PRE-PR state, which is
always 0 for a brand-new file - so a genuinely complex brand-new file was
invisible to the trained model regardless of its actual structure.

This script retroactively computes max_touched_method_complexity for every
already-processed historical PR: the highest single-method Campbell-rule
complexity (this framework's own AST-based approximation, already used
throughout the Act layer) found across every Java file the PR touched, at
HEAD (post-PR) state - independent of whether any pre-PR baseline exists.
Only re-fetches raw file content already publicly available at each PR's
own head_sha (via raw.githubusercontent.com, no GitHub API calls, no rate
limit) - no local clone or SonarQube rescan needed, since this is a pure
AST-parsing computation, not a SonarQube measurement.

Leakage-safe: HEAD is the PR's own proposed content, exactly what a real
pre-merge review would see (this PR's diff itself, not anything about its
outcome) - not different in kind from reading additions/deletions, which
are already legitimate pre-submission features.

Usage:
    python 06_compute_touched_code_complexity.py            # backfill all
    python 06_compute_touched_code_complexity.py --pr-number 1719
"""

import argparse
import functools
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]  # ppch-framework/
RAW_DIR = ROOT / "sense" / "data" / "raw"
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
SCAN_RESULTS_PATH = RAW_DIR / "pilot_scan_results.jsonl"

sys.path.insert(0, str(ROOT / "act" / "ilp-engine"))
from java_statement_extractor import max_complexity_across_sources  # noqa: E402

GITHUB_OWNER = "apache"
GITHUB_REPO = "commons-lang"
RAW_BASE = "https://raw.githubusercontent.com"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 3

print = functools.partial(print, flush=True)  # noqa: A001 - this run's own DNS flakiness made
# buffered output indistinguishable from a hang for ~15 real minutes; every print here must
# be immediately visible, not just at process exit.


def fetch_with_retry(owner: str, repo: str, sha: str, file_path: str) -> str | None:
    """Returns file content, or None if genuinely unreachable (a real 404 -
    e.g. this commit was garbage-collected after a squash-merge - is NOT
    retried, since retrying won't change that). Transient errors (DNS
    failures, connection resets - a real, observed intermittent issue on
    this machine, not hypothetical) get up to MAX_ATTEMPTS with backoff."""
    url = f"{RAW_BASE}/{owner}/{repo}/{sha}/{file_path}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError:
            return None
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt == MAX_ATTEMPTS:
                print(f"    [give up] {file_path}@{sha[:10]} after {MAX_ATTEMPTS} attempts: {exc}")
                return None
            time.sleep(BACKOFF_SECONDS)
    return None


def load_scan_index() -> dict:
    """{pr_number: {"head_sha": ..., "changed_java_files": [...]}} - the
    same raw scan records the rest of the Sense/Act layers already use, just
    indexed by number for direct lookup instead of a linear scan per PR."""
    index = {}
    with SCAN_RESULTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            number = record.get("number")
            if number is not None:
                index[number] = record
    return index


def compute_for_pr(number: int, scan_index: dict) -> float | None:
    """Returns max_touched_method_complexity for PR `number`, or None if no
    scan record / no Java files to fetch (caller decides the fallback -
    0.0 is a legitimate value, so this distinguishes "computed as 0" from
    "could not compute at all")."""
    record = scan_index.get(number)
    if not record:
        return None
    changed_java_files = record.get("changed_java_files") or []
    head_sha = record.get("head_sha")
    if not changed_java_files or not head_sha:
        return 0.0

    sources = []
    for file_path in changed_java_files:
        content = fetch_with_retry(GITHUB_OWNER, GITHUB_REPO, head_sha, file_path)
        if content is not None:
            sources.append(content)
    return max_complexity_across_sources(sources)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr-number", type=int, nargs="+", default=None,
                         help="Specific PR(s) to backfill. Default: every PR with a feature_table.json.")
    args = parser.parse_args()

    scan_index = load_scan_index()
    print(f"Loaded {len(scan_index)} scan records from {SCAN_RESULTS_PATH.name}.")

    if args.pr_number:
        numbers = args.pr_number
    else:
        numbers = sorted(
            int(p.name.removeprefix("pr_"))
            for p in PROCESSED_DIR.glob("pr_*")
            if (p / "feature_table.json").exists()
        )

    print(f"Backfilling max_touched_method_complexity for {len(numbers)} PR(s)...")
    computed = 0
    skipped = 0
    for number in numbers:
        feature_path = PROCESSED_DIR / f"pr_{number}" / "feature_table.json"
        if not feature_path.exists():
            skipped += 1
            continue
        value = compute_for_pr(number, scan_index)
        if value is None:
            print(f"  [skip] PR #{number}: no scan record found")
            skipped += 1
            continue
        row = json.loads(feature_path.read_text(encoding="utf-8"))
        row["max_touched_method_complexity"] = value
        feature_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        computed += 1
        if computed % 10 == 0:
            print(f"  ... {computed}/{len(numbers)} done (PR #{number})")

    print(f"\nDone. Computed for {computed}/{len(numbers)} PRs ({skipped} skipped).")


if __name__ == "__main__":
    main()
