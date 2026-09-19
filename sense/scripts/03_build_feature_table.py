"""
Phase I.6-1.7 — Build leakage-aware feature tables for selected PRs.

This first vertical slice joins pre-submission PR metadata with the already
computed post-submission SonarQube result. The complexity measurements are
labels/evidence, not prediction features.
"""

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "sense" / "data" / "raw"
PROCESSED_DIR = ROOT / "sense" / "data" / "processed"
PR_METADATA_PATH = RAW_DIR / "apache_commons-lang_prs.jsonl"
SCAN_RESULTS_PATH = RAW_DIR / "pilot_scan_results.jsonl"


def load_record(path: Path, number: int) -> dict:
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record.get("number") == number:
                return record
    raise ValueError(f"PR #{number} was not found in {path.name}")


def build_feature_row(number: int, complexity_threshold: float = 15.0, delta_threshold: float = 3.0) -> dict:
    """`complexity_before`/`complexity_after` are FILE-SCOPED SUMS across
    every .java file the PR touched (see 02_scan_pilot_batch.py's own
    scoping note) - i.e. they include every OTHER method already in those
    files, not just what the PR itself changed. On the real 150-PR pilot
    this puts the median `complexity_before` at ~180 (max ~5974), so an
    ABSOLUTE threshold of 15 - which only makes sense for a single
    method's own complexity, exactly what SonarQube's own S3776 rule
    checks - was true for 79% of PRs regardless of what the PR actually
    did. That made `exceeds_complexity_threshold_after` (the earlier name
    of this label) close to a near-constant, largely just re-stating "is
    the touched file already large," not "did this PR introduce a
    complexity spike" - which is almost certainly why pilot models trained
    against it scored a suspicious ~1.000 AUC dominated entirely by
    complexity_before.

    The classification target here is instead `complexity_delta`, which
    cancels out each file's large, UNCHANGED pre-existing complexity (it
    only reflects what moved between the before/after snapshots), compared
    against `delta_threshold` (default 3.0 - roughly the cost of one new
    non-trivial nested conditional under Campbell's rules) rather than the
    absolute per-method ceiling of 15, which was never a sound comparison
    point for a file-level sum in the first place."""
    metadata = load_record(PR_METADATA_PATH, number)
    scan = load_record(SCAN_RESULTS_PATH, number)
    before = scan["cognitive_complexity_before"]
    after = scan["cognitive_complexity_after"]
    delta = scan["cognitive_complexity_delta"]

    if before is None or after is None or delta is None:
        raise ValueError(f"PR #{number} does not have complete complexity measurements")

    body = metadata.get("body") or ""
    changed_java_files = scan.get("changed_java_files", [])
    return {
        "pr_number": number,
        "title": metadata.get("title", ""),
        "body": body,
        "created_at": metadata.get("created_at"),
        "contributor": metadata.get("user_login"),
        "additions": metadata.get("additions", 0),
        "deletions": metadata.get("deletions", 0),
        "changed_files": metadata.get("changed_files", 0),
        "changed_java_files": len(changed_java_files),
        "commits": metadata.get("commits", 0),
        "comments": metadata.get("comments", 0),
        "review_comments": metadata.get("review_comments", 0),
        "body_character_count": len(body),
        "title_word_count": len(metadata.get("title", "").split()),
        "complexity_before": before,
        "complexity_after": after,
        "complexity_delta": delta,
        "complexity_increased": int(delta > 0),
        "exceeds_significant_complexity_increase": int(delta >= delta_threshold),
        "complexity_threshold": complexity_threshold,
        "delta_threshold": delta_threshold,
        "label_definition": "complexity_delta_significant_increase",
        # Methodology §3.3.2's named code smells (God Class -> SonarJava
        # S6539 "Monster Class", Long Method -> S138), scoped to this PR's
        # touched files the same way complexity is - see
        # 02_scan_pilot_batch.py's get_scoped_smell_counts. None on scan
        # records collected before this field existed (legacy pilot data) -
        # not yet wired into the trained model's active feature set (kept as
        # collected evidence for now, to limit how many places need to stay
        # in sync at once - a natural, low-risk next feature-set expansion).
        "god_class_smells_before": scan.get("god_class_smells_before"),
        "god_class_smells_after": scan.get("god_class_smells_after"),
        "long_method_smells_before": scan.get("long_method_smells_before"),
        "long_method_smells_after": scan.get("long_method_smells_after"),
    }


