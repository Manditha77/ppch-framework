# Phase I — Data Collection: Full Progress & Rationale
IM/2021/028 · Manditha Madushanka · Supervisor: Prof. Janaka Wijayanayake
For supervisor discussion — post-interim implementation progress (updated)

---

## PART A — ENGLISH

### A.1 GitHub PR extraction — what was done, step by step, and why

| Step | What happened | Why (mapped to Methodology) |
|---|---|---|
| **1. Created a GitHub Personal Access Token (PAT)** | Generated an authentication token from a personal GitHub account | GitHub's API allows only 60 requests/hour without authentication, but 5,000/hour with a token. Since §3.3.2 requires pulling PR history "through the GitHub REST and GraphQL Application Programming Interfaces," an authenticated token is required to do this at any real scale. |
| **2. Set up Python environment (VS Code, venv, requirements.txt)** | Installed PyGithub, pandas, python-dotenv | Tools needed to call the GitHub API and later do feature engineering — practical machinery, no methodology significance on its own. |
| **3. Stored the token in a `.env` file** | Token kept out of the script itself | Standard security practice — a secret token should never be hardcoded or committed to version control. |
| **4. Ran the extraction script on `apache/commons-lang`** | Script pulled every PR regardless of outcome — open, closed, merged, or rejected — along with title, body, diff size, timestamps, contributor identity, and discussion counts | Implements §3.3.1: *"All PRs opened during the sampled projects' history were included in the frame, and no PR was excluded on the grounds of its outcome."* And §3.3.2: *"Historical PR data were extracted through the GitHub REST and GraphQL... the metadata retrieved included the title, the body, the change-set diff, the list of modified files, the timestamps of submission and merge (or closure), the identity and history of the contributor, and the full review discussion."* |
| **5. Result** | 1,767 PRs successfully extracted and saved locally as raw data | First concrete evidence the Sense-layer data pipeline works; gives a real, sized dataset to build the rest of Phase I against. |

**Important distinction for supervisor:** this step only collected *raw metadata*. No cognitive-complexity values, no labels, no leakage-safe features existed at this point — that was the next stretch of work, described below, because §3.3.2 requires *"all features [to be] computed strictly from the state of the world visible at the moment of PR submission... post-submission signals... used only as labels."*

### A.2 Deeper rationale behind the tools and choices made

**Why GitHub's API was needed at all**
- The ML model needs thousands of real, labeled historical PRs to learn from — this data isn't available as a ready-made dataset anywhere.
- It only exists inside GitHub's servers, attached to each project's repository.
- The only practical way to pull PR data at this scale (1,700+ PRs) is programmatically, through GitHub's API — manually opening and copying 1,767 web pages is not feasible, nor reproducible as a research method.

