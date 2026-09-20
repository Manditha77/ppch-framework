"""Phase II/III — Comparative benchmark vs. a reactive SonarQube baseline
(Methodology §3.5.3, answers RQ3).

IMPORTANT METHODOLOGICAL NOTE, stated plainly rather than left implied: this
is a MODELED/SIMULATED comparison built from real PR timestamps already
collected (sense/data/raw/apache_commons-lang_prs.jsonl's `created_at`/
`merged_at`), not a live, continuous-deployment field measurement. These
historical PRs never actually received a proactive warning at the time (the
framework didn't exist yet), so there is no ground truth on whether a
developer would have acted on one. The benchmark computes what CAN be
directly measured from real data (detection timing) and is explicit about
what it does NOT claim (confirmed actual remediation).

Operationalization:
  - A "complexity issue" = a merged PR with exceeds_significant_complexity_
    increase == 1 (the same label used throughout Phase II) - i.e. a PR that
    genuinely introduced a significant complexity increase and landed in
    master.
  - Reactive baseline = a SonarQube scan of the master branch (periodic/CI,
    not PR-aware). It can only observe the complexity increase once the PR
    has actually MERGED - so reactive MTTD, for each such PR, is exactly
    `merged_at - created_at`: the entire PR review window is dead time from
    a reactive tool's perspective.
  - Proactive baseline (this framework) = detection at `created_at`, the
    moment of PR submission, by construction (the Analyze layer runs on
    pre-submission features only - see analyze/train_models.py FEATURES).
    Proactive MTTD = 0.
  - "Recovery window" (a deliberately modest stand-in for MTTR, given what
    this dataset can support): the reactive MTTD value itself, reframed as
    "time available for a fix before the issue reaches master, that a
    proactive warning would buy back." This is NOT a claim that the issue
    was actually fixed in that window - just that the window existed and a
    reactive tool would not have had it.
  - Realistic catch rate: of the PRs that truly introduced a significant
    complexity increase, what fraction would the trained models' own
    risk_score have actually cleared WARNING_THRESHOLD on (reusing
    pipeline.py's real predict_risk/build_intervention, not an assumed 100%
    detection rate) - this keeps the benchmark honest about the Analyze
    layer's real, imperfect accuracy rather than assuming perfect detection.
  - Proportion merged under each regime: 100% under reactive (by
    definition - a reactive tool doesn't gate merging, it only reports
    after the fact) vs. the fraction that would have been FLAGGED pre-merge
    under the proactive regime (not a claim that flagging would have
    prevented the merge - just that the developer would have had the
    warning in hand before it happened).

Usage:
    python evaluation/run_mttd_mttr_benchmark.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
sys.path.insert(0, str(ROOT / "act" / "github-action"))
sys.path.insert(0, str(ROOT / "act" / "ilp-engine"))
sys.path.insert(0, str(ROOT / "analyze"))

from pipeline import FEATURES, MODEL_DIR, WARNING_THRESHOLD, predict_risk  # noqa: E402
from feature_utils import apply_log_transform  # noqa: E402

PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
RAW_DIR = ROOT / "sense" / "data" / "raw"
PR_METADATA_PATH = RAW_DIR / "apache_commons-lang_prs.jsonl"
EVALUATION_DIR = ROOT / "evaluation"
LABEL = "exceeds_significant_complexity_increase"


def load_pr_timestamps() -> dict:
    """{pr_number: {"created_at": datetime, "merged_at": datetime or None}}"""
    timestamps = {}
    with PR_METADATA_PATH.open(encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            created = record.get("created_at")
            merged = record.get("merged_at")
            if not created:
                continue
            timestamps[record["number"]] = {
                "created_at": datetime.fromisoformat(created),
                "merged_at": datetime.fromisoformat(merged) if merged else None,
            }
    return timestamps


def load_feature_rows() -> list:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in PROCESSED_DIR.glob("pr_*/feature_table.json")
    ]


def load_models() -> dict:
    return {
        "random_forest": joblib.load(MODEL_DIR / "random_forest.joblib"),
        "xgboost": joblib.load(MODEL_DIR / "xgboost.joblib"),
    }


def main() -> None:
    timestamps = load_pr_timestamps()
    rows = load_feature_rows()
    models = load_models()

    complexity_issues = []
    skipped_no_merge = 0
    skipped_no_timestamp = 0

    for row in rows:
        number = row["pr_number"]
        if row.get(LABEL) != 1:
            continue
        ts = timestamps.get(number)
        if ts is None:
            skipped_no_timestamp += 1
            continue
        if ts["merged_at"] is None:
            # Never landed in master - not a master-branch complexity-
            # accumulation event, and reactive MTTD is undefined (a reactive
            # scanner never sees code that was never merged).
            skipped_no_merge += 1
            continue

        reactive_mttd_hours = (ts["merged_at"] - ts["created_at"]).total_seconds() / 3600.0
        if reactive_mttd_hours < 0:
            continue  # data anomaly guard - shouldn't happen, skip rather than corrupt the mean

        prediction = predict_risk(models, row)
        risk_score = prediction["risk_score"]
        would_flag_pre_merge = risk_score >= WARNING_THRESHOLD

        complexity_issues.append({
            "pr_number": number,
            "created_at": ts["created_at"].isoformat(),
            "merged_at": ts["merged_at"].isoformat(),
            "reactive_mttd_hours": reactive_mttd_hours,
            "proactive_mttd_hours": 0.0,
            "risk_score": risk_score,
            "would_flag_pre_merge": would_flag_pre_merge,
        })

    n = len(complexity_issues)
    if n == 0:
        raise RuntimeError("No merged, complexity-increasing PRs with both timestamps and a feature "
                            "table were found - nothing to benchmark.")

    reactive_mttds = [c["reactive_mttd_hours"] for c in complexity_issues]
    mean_reactive_mttd_hours = sum(reactive_mttds) / n
    sorted_mttds = sorted(reactive_mttds)
    median_reactive_mttd_hours = sorted_mttds[n // 2] if n % 2 else \
        (sorted_mttds[n // 2 - 1] + sorted_mttds[n // 2]) / 2
    catch_count = sum(1 for c in complexity_issues if c["would_flag_pre_merge"])
    catch_rate = catch_count / n

    results = {
        "phase": "III_ACT",
        "study": "mttd_mttr_benchmark_vs_reactive_sonarqube",
        "methodology_note": (
            "Modeled/simulated comparison from real PR timestamps, not a live "
            "continuous-deployment field measurement - see this script's own docstring "
            "for the full operationalization and its limits."
        ),
        "complexity_issue_count": n,
        "skipped_not_merged": skipped_no_merge,
        "skipped_no_timestamp": skipped_no_timestamp,
        "warning_threshold": WARNING_THRESHOLD,
        "proactive_mttd_hours": 0.0,
        "reactive_mttd_hours": {
            "mean": mean_reactive_mttd_hours,
            "median": median_reactive_mttd_hours,
            "min": min(reactive_mttds),
            "max": max(reactive_mttds),
        },
        "recovery_window_hours_bought_back": {
            "mean": mean_reactive_mttd_hours,
            "median": median_reactive_mttd_hours,
            "note": "Time available for a fix before the issue reaches master under the "
                    "proactive regime - NOT a claim of confirmed actual remediation (see "
                    "methodology_note).",
        },
        "realistic_catch_rate": {
            "would_have_flagged_pre_merge": catch_count,
            "total_complexity_issues": n,
            "rate": catch_rate,
            "note": "Fraction of true complexity-increasing PRs the trained models' actual "
                    "risk_score would have cleared WARNING_THRESHOLD on - NOT an assumed 100% "
                    "detection rate.",
        },
        "proportion_merged_under_each_regime": {
            "reactive": 1.0,
            "reactive_note": "By definition - a reactive scanner does not gate merging, it only "
                              "reports after the fact.",
            "proactive_flagged_pre_merge": catch_rate,
            "proactive_note": "Fraction that would have carried a warning BEFORE merge under the "
                               "proactive regime - not a claim that flagging would have prevented "
                               "the merge.",
        },
        "per_pr": complexity_issues,
    }

    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    (EVALUATION_DIR / "mttd_mttr_benchmark.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# MTTD/MTTR Benchmark vs. Reactive SonarQube (RQ3)",
        "",
        "**Methodology note:** " + results["methodology_note"],
        "",
        f"- Complexity-increasing, merged PRs analyzed: {n}",
        f"  (skipped: {skipped_no_merge} never merged, {skipped_no_timestamp} missing timestamps)",
        "- Proactive MTTD: **0 hours** (detection at PR submission, by construction)",
        f"- Reactive MTTD: **{mean_reactive_mttd_hours:.1f} hours mean** "
        f"({mean_reactive_mttd_hours / 24:.1f} days), median {median_reactive_mttd_hours:.1f} hours "
        f"({median_reactive_mttd_hours / 24:.1f} days) — the full PR review window, dead time for a "
        "reactive scanner.",
        "",
        "## Recovery window bought back",
        "",
        f"Mean **{mean_reactive_mttd_hours:.1f} hours** ({mean_reactive_mttd_hours / 24:.1f} days) of "
        "fix time made available before the issue would reach master, under the proactive regime. "
        "This is the available window, not a confirmed remediation — these are retrospective PRs "
        "that never actually received the warning at the time; there is no ground truth on whether "
        "a developer would have acted on it. Stated as a limitation, not glossed over.",
        "",
        "## Realistic catch rate",
        "",
        f"Of the {n} PRs that genuinely introduced a significant complexity increase, the trained "
        f"models' real risk_score would have cleared WARNING_THRESHOLD ({WARNING_THRESHOLD}) on "
        f"**{catch_count} ({catch_rate:.1%})** of them before merge — not an assumed 100% detection "
        "rate, the actual figure from the Analyze layer's own (imperfect) accuracy.",
        "",
        "## Proportion merged under each regime",
        "",
        "| Regime | Proportion |",
        "|---|---:|",
        "| Reactive (SonarQube, post-merge) | 100% (by definition - doesn't gate merging) |",
        f"| Proactive (this framework) | {catch_rate:.1%} flagged with a warning before merge |",
    ]
    (EVALUATION_DIR / "mttd_mttr_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Analyzed {n} complexity-increasing merged PRs.")
    print(f"Mean reactive MTTD: {mean_reactive_mttd_hours:.1f} hours ({mean_reactive_mttd_hours/24:.1f} days)")
    print(f"Realistic catch rate: {catch_count}/{n} ({catch_rate:.1%})")
    print(f"\nWrote {EVALUATION_DIR / 'mttd_mttr_benchmark.json'}")
    print(f"Wrote {EVALUATION_DIR / 'mttd_mttr_benchmark.md'}")


if __name__ == "__main__":
    main()
