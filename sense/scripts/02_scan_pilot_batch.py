"""
Phase I.3-1.5 — Pilot Batch Complexity Scanning (Methodology 3.3.2, 3.3.3)

IMPORTANT SCOPING NOTE (see docs/04_phase1_full_progress_bilingual.md §A.7):
This script measures cognitive complexity SCOPED TO THE FILES EACH PR ACTUALLY CHANGED,
not the whole-project total. Whole-project totals would bury a PR's real contribution
under years of pre-existing baseline complexity on a mature codebase like commons-lang,
producing a noisy, practically meaningless delta. The methodology (proposal §1.2.2,
dissertation §3.3.3) explicitly specifies complexity at the method/modified-file level,
not project-wide — this script now matches that design.

For a randomly sampled batch of PRs (default 150, drawn from the most recent ~2 years of
project history), this script:

  1. Selects the sample (reproducibly, via a fixed random seed) and saves the sample list
     to a size-specific file (pilot_sample_<N>.jsonl), so different sample sizes never
     collide or silently reuse a stale, smaller sample.
  2. For each PR: identifies which .java files the PR actually changed, via `git diff`
     between base_sha and head_sha (no GitHub API call needed — uses the local clone).
  3. Checks out base_sha and head_sha in turn (falling back to `git fetch <sha>` for
     commits not present in a standard clone — the issue discovered during manual testing).
  4. Runs SonarScanner against each full snapshot with a unique project key (the tool
     always analyzes the whole tree — that's unavoidable), but only QUERIES the
     per-file cognitive_complexity measure for the files identified in step 2.
  5. Sums those file-level complexity values before and after → the delta is scoped to
     what the PR actually changed. This becomes the prediction label later.
  6. Deletes the scanned SonarQube projects via the API to keep the server tidy.
  7. Appends one JSON record per PR to sense/data/raw/pilot_scan_results.jsonl
     (resumable — already-scanned PR numbers are skipped on re-run, across ANY sample
     size, since the results file is shared and keyed by PR number).

Note on sample size: a 30-PR pilot run showed ~30% of PRs touch no .java files (no
complexity signal) and ~13% hit unreachable commits (see docs/04_phase1_full_progress_
bilingual.md §A.8 for why — squash-merged PRs from forks). At that ~57% usable rate,
150 sampled PRs yields roughly 85 usable labeled rows — enough to be a defensible pilot
training set, versus the 17 usable rows the original 30-PR sample produced.

PRs that touch no .java files (e.g. doc-only or build-config-only PRs) are recorded
with delta=None and a reason, since they carry no cognitive-complexity signal at all.

Prerequisites:
  - sense/data/raw/repo_commons-lang must already exist (git clone apache/commons-lang)
  - .env must have SONAR_TOKEN and SONAR_HOST_URL set
  - sonar-scanner must be on PATH

Usage:
    python 02_scan_pilot_batch.py                          # defaults to 150 PRs
    python 02_scan_pilot_batch.py --sample-size 150 --years 2 --seed 42
"""

import argparse
import json
import os
import platform
import random
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # ppch-framework/
RAW_DIR = ROOT / "sense" / "data" / "raw"
REPO_DIR = RAW_DIR / "repo_commons-lang"
PR_JSONL = RAW_DIR / "apache_commons-lang_prs.jsonl"
RESULTS_PATH = RAW_DIR / "pilot_scan_results.jsonl"


def sample_path_for(sample_size: int) -> Path:
    return RAW_DIR / f"pilot_sample_{sample_size}.jsonl"


def load_env():
    load_dotenv(ROOT / ".env")
    token = os.getenv("SONAR_TOKEN")
    host = os.getenv("SONAR_HOST_URL", "http://localhost:9000")
    if not token:
        raise RuntimeError("SONAR_TOKEN not found in .env — add it before running this script.")
    return token, host.rstrip("/")


# ---------------------------------------------------------------------------
# Step 1: sample selection
# ---------------------------------------------------------------------------