**Why both REST and GraphQL are named in the methodology**
- **REST API** — simple, one-request-per-resource (e.g. "give me PR #452"). Used for this first pilot run because it is easy to build and debug — the right choice for a first working version.
- **GraphQL API** — can fetch multiple nested pieces of data (a PR + its reviews + its commits + its author's history) in a *single* request, saving API rate-limit quota.
- REST got a working pipeline running fast; GraphQL becomes the relevant optimization if a larger repo (e.g. Kafka's much bigger PR volume) starts hitting rate-limit constraints under REST.

**Why `apache/commons-lang` was chosen as the pilot project**
- **Pure Java, lightweight build** — no complex multi-module Maven/Gradle setup, so it's fast to clone and fast for SonarScanner to analyze.
- **Mature project with a large, complete PR history** (1,767 PRs) — satisfies the "mature, actively maintained" requirement from scope §3.5/§1.5.
- **Cheap to debug the pipeline against** before scaling to the full three-project sample (commons-lang + Kafka + Dubbo) required for domain diversity in the scope.

---

### A.3 SonarQube & SonarScanner environment setup (Methodology §3.3.2)

Extraction only gives PR *metadata* — none of it says anything about **cognitive complexity**. That number has to be computed by actually running a static-analysis tool against the real source code, which is why a second toolchain had to be installed and validated before any complexity data could be collected.

| Step | What was done | Why |
|---|---|---|
| 1 | Ran a local **SonarQube server** via Docker (`docker run ... sonarqube:community`) | SonarQube is the engine that computes SonarSource Cognitive Complexity (SSCC) and stores analysis results. Running it locally means no cost, no external account, and full control — appropriate for a reproducible research pipeline. |
| 2 | Logged in with the default `admin`/`admin` credentials, then set a new password | SonarQube ships with a built-in admin account; no separate registration is needed. |
| 3 | Generated a **SonarQube authentication token** (My Account → Security → Generate Tokens) | Same purpose as the GitHub PAT — authenticates the scanner client against the server without exposing a password. |
| 4 | Installed the **SonarScanner CLI** and added it to the system PATH | This is the command-line tool that actually walks a codebase and sends the analysis to the SonarQube server. |
| 5 | Verified installation with `sonar-scanner -v` | Confirmed correct install before attempting a real scan — same "verify before automating" discipline used for the GitHub script. |

---

### A.4 Manual single-PR validation test — proving the pipeline before automating it

Rather than writing an automated script that loops through 1,767 PRs untested, a **single PR was scanned manually first** — the same "pilot before scale" discipline applied earlier to project selection. This step deliberately mirrors real empirical software-engineering practice: validate the mechanism on one unit before trusting it across the full sample.

**What was done:**
1. Cloned the actual `apache/commons-lang` source repository locally (separate from the PR metadata, which only contains commit references, not the code itself).
2. Selected **PR #1** from the dataset and pulled its `base_sha` (code state *before* the PR) and `head_sha` (code state *after*).
3. Attempted `git checkout <base_sha>` to get the pre-PR code snapshot.
4. Created a `sonar-project.properties` config file and ran `sonar-scanner` against that snapshot.
5. Confirmed success on the SonarQube dashboard (`http://localhost:9000`) — the project appeared with a computed complexity measure.

**Issues encountered and resolved (worth reporting to supervisor as real findings, not just obstacles):**

| Issue | What happened | Resolution | Significance |
|---|---|---|---|
| **Unreachable commit SHA** | `git checkout <base_sha>` failed with `fatal: unable to read tree` — the commit existed according to GitHub's API, but wasn't present in a standard clone | Ran `git fetch origin <sha>` directly, then `git checkout FETCH_HEAD`, which successfully retrieved it | `commons-lang` was migrated to the Apache Top-Level Project (visible in the log as commit `"Moving to TLP"`) years ago; very old commits like PR #1's base can be orphaned from the default branch history even though GitHub still serves them by SHA. **This is a genuine data-quality finding**, directly relevant to the "threats to validity" discussion already anticipated in Methodology §3.5.5 (label/history noise) — it means the automation script must gracefully handle and log unreachable commits rather than assume every SHA in the dataset is checkoutable. |
| **PowerShell argument-parsing error** | `sonar-scanner -Dsonar.host.url=... -Dsonar.token=...` failed with `Unrecognized option` | Switched to setting `$env:SONAR_HOST_URL` and `$env:SONAR_TOKEN` as environment variables instead of command-line flags, then ran `sonar-scanner` with no arguments | Purely a tooling/shell quirk, not a methodology issue — but a useful implementation note, since the automation script will need to set these programmatically (e.g. via Python's `subprocess` with an environment dict) rather than relying on inline CLI flags. |

**Result:** `EXECUTION SUCCESS` — the scan completed in ~1 minute 22 seconds, uploaded a report to SonarQube, and the project (`commons-lang-test-pr`) appeared on the dashboard with a visible complexity measure. **This confirms the entire chain works end-to-end: GitHub metadata → git checkout → SonarScanner → SonarQube analysis → retrievable metric.**

---

### A.5 Decision: scaling down from 1,767 to a 30-PR automated batch

**The constraint:** the manual test took ~1.5 minutes for a single scan. Each PR requires **two** scans (before and after). Scanning all 1,767 PRs sequentially would take:

```
1,767 PRs × 2 scans × ~1.5 min ≈ 88 hours of continuous scanning
```

This is impractical for a solo research implementation on this timeline, and — critically — **not necessary** for the purpose of this dissertation phase. The goal at this stage is to **demonstrate that the PPCH framework works end-to-end as a proof of concept**: that predictive analysis and proactive intervention can be built, integrated, and shown to function correctly. A full-scale 1,767-PR dataset would be appropriate for a production deployment or a large-scale empirical replication study, but is not a precondition for validating the framework's design and mechanics.

**Decision:** scale the automated extraction down to a **~30-PR batch**, sufficient to build a working, demonstrable, and defensible version of the full Sense → Analyze → Act pipeline, with the option to scale up later if time permits.

**Two implementation refinements made alongside this decision, to make the automation robust:**
1. **Unique SonarQube project keys per scan** — the manual test used a single fixed key (`commons-lang-test-pr`); the automated script must generate a unique key per PR/commit (e.g. `cl-pr1-base`, `cl-pr1-head`) so results don't overwrite one another.
2. **Pulling results via the SonarQube Web API** rather than reading the dashboard by eye — `GET /api/measures/component` returns the Cognitive Complexity value directly as JSON, which is what allows the script to save results into the dataset automatically instead of requiring manual lookup for every one of 60 scans (30 PRs × 2 states).

### A.6 What happens next — from raw data to a trained model (revised)

```
sense/data/raw/apache_commons-lang_prs.jsonl   ← 1,767 raw PR records (done)
        │
        │  Sample 30 PRs for the pilot batch
        ▼
   For each of the 30 PRs:
        │  Step A: git checkout base_sha and head_sha (handling unreachable
        │           commits via explicit "git fetch <sha>" fallback, as
        │           validated in the manual test)
        ▼
   two code snapshots per PR: before / after
        │
        │  Step B: run SonarScanner on both, each with a unique project key
        ▼
   Step C: pull the Cognitive Complexity value for each snapshot via the
           SonarQube Web API → compute the DELTA (before → after) →
           this becomes the prediction LABEL
        │
        │  Step D: clean up (delete) the scanned SonarQube projects via API
        │           to keep the local server tidy
        ▼
   Step E: combine with the raw metadata already collected (title, body,
           additions/deletions, contributor info) into ONE structured row
           per PR = the feature table
        │
        ▼
   sense/data/processed/train.parquet, test.parquet (30-PR pilot dataset)
        │
        ▼
   Phase II: feed this table into Random Forest / XGBoost → train and
   validate the classifier on the pilot batch, proving the Analyze layer
   before any decision on scaling the dataset further
```

Methodology reference: §3.3.2–§3.3.4.

---

### A.7 Correction: scoping complexity to touched files, not whole-project totals

Before running the 30-PR automated batch, a design flaw was identified in the scanning
approach described in §A.5–A.6 and caught before any scan data was produced.

**The flaw:** the script as first written queried SonarQube for each snapshot's
**whole-project** `cognitive_complexity` total, before and after each PR, and used the
difference as the label. On a mature codebase like `commons-lang` — with years of
accumulated complexity across hundreds of files — a single PR typically touches only
1–5 files. Its real contribution gets buried inside a baseline total that may already be
in the thousands, producing a delta that mostly reflects the passage of time and the
size of the existing codebase, not the quality of that specific PR.

**Why this matters for validity, not just accuracy:** this is not a rounding error — it
would have meant the model's prediction target didn't actually measure what the research
question asks. It also directly contradicts the project's own stated design:
Proposal §1.2.2 defines complexity as a **method-level** quantity (`MC = Σ(ι) + Σ(ν)`),
and Dissertation §3.3.3 explicitly lists *"the delta in SSCC **per modified method**"*
as a structural feature — not a whole-project delta. The original script had drifted
from the methodology already written and committed to.

**The fix:** the script now identifies exactly which `.java` files a PR changed (via
`git diff --name-only base_sha head_sha`, computed locally — no extra API calls needed),
and queries SonarQube's **per-file** complexity measure only for those files, before and
after. The scanner still has to analyze the whole tree (that's unavoidable — it's how
SonarScanner works), but the *query* is scoped, so the resulting delta reflects only what
the PR itself changed. Files that are new in the "after" snapshot correctly contribute
zero to the "before" total. PRs that touch no `.java` files (documentation, build config)
are recorded explicitly as carrying no complexity signal, rather than being forced into a
misleading number.

**Impact on prior work:** none of the setup, tooling, or manual PR #1 validation test
(§A.4) is invalidated — that test proved the *scanning mechanism* works, which is still
true regardless of which metric is queried afterward. Only the query logic changed,
before any of the 30-PR batch was actually run — no rework of completed data was needed.

---

### A.8 Pilot batch run completed — results and a second data-quality finding

The corrected, scoped scanning script (§A.7) was run to completion across the full 30-PR
sample. Results:

| Outcome | Count | Meaning |
|---|---|---|
| Usable — real cognitive-complexity delta computed | 17 | Ready to become labeled training rows |
| Correctly excluded — no `.java` files changed | 9 | Dependency/CI-config-only PRs (e.g. Dependabot version bumps); carry no complexity signal by definition |
| Excluded — commit unreachable | 4 | PR #1626, #1633, #1644, #1723 |

**A second, distinct data-quality finding, on top of the one in §A.4:** the 4 unreachable
commits were not random network failures. The failure pattern (PR #1626 failed only on
`head_sha`; PRs #1633/#1644/#1723 failed on *both* `base_sha` and `head_sha`) is
consistent with **squash-merging**: when a PR is opened from a contributor's fork and
merged via GitHub's "Squash and merge" option, the original commit SHAs recorded in the
PR's metadata may never actually be pushed to the upstream repository — they exist only
in the contributor's fork, which was not cloned. This is a distinct mechanism from the
Top-Level-Project migration issue found in §A.4 (that was about *old, rewritten* history;
this is about *commits that were never in the upstream repo at all*), but both fall under
the same category of threat already anticipated in Methodology §3.5.5.

**Decision:** these 4 PRs are excluded from the labeled dataset and documented, rather
than pursued further (e.g. by tracking and fetching from each contributor's fork). For a
30-PR proof-of-concept pilot, the added engineering complexity of fork-tracking is not
justified — this is a standard, accepted limitation in empirical software-repository
mining research, not a flaw specific to this implementation.

**Net result: a working, labeled pilot dataset of 17 PRs**, each with a real, file-scoped
cognitive-complexity delta, ready to be joined with the original PR metadata (title,
size, contributor info) into the feature table in Step 1.6.

---

### A.9 Decision: scaling the batch from 30 to 150 sampled PRs

17 usable labeled PRs from the 30-PR run was sufficient to prove the pipeline mechanism
works, but is too small to be a defensible pilot training set for Phase II (Random
Forest/XGBoost). Using the observed rates from the 30-PR run (~30% no-Java-file PRs,
~13% unreachable-commit PRs, ~57% usable), the batch was scaled to **150 sampled PRs**,
projected to yield **~85 usable labeled rows** — before moving to feature engineering
(Step 1.6), so that step is only built once against a dataset large enough to be worth
using for actual model training.

**Implementation fix made alongside this decision:** the script previously reused a
fixed `pilot_sample_30.jsonl` file regardless of the requested sample size, which would
have silently ignored a larger `--sample-size` argument. The sample file is now named by
size (`pilot_sample_150.jsonl`), so different batch sizes never collide, while the
results file (`pilot_scan_results.jsonl`) remains shared and resumable across runs —
PRs already scanned in the 30-PR run are not rescanned.

---

## PART B — සිංහල

### B.1 GitHub PR extraction — කරපු දේ, පියවරෙන් පියවර, සහ ඇයි

| පියවර | සිදුවුණේ මොකක්ද | ඇයි (Methodology එකට සම්බන්ධ කරගෙන) |
|---|---|---|
| **1. GitHub Personal Access Token (PAT) එකක් සෑදුවා** | Personal GitHub account එකෙන් authentication token එකක් generate කළා | GitHub API එකෙන් authentication නැතුව පැයකට request 60ක් විතරයි ගන්න පුළුවන්, token එකක් තිබ්බොත් 5,000ක් ගන්න පුළුවන්. §3.3.2 එකේ කියන විදිහට authenticated token එකක් අවශ්‍යයි ලොකු scale එකකදී. |
| **2. Python පරිසරය සකස් කළා (VS Code, venv, requirements.txt)** | PyGithub, pandas, python-dotenv install කළා | GitHub API එකට connect වෙන්නත්, ඉදිරියේදී feature engineering කරන්නත් අවශ්‍ය tools. |
| **3. Token එක `.env` file එකක සුරැකුවා** | Token එක code එකේ directly නැහැ | Standard security practice. |
| **4. `apache/commons-lang` වලට extraction script එක run කළා** | Accept වුනත් reject වුනත් සියලුම PRs ලබාගත්තා | §3.3.1 සහ §3.3.2 implement කරනවා. |
| **5. ප්‍රතිඵලය** | PRs 1,767ක් සාර්ථකව extract කරලා local එකේ save කළා | Sense-layer pipeline එක වැඩ කරනවා කියලා පළවෙනි concrete සාක්ෂිය. |

**Supervisor ට කියන්න වැදගත් වෙනස:** මේ පියවරෙන් ලබාගත්තේ *raw metadata* විතරයි. Cognitive-complexity values, labels, තවම නැහැ — ඒක තමයි පහත විස්තර කරන ඊළඟ පියවර.

### B.2 Tools සහ තෝරාගැනීම් පිටුපස ගැඹුරු හේතු

**GitHub API එක ඇයි අවශ්‍ය වුණේ**
- ML model එකට historical PRs දහස් ගණනක්, labels සමඟ අවශ්‍යයි — ready-made dataset එකක් නැහැ.
- Data තියෙන්නේ GitHub servers තුළ විතරයි; scale එකේ (PRs 1,700+) manually copy කරන්න බැහැ.

**REST සහ GraphQL දෙකම සඳහන් වෙන්නේ ඇයි**
- **REST** — simple, එකින් එක resource එකක් ඉල්ලනවා; පලවෙනි pilot එකට හොඳම choice එක.
- **GraphQL** — request එකකින් nested data ගොඩක් ගන්න පුළුවන්, rate-limit quota save වෙනවා; ලොකු repo (Kafka) වලට optimization එකක් විදිහට ඉදිරියේදී අවශ්‍ය වෙන්න පුළුවන්.

**`apache/commons-lang` තෝරගත්තේ ඇයි**
- Pure Java, lightweight build — clone/scan කරන්නත් ඉක්මන්.
- Mature, PR history එකත් ලොකුයි (1,767) — scope requirement එක සපුරනවා.
- Pipeline එක debug කරන්න cheap — Kafka/Dubbo වලට scale කරන්න කලින් "practice repo" එක.

---

### B.3 SonarQube සහ SonarScanner පරිසරය සකස් කිරීම (Methodology §3.3.2)

Extraction එකෙන් ලැබෙන්නේ PR *metadata* විතරයි — cognitive complexity ගැන කිසිම දෙයක් නැහැ. ඒ අගය ගණනය කරන්න ඕන static-analysis tool එකක් source code එකට එරෙහිව actual run කරලා, ඒ නිසා ඊළඟට toolchain දෙවෙනි එකක් install කරලා validate කරන්න වුණා.

| පියවර | කළේ මොකක්ද | ඇයි |
|---|---|---|
| 1 | Docker එකෙන් local **SonarQube server** එකක් run කළා | SSCC ගණනය කරන engine එක සහ results store කරන එක. Local run කිරීමෙන් cost, account අවශ්‍යතා නැහැ. |
| 2 | Default `admin`/`admin` credentials වලින් login වෙලා password එකක් set කළා | SonarQube එක්ක built-in admin account එකක් තියෙනවා. |
| 3 | **SonarQube token** එකක් generate කළා | Scanner එකට server එකට authenticate වෙන්න. |
| 4 | **SonarScanner CLI** install කරලා PATH එකට add කළා | Codebase එකක් scan කරලා SonarQube එකට upload කරන command-line tool එක. |
| 5 | `sonar-scanner -v` කරලා verify කළා | Install එක නිවැරදිද කියලා confirm කරගත්තා. |

---

### B.4 Manual single-PR validation test — Automate කරන්න කලින් pipeline එක prove කිරීම

PRs 1,767ම loop කරලා automate කරන්න කලින්, **එක PR එකක් manually scan කළා** — project selection එකේදී use කරපු "pilot before scale" discipline එකම.

**කළේ මොකක්ද:**
1. `apache/commons-lang` source repo එක locally clone කළා.
2. Dataset එකෙන් **PR #1** තෝරගත්තා, `base_sha` සහ `head_sha` ලබාගත්තා.
3. `git checkout <base_sha>` try කළා.
4. `sonar-project.properties` file එකක් හදලා `sonar-scanner` run කළා.
5. SonarQube dashboard එකේ (`http://localhost:9000`) success එක confirm කළා — complexity measure එකක් සමඟ project එක පෙන්නුවා.

**මුහුණ දුන් issues සහ solutions (supervisor ට කියන්න වටින real findings):**

| Issue | සිදුවුණේ මොකක්ද | Solution | වැදගත්කම |
|---|---|---|---|
| **Unreachable commit SHA** | `git checkout <base_sha>` fail වුණා — GitHub API එකට අනුව commit එක තියෙනවා, ඒත් standard clone එකේ නැහැ | `git fetch origin <sha>` කෙලින්ම run කරලා, `git checkout FETCH_HEAD` කළා | `commons-lang` project එක Apache TLP එකට migrate කරපු (log එකේ `"Moving to TLP"` commit එකෙන් පේනවා) ගොඩක් පරණ project එකක් නිසා, ගොඩක් පරණ commits default branch history එකෙන් orphan වෙන්න පුළුවන්. **මේක real data-quality finding එකක්**, Methodology §3.5.5 එකේ කියන "threats to validity" එකට direct සම්බන්ධයි — automation script එකට unreachable commits handle කරලා log කරන්න ඕන. |
| **PowerShell argument-parsing error** | `-Dsonar.host.url=...` flag එකෙන් `Unrecognized option` error එකක් | `$env:SONAR_HOST_URL`, `$env:SONAR_TOKEN` environment variables විදිහට set කරලා, arguments නැතුව `sonar-scanner` run කළා | Tooling quirk එකක් විතරයි, methodology issue එකක් නෙවෙයි — ඒත් automation script එකට Python subprocess එකෙන් environment variables set කරන්න ඕන කියන implementation note එකක්. |

**ප්‍රතිඵලය:** `EXECUTION SUCCESS` — scan එක විනාඩි 1.5ක් තුළ complete වුණා, SonarQube එකට upload වුණා, complexity measure එකක් සමඟ dashboard එකේ පෙන්නුවා. **මේකෙන් confirm වෙනවා මුළු chain එකම වැඩ කරනවා: GitHub metadata → git checkout → SonarScanner → SonarQube analysis → retrievable metric.**

---

### B.5 තීරණය: PRs 1,767 සිට 30ක automated batch එකකට scale down කිරීම

**Constraint එක:** manual test එකට විනාඩි 1.5ක් ගියා එක scan එකකට. PR එකකට scan **දෙකක්** ඕන (before/after). 1,767ම sequentially scan කරන්න:

```
PRs 1,767 × scans 2 × විනාඩි 1.5 ≈ පැය 88ක් continuous scanning
```

මේක solo research implementation එකකට මේ timeline එකේදී practical නැහැ, සහ **අවශ්‍යත් නැහැ**. මේ stage එකේ අරමුණ තමයි **PPCH framework එක end-to-end වැඩ කරනවා කියලා prove කිරීම** — predictive analysis සහ proactive intervention build කරලා, integrate කරලා, correct විදිහට වැඩ කරනවා කියලා පෙන්නීම. Production deployment එකකට හෝ ලොකු empirical study එකකට PRs 1,767ම ඕන වෙයි, ඒත් framework එකේ design/mechanics validate කරන්න precondition එකක් නෙවෙයි.

**තීරණය:** automated extraction එක **PRs ~30ක** batch එකකට scale down කරනවා, Sense → Analyze → Act pipeline එකේ working, demonstrable version එකක් හදන්න ප්‍රමාණවත්, පස්සේ time තියෙනවා නම් scale up කරන්න option එකත් තියෙනවා.

**මේ decision එකත් එක්ක කරගත්ත refinement දෙක:**
1. **Scan එකකට unique SonarQube project key එකක්** — manual test එකේ fixed key එකක් (`commons-lang-test-pr`) use කළා; automated script එකට PR/commit එකකට unique key එකක් (e.g. `cl-pr1-base`, `cl-pr1-head`) generate කරන්න ඕන, results overwrite වෙන්නේ නැතුව.
2. **SonarQube Web API එකෙන් results ලබාගැනීම** dashboard එක manually බලනවා වෙනුවට — `GET /api/measures/component` එකෙන් Cognitive Complexity value එක JSON විදිහට direct ලැබෙනවා, script එකට dataset එකට automatically save කරන්න පුළුවන්.

### B.6 ඊළඟට වෙන්නේ මොකද්ද — Raw data එකෙන් trained model එකකට (updated)

1. Raw dataset එකෙන් PRs 30ක් sample කරනවා
2. සෑම PR එකකටම base/head commits checkout කරනවා (unreachable commits handle කරමින්)
3. SonarScanner දෙකෙන්ම run කරනවා, unique project keys සමඟ
4. SonarQube Web API එකෙන් Cognitive Complexity values ලබාගෙන DELTA එක ගණනය කරනවා → **LABEL** එක
5. SonarQube projects cleanup කරනවා (delete via API)
6. Raw metadata + complexity numbers combine කරලා feature table එකක් හදනවා (PRs 30ක් සඳහා)
7. **Phase II** — Random Forest / XGBoost train කරලා pilot batch එකේ validate කරනවා

Methodology reference: §3.3.2–§3.3.4.

---

### B.7 නිවැරදි කිරීම: Whole-project totals වෙනුවට, touch කරපු files වලට complexity scope කිරීම

30-PR automated batch එක run කරන්න කලින්, §B.5–B.6 එකේ විස්තර කරපු scanning approach එකේ
design flaw එකක් හඳුනාගත්තා, scan data කිසිවක් produce වෙන්න කලින්ම.

**Flaw එක:** පලවෙනි script එක query කළේ SonarQube එකෙන් snapshot එකකට **whole-project**
`cognitive_complexity` total එක, PR එකට කලින් සහ පස්සේ, ඒ දෙකේ වෙනස label එක විදිහට use
කළා. `commons-lang` වගේ අවුරුදු ගණනාවක history එකක් තියෙන mature codebase එකක, PR එකක්
සාමාන්‍යයෙන් touch කරන්නේ files 1–5ක් විතරයි. ඒ PR එකේ real contribution එක, දහස් ගණනක
already-existing baseline total එකක් යටතේ hide වෙනවා, delta එකෙන් පේන්නේ codebase එකේ
size එකයි වයස්සයි, ඒ specific PR එකේ quality එක නෙවෙයි.

**මේක validity issue එකක් වෙන්නේ ඇයි:** මේක simple rounding error එකක් නෙවෙයි — model
එකේ prediction target එක, research question එක actual විදිහට measure කරන්නේ නැහැ කියන
එකයි. මේක project එකේම stated design එකට direct contradict වෙනවා: Proposal §1.2.2
complexity එක **method-level** quantity එකක් විදිහට define කරනවා (`MC = Σ(ι) + Σ(ν)`),
Dissertation §3.3.3 structural feature එකක් විදිහට *"delta in SSCC **per modified
method**"* කියලා specific විදිහට list කරනවා — whole-project delta එකක් නෙවෙයි. Original
script එක දැනටමත් ලියලා commit කරපු methodology එකෙන් drift වෙලා තිබුණා.

**Fix එක:** script එක දැන් `git diff --name-only base_sha head_sha` එකෙන් (locally
compute කරනවා, extra API calls අවශ්‍ය නැහැ) PR එකක් හරියටම මොන `.java` files touch
කළාද කියලා identify කරනවා, SonarQube එකේ **per-file** complexity measure එක ඒ files
වලට විතරක් query කරනවා, කලින් සහ පස්සේ. Scanner එකට තවමත් tree එකම analyze කරන්න ඕන
(ඒක avoid කරන්න බැහැ — SonarScanner වැඩ කරන විදිහ ඒකයි), ඒත් *query* එක scope කරලා, delta
එකෙන් පේන්නේ PR එකෙන්ම වෙනස් කරපු දේ විතරයි. "After" snapshot එකේ අලුත් files, "before"
total එකට 0ක් contribute කරනවා, correct විදිහට. `.java` files කිසිවක් touch නොකරන PRs
(documentation, build config) explicit විදිහට "complexity signal එකක් නැහැ" කියලා record
කරනවා, misleading number එකකට force කරනවා වෙනුවට.

**කලින් කරපු වැඩට impact එක:** setup, tooling, manual PR #1 validation test (§B.4)
කිසිවක් invalidate වෙන්නේ නැහැ — ඒ test එක prove කළේ *scanning mechanism* එක වැඩ කරනවා
කියලා, ඊට පස්සේ මොන metric query කළත් ඒක true ම තමයි. Query logic එක විතරයි වෙනස් වුණේ,
30-PR batch එකෙන් කිසිවක් actual run කරන්න කලින්ම — completed data කිසිවක් rework කරන්න
ඕන වුණේ නැහැ.

---

### B.8 Pilot batch run එක complete වුණා — results සහ දෙවෙනි data-quality finding එකක්

Corrected, scoped scanning script එක (§B.7) PRs 30ම run කරලා complete කළා. Results:

| Outcome | Count | තේරුම |
|---|---|---|
| Usable — real complexity delta ගණනය කළා | 17 | Labeled training rows බවට පත් කරන්න ready |
| Correctly excluded — `.java` files වෙනස් වුණේ නැහැ | 9 | Dependency/CI-config-only PRs; complexity signal එකක් නැහැ, definition එකෙන්ම |
| Excluded — commit unreachable | 4 | PR #1626, #1633, #1644, #1723 |

**දෙවෙනි, වෙනස් data-quality finding එකක්, §B.4 එකේ එකට අමතරව:** Unreachable commits 4
random network failures නෙවෙයි. Failure pattern එක (PR #1626 fail වුණේ `head_sha` එකට
විතරයි; #1633/#1644/#1723 fail වුණේ `base_sha` සහ `head_sha` දෙකටම) **squash-merging**
එකට consistent වෙනවා: PR එකක් contributor fork එකකින් open කරලා, GitHub එකේ "Squash and
merge" option එකෙන් merge කළොත්, PR metadata එකේ තියෙන original commit SHAs upstream
repo එකට push වෙන්නේම නැහැ — ඒවා තියෙන්නේ contributor ගේ fork එකේ විතරයි, clone කරලා
නැති තැනක. මේක §B.4 එකේ තිබ්බ issue එකට වෙනස් mechanism එකක් (ඒක *පරණ, rewrite වුණු*
history ගැන; මේක *upstream repo එකේ කවදාවත් තිබ්බේ නැති* commits ගැන), ඒත් දෙකම
Methodology §3.5.5 එකේ කියන threat category එකටම වැටෙනවා.

**තීරණය:** මේ PRs 4 labeled dataset එකෙන් exclude කරලා document කරනවා, fork-tracking
කරලා fix කරන්න try කරනවා වෙනුවට. PRs 30ක proof-of-concept pilot එකකට, fork-tracking එකේ
extra engineering complexity එක justify වෙන්නේ නැහැ — මේක empirical software-repository
mining research එකේ standard, accepted limitation එකක්, මේ implementation එකට විතරක්
වුණු flaw එකක් නෙවෙයි.

**අවසාන ප්‍රතිඵලය: PRs 17ක working, labeled pilot dataset එකක්**, එකින් එකට real,
file-scoped cognitive-complexity delta එකක් සමඟ, Step 1.6 එකේදී original PR metadata
(title, size, contributor info) එක්ක combine කරලා feature table එකක් හදන්න ready.

---

### B.9 තීරණය: Batch එක PRs 30 සිට 150ට scale කිරීම

PRs 30ක run එකෙන් ලැබුණු usable labeled PRs 17 pipeline mechanism එක වැඩ කරනවා කියලා
prove කරන්න ප්‍රමාණවත් වුණා, ඒත් Phase II (Random Forest/XGBoost) සඳහා defensible pilot
training set එකක් විදිහට ගොඩක් කුඩායි. PRs 30 run එකේ observed rates (no-Java-file PRs
~30%, unreachable-commit PRs ~13%, usable ~57%) use කරලා, batch එක **PRs 150ක්** දක්වා
scale කළා, **usable labeled rows ~85ක්** ලැබෙයි කියලා estimate කරලා — feature engineering
(Step 1.6) එකට යන්න කලින්, ඒ step එක model training එකට actual value එකක් තියෙන dataset
එකකට එරෙහිව එක පාරක් විතරක් build කරන්න.

**මේ decision එකත් එක්ක කරගත්ත implementation fix එක:** script එක කලින් fixed
`pilot_sample_30.jsonl` file එකක් reuse කළේ, request කරපු sample size එක කුමක් වුණත්,
ඒක ලොකු `--sample-size` argument එකක් silently ignore කරන්න තිබුණා. Sample file එක දැන්
size එකෙන් name කරනවා (`pilot_sample_150.jsonl`), විවිධ batch sizes කවදාවත් collide
වෙන්නේ නැහැ, results file එක (`pilot_scan_results.jsonl`) shared සහ resumable විදිහටම
තියෙනවා — PRs 30 run එකේදී දැනටමත් scan කරපු PRs ආයෙත් scan වෙන්නේ නැහැ.
