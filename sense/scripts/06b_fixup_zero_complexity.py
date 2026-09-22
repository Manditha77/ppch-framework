"""
Phase I.9b — targeted retry pass for max_touched_method_complexity.

06_compute_touched_code_complexity.py's backfill ran across an unreliable
network connection (two separate runs both hit mid-run DNS resolution
failures to raw.githubusercontent.com - a real, observed intermittent
connectivity issue on this machine, not a one-off). Its per-file fetch
failures are swallowed (logged, not fatal) so one bad file doesn't kill an
otherwise-good PR's computation - but that means a PR where EVERY file
happened to fail is silently indistinguishable from a PR that genuinely has
0.0 complexity (e.g. a single trivial one-line change).

This script finds every PR whose recorded max_touched_method_complexity is
exactly 0.0 AND which genuinely had changed_java_files (so a 0.0 is
suspicious, not simply "no Java files touched"), and retries fetching with
real backoff - distinguishing a genuine 404 (the commit is unreachable,
e.g. from a squash-merge where the original head_sha was garbage-collected
- a real, unfixable data-availability limit, not a bug) from a transient
connection error (DNS hiccup, reset - worth retrying).

Usage:
    python 06b_fixup_zero_complexity.py
"""

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "sense" / "data" / "raw"
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
SCAN_RESULTS_PATH = RAW_DIR / "pilot_scan_results.jsonl"

sys.path.insert(0, str(ROOT / "act" / "ilp-engine"))
from java_statement_extractor import max_complexity_across_sources  # noqa: E402

GITHUB_OWNER = "apache"
GITHUB_REPO = "commons-lang"
RAW_BASE = "https://raw.githubusercontent.com"
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 3


def fetch_with_retry(owner: str, repo: str, sha: str, file_path: str) -> str | None:
    """Returns the file's content, or None if it's a genuine 404 (not
    retried - a 404 means the commit/file is unreachable, not that the
    network hiccuped). Transient errors (connection/DNS) get up to
    MAX_ATTEMPTS with linear backoff before giving up."""
    url = f"{RAW_BASE}/{owner}/{repo}/{sha}/{file_path}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError:
            return None  # any other real HTTP error status - not a network issue, don't retry
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt == MAX_ATTEMPTS:
                print(f"    [give up] {file_path}@{sha[:10]} after {MAX_ATTEMPTS} attempts: {exc}")
                return None
            print(f"    [retry {attempt}/{MAX_ATTEMPTS}] {file_path}@{sha[:10]}: {exc}")
            time.sleep(BACKOFF_SECONDS * attempt)
    return None


def load_scan_index() -> dict:
    index = {}
    with SCAN_RESULTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            number = record.get("number")
            if number is not None:
                index[number] = record
    return index


def main() -> None:
    scan_index = load_scan_index()

    suspects = []
    for path in sorted(PROCESSED_DIR.glob("pr_*/feature_table.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("max_touched_method_complexity") != 0.0:
            continue
        number = row.get("pr_number")
        record = scan_index.get(number)
        if record and record.get("changed_java_files"):
            suspects.append((number, path, record))

    print(f"Found {len(suspects)} PR(s) with max_touched_method_complexity == 0.0 "
          f"despite having changed_java_files - re-checking with retries.")

    fixed = 0
    confirmed_genuine = 0
    still_unreachable = 0
    for number, path, record in suspects:
        head_sha = record["head_sha"]
        sources = []
        any_genuine_404 = False
        any_success = False
        for file_path in record["changed_java_files"]:
            content = fetch_with_retry(GITHUB_OWNER, GITHUB_REPO, head_sha, file_path)
            if content is None:
                any_genuine_404 = True
            else:
                any_success = True
                sources.append(content)

        value = max_complexity_across_sources(sources)
        if any_success:
            row = json.loads(path.read_text(encoding="utf-8"))
            if value != row.get("max_touched_method_complexity"):
                row["max_touched_method_complexity"] = value
                path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
                fixed += 1
                print(f"  [fixed] PR #{number}: 0.0 -> {value}")
            else:
                confirmed_genuine += 1
        elif any_genuine_404:
            confirmed_genuine += 1
        else:
            still_unreachable += 1
            print(f"  [still failing] PR #{number}: every file still unreachable after retries")

    print(f"\nDone. {fixed} corrected, {confirmed_genuine} confirmed genuinely 0.0/unreachable, "
          f"{still_unreachable} still failing after retries.")


if __name__ == "__main__":
    main()