def select_sample(sample_size: int, years: int, seed: int) -> list:
    sample_path = sample_path_for(sample_size)
    if sample_path.exists():
        print(f"Sample already exists at {sample_path.name} — reusing it (delete the file to resample).")
        with open(sample_path) as f:
            return [json.loads(line) for line in f]

    with open(PR_JSONL) as f:
        all_prs = [json.loads(line) for line in f]

    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years)
    recent = [
        pr for pr in all_prs
        if pr.get("created_at") and datetime.fromisoformat(pr["created_at"]) >= cutoff
    ]
    print(f"{len(recent)} PRs found in the last {years} years (out of {len(all_prs)} total).")

    random.seed(seed)
    sample = random.sample(recent, min(sample_size, len(recent)))
    sample.sort(key=lambda pr: pr["number"])

    with open(sample_path, "w") as f:
        for pr in sample:
            f.write(json.dumps(pr) + "\n")
    print(f"Sampled {len(sample)} PRs (seed={seed}) -> saved to {sample_path.name}")
    return sample


# ---------------------------------------------------------------------------
# Step 2: ensure commits are present locally, and diff to find changed .java files
# ---------------------------------------------------------------------------

def ensure_commit_available(sha: str, repo_dir: Path = REPO_DIR) -> bool:
    check = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repo_dir, capture_output=True
    )
    if check.returncode == 0:
        return True
    r = subprocess.run(["git", "fetch", "origin", sha], cwd=repo_dir, capture_output=True, text=True)
    return r.returncode == 0


