"""Phase II — Analyze preparation and honest small-sample demonstration."""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
OUTPUT_DIR = ROOT / "evaluation"

PREDICTOR_FIELDS = [
    "additions",
    "deletions",
    "changed_files",
    "changed_java_files",
    "commits",
    "comments",
    "review_comments",
    "body_character_count",
    "title_word_count",
    "contributor_prior_pr_count",
    "contributor_prior_acceptance_rate",
    "contributor_tenure_days",
    "contributor_follower_count",
]
LABEL_FIELD = "exceeds_significant_complexity_increase"
POST_SUBMISSION_FIELDS = {
    "complexity_before",
    "complexity_after",
    "complexity_delta",
    "complexity_increased",
    "exceeds_significant_complexity_increase",
    "complexity_threshold",
    "delta_threshold",
    "label_definition",
}


def load_rows() -> list[dict]:
    rows = []
    for path in PROCESSED_DIR.glob("pr_*/feature_table.json"):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    if not rows:
        raise RuntimeError("No per-PR feature tables found")
    return sorted(rows, key=lambda row: datetime.fromisoformat(row["created_at"]))


def build_report(rows: list[dict]) -> dict:
    split_index = max(1, int(len(rows) * 0.5))
    train_rows = rows[:split_index]
    test_rows = rows[split_index:]
    labels = {row[LABEL_FIELD] for row in rows}
    enough_for_model = len(rows) >= 10 and len(labels) == 2 and len(test_rows) >= 2

    return {
        "phase": "II_ANALYZE",
        "status": "ready_for_training" if enough_for_model else "blocked_pending_more_labeled_rows",
        "reason": (
            "The two-row demonstration is sufficient to verify feature preparation, but not to estimate model performance."
            if not enough_for_model
            else "Dataset satisfies the demonstration minimum."
        ),
        "row_count": len(rows),
        "predictor_fields": PREDICTOR_FIELDS,
        "excluded_post_submission_fields": sorted(POST_SUBMISSION_FIELDS),
        "label_field": LABEL_FIELD,
        "temporal_split": {
            "train_pr_numbers": [row["pr_number"] for row in train_rows],
            "test_pr_numbers": [row["pr_number"] for row in test_rows],
        },
        "class_values": sorted(labels),
        "rows": [
            {
                "pr_number": row["pr_number"],
                "created_at": row["created_at"],
                "features": {field: row[field] for field in PREDICTOR_FIELDS},
                "label": row[LABEL_FIELD],
            }
            for row in rows
        ],
    }


def write_outputs(report: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "phase2_demo.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Phase II Analyze Readiness",
        "",
        f"**Status:** `{report['status']}`",
        "",
        report["reason"],
        "",
        f"- Rows available: {report['row_count']}",
        f"- Predictor fields: `{', '.join(report['predictor_fields'])}`",
        f"- Label field: `{report['label_field']}`",
        f"- Temporal training PRs: `{report['temporal_split']['train_pr_numbers']}`",
        f"- Temporal test PRs: `{report['temporal_split']['test_pr_numbers']}`",
        "",
        "Post-submission complexity fields are excluded from predictors to prevent leakage.",
        "Model metrics will be reported only after the larger labeled feature table is available.",
    ]
    (OUTPUT_DIR / "phase2_demo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_DIR / 'phase2_demo.json'}")
    print(f"Wrote {OUTPUT_DIR / 'phase2_demo.md'}")


def main() -> None:
    report = build_report(load_rows())
    write_outputs(report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
