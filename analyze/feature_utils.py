"""Shared feature-preprocessing utility (Methodology §3.3.4: "Skewed
distributions in the raw feature space were addressed through logarithmic
transformation of heavy-tailed numeric features").

Used by train_models.py, run_ablation.py, and run_bootstrap.py so the same
transform is applied identically everywhere, rather than three independent
copies that could quietly drift apart.

Deliberately NOT a fitted transform (no parameters learned from training
data) - log1p is a fixed, stateless, monotonic function applied identically
to every row - so applying it before the train/test split introduces no
leakage (unlike, say, StandardScaler, which must be fit on train only).

Which features: count-like, right-skewed fields where a small number of
PRs have very large values (e.g. complexity_before ranges from 0 to several
thousand on real commons-lang PRs - see sense/scripts/03_build_feature_
table.py's docstring). `contributor_prior_acceptance_rate` is deliberately
EXCLUDED - it's already a bounded [0, 1] rate, not a heavy-tailed count.
"""

import numpy as np
import pandas as pd

LOG_TRANSFORM_FEATURES = [
    "additions", "deletions", "changed_files", "changed_java_files",
    "commits", "comments", "review_comments", "body_character_count",
    "contributor_prior_pr_count", "contributor_tenure_days",
    "contributor_follower_count", "complexity_before",
    "max_touched_method_complexity",
]


def apply_log_transform(frame: pd.DataFrame) -> pd.DataFrame:
    """Returns a COPY of `frame` with LOG_TRANSFORM_FEATURES replaced by
    log1p(value) (log1p, not log, since these fields can legitimately be 0 -
    e.g. a contributor's first-ever PR has contributor_prior_pr_count=0).
    Columns not present in `frame` (e.g. an older feature_table.json without
    the contributor_* fields) are silently skipped, not an error."""
    frame = frame.copy()
    for feature in LOG_TRANSFORM_FEATURES:
        if feature in frame.columns:
            frame[feature] = np.log1p(frame[feature].astype(float))
    return frame