def write_outputs(row: dict) -> None:
    output_dir = PROCESSED_DIR / f"pr_{row['pr_number']}"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_dir / "feature_table"
    json_path = stem.with_suffix(".json")
    csv_path = stem.with_suffix(".csv")
    markdown_path = stem.with_suffix(".md")

    json_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)

    feature_fields = [
        "pr_number", "title", "contributor", "additions", "deletions",
        "changed_files", "changed_java_files", "commits", "comments",
        "review_comments", "body_character_count", "title_word_count",
    ]
    label_fields = [
        "complexity_before", "complexity_after", "complexity_delta",
        "complexity_increased", "exceeds_significant_complexity_increase",
        "complexity_threshold", "delta_threshold",
    ]
    lines = [
        f"# PPCH Feature Table: PR #{row['pr_number']}",
        "",
        "This is a one-PR vertical slice of Phase I.6-1.7.",
        "Features are available before submission; complexity fields are post-submission labels/evidence.",
        "",
        "## Pre-submission features",
        "",
        "| Feature | Value |",
        "|---|---|",
    ]
    for field in feature_fields:
        value = str(row[field]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{field}` | {value} |")
    threshold_text = (
        "This PR introduced a significant new complexity increase (>= delta_threshold), "
        "the classification target used for model training."
        if row["exceeds_significant_complexity_increase"]
        else "This PR did not introduce a significant complexity increase."
    )
    lines.extend([
        "",
        "## Post-submission label and evidence",
        "",
        "| Measurement | Value |",
        "|---|---|",
    ])
    for field in label_fields:
        lines.append(f"| `{field}` | {row[field]} |")
    lines.extend([
        "",
        "## Interpretation",
        "",
        f"SonarQube measured the touched-file complexity as {row['complexity_before']} before and {row['complexity_after']} after the PR, giving a delta of {row['complexity_delta']:+.1f}.",
        f"{threshold_text}",
        "",
        "Note: `complexity_before`/`complexity_after` are FILE-SCOPED SUMS across every file "
        "the PR touched (including other, unrelated methods already in those files) - not "
        "directly comparable to SonarQube's own per-method complexity ceiling of "
        f"{row['complexity_threshold']}. The classification label above uses the delta "
        "instead, precisely to avoid that comparison.",
    ])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {markdown_path}")


def all_usable_pr_numbers() -> list:
    """Every PR number in pilot_scan_results.jsonl with complete
    before/after/delta measurements - i.e. every PR build_feature_row can
    actually process. Used by --all to regenerate the full feature-table
    set in one command (e.g. after changing the label definition, or after
    a fresh scan of a larger sample) without hand-listing PR numbers."""
    numbers = []
    with SCAN_RESULTS_PATH.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if all(record.get(k) is not None for k in
                   ("cognitive_complexity_before", "cognitive_complexity_after", "cognitive_complexity_delta")):
                numbers.append(record["number"])
    return numbers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, nargs="+", default=[1324, 1633],
                         help="Ignored if --all is passed.")
    parser.add_argument("--all", action="store_true",
                         help="Regenerate feature tables for every usable PR in pilot_scan_results.jsonl.")
    parser.add_argument("--complexity-threshold", type=float, default=15.0)
    parser.add_argument("--delta-threshold", type=float, default=3.0,
                         help="Minimum complexity_delta to count as a significant increase "
                              "(the classification target) - see build_feature_row's docstring.")
    args = parser.parse_args()
    numbers = all_usable_pr_numbers() if args.all else args.pr_number
    print(f"Building feature tables for {len(numbers)} PR(s)...")
    for number in numbers:
        row = build_feature_row(number, args.complexity_threshold, args.delta_threshold)
        write_outputs(row)
    positives = sum(1 for n in numbers
                     if json.loads((PROCESSED_DIR / f"pr_{n}" / "feature_table.json").read_text())
                     ["exceeds_significant_complexity_increase"])
    print(f"\nDone. {positives}/{len(numbers)} PRs flagged as a significant complexity increase "
          f"(delta >= {args.delta_threshold}).")


if __name__ == "__main__":
    main()
