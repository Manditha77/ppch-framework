# MTTD/MTTR Benchmark vs. Reactive SonarQube (RQ3)

**Methodology note:** Modeled/simulated comparison from real PR timestamps, not a live continuous-deployment field measurement - see this script's own docstring for the full operationalization and its limits.

- Complexity-increasing, merged PRs analyzed: 52
  (skipped: 50 never merged, 0 missing timestamps)
- Proactive MTTD: **0 hours** (detection at PR submission, by construction)
- Reactive MTTD: **82.4 hours mean** (3.4 days), median 12.9 hours (0.5 days) — the full PR review window, dead time for a reactive scanner.

## Recovery window bought back

Mean **82.4 hours** (3.4 days) of fix time made available before the issue would reach master, under the proactive regime. This is the available window, not a confirmed remediation — these are retrospective PRs that never actually received the warning at the time; there is no ground truth on whether a developer would have acted on it. Stated as a limitation, not glossed over.

## Realistic catch rate

Of the 52 PRs that genuinely introduced a significant complexity increase, the trained models' real risk_score would have cleared WARNING_THRESHOLD (0.7) on **22 (42.3%)** of them before merge — not an assumed 100% detection rate, the actual figure from the Analyze layer's own (imperfect) accuracy.

## Proportion merged under each regime

| Regime | Proportion |
|---|---:|
| Reactive (SonarQube, post-merge) | 100% (by definition - doesn't gate merging) |
| Proactive (this framework) | 42.3% flagged with a warning before merge |
