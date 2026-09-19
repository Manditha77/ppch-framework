"""Builds the final BEFORE vs AFTER comparison — the artifact to show live
to the panel. Requires sense_scan.py and analyze_predict.py to have already
been run for BOTH "before" and "after" (act_decide_and_suggest.py only
applies to "before", since "after" is the already-refactored result and
should not need a further suggestion).

Usage (after all prior steps have been run for both versions):
    python compare_results.py
"""

import json
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
DEMO_DIR = SCRIPTS_DIR.parent


def load(version: str, name: str):
    path = DEMO_DIR / "results" / version / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    before_sense = load("before", "sense_result.json")
    before_analyze = load("before", "analyze_result.json")
    before_act = load("before", "act_result.json")
    after_sense = load("after", "sense_result.json")
    after_analyze = load("after", "analyze_result.json")

    missing = [
        (label, val) for label, val in [
            ("before/sense_result.json", before_sense),
            ("before/analyze_result.json", before_analyze),
            ("after/sense_result.json", after_sense),
            ("after/analyze_result.json", after_analyze),
        ] if val is None
    ]
    if missing:
        names = ", ".join(label for label, _ in missing)
        raise RuntimeError(
            f"Missing result file(s): {names}. Run sense_scan.py and analyze_predict.py "
            f"for both --version before and --version after first."
        )

    complexity_before = before_sense["cognitive_complexity"]
    complexity_after = after_sense["cognitive_complexity"]
    risk_before = before_analyze["risk_score"]
    risk_after = after_analyze["risk_score"]

    comparison = {
        "cognitive_complexity": {
            "before": complexity_before,
            "after": complexity_after,
            "change": complexity_after - complexity_before,
            "percent_change": round(
                100 * (complexity_after - complexity_before) / complexity_before, 1
            ) if complexity_before else None,
        },
        "predicted_risk_score": {
            "before": risk_before,
            "after": risk_after,
            "change": round(risk_after - risk_before, 3),
        },
        "action": {
            "before": before_analyze["action"],
            "after": after_analyze["action"],
        },
        "refactoring_suggestion_applied": (
            before_act.get("status") in ("optimal", "threshold_unreachable") if before_act else False
        ),
        "act_trigger_reasons": (before_act or {}).get("trigger_reasons", []),
    }

    out_dir = DEMO_DIR / "results"
    (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# PPCH Live Demo — Before vs After",
        "",
        "## Cognitive Complexity (real SonarScanner measurement, PricingEngine.java)",
        "",
        f"- Before: **{complexity_before}**",
        f"- After:  **{complexity_after}**",
        f"- Change: **{comparison['cognitive_complexity']['change']:+.1f}** "
        f"({comparison['cognitive_complexity']['percent_change']}%)" if complexity_before else "",
        "",
        "## Predicted Risk (Analyze layer, same trained models throughout)",
        "",
        f"- Before: risk_score = **{risk_before:.3f}** -> action = `{before_analyze['action']}`",
        f"- After:  risk_score = **{risk_after:.3f}** -> action = `{after_analyze['action']}`",
        "",
        "## Refactoring suggestion (Act layer)",
        "",
    ]
    if before_act and before_act.get("status") in ("optimal", "threshold_unreachable"):
        method = before_act.get("method_name")
        suggestion = before_act.get("suggestion", {})
        lines += [
            f"A refactoring suggestion WAS generated for the BEFORE version, targeting "
            f"`{method}` (approximate complexity {before_act.get('approximate_method_complexity'):.1f}).",
        ]
        for reason in before_act.get("trigger_reasons", []):
            lines.append(f"- Triggered by: {reason}")
        if suggestion.get("rendered"):
            lo, hi = suggestion["source_line_range"]
            lines += [
                f"- Suggested extraction: lines {lo}-{hi} of PricingEngine.java",
                f"- Inferred parameters: {suggestion['inferred_parameters']}",
                f"- Suggested method name: `{suggestion['suggested_method_name']}`",
            ]
        # The Act layer here triggers on EITHER the Analyze layer's ML
        # prediction OR the measured complexity directly exceeding
        # SonarQube's own per-method ceiling (15) - see
        # act_decide_and_suggest.py's module docstring. Worth surfacing
        # explicitly when the ML side didn't itself cross the warning
        # threshold, so a viewer doesn't assume risk_score alone explains
        # why a suggestion appears below.
        if not before_analyze.get("refactoring_suggestion_requested"):
            lines.append(
                f"- Note: risk_score ({risk_before:.3f}) was below the Analyze layer's own warning "
                "threshold; this suggestion was triggered by the measured complexity alone, "
                "independent of the ML prediction."
            )
    else:
        reason = (before_act or {}).get("reason", "no reason recorded")
        lines.append(f"No refactoring suggestion was generated ({reason}).")

    (out_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(comparison, indent=2))
    print(f"\nWrote {out_dir / 'comparison.json'}")
    print(f"Wrote {out_dir / 'comparison.md'}")


if __name__ == "__main__":
    main()
