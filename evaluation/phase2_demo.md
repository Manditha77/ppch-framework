# Phase II Analyze Readiness

**Status:** `ready_for_training`

Dataset satisfies the demonstration minimum.

- Rows available: 62
- Predictor fields: `additions, deletions, changed_files, changed_java_files, commits, comments, review_comments, body_character_count, title_word_count`
- Label field: `exceeds_complexity_threshold_after`
- Temporal training PRs: `[1311, 1319, 1324, 1381, 1386, 1392, 1407, 1481, 1483, 1525, 1546, 1554, 1569, 1575, 1594, 1599, 1610, 1613, 1616, 1619, 1624, 1626, 1633, 1634, 1640, 1644, 1648, 1652, 1655, 1657, 1658]`
- Temporal test PRs: `[1662, 1679, 1680, 1681, 1683, 1686, 1691, 1699, 1700, 1705, 1710, 1712, 1713, 1719, 1723, 1726, 1735, 1736, 1739, 1742, 1746, 1750, 1752, 1754, 1755, 1758, 1762, 1764, 1766, 1768, 1771]`

Post-submission complexity fields are excluded from predictors to prevent leakage.
Model metrics will be reported only after the larger labeled feature table is available.
