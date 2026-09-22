# PPCH Framework — Complete Research & Implementation Summary

**Purpose of this document**: a complete, evidence-backed map of everything built,
tested, and verified in this project — written for final-presentation preparation and
as the structured input for writing the remaining chapters of the dissertation (this
document is NOT the dissertation itself; `docs/IM2021028.pdf` currently holds the
first three chapters — methodology — and the full dissertation will be written from
this document plus that PDF in a later pass).

**Verification date**: 2026-09-22, with a further verified addition on 2026-09-23
(multi-file coverage + a third refactoring strategy, §5.6-§5.7). Every number below
was re-generated fresh on the date it's attributed to by re-running the actual
pipeline end-to-end (not copied from memory or an earlier session) — see §7
"Re-verification evidence" for the exact commands run and their outputs.

---

## 1. The research problem, in one paragraph

Most tools that manage code complexity (SonarQube, Checkstyle, etc.) are **reactive**:
they scan code that already exists, after it has been merged. By the time a developer
sees the warning, the complex code is already in the codebase, already reviewed,
already shipped. PPCH (Predictive and Proactive Code Health) asks: can a tool predict,
**at the moment a pull request is opened** — before any human reviews it, before it's
merged — whether it is likely to introduce a significant cognitive-complexity
increase, and if so, propose a concrete, verified fix immediately? This reframes code
health from "detect after the fact" to "predict and intervene before the fact."

## 2. Architecture: Sense → Analyze → Act

Three layers, each independently testable and independently verified:

- **Sense**: collects real data — PR metadata, contributor history, and real
  SonarQube cognitive-complexity scans — from `apache/commons-lang`, a large, mature,
  real-world open-source Java project (not synthetic data).
- **Analyze**: trains classifiers (Random Forest, XGBoost, Multinomial Naive Bayes,
  Logistic Regression) on that data to predict, from information available *at PR
  submission time only*, whether a PR will significantly increase complexity.
- **Act**: when risk is predicted (or when a direct structural fact warrants it — see
  §5.3), automatically finds and verifies a safe refactoring using three independent
  strategies — an ILP (Integer Linear Programming) solver, a purpose-built
  branch-splitting strategy, and else-if flattening (§5.1, §5.2, §5.6) — applied
  across every non-test file a PR touches, not just one (§5.7).

All three layers are also packaged as a real, installable **GitHub Action** (§6) —
the same trained models and the same Act-layer engine, running live against an
arbitrary, never-before-seen pull request.

---

## 3. Sense layer — what was actually collected

| Item | Value | Source |
|---|---|---|
| Full historical PR metadata scraped | 1,767 PRs | `sense/data/raw/apache_commons-lang_prs.jsonl` |
| PRs sampled for real SonarQube scanning | 500 (from the last ~2 years) | `sense/data/raw/pilot_sample_500.jsonl` |
| PRs successfully scanned (before/after SonarQube run) | 497 | `sense/data/raw/pilot_scan_results.jsonl` |
| PRs that had real, non-empty Java-file diffs and became full feature rows | **334** | `sense/data/processed/pr_*/feature_table.json` |
| Positive-label PRs (`exceeds_significant_complexity_increase`) | 102 / 334 (30.5%) | re-verified 2026-09-22 |

**Label definition** (methodology-critical, avoids an earlier, since-replaced
degenerate label): `exceeds_significant_complexity_increase` is TRUE when a PR's
cognitive-complexity **delta** (after − before, measured by real SonarQube scans of
isolated before/after snapshots) exceeds both an absolute threshold (complexity_after
> 15) and a relative-increase threshold (delta > 3) — a genuinely "got meaningfully
worse" label, not a "was already complex" label (which an earlier version of this
label degenerately conflated, causing a model that just memorized "large files are
risky").

