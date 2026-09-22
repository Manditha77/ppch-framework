"""Multi-file refactoring orchestration - extends the single-target-file
refactor engine (act/refactor_file.py::refactor_source) to cover EVERY
non-test Java file a PR touches, not just the single file
generate_refactoring_suggestion's diff-scoped selection picks as "the"
target.

Found necessary via direct user analysis of the 10-PR historical case-study
table (2026-09-23): several PRs showed flat SonarQube file-total numbers
(e.g. PR #1422: 170.0 -> 170.0) because the reported number was scoped to
ONE file, while other files the same PR touched - potentially with their
own unaddressed complexity - were never even looked at. A distribution
check across all 334 processed historical PRs confirmed this matters:
25.4% touch 2+ non-test Java files, 18.3% touch 2-5 (the zone this
extension covers completely).

Deliberately capped at MAX_FILES_PER_PR (10) - covers 92.8% of the 334-PR
historical sample completely (only 12/334 PRs, 3.6%, touch more than 20
files - typically sweeping style/license-header PRs where most files have
zero complexity issues anyway). Unbounded processing of, say, a 153-file
PR is not a reasonable use of the per-file real-SonarQube-scan time budget
(each verified file costs two full isolated scanner runs). This is a
deliberate, documented engineering cap, not a silent limitation - the
PRIMARY file (the one generate_refactoring_suggestion's diff-scoped
selection identifies) is always included first, so the existing,
already-verified single-file behavior is a strict subset of this, never
altered.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parents[1]
sys.path.insert(0, str(ROOT / "act"))

from refactor_file import refactor_source  # noqa: E402

MAX_FILES_PER_PR = 10


def refactor_all_files(candidate_files: list, primary_file: str, fetch_fn,
                        threshold: float = 15.0, max_iterations: int = 8,
                        safety_margin: float = 2.0) -> dict:
    """`candidate_files`: every non-test Java file the PR touched.
    `primary_file`: the one generate_refactoring_suggestion already picked -
    always processed first and always included, so its result is identical
    to what the existing single-file path already produces (verified by
    regression test, not just by construction).
    `fetch_fn(file_path) -> str`: fetches that file's real HEAD content -
    injected rather than hardcoded so this works identically for the
    historical path (fetch_file_at_commit against a fixed head_sha) and the
    live path (same function, different sha) without duplicating fetch
    logic here.

    Returns {"per_file": {file_path: {...}}, "files_analyzed": [...],
    "files_skipped_due_to_cap": [...], "total_extractions_applied": int}."""
    ordered = [primary_file] + [f for f in candidate_files if f != primary_file]
    files_to_process = ordered[:MAX_FILES_PER_PR]
    skipped = ordered[MAX_FILES_PER_PR:]

    per_file = {}
    for file_path in files_to_process:
        try:
            source = fetch_fn(file_path)
        except Exception as exc:  # noqa: BLE001 — real, reportable per-file fetch failure
            per_file[file_path] = {"status": "fetch_failed", "error": str(exc)}
            continue

        # A parse failure in ONE of potentially several additional files must
        # not take down the whole multi-file pass - found via a real case
        # (PR #1470's SystemUtils.java, which javalang's aging parser can't
        # handle) where an unguarded exception here crashed analysis of
        # every other file, including the primary one already known to work.
        try:
            result = refactor_source(source, threshold, max_iterations, safety_margin=safety_margin)
        except Exception as exc:  # noqa: BLE001 — javalang parse errors and similar per-file failures
            per_file[file_path] = {"status": "parse_failed", "error": str(exc) or type(exc).__name__}
            continue

        applied = [step for step in result["log"] if step["outcome"] in ("extracted", "branch_split_applied")]
        per_file[file_path] = {
            "status": "ok",
            "before_text": source,
            "after_text": result["final_text"],
            "log": result["log"],
            "still_over_threshold": result["still_over_threshold"],
            "extractions_applied": len(applied),
        }

    total_applied = sum(r.get("extractions_applied", 0) for r in per_file.values())
    return {
        "per_file": per_file,
        "files_analyzed": files_to_process,
        "files_skipped_due_to_cap": skipped,
        "total_extractions_applied": total_applied,
    }
