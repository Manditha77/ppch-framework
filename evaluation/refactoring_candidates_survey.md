# Refactoring Candidate Survey

Ran the real ILP pipeline across 85 PRs at/above the notice threshold (0.4). Sorted first by whether the target method was confirmed as part of the PR's actual diff (trustworthy candidates first), then by line_span (smaller = more localized, more classically "Extract Method"-shaped suggestion).

| PR | Risk | Method | Touched by PR? | Selected stmts | Line span | Remaining complexity | Balanced |
|---|---:|---|---|---:|---:|---:|---|
| #1422 | 0.979 | `getCanonicalName` | ✅ | 2 | 3 | 13.0 | True |
| #1591 | 0.960 | `getShortClassName` | ✅ | 2 | 3 | 4.0 | True |
| #1427 | 0.958 | `getMatchingAccessibleMethod` | ✅ | 2 | 3 | 9.0 | True |
| #1435 | 0.952 | `containsAllWords` | ✅ | 2 | 3 | 4.0 | True |
| #1494 | 0.937 | `toCanonicalName` | ✅ | 2 | 3 | 5.0 | True |
| #1637 | 0.933 | `getAnnotation` | ✅ | 2 | 3 | 10.0 | True |
| #1459 | 0.933 | `numericToIso2` | ✅ | 2 | 3 | 1.0 | True |
| #1382 | 0.932 | `findMatches` | ✅ | 2 | 3 | 1.0 | True |
| #1385 | 0.929 | `toLocalDateTime` | ✅ | 2 | 3 | 0.0 | True |
| #1532 | 0.899 | `isParsable` | ✅ | 2 | 3 | 3.0 | True |
| #1398 | 0.897 | `repeatChars` | ✅ | 2 | 3 | 16.0 | True |
| #1445 | 0.895 | `isAssignable` | ✅ | 2 | 3 | 14.0 | True |
| #1389 | 0.895 | `camelCase` | ✅ | 2 | 3 | 5.0 | True |
| #1495 | 0.887 | `toCleanName` | ✅ | 2 | 3 | 13.0 | True |
| #1482 | 0.887 | `getTimeZone` | ✅ | 2 | 3 | 0.0 | True |
| #1323 | 0.885 | `inContainer` | ✅ | 2 | 3 | 0.0 | True |
| #1390 | 0.885 | `countUpperCaseLetters` | ✅ | 2 | 3 | 2.0 | True |
| #1278 | 0.877 | `equalsAny` | ✅ | 2 | 3 | 3.0 | True |
| #1373 | 0.875 | `truncateToLength` | ✅ | 2 | 3 | 0.0 | True |
| #1633 | 0.851 | `readObject` | ✅ | 2 | 3 | 0.0 | True |
| #1546 | 0.843 | `isParsableDecimal` | ✅ | 2 | 3 | 12.0 | True |
| #1476 | 0.842 | `concat` | ✅ | 2 | 3 | 1.0 | True |
| #1437 | 0.837 | `getCanonicalName` | ✅ | 2 | 3 | 11.0 | True |
| #1630 | 0.817 | `parseLocale` | ✅ | 2 | 3 | 10.0 | True |
| #1649 | 0.813 | `wrap` | ✅ | 2 | 3 | 21.0 | True |
| #1648 | 0.785 | `appendDetail` | ✅ | 2 | 3 | 3.0 | True |
| #1615 | 0.764 | `reflectionEquals` | ✅ | 2 | 3 | 2.0 | True |
| #1664 | 0.761 | `fromChar` | ✅ | 2 | 3 | 1.0 | True |
| #1719 | 0.695 | `abbreviate` | ✅ | 2 | 3 | 11.0 | True |
| #1538 | 0.685 | `truncate` | ✅ | 2 | 3 | 4.0 | True |
| #1704 | 0.667 | `join` | ✅ | 2 | 3 | 2.0 | True |
| #1534 | 0.662 | `join` | ✅ | 2 | 3 | 3.0 | True |
| #1758 | 0.598 | `parse` | ✅ | 2 | 3 | 2.0 | True |
| #1769 | 0.483 | `multiplyBy` | ✅ | 2 | 3 | 0.0 | True |
| #1636 | 0.463 | `join` | ✅ | 2 | 3 | 2.0 | True |
| #1544 | 0.428 | `join` | ✅ | 2 | 3 | 2.0 | True |
| #1392 | 0.947 | `substitute` | ✅ | 3 | 4 | 75.0 | True |
| #1470 | 0.947 | `format` | ✅ | 3 | 4 | 0.0 | True |
| #1328 | 0.912 | `substitute` | ✅ | 3 | 4 | 75.0 | True |
| #1287 | 0.830 | `substitute` | ✅ | 3 | 4 | 75.0 | True |
| #1355 | 0.826 | `append` | ✅ | 3 | 4 | 1.0 | True |
| #1639 | 0.923 | `acquire` | ✅ | 4 | 6 | 1.0 | True |
| #1475 | 0.921 | `acquire` | ✅ | 3 | 6 | 2.0 | True |
| #1474 | 0.848 | `acquire` | ✅ | 3 | 6 | 2.0 | True |
| #1447 | 0.729 | `init` | ✅ | 5 | 7 | 0.0 | True |
| #1760 | 0.671 | `setAccessibleTrue` | ✅ | 4 | 7 | 0.0 | True |
| #1713 | 0.420 | `indexOfDifference` | ✅ | 6 | 8 | 14.0 | True |
| #1558 | 0.836 | `reflectionAppend` | ✅ | 2 | 9 | 1.0 | True |
| #1310 | 0.831 | `toSnakeCase` | ✅ | 5 | 9 | 2.0 | True |
| #1603 | 0.714 | `getLevenshteinDistance` | ✅ | 5 | 9 | 21.0 | True |
| #1601 | 0.697 | `getLevenshteinDistance` | ✅ | 5 | 9 | 21.0 | True |
| #1647 | 0.793 | `reflectionAppend` | ✅ | 3 | 10 | 1.0 | True |
| #1481 | 0.836 | `getTimeZone` | ✅ | 4 | 11 | 0.0 | True |
| #1728 | 0.476 | `swapCase` | ✅ | 3 | 13 | 7.0 | True |
| #1548 | 0.950 | `isAssignable` | ✅ | 7 | 14 | 12.0 | True |
| #1651 | 0.783 | `get` | ✅ | 3 | 14 | 1.0 | True |
| #1629 | 0.902 | `createNumber` | ✅ | 18 | 25 | 21.0 | True |
| #1716 | 0.663 | `createNumber` | ✅ | 18 | 25 | 21.0 | True |
| #1623 | 0.954 | `isCreatable` | ✅ | 14 | 27 | 47.0 | True |
| #1523 | 0.801 | `random` | ✅ | 19 | 43 | 27.0 | True |
| #1521 | 0.739 | `random` | ✅ | 19 | 43 | 30.0 | True |
| #1537 | 0.654 | `random` | ✅ | 19 | 43 | 29.0 | True |
| #1638 | 0.887 | `random` | ✅ | 17 | 45 | 51.0 | True |
| #1703 | 0.655 | `random` | ✅ | 17 | 45 | 56.0 | True |
| #1369 | 0.698 | `listSplitWorker` | ✅ | 15 | 62 | 32.0 | True |
| #1587 | 0.971 | `arrayMemberEquals` | ⚠️ NO | 2 | 3 | 8.0 | True |
| #1394 | 0.898 | `waitFor` | ⚠️ NO | 2 | 3 | 1.0 | True |
| #1643 | 0.877 | `close` | ⚠️ NO | 2 | 3 | 0.0 | True |
| #1497 | 0.863 | `toJson` | ⚠️ NO | 2 | 3 | 15.0 | True |
| #1765 | 0.666 | `getContent` | ⚠️ NO | 2 | 3 | 0.0 | True |
| #1388 | 0.857 | `substitute` | ⚠️ NO | 3 | 4 | 75.0 | True |
| #1600 | 0.657 | `report` | ⚠️ NO | 2 | 7 | 1.0 | False |
| #1700 | 0.971 | `format` | ⚠️ NO | 5 | 9 | 48.0 | True |
| #1590 | 0.875 | `start` | ⚠️ NO | 8 | 12 | 0.0 | True |
| #1714 | 0.602 | `toBooleanObject` | ⚠️ NO | 7 | 17 | 3.0 | True |
| #1411 | 0.988 | `isAssignable` | ⚠️ NO | 18 | 29 | 14.0 | True |

**11 of 76 candidates could not be confirmed as touching the reported method** - these fell back to the file's globally most complex method, which may be unrelated to what the PR actually changed. Prefer ✅-marked rows for any dissertation demo or claim.

**18 of 76 candidates could not get remaining complexity under the target threshold with a single extraction** - shown as best-effort suggestions; these methods likely need more than one extraction to fully resolve.

9 candidates did not produce an optimal suggestion (skipped, extraction_failed, or error) — see the JSON for details.