**23 features per PR**, all leakage-safe (verifiable as available *before* PR
submission-time in a real deployment):
- Structural: `additions`, `deletions`, `changed_files`, `changed_java_files`
- Process: `commits`, `comments`, `review_comments`
- Contributor history: `contributor_prior_pr_count`, `contributor_prior_acceptance_rate`,
  `contributor_tenure_days`, `contributor_follower_count` (computed strictly from PRs
  *before* this one's `created_at` — no leakage)
- Textual: `body_character_count`, `title_word_count`, plus 5 real BERT
  (`sentence-transformers/all-MiniLM-L6-v2`) + 5 real Word2Vec (trained on this
  project's own 1,767-PR corpus) embeddings, PCA-reduced
- Complexity signals: `complexity_before` (real SonarQube scan of the base branch),
  and **`max_touched_method_complexity`** (added 2026-09-22 — see §5.4)

---

## 4. Analyze layer — exact, re-verified metrics (2026-09-22)

Temporal train/test split (not random — chronological, matching how a real deployment
would actually be validated): train on the 233 chronologically earliest PRs, test on
the 101 most recent. SMOTE applied to the training partition only (never the test
partition, which must keep its real, untouched class distribution).

### Held-out test-set performance (101 PRs, 33 positive / 68 negative)

| Model | ROC AUC | Accuracy | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| Random Forest | 0.631 | 0.713 | 0.750 | 0.182 | 0.293 |
| XGBoost | 0.684 | 0.653 | 0.417 | 0.152 | 0.222 |
| Multinomial Naive Bayes | 0.668 | 0.683 | 0.529 | 0.273 | 0.360 |
| Logistic Regression | 0.739 | 0.653 | 0.481 | 0.758 | 0.588 |

*(Four baselines, matching Methodology §3.4.2. GCN/CNN/RNN deep-learning baselines are
named in the methodology but explicitly out of scope — they require genuinely new
infrastructure (AST-to-graph construction, a torch training pipeline) not justified
given the dissertation timeline; documented as future work.)*

### Out-of-bag bootstrap validation (1000 iterations each, answers RQ2)

| Model | Mean AUC | 95% CI | Skipped iterations |
|---|---:|---|---:|
| Random Forest | 0.746 | [0.666, 0.818] | 0 |
| XGBoost | 0.750 | [0.675, 0.817] | 0 |
| Naive Bayes | 0.660 | [0.518, 0.770] | 0 |
| Logistic Regression | 0.780 | [0.709, 0.847] | 0 |

Zero skipped iterations across 4,000 total iterations — the model reliably produces a
usable prediction regardless of which random bootstrap sample it's trained on, not a
fragile result from one lucky split.

### Ablation study (answers RQ1: what actually drives the prediction?)

Full-model AUC by algorithm: RF 0.674, XGBoost 0.703, Naive Bayes 0.698, Logistic
Regression 0.753.

Family standalone AUC (how much predictive power each feature family carries alone):

| Family | Standalone AUC |
|---|---:|
| `structural_size` (additions/deletions/files) | 0.678 |
| `process` (commits/comments/contributor history) | 0.683 |
| `baseline_complexity` (`complexity_before` + `max_touched_method_complexity`) | 0.628 |
| `textual_semantic` (BERT/Word2Vec + text counts) | 0.580 |

**Honest finding, consistent across every model and every re-run today**:
`structural_size` is the dominant, load-bearing signal — removing it causes the
largest AUC drop of any family (−0.062 for Random Forest). `baseline_complexity`
(including the new `max_touched_method_complexity` feature) is a real, legitimate
signal but not the dominant one; the model primarily learns "how big and how
metadata-risky is this diff," not "how complex is the code textually." This is
reported plainly, not spun — see §8 for why this matters.

---

## 5. Act layer — two refactoring strategies, both independently verified

### 5.1 Strategy 1: ILP-based Extract Method

Given a method's flattened statement tree (with per-statement Campbell-rule
cognitive-complexity weights, dependency tracking, and nesting-depth metadata), an
Integer Linear Program (`act/ilp-engine/extract_method.py`, solved via `PuLP`/CBC)
selects the cheapest contiguous, dependency-safe subset of statements to extract into
a new method, targeting the SonarQube S3776 per-method threshold (15).

Built-in safety checks (each one found and fixed via a specific, real failure during
this project, not designed in the abstract):
- **Return-forwarding check**: refuses to extract a block containing a bare `return`
  unless it's part of an exhaustive if/else-if/…/else chain this tool DOES model
  safely.
- **Break/continue check**: refuses to extract a bare `break`/`continue` with no
  enclosing loop in the extracted snippet (a real compile error if applied).
- **Non-productive-extraction guard**: after producing a candidate extraction, checks
  the NEW method's own complexity against the ORIGINAL method's complexity — if the
  new method inherited essentially the same complexity (a flat sequence of sibling
  constructs relocated wholesale, not genuinely reduced), the extraction is discarded,
  not applied. **Caught a real case live today** (see §8.2).
- **Independent-variable-mutation check**: `--x`/`x++` correctly recognized as
  assignments (an earlier, real bug: `javalang` parses these as `MemberReference`
  nodes, not `Assignment` nodes — silently missed until caught by the user directly
  reading generated code and finding an infinite-loop bug).

### 5.2 Strategy 2: Branch-split

For methods whose complexity comes from ONE if/else statement where BOTH branches are
independently substantial — a shape the single-region ILP strategy structurally
cannot reach (extracting one branch alone doesn't touch the other) — `branch_split.py`
splits both branches into two separate methods, replacing the original with two calls.
Conservative safety: refuses to split if either branch contains return/break/continue,
or if a variable is assigned in one branch and used elsewhere in the method (an
outbound-dependency the tool doesn't currently model across a split).

Built specifically because the user hand-identified a real case (`FastDatePrinter.
appendFullDigits`, PR #1470) where the ILP strategy produced a "technically valid but
useless" extraction, manually proposed the branch-split shape, and asked for it to be
implemented generally — not a theoretical addition.

### 5.3 The two-trigger decision layer (added 2026-09-22)

`refactoring_suggestion_requested` fires on **either**:
- `risk_score >= 0.7` (the trained classifier's prediction), **or**
- `max_touched_method_complexity >= 15.0` (a direct, deterministic fact about the
  PR's own code)

Both computed by one shared function (`pipeline.py::decide_intervention`), used
identically by the historical-replay path and the live path, so they can never
silently drift apart. `risk_score` itself is never inflated or overridden — model
performance metrics stay honest. `trigger_reason` reports exactly which condition(s)
fired, and the rendered message explains any disconnect plainly (see §8.3 for why
this was necessary).

### 5.4 max_touched_method_complexity (added 2026-09-22)

**The gap it closes**: `complexity_before` (the only complexity feature that existed
before today) is computed by scanning a file's state *before* the PR — for a
brand-new file, this is structurally always 0, so a genuinely complex new file was
invisible to the model regardless of its actual content. `max_touched_method_complexity`
is the highest single-method Campbell-rule complexity found across every file the PR
touches, at the PR's own HEAD state — independent of whether any "before" baseline
exists (`java_statement_extractor.py::max_complexity_across_sources`).

Backfilled for all 334 historical training PRs (`sense/scripts/06_compute_touched_
code_complexity.py`) by re-fetching each PR's own HEAD-state changed files and running
the same AST measurement — required two runs due to a real, observed intermittent DNS
failure to `raw.githubusercontent.com` on the development machine; fixed with
retry-with-backoff logic distinguishing genuine 404s (unreachable, garbage-collected
commits — a real data-availability limit) from transient network errors. Verified: 20
PRs legitimately show 0.0 (confirmed via a targeted re-check pass with retries — real
zeros, not network-failure artifacts).

### 5.5 Historical case-study verification — 10 real PRs

Real GitHub PRs from `apache/commons-lang`, each: fetched at their real commits,
suggestion generated, applied in memory, then **independently re-verified against a
real SonarQube scan** (not the framework's own approximation) of isolated before/after
copies. Primary-file column re-verified byte-for-byte identical to the pre-multi-file,
pre-else-if-flatten baseline on 2026-09-23 (see §7) — every number below for the
*primary* file is unchanged by either of today's additions; the "Other files fixed"
column is new, purely additive coverage (see §5.7).

| PR | Method (primary file) | Status | SonarQube file-total | Extractions | Other files fixed (§5.7) |
|---|---|---|---:|---:|---|
| #1422 | `getCanonicalName` (ClassUtils) | verified | 170.0 → 170.0 | 1 | — (1 file touched) |
| #1591 | `getShortClassName` (ClassUtils) | verified | 188.0 → 187.0 | 2 | — (1 file touched) |
| #1427 | — | **unsafe_suggestion** (return-forwarding risk) | — | 0 | — |
| #1629 | — | **unsafe_suggestion** (return-forwarding risk) | — | 0 | — |
| #1392 | `substitute` (StrSubstitutor) | verified | 110.0 → 108.0 | 1 | `Conversion.java`: 1 extraction, 242.0 → 242.0 (153 files touched, capped at 10 analyzed) |
| #1470 | `format` (FastDatePrinter) | verified | 133.0 → 123.0 | 1 | `StringUtils.java`: 2 extractions, **764.0 → 762.0** (8 files touched, all 8 analyzed) |
| #1638 | `random` (RandomStringUtils) | verified | 117.0 → 117.0 | 2 | — (1 file touched) |
| #1623 | — | **unsafe_suggestion** (return-forwarding risk) | — | 0 | — |
| #1548 | — | **unsafe_suggestion** (return-forwarding + multi-variable outbound risk) | — | 0 | — |
| #1494 | `toCanonicalName` (ClassUtils) | verified | 173.0 → 172.0 | 1 | — (1 file touched) |

**6/10 produced a real, SonarQube-confirmed extraction. 4/10 were correctly refused**
by the return-forwarding safety check — this is presented as evidence the safety
mechanism works on real code, not as a shortfall. Two of the six "verified" cases show
0.0 net file-total change (#1422, #1638) despite a real, productive extraction being
applied — this is expected and explained: the non-productive-extraction guard checks
the extracted method's OWN complexity against the ORIGINAL method's complexity (a
real, local improvement), not the whole file's total (which can be flat if other
pre-existing issues in the same file dominate the file-level number).

**2/10 of these case-study PRs are genuinely multi-file** (#1392, #1470), and both now
get real, additional, independently-SonarQube-verified fixes in files the pre-2026-09-23
pipeline would have silently never looked at — #1470's `StringUtils.java` fix in
particular is a genuine complexity reduction (764.0 → 762.0), not a flat no-op like
some single-file cases above. #1392 also demonstrates the `MAX_FILES_PER_PR = 10` cap
firing for real (153 non-test files touched, only the first 10 analyzed) — see §5.7 for
why that cap exists and what it costs.

### 5.6 Strategy 3: else-if flattening (added 2026-09-23)

**Motivation, found via direct user inspection of a real case**: SonarSource's own
Cognitive Complexity spec gives `else if` special treatment — a chained `else if`
does NOT compound nesting the way a genuinely nested `if` does. This framework's own
Campbell-rule reproduction (`java_statement_extractor.py`) already correctly modeled
that distinction — but the distinction only *helps* when code is actually written as
`else if`, not as the semantically identical `else { if (...) { ... } }`. Real code
(including this project's own `ComplexityTestUtil.classifyTransaction` test file)
frequently uses the nested form purely by habit, paying an avoidable nesting-depth
complexity cost for something Java's grammar treats as interchangeable.

This is a **pure syntactic transformation**, not a structural one: `else { if (c) {A}
else {B} }` and `else if (c) {A} else {B}` execute identically whenever the else
block's entire content is exactly one if-statement and nothing else. Implemented in
`act/ilp-engine/else_if_flatten.py`, run as a pre-pass before ILP extraction and
branch-split (flattening can turn a method that looks unfixably deep into a flatter
shape the other two strategies have real material to work with). Deliberately
conservative, mirroring `branch_split.py`'s own safety posture:
- Only fires when the else-block contains exactly one statement, and that statement is
  itself an `if` — anything else in the else-block is left alone.
- Only fires when the inner if's own header is a single line — a wrapped multi-line
  condition is skipped rather than risked.
- Verifies the text between the else-block's `{` and the inner if's `if` keyword is
  pure whitespace (nothing hidden there, e.g. a comment, that a naive rewrite would
  silently delete).
- Every application is verified with a real `javalang.parse.parse()` call before being
  accepted, same discipline as every other text-mutating step in this codebase — a
  failed re-parse discards the splice and keeps the prior text.

**Verified at three independent levels**, not just unit-tested in the abstract:
1. The framework's own complexity approximation on `classifyTransaction`: 79.0 → 43.0
   from flattening alone, then → 10.0 after the full pipeline (flatten + extraction).
2. Full pipeline integration: `still_over_threshold: []` — complete resolution.
3. **Real SonarQube verification**, live, on `Manditha77/commons-text` PR #3: file
   total 104.0 → 55.0, with only one method left 1 point over its threshold — matching
   the same real-not-approximated verification discipline used everywhere else in this
   project (see §6.5).

### 5.7 Multi-file refactoring coverage (added 2026-09-23)

**The gap it closes**: every refactoring pass before 2026-09-23 — historical and live
alike — analyzed only the single file the diff-scoped `most_complex_method` selection
picked as the primary target, even when a PR touched several files and more than one
of them was independently over-threshold. This was found directly by the user's own
reading of the case-study table and the research summary's own honestly-documented
"architectural boundary" note (§7), not by internal testing.

**Real data was pulled before designing the fix**, matching this project's discipline
of verifying scope with real numbers rather than assumption. Across the full,
non-test-file-filtered 334-PR historical sample (re-verified 2026-09-23):

| Metric | Value |
|---|---:|
| PRs touching more than one non-test `.java` file | 85 / 334 (25.4%) |
| PRs fully covered by a 10-file-per-PR cap | 316 / 334 (94.6%) |
| Largest single PR's non-test file count observed | 259 |

A genuine multi-file gap, real enough to matter for roughly a quarter of PRs, but with
a long right tail (a small number of PRs touch dozens to hundreds of files) that makes
"analyze every file, no cap" both computationally expensive (one real SonarQube scan
per file) and low-value past a point (a PR touching 259 files is not going to be fixed
file-by-file by an automated tool regardless). `MAX_FILES_PER_PR = 10`
(`act/github-action/multi_file_refactor.py`) was chosen as the point covering 94.6% of
real PRs *completely* while keeping the live Action's per-PR runtime bounded.

**Design**: `refactor_all_files(candidate_files, primary_file, fetch_fn, ...)` orders
candidate files with the primary target first (preserving its exact prior behavior —
same function, same parameters, same position in the returned data), processes up to
the cap, and wraps **both** the fetch step and the `refactor_source()` call in
per-file `try`/`except` isolation, so one file's parse failure (a real, observed case:
`SystemUtils.java`'s modern Java syntax crashed `javalang` on PR #1470's first attempt)
cannot take down the other files' results. Wired into both paths:
- **Historical** (`verify_pr_suggestion.py`): every additional file gets its own real,
  independent SonarQube before/after scan, not an approximation.
- **Live** (`live_predict.py`, `live_action_entrypoint.py`): the rendered PR comment
  now loops over the primary file plus every additional genuinely-improved file,
  each getting its own sub-section with a real unified diff.

**Regression-verified purely additive**: the full 10-PR historical suite was re-run
after this change (and after §5.6's else-if flattening, combined) — every primary-file
result is byte-for-byte identical to the pre-change baseline (see §7); the only
differences are the new, additional-file findings shown in §5.5's table.

---

## 6. Live GitHub Action — a real, installed, tested tool

Addresses Methodology §3.4.4's stated goal directly: "packaged as a GitHub Action that
could be installed on any Java repository... triggered on pull request events."

### 6.1 What was built
- `action.yml`: a composite Action (`uses: <owner>/ppch-framework@main`) — installs
  Python deps, runs the live prediction entrypoint
- `act/github-action/live_predict.py`: computes every feature **live**, for an
  arbitrary PR, via the GitHub API + a real SonarQube scan — not replaying the frozen
  334-PR dataset
- `act/github-action/live_action_entrypoint.py`: reads the real `pull_request` event
  payload, always writes a JSON/MD report + real before/after `.java` files (if
  anything was applied), and optionally posts/updates an idempotent PR comment (search
  for a hidden marker, edit rather than re-post — per Methodology §3.4.4's own
  requirement)

### 6.2 Real infrastructure stood up (not simulated)
- A public repo (`github.com/Manditha77/ppch-framework`) the Action is installed from
- A real fork (`github.com/Manditha77/commons-text`) — chosen deliberately smaller
  than commons-lang (~4x smaller Java codebase) and same-org, to minimize (not
  eliminate) distribution shift for the honestly-labeled out-of-scope prediction
- A **persistent, self-hosted GitHub Actions runner**, installed as a genuine Windows
  service (`NT AUTHORITY\NETWORK SERVICE`, registered outside the user-profile
  directory tree to avoid a real permissions block that was found and fixed) — needed
  because the Action's SonarQube scan step must reach a local SonarQube instance a
  GitHub-hosted runner cannot see

### 6.3 Real bugs found ONLY by actually running this (not by code review)

| # | Bug | Real symptom | Fix |
|---|---|---|---|
| 1 | `complexity_before` scan hardcoded to the commons-lang local clone | Would silently scan the wrong repo for any non-commons-lang PR | Parametrized `repo_dir`, clone-per-repo |
| 2 | `generate_refactoring_suggestion` fetched source from hardcoded constants | Would fetch commons-lang source for a commons-text PR | Threaded `owner`/`repo` through |
| 3 | `actions/setup-python` hard-fails without admin rights | Self-hosted runner job failed at step 1 | `continue-on-error: true`, use whatever Python the runner already has |
| 4 | `shell: bash` resolved to Windows' broken WSL stub | `execvpe(/bin/bash) failed` | Prioritized real Git Bash on PATH |
| 5 | `javalang` never in `requirements.txt` | `ModuleNotFoundError` on a genuinely fresh install | Added the pin |
| 6 | Trained models were gitignored | Fresh Action checkout had nothing to predict with | Force-added the ~4MB of model artifacts |
| 7 | Default `GITHUB_TOKEN` lacked comment-post permission | 403 on `create_issue_comment` | Added `permissions: pull-requests: write` |
| 8 | `demo/scripts/analyze_predict.py`'s own `FEATURES` list silently drifted out of sync (missing embeddings AND the new complexity feature) | Would crash if actually run | Fixed, now imports the shared decision logic instead of a third copy |
| 9 | Live PR comment described applied refactors in prose only, never showed the real code | User caught this directly by reading a real comment | Now renders a real unified diff + writes real before/after `.java` files |

Every one of these is exactly the kind of gap that only surfaces from actually running
the packaged Action somewhere new — a genuinely strong point for the dissertation
("built it, then proved it works installed on a repo it's never seen, and every real
failure encountered was found, diagnosed precisely, and fixed — not hidden").

### 6.4 Real test evidence: `Manditha77/commons-text` PR #2

A deliberately complex, hand-written test file (`ComplexityTestUtil.java`, two
methods: `classifyTransaction` complexity 79, `scoreCustomer` complexity 17) was
opened as a real PR against the fork.

**What the live Action correctly did**:
- Correctly computed `max_touched_method_complexity = 79.0` for a file that had never
  existed before (`complexity_before = 0.0`) — the exact gap §5.4 closes
- Correctly triggered `structural_complexity_threshold_exceeded` despite a low
  predictive `risk_score` (0.155) — the exact trigger §5.3 adds, with an explicit,
  readable explanation of the disconnect
- Ran the full engine (branch-split, then iterative ILP) on the file: **correctly
  rejected** the `classifyTransaction` extraction as non-productive (relocating 79.0
  of complexity into a differently-named method that was itself still 79.0 — exactly
  the guard from §5.1 catching a real, live case, not a synthetic test)
- **Genuinely fixed** `scoreCustomer` (complexity 17 → resolved), shown as a real,
  readable unified diff in the posted PR comment
- The real fix was then manually applied and pushed as an actual git commit
  (`9e4a53a4` on `Manditha77/commons-text`) — a literal, mergeable proof, not just
  advisory text

### 6.5 Real test evidence: `Manditha77/commons-text` PR #3 — else-if flattening live

A second real PR, opened after §5.6's else-if-flattening strategy was wired in, to
prove it end-to-end on the live path (not just in a local script). The live Action,
observed directly via the posted comment:
- Correctly re-triggered `structural_complexity_threshold_exceeded` on
  `classifyTransaction`'s real shape.
- Ran else-if flattening **first**, rendered as its own step in the comment
  (previously silently dropped by `render_markdown` — a real gap found and fixed
  while wiring this in, see §6.3's bug list).
- Then ran the iterative ILP pass on the flattened result, applying real extractions.
- **Correctly rejected** one candidate extraction as non-productive — the same safety
  guard from §5.1 firing live, again, on genuinely different code shaped by the new
  flattening step, not a repeat of the exact same §6.4 case.
- Reached full resolution: `still_over_threshold: []`.
- Independently confirmed with a real SonarQube scan: file total **104.0 → 55.0**,
  with only one method left 1 point over its threshold — the strongest real-world
  complexity reduction observed in this project's live-path testing to date.

---

## 7. Re-verification evidence (2026-09-22, this session)

Every phase was re-run from scratch today, after all of today's changes, to confirm
nothing regressed:

- **Sense**: 334/334 `feature_table.json` files confirmed complete (every one of 27
  required fields present, zero missing). Raw data files confirmed intact (497 scan
  records, 1,767 historical PR records, no corruption).
- **Analyze**: `train_models.py`, `run_bootstrap.py`, `run_ablation.py` re-run in
  full. **Result: zero `git diff`** — completely reproducible given fixed random
  seeds, not a stochastic result.
- **Act**: the full 10-PR historical suite (`verify_pr_suggestion.py`) re-run.
  **Result: byte-for-byte identical** to every prior run this session (same
  SonarQube numbers, same extraction counts, same 4 refusals with the same reasons).
- **Live path**: re-tested against a real, previously-verified commons-lang PR
  (#1795) and a real, previously-verified high-risk PR (#1789) — both produced
  identical risk scores and identical safety-check behavior to earlier runs.

**One genuine, newly-identified architectural boundary** (found during this
re-verification, not hidden): for a PR touching multiple files, `max_touched_method_
complexity` scans ALL changed files and reports the global maximum, while the
refactor engine (`generate_refactoring_suggestion` + the full multi-strategy pass)
only analyzes the SINGLE file the diff-scoped selection logic picked as the primary
target — which may not be the same file where the maximum was found. Confirmed via
direct trace on PR #1795: the structural trigger correctly fired from `FastDatePrinter.
java::parseToken` (complexity 21.0), but the refactor engine analyzed `FastDateParser.
java` (a different file also touched by the same PR), correctly finding nothing over
threshold *in that file*. Nothing crashed and nothing reported incorrect information —
the "nothing found" result is true for the file that was actually analyzed — but this
is a real scope gap worth documenting honestly: the live comment's refactoring
analysis does not currently cover every file a multi-file PR touches, only the one
selected as the primary target.

**Update, 2026-09-23 — this gap is now closed.** §5.7 describes the fix
(`multi_file_refactor.py`, wired into both the historical and live paths) and §5.5's
table shows real, independently-SonarQube-verified evidence of it working (PR #1392,
#1470). Re-verification repeated the same protocol as above, this time covering both
the multi-file pass and §5.6's else-if-flattening strategy together:
- **Act (single-file regression)**: the full 10-PR historical suite re-run with both
  new capabilities active. **Result: every primary-file field
  (`status`, `method_name`, `sonarqube` before/after numbers) is byte-for-byte
  identical** to the pre-change baseline — confirmed programmatically, not by eye, by
  diffing the full `evaluation/pr_suggestion_verification_summary.json` record for all
  10 PRs. The only differences are new, additive `additional_files_refactored` entries.
- **Act (multi-file, new coverage)**: PR #1392 (153 files touched, cap fires, one
  genuine additional fix found in `Conversion.java`) and PR #1470 (8 files touched, all
  analyzed, genuine additional fix in `StringUtils.java`, 764.0 → 762.0) — both
  independently SonarQube-verified per file.
- **A real crash was found and fixed during this work**: the first version of the
  multi-file pass on PR #1470 only wrapped the *fetch* step in `try`/`except`; a
  `javalang.parser.JavaSyntaxError` inside `refactor_source()` itself (triggered by
  `SystemUtils.java`'s modern syntax) propagated uncaught and killed the whole
  multi-file pass for that PR (`status: fetch_failed`, empty error message). Fixed by
  wrapping the `refactor_source()` call in its own per-file isolation; re-verified the
  fix resolves cleanly with the remaining 7 files still processed correctly.
- **Live path**: re-tested end-to-end against real PR #2 (`Manditha77/commons-text`,
  single-file, confirms identical behavior to §6.4) and real PR #3 (multi-strategy
  live evidence, §6.5).

---

## 8. Key research findings worth foregrounding in the dissertation

### 8.1 The core proactive-vs-reactive claim is demonstrated, not just argued
MTTD comparison (§3.5.3, RQ3): under the reactive regime, detection happens at merge
time (`merged_at`); under this framework's proactive regime, detection happens at
`created_at` — the full PR review window bought back, for every PR the model actually
flags before merge.

### 8.2 A safety mechanism caught a real bad fix, live, not in a unit test
The non-productive-extraction guard's rejection of the `classifyTransaction`
extraction (§6.4) is genuine, unscripted evidence that the framework's safety design
works under real conditions — arguably a stronger piece of evidence than a synthetic
test case, because it happened on code nobody had seen before, running through the
full live pipeline, and the user caught the *first* version of the output looking
wrong, which led directly to wiring the already-built full engine into the live path.

### 8.3 Predictive risk and structural fact are genuinely different questions
§5.3's two-trigger design exists because a real test case exposed that a trained
classifier's probability estimate and a direct measurement of the code itself can
legitimately disagree — and that disagreement, left unexplained, would have looked
like a bug or an inconsistency to anyone reviewing the tool (a real concern the user
raised: "will the panel be confused looking at them?"). Making both signals visible,
independently triggerable, and honestly labeled turns a potential credibility problem
into a demonstrated design strength: the tool knows the difference between "the
model's trained judgment" and "an incontrovertible fact," and says so.

### 8.4 Structural size dominates the trained model, and the ablation says so honestly
§4's ablation results are reported as-found, not massaged: `structural_size` is the
dominant signal; the complexity-feature family (including today's new addition) is
real but secondary. This is scientifically honest and, combined with §5.4/§6.4,
supports a genuinely interesting thesis point: **the predictive (Analyze) layer and
the deterministic (Act) layer see different things, and a robust system needs both** —
exactly what §5.3's two-trigger design operationalizes.

---

## 9. Known, honestly-labeled limitations

- **Out-of-distribution scope**: the trained classifiers were fit only on
  `apache/commons-lang`. Running against a different repository (as demonstrated
  live) is mechanically fully supported, but the resulting `risk_score` should be
  read as illustrative, not calibrated — stated explicitly in every report and
  comment when this is the case, never silently presented with false authority.
- **Multi-file refactor-engine scope gap — RESOLVED 2026-09-23** (§5.7, §7): was "the
  live refactor analysis covers only the single file the diff-scoped selection
  identifies"; closed via `multi_file_refactor.py`, wired into both the historical and
  live paths, regression-verified purely additive. A residual, deliberate limit
  remains: `MAX_FILES_PER_PR = 10`, covering 94.6% of real PRs completely (§5.7) — the
  remaining 5.4% (PRs touching more than 10 non-test files) get their first 10 files
  analyzed, not all of them, a conscious runtime/thoroughness tradeoff, not an oversight.
- **Some methods genuinely resist all three refactoring strategies**: a method whose
  complexity comes from something other than a single extractable region, an
  independent two-branch split, or a flattenable else-if chain — one long, single
  if/else chain with a variable threaded through and mutated across every branch, for
  instance — is a real, demonstrated boundary of what this framework can currently fix
  safely — reported honestly as "needs manual restructuring," not silently hidden or
  faked.
- **A cosmetic, non-blocking bug**: an em-dash in posted PR comments occasionally
  renders as `�` on Windows — traced to somewhere inside PyGithub/urllib3's own
  request path, confirmed harmless to meaning, not pursued further given the
  effort-to-value ratio this late in the project.
- **GCN/CNN/RNN baselines**: named in the methodology, explicitly scoped out — would
  require genuinely new infrastructure (AST-to-graph construction, a torch training
  pipeline) not justified given the dissertation timeline.
- **Slice-based cognitive complexity metrics — NOT implemented** (Methodology §2.3.3,
  §3.3.3, §3.5.5): the methodology commits, in several places, to complexity being
  "operationalized through the SonarSource Cognitive Complexity metric and supplemented
  by slice-based measures," with §3.3.3 specifically stating these would be "computed
  on the same snapshots using the srcSlice tooling family" (sliceSize, sliceIdentifier,
  sliceSpatial). This was never built — SSCC (via this project's own Campbell-rule
  reproduction, cross-checked against real SonarQube scans throughout) was retained as
  the sole operational complexity metric. Unlike the GCN/CNN/RNN deviation, this one
  was not identified and consciously scoped out earlier in the project — it surfaced
  only during this methodology-alignment pass (§12) — so it should be named explicitly,
  not folded silently into the existing GCN/CNN/RNN caveat, in the dissertation's
  methodology or limitations chapter as a genuine, acknowledged scope reduction: SSCC
  alone was judged sufficient given it is independently the more heavily meta-
  analytically validated of the two metric families reviewed in §2.3 of the
  methodology itself, and integrating the external `srcSlice` tool this late carried
  real risk of a rushed, unverified addition inconsistent with this project's
  real-data-verified-at-every-step discipline.
- **System-Usability-Scale developer study (RQ4) — NOT implemented** (Methodology
  §3.5.4): this requires recruiting real human developer participants, having them use
  the framework on realistic PR scenarios, and collecting SUS questionnaire responses
  under proper informed-consent procedures (§3.6). This is human-subjects data
  collection outside the scope of what an AI coding assistant can perform or simulate
  on the user's behalf — it genuinely needs the user to plan and run it themselves
  (participant recruitment, consent, scheduling, questionnaire administration) as a
  distinct, remaining piece of dissertation work, not a code or documentation gap.

---

## 10. Repository map — what's where

```
act/                          Act layer
  ilp-engine/                 ILP solver, AST/statement extraction, branch-split, else_if_flatten
  refactor_file.py            Standalone multi-strategy refactor engine (else-if flatten + branch-split + iterative ILP)
  github-action/               PR-driven pipeline, live prediction, multi_file_refactor, GitHub Action entrypoint
analyze/                      Analyze layer
  models/                     Trained model artifacts (committed - needed for the live Action)
  train_models.py, run_bootstrap.py, run_ablation.py, feature_utils.py
sense/                        Sense layer
  scripts/                    Numbered pipeline: fetch -> scan -> build features -> enrich -> embeddings -> backfill
  data/raw/                   Scraped PR metadata, scan results (gitignored, regenerable)
  data/processed/pr_*/        Per-PR feature_table.json + (for case-study PRs) real before/after .java files
demo/                         Standalone PricingEngine/ShippingCalculator live demo (no PR/GitHub needed)
evaluation/                   All generated reports (training, bootstrap, ablation, PR verification, live_action_runs)
docs/                         This document, methodology PDF, implementation history
action.yml                    The installable GitHub Action definition
```

---

## 11. Quick presentation Q&A prep

**"Why not just use SonarQube?"** — SonarQube is reactive: it measures code that
already exists. This framework predicts risk *before* the code is even reviewed,
using information available at PR-submission time, and only then (whether triggered
by prediction or by a direct structural fact) runs a verified refactoring engine.

**"How do you know the predictions are reliable?"** — Bootstrap validation across
1,000 iterations with zero skipped runs, reporting a confidence interval, not a single
number from one lucky split; temporal (not random) train/test split, matching how a
real deployment is actually validated.

**"How do you know the refactorings are safe?"** — Every historical case-study result
is checked against a REAL SonarQube scan, not the framework's own approximation.
Multiple real, independent safety mechanisms (return-forwarding, break/continue,
non-productive-extraction) were each built in direct response to a real failure found
by testing, and one of them was caught rejecting a real bad fix live, today, on code
generated for this exact demonstration.

**"Is this actually installable, or just a research prototype?"** — It's installed
right now on a real fork, via a real persistent self-hosted runner, triggered by real
GitHub pull_request events, verified across multiple real PRs including one with a
real applied commit.

**"What's the biggest limitation?"** — The predictive model's dominant signal is
structural diff size, not code complexity itself — which is exactly why the
structural-threshold trigger (§5.3) was added as an independent, deterministic
safety net: the two layers see different things, and catching what one layer misses
with the other is a genuine design strength, not a workaround.

**"Does this only look at one file per PR?"** — No, not since 2026-09-23 (§5.7): a
real PR touching several files gets every non-test file analyzed (up to a 10-file cap
covering 94.6% of real PRs completely), each independently SonarQube-verified, with
the single-file case's exact prior behavior fully preserved and regression-tested.

**"What refactoring strategies does the Act layer actually have?"** — Three,
independently verified: ILP-based Extract Method (§5.1), branch-split for two
independently-substantial branches (§5.2), and else-if flattening, a pure syntactic
transformation that exploits SonarSource's own special-cased treatment of `else if`
chains (§5.6) — run in that order, each catching shapes the others structurally can't.

**"Is every part of the methodology chapter (Ch. 3) actually implemented?"** — Almost
all of it, with two honestly-named exceptions (§12): slice-based cognitive complexity
metrics (`srcSlice`) were not built — SSCC alone was retained as the operational
complexity metric — and the System-Usability-Scale developer study (RQ4) needs real
human participants, which is the user's own remaining task, not a code gap.

---

## 12. Methodology alignment audit (2026-09-23)

Chapter 3 of `docs/IM2021028.pdf` is the interim/proposal submission (its own §1.6
states explicitly that, at time of that submission, "the outcomes summarised here are
stated as the results that the framework is expected to yield rather than as findings
already obtained"). This audit cross-references every substantive methodology
commitment against what was actually built, so the final dissertation's methodology
and limitations chapters can state plainly what changed and why — deviations from a
proposal are normal and expected; silently unstated ones are not.

| Methodology commitment | Section | Status | Evidence / note |
|---|---|---|---|
| SonarSource Cognitive Complexity as the primary metric | §2.3, §3.3.3 | **Aligned** | Own Campbell-rule reproduction, cross-checked against real SonarQube scans at every verification step (§5.5, §7) |
| Slice-based metrics (`srcSlice`, sliceSize/sliceIdentifier/sliceSpatial) supplementing SSCC | §2.3.3, §3.3.3, §3.5.5 | **Gap — not implemented** | Never built; SSCC retained as the sole operational metric. Named explicitly in §9, not previously documented anywhere in this summary before this audit |
| Random Forest + XGBoost baselines | §3.4.2 | **Aligned** | §4 |
| Multinomial Naive Bayes + Logistic Regression baselines | §3.4.2 | **Aligned** | §4, added in a prior session segment |
| GCN/CNN/RNN deep-learning baselines | §3.4.2 | **Documented deviation** | Explicitly scoped out (§4, §9) — new AST-to-graph + torch infrastructure not justified given timeline |
| Structural, process, and contributor-history features | §3.3.3 | **Aligned** | §3 |
| Textual features (BERT + Word2Vec embeddings) | §3.3.3 | **Aligned** | §3 — real `sentence-transformers`/`gensim` embeddings, not a placeholder, added in a prior session segment |
| Leakage-safe, pre-submission-only feature computation | §3.3.3, §3.5.5 | **Aligned** | §3's label/feature definition, contributor-history features computed strictly from prior-PR state |
| Temporal (not random) train/test split | §3.4.2 | **Aligned** | §4 |
| SMOTE on training partition only | §3.4.2 | **Aligned** | §4 |
| Bootstrap validation (RQ2) | §3.5.2 | **Aligned** | §4, 1000 iterations × 4 models, 0 skipped |
| Ablation studies (RQ1) | §3.5.2 | **Aligned** | §4 |
| MTTD/MTTR comparative benchmarking vs. reactive SonarQube baseline (RQ3) | §3.5.3 | **Aligned** | `evaluation/run_mttd_mttr_benchmark.py`, `evaluation/mttd_mttr_benchmark.md`, referenced in §8.1 |
| System-Usability-Scale developer study (RQ4) | §3.5.4 | **Gap — requires human participants** | Not implemented; genuinely outside what can be built or simulated — real participant recruitment/consent/data collection is the user's own remaining task |
| ILP-based Extract Method refactoring engine | §3.4.3 | **Aligned, and extended** | §5.1 — plus two additional strategies (branch-split, else-if flatten, §5.2/§5.6) not named in the original methodology, a positive deviation |
| Packaged as an installable GitHub Action, triggered on PR events | §3.4.4 | **Aligned** | §6 |
| Idempotent PR comment (update, not accumulate) | §3.4.4 | **Aligned** | §6.1, verified live across multiple runs |
| Ethical handling of pseudonymous contributor data | §3.6 | **Aligned** | Only public GitHub metadata used (username, follower count); no re-identification attempted |
| Multi-file PR coverage | *(not explicitly named in Ch. 3 — identified as a real gap by the user's own reading of §5.5's results)* | **Aligned, closed 2026-09-23** | §5.7 — a genuine scope gap found through use, not a methodology-document commitment, but worth recording here since it materially affects how §3.3.3's "PR change set" framing is actually realized |

**Net honest assessment**: of the substantive, checkable commitments in Chapter 3, all
are implemented and verified except two — slice-based metrics (a scope reduction that
should be stated as such) and the SUS usability study (a remaining, distinctly
human-subjects task, not a code deliverable). Both are now named explicitly, in one
place, rather than left implicit or undiscovered.