def get_changed_java_files(base_sha: str, head_sha: str, repo_dir: Path = REPO_DIR) -> list:
    if not (ensure_commit_available(base_sha, repo_dir) and ensure_commit_available(head_sha, repo_dir)):
        return []
    r = subprocess.run(
        ["git", "diff", "--name-only", base_sha, head_sha],
        cwd=repo_dir, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return []
    return [f for f in r.stdout.splitlines() if f.endswith(".java")]


def checkout_commit(sha: str, repo_dir: Path = REPO_DIR) -> bool:
    if not ensure_commit_available(sha, repo_dir):
        return False
    r = subprocess.run(["git", "checkout", sha], cwd=repo_dir, capture_output=True, text=True)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Step 3: run SonarScanner (always scans the whole tree — that's how the tool works;
# scoping happens at the QUERY stage below, not the scan stage)
# ---------------------------------------------------------------------------

def run_scanner(project_key: str, sonar_token: str, sonar_host: str, repo_dir: Path = REPO_DIR) -> bool:
    env = os.environ.copy()
    env["SONAR_HOST_URL"] = sonar_host
    env["SONAR_TOKEN"] = sonar_token

    r = subprocess.run(
        [
            "sonar-scanner",
            f"-Dsonar.projectKey={project_key}",
            f"-Dsonar.projectName={project_key}",
            "-Dsonar.sources=.",
            "-Dsonar.sourceEncoding=UTF-8",
        ],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        # On Windows, sonar-scanner is a .bat file — subprocess needs shell=True
        # to resolve it via PATH the same way typing the command in PowerShell does.
        shell=(platform.system() == "Windows"),
    )
    if "EXECUTION SUCCESS" not in r.stdout:
        print(f"    [scan] FAILED for {project_key}")
        print(r.stdout[-1500:])
        return False
    return True


# ---------------------------------------------------------------------------
# Step 4: poll the compute-engine task, then pull PER-FILE complexity for only
# the files this PR touched (this is the corrected, scoped query)
# ---------------------------------------------------------------------------

def read_ce_task_url(repo_dir: Path = REPO_DIR) -> str | None:
    report_file = repo_dir / ".scannerwork" / "report-task.txt"
    if not report_file.exists():
        return None
    props = {}
    for line in report_file.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    return props.get("ceTaskUrl")


def wait_for_processing(ce_task_url: str, sonar_token: str, timeout: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(ce_task_url, auth=(sonar_token, ""))
        status = resp.json().get("task", {}).get("status")
        if status == "SUCCESS":
            return True
        if status in ("FAILED", "CANCELED"):
            return False
        time.sleep(2)
    return False


def get_scoped_complexity(project_key: str, file_paths: list, sonar_token: str, sonar_host: str) -> float | None:
    """Sum cognitive_complexity across only the given files (the PR's touched files),
    not the whole project. A file returning 404 means it didn't exist in this snapshot
    (e.g. newly added in the PR) — treated as contributing 0, which is correct."""
    if not file_paths:
        return None

    total = 0.0
    for fp in file_paths:
        component_key = f"{project_key}:{fp}"
        resp = requests.get(
            f"{sonar_host}/api/measures/component",
            params={"component": component_key, "metricKeys": "cognitive_complexity"},
            auth=(sonar_token, ""),
        )
        if resp.status_code != 200:
            continue  # file absent in this snapshot -> contributes 0
        for m in resp.json().get("component", {}).get("measures", []):
            if m["metric"] == "cognitive_complexity":
                total += float(m["value"])
    return total


# Methodology §3.3.2: "SonarScanner was executed... to identify code smells
# such as God Class and Long Method." SonarJava has no rule literally named
# "God Class" - S6539 ("Monster Class") is SonarSource's own modern name for
# the same smell (a class doing/knowing too much); S138 ("Methods should not
# have too many lines") is the direct Long Method analog. Verified against
# this project's own SonarQube instance's /api/rules/search before use, not
# guessed - see the god-class/long-method verification note in
# docs/04_phase1_full_progress_bilingual_continue.md.
GOD_CLASS_RULE = "java:S6539"
LONG_METHOD_RULE = "java:S138"


def get_scoped_smell_counts(project_key: str, file_paths: list, sonar_token: str, sonar_host: str) -> dict:
    """Count God-Class/Long-Method issues, scoped to `file_paths` only (same
    scoping principle as get_scoped_complexity - a PR's own smell signal, not
    the whole project's pre-existing smells)."""
    counts = {"god_class_smells": 0, "long_method_smells": 0}
    if not file_paths:
        return counts

    scoped_components = {f"{project_key}:{fp}" for fp in file_paths}
    resp = requests.get(
        f"{sonar_host}/api/issues/search",
        params={
            "componentKeys": project_key,
            "rules": f"{GOD_CLASS_RULE},{LONG_METHOD_RULE}",
            "ps": 500,
        },
        auth=(sonar_token, ""),
    )
    if resp.status_code != 200:
        return counts
    for issue in resp.json().get("issues", []):
        if issue.get("component") not in scoped_components:
            continue  # a pre-existing smell in a file this PR didn't touch
        if issue.get("rule") == GOD_CLASS_RULE:
            counts["god_class_smells"] += 1
        elif issue.get("rule") == LONG_METHOD_RULE:
            counts["long_method_smells"] += 1
    return counts


# ---------------------------------------------------------------------------
# Step 6: cleanup
# ---------------------------------------------------------------------------

def delete_project(project_key: str, sonar_token: str, sonar_host: str):
    requests.post(
        f"{sonar_host}/api/projects/delete",
        params={"project": project_key},
        auth=(sonar_token, ""),
    )


# ---------------------------------------------------------------------------
# Per-snapshot pipeline: checkout -> scan -> scoped-query
# ---------------------------------------------------------------------------

def scan_snapshot(
    sha: str, project_key: str, changed_files: list, sonar_token: str, sonar_host: str,
    repo_dir: Path = REPO_DIR,
) -> dict | None:
    """Returns {"complexity": float, "god_class_smells": int,
    "long_method_smells": int} for one snapshot, or None if the checkout/
    scan/processing failed. Both the complexity measure and the smell
    issues come from the SAME completed analysis - no second scan needed.

    `repo_dir` defaults to REPO_DIR (the commons-lang clone the historical
    500-PR batch pipeline below always uses) so every existing call site
    is unaffected; live_predict.py passes a different repo's local clone
    explicitly when predicting against a non-commons-lang PR - see its own
    module docstring for why this parameter exists at all."""
    if not checkout_commit(sha, repo_dir):
        print(f"    [skip] could not check out {sha[:10]}")
        return None
    if not run_scanner(project_key, sonar_token, sonar_host, repo_dir):
        return None
    ce_task_url = read_ce_task_url(repo_dir)
    if not ce_task_url or not wait_for_processing(ce_task_url, sonar_token):
        print(f"    [skip] analysis processing did not complete for {project_key}")
        return None
    complexity = get_scoped_complexity(project_key, changed_files, sonar_token, sonar_host)
    if complexity is None:
        return None
    smells = get_scoped_smell_counts(project_key, changed_files, sonar_token, sonar_host)
    return {"complexity": complexity, **smells}


def already_scanned() -> set:
    if not RESULTS_PATH.exists():
        return set()
    seen = set()
    with open(RESULTS_PATH) as f:
        for line in f:
            try:
                seen.add(json.loads(line)["number"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=150)
    parser.add_argument("--years", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not REPO_DIR.exists():
        raise RuntimeError(
            f"{REPO_DIR} not found. Clone it first:\n"
            f"  git clone https://github.com/apache/commons-lang.git {REPO_DIR}"
        )

    sonar_token, sonar_host = load_env()
    sample = select_sample(args.sample_size, args.years, args.seed)
    done = already_scanned()
    if done:
        print(f"Resuming — {len(done)} PRs already scanned.")

    with open(RESULTS_PATH, "a") as out:
        for i, pr in enumerate(sample, 1):
            number = pr["number"]
            if number in done:
                continue

            print(f"\n[{i}/{len(sample)}] PR #{number} — {pr['title'][:60]}")

            changed_files = get_changed_java_files(pr["base_sha"], pr["head_sha"])
            if not changed_files:
                print("  [skip] no .java files changed by this PR (doc/config-only) — no complexity signal")
                record = {
                    "number": number,
                    "title": pr["title"],
                    "created_at": pr["created_at"],
                    "base_sha": pr["base_sha"],
                    "head_sha": pr["head_sha"],
                    "changed_java_files": [],
                    "cognitive_complexity_before": None,
                    "cognitive_complexity_after": None,
                    "cognitive_complexity_delta": None,
                    "skip_reason": "no_java_files_changed",
                }
                out.write(json.dumps(record) + "\n")
                out.flush()
                continue

            print(f"  Changed Java files ({len(changed_files)}): {changed_files[:5]}{'...' if len(changed_files) > 5 else ''}")

            base_key = f"cl-pr{number}-base"
            head_key = f"cl-pr{number}-head"

            print("  Scanning base (before)...")
            before = scan_snapshot(pr["base_sha"], base_key, changed_files, sonar_token, sonar_host)
            delete_project(base_key, sonar_token, sonar_host)

            print("  Scanning head (after)...")
            after = scan_snapshot(pr["head_sha"], head_key, changed_files, sonar_token, sonar_host)
            delete_project(head_key, sonar_token, sonar_host)

            complexity_before = before["complexity"] if before else None
            complexity_after = after["complexity"] if after else None
            if complexity_before is None or complexity_after is None:
                print(f"  [warn] incomplete data for PR #{number} — recording as null")

            delta = (
                complexity_after - complexity_before
                if complexity_before is not None and complexity_after is not None
                else None
            )

            record = {
                "number": number,
                "title": pr["title"],
                "created_at": pr["created_at"],
                "base_sha": pr["base_sha"],
                "head_sha": pr["head_sha"],
                "changed_java_files": changed_files,
                "cognitive_complexity_before": complexity_before,
                "cognitive_complexity_after": complexity_after,
                "cognitive_complexity_delta": delta,
                # Methodology §3.3.2's named code smells, scoped to this PR's
                # touched files the same way complexity is - see
                # get_scoped_smell_counts.
                "god_class_smells_before": before["god_class_smells"] if before else None,
                "god_class_smells_after": after["god_class_smells"] if after else None,
                "long_method_smells_before": before["long_method_smells"] if before else None,
                "long_method_smells_after": after["long_method_smells"] if after else None,
            }
            out.write(json.dumps(record) + "\n")
            out.flush()
            print(f"  Result (scoped to touched files): before={complexity_before}, after={complexity_after}, delta={delta}")
            if before and after:
                print(f"  Smells: God Class {before['god_class_smells']}->{after['god_class_smells']}, "
                      f"Long Method {before['long_method_smells']}->{after['long_method_smells']}")

    print(f"\nDone. Results written to {RESULTS_PATH}")


if __name__ == "__main__":
    main()