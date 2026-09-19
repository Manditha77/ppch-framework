# Phase I.1 — Target Project Selection

## Selection criteria (from Methodology §3.3.1)
1. **Java-dominant** (>80% of codebase) — needed for SSCC/srcSlice tooling to apply cleanly.
2. **Mature and actively maintained** — long, complete PR history (thousands of PRs), not a young
   or abandoned repo.
3. **Domain diversity** — the proposal specifically calls for spread across data-processing
   frameworks, web frameworks, and infrastructure libraries, so the learned features aren't
   an artifact of one codebase's style.
4. **Practical size for a solo, locally-run pipeline** — cloning, checking out hundreds/thousands
   of commit pairs, and running SonarScanner on each is expensive. A monorepo like Kafka or
   Cassandra has a huge, heavy build; that's fine for the *final* full-scale run but painful
   for iterating on the pipeline itself.

## Recommended approach: pilot first, then scale

**Pilot project (build & debug the whole Sense pipeline against this one first):**
- **Apache Commons Lang** (`apache/commons-lang`) — pure Java utility library, no heavy build
  dependencies, ~2,000+ closed PRs, long history, fast to clone and fast for SonarScanner to
  analyze. Ideal for proving the extraction → SonarScanner → feature-engineering pipeline works
  end-to-end before committing compute time to bigger repos.

**Full sample (once the pipeline is validated on the pilot), one per domain:**
| Domain | Project | Why |
|---|---|---|
| Infrastructure / utility library | `apache/commons-lang` (pilot repo, reused) | Small, fast, foundational |
| Data-processing framework | `apache/kafka` | Canonical ASF streaming/data project, large mature PR history |
| Web / RPC framework | `apache/dubbo` | High-throughput RPC framework, different architectural style from Kafka |

This gives exactly the three-domain spread the proposal specifies, while keeping the first
working pipeline cheap to iterate on.

**Your call:** if you'd rather substitute Kafka/Dubbo for other ASF projects you already know
well (e.g. because you have local familiarity with the codebase, which helps when interpreting
false positives/negatives later), just say so — the pipeline doesn't care which repos go in
`project_list.json`.

## Action for you
Nothing needed yet — I'll wire `commons-lang` in as the pilot target in the extraction script.
You can swap it later by editing `sense/data/raw/project_list.json`.
