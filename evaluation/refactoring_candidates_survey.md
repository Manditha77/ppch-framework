# Refactoring Candidate Survey

Ran the real ILP pipeline across 49 PRs at/above the notice threshold (0.4). Sorted first by whether the target method was confirmed as part of the PR's actual diff (trustworthy candidates first), then by line_span (smaller = more localized, more classically "Extract Method"-shaped suggestion).

| PR | Risk | Method | Touched by PR? | Selected stmts | Line span | Remaining complexity | Balanced |
|---|---:|---|---|---:|---:|---:|---|
| #1610 | 0.983 | `split` | ✅ | 2 | 3 | 0.0 | True |
| #1626 | 0.979 | `isCreatable` | ✅ | 2 | 3 | 0.0 | True |
| #1386 | 0.975 | `fill` | ✅ | 2 | 3 | 0.0 | True |
| #1634 | 0.985 | `readObject` | ✅ | 2 | 4 | 0.0 | True |
| #1762 | 0.983 | `appendTo` | ✅ | 2 | 4 | 0.0 | True |
| #1481 | 0.981 | `getTimeZone` | ✅ | 2 | 4 | 0.0 | True |
| #1483 | 0.979 | `getTimeZone` | ✅ | 2 | 4 | 0.0 | True |
| #1633 | 0.980 | `readObject` | ✅ | 2 | 6 | 0.0 | True |
| #1657 | 0.935 | `toMillisInt` | ✅ | 2 | 7 | 0.0 | True |
| #1742 | 0.981 | `primitiveArrayEquals` | ✅ | 8 | 8 | 0.0 | True |
| #1319 | 0.977 | `compare` | ✅ | 3 | 9 | 0.0 | True |
| #1699 | 0.983 | `mid` | ✅ | 4 | 12 | 0.0 | True |
| #1681 | 0.940 | `trimControl` | ✅ | 5 | 12 | 0.0 | True |
| #1758 | 0.983 | `abbreviateMiddle` | ✅ | 6 | 13 | 0.0 | True |
| #1644 | 0.976 | `repeat` | ✅ | 5 | 13 | 0.0 | True |
| #1648 | 0.952 | `appendDetail` | ✅ | 2 | 13 | 0.0 | True |
| #1686 | 0.981 | `readObject` | ✅ | 5 | 15 | 0.0 | True |
| #1723 | 0.914 | `translate` | ✅ | 4 | 15 | 0.0 | True |
| #1768 | 0.983 | `leftPad` | ✅ | 10 | 26 | 0.0 | True |
| #1735 | 0.959 | `splitByCharacterType` | ✅ | 4 | 27 | 0.0 | True |
| #1662 | 0.985 | `getMatchingMethod` | ✅ | 4 | 28 | 0.0 | True |
| #1736 | 0.973 | `leftPad` | ✅ | 11 | 29 | 0.0 | True |
| #1719 | 0.971 | `abbreviate` | ✅ | 11 | 38 | 1.0 | True |
| #1546 | 0.985 | `isParsableDecimal` | ✅ | 6 | 43 | 2.0 | True |
| #1713 | 0.969 | `indexOfDifference` | ✅ | 7 | 44 | 2.0 | True |
| #1392 | 0.959 | `createNumber` | ✅ | 8 | 69 | 3.0 | True |
| #1640 | 0.986 | `random` | ✅ | 11 | 137 | 0.0 | True |
| #1652 | 0.983 | `get` | ⚠️ NO | 2 | 14 | 0.0 | True |
| #1691 | 0.932 | `translate` | ⚠️ NO | 2 | 16 | 0.0 | True |
| #1599 | 0.981 | `appendArray` | ⚠️ NO | 9 | 22 | 0.0 | True |
| #1658 | 0.973 | `parseLocale` | ⚠️ NO | 5 | 30 | 0.0 | True |
| #1752 | 0.827 | `tryWithResources` | ⚠️ NO | 4 | 30 | 0.0 | True |
| #1712 | 0.983 | `createBigInteger` | ⚠️ NO | 10 | 31 | 0.0 | True |
| #1754 | 0.939 | `getCanonicalName` | ⚠️ NO | 10 | 38 | 0.0 | True |
| #1575 | 0.943 | `isAssignable` | ⚠️ NO | 8 | 43 | 0.0 | True |
| #1381 | 0.944 | `isAssignable` | ⚠️ NO | 8 | 51 | 0.0 | True |
| #1739 | 0.981 | `translate` | ⚠️ NO | 2 | 52 | 0.0 | True |
| #1311 | 0.919 | `wrap` | ⚠️ NO | 7 | 67 | 0.0 | True |
| #1655 | 0.978 | `wrap` | ⚠️ NO | 7 | 70 | 0.0 | True |
| #1700 | 0.983 | `formatPeriod` | ⚠️ NO | 12 | 97 | 1.0 | True |
| #1710 | 0.984 | `getLevenshteinDistance` | ⚠️ NO | 11 | 130 | 1.0 | True |
| #1771 | 0.983 | `getLevenshteinDistance` | ⚠️ NO | 11 | 130 | 1.0 | True |

**15 of 42 candidates could not be confirmed as touching the reported method** - these fell back to the file's globally most complex method, which may be unrelated to what the PR actually changed. Prefer ✅-marked rows for any dissertation demo or claim.

7 candidates did not produce an optimal suggestion (skipped, extraction_failed, or error) — see the JSON for details.
