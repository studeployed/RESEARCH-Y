# P1-06k4c2 — A single selected run containing 100,000 audited original sources

**Baseline:** owner-merged pull request (PR) #82, `main` commit `eee25712824032040cf28990620ecafeb7bba4db` on 10 November 2026. The authoritative `RESEARCH-Y_SPEC.md` is unchanged. This is an additional **synthetic, source-backed, single-run performance and integrity gate**, not acceptance of AT-22 or any deduplicated master-list requirement.

## Gap addressed

PR82 exercised an actual versioned SQLite project with **100,000 original source retrievals**, one independently audited provisional publication identity for each, and **100,000 query memberships**, but its selected run had only **512 source records**. The remaining 99,488 were historical. That distinction matters to run-specific count projections, pagination and candidate review. PR82's completed 10 November performance workflow observed original-source candidate-page reads of approximately **15.5 seconds on Linux** and **18.8 seconds on Windows**; these are measurements, not a promised performance level.

The new fixture changes **which run owns the records**, not publication identity or scientific search logic. A new `--selected 100000` scenario places **all 100,000 source records in the current run**. It introduces 64 pairs of separately retained, equal-title/DOI **PubMed vs Web of Science** sources entirely *within* that run. All the other sources have different synthetic citation keys. The earlier cross-run baseline is unchanged.

## What is checked

| Evidence | Required value |
|---|---:|
| Original retained source retrievals | 100,000 |
| Source/query memberships | 100,000 |
| Selected-run source records | 100,000 |
| Historical-run source records | 0 |
| Independent provisional publication identities | 100,000 |
| Original identity-link audit events | 100,000 |
| Unmaterialised original source records | 0 |
| Cross-provider exact-key candidate pairs in selected run | 64 |
| Verified deduplicated publication total | **Unknown**, not 100,000 |

The original fixture-only source identity writer remains unchanged. The benchmark first uses the **production single-source materialisation service** for the 128 source records in 64 pairs, then writes the other provisional identities in bounded, recoverable, original-validated SQLite batches, invoking the original append-only identity-link audit writer. This is **not** execution of the researcher-authorised production 64-record GUI command for 100,000 records.

The script measures the existing `read_run_counts`, `read_publication_page`, `read_candidate_queue` (first and second 20-pair pages), and a real spawned `ApplicationWorker` candidate-page command. It independently reopens the project and checks original counts, selected-run membership, metadata fingerprints, identity receipts, `integrity_check` and `foreign_key_check` after the reads. The worker must return the matching 64-pair evidence within the unchanged **35-second host budget**; a timeout is a failed performance gate, not a successful result.

A smaller, normal-continuous-integration test checks both a partly materialised and a fully materialised 512-source *single-run* case. Another test checks that the paired originals have two distinct provider identities, exactly matching citation keys and separate provisional publication IDs. The previous cross-run, rollback, recovery and mutation-safety tests remain in place.

## Reproducing the isolated workload

```sh
python -m pip install -e .
python scripts/benchmark_original_project.py --records 100000 --selected 100000 --matched 64 --materialise-all --worker-timeout-seconds 35 --json-output single-run-original-100k.json
```

The [dedicated Linux/Windows workflow](../.github/workflows/single-run-original-100k.yml) uses Python 3.12 and retains the measured JSON separately on each platform. Record actual results by workflow run, code commit, operating system, timings and peak parent-process resident memory; until those jobs complete, **no timing/pass result is asserted**. Existing original 100k materialised/split-run benchmark jobs remain independent comparators.

## Observed performance gate and provenance-preserving repair (10 November 2026)

The **first** same-run 100,000-original-source benchmark, [GitHub Actions run #42849832745](https://github.com/studeployed/RESEARCH-Y/actions/runs/42849832745), on PR HEAD `ba464df77f23af4038498d7290b7c2eb88796809`, established the bottleneck. All 100,000 original source rows, membership rows and 100,000 independent audited provisional identities passed integrity/reopen checks, but the spawned worker exceeded the unchanged 35-second host budget on **both** platforms. The failure was correctly retained, not suppressed.

The subsequent fix uses the original project SQLite read transaction and **original source, publication-link and audit receipt rows**, but avoids repeating one or more separate SQLite lookups for *each* of 100,000 current-run identities. For large runs, source count projection validates original source tuples in an ordered join and reconstructs **canonical publication snapshot revisions** from their original association events, query memberships and `created_at_utc`/chosen-metadata state. Publications involving **more than one source** (including cross-run links) or any chosen-field state continue through the original full identity snapshot validator; no final uniqueness decision is inferred. Small runs retain the established canonical read path. The source-backed candidate queue also joins its linked audit evidence and verifies the same source SHA-256, pointer/version, event, timestamp, status and publication association invariants via the shared original-evidence verifier. The original `_link` and `_snapshot` services remain authoritative for interactive candidate decisions and record details.

The targeted offline tests explicitly compare streamed original association/audit evidence against `_link`, compare reconstructed publication revisions and full count projections against original `_snapshot` outputs for mixed run/association/field/receipt cases, and reject malformed or mismatched original audit pointers without modifying retained data. None of these changes relax the 35-second worker budget, weaken the SQLite integrity gates, change stored evidence or invent a deduplicated count.

**Measured full-size workflow:** [GitHub Actions run #42887936177](https://github.com/studeployed/RESEARCH-Y/actions/runs/42887936177), exact code commit `756699542ac55fb41413a47b6a6e11a91e640ff2`. Both Linux and Windows Python 3.12 jobs passed all original source/identity/reopen checks and returned the actual spawned worker within the 35-second bound. Values are from retained per-platform JSON artifacts; times are independent shared-runner observations, not guarantees across computers.

| Observed component | First-run Linux | Corrected Linux | First-run Windows | Corrected Windows |
|---|---:|---:|---:|---:|
| Selected-run count projection | 25.685 s | **11.744 s** | 38.494 s | **14.100 s** |
| First provisional publication page | 24.896 s | **12.058 s** | 41.060 s | **14.451 s** |
| First source-backed candidate page | 36.732 s | **20.025 s** | 57.547 s | **25.026 s** |
| Second source-backed candidate page | 36.449 s | **20.064 s** | 56.447 s | **26.291 s** |
| Actual spawned worker | timeout at 35.012 s | **returned in 20.330 s** | timeout at 35.007 s | **returned in 24.830 s** |
| Observed peak parent resident memory | 1,209.5 MB | **799.6 MB** | 1,197.2 MB | **786.7 MB** |

This evidence establishes only the narrow single-run fixture performance and original-data checks. A further documentation/review commit may regenerate workflow runs; merge readiness still requires all checks and both commit-specific reviews on the **latest** PR HEAD, not just these performance measurements.

## Non-negotiable boundaries

- Even 100,000 original source retrievals, 100,000 source-linked provisional identities and 64 matching pairs **do not prove 100,000 unique publications**. No equality-based merge or definitive deduplication is performed. `global_unique_publications=null`, `deduplication_complete=false`, `verified_complete=false` and `full_AT_22_acceptance=false` remain required.
- The source queries have no verified provider completeness. This is offline synthetic evidence; it makes **no** live PubMed, Web of Science, Crossref, model or other network calls.
- No actual native Windows GUI frame painting, large-page researcher interaction, cumulative child+parent memory, fully classified/all-row Excel export, real-source retrieval or 100,000-row user-confirmed 64-record materialisation workflow is validated. Those remain separate acceptance work.
- The cross-run fixture is not rewritten to fake same-run behaviour. Both modes remain selectable and are tested without new application dependencies or schema changes.

## Review and future decision

Before any merge recommendation, verify the exact current PR HEAD, all four required Python test jobs, both new 100k single-run platform jobs, any impacted older performance jobs, and definitive commit-matched Codex **code review first**, followed by **security review**. Review individual receipts and resolve findings. No automatic merge.

If the full-size source-backed candidate read or worker fails the finite host budget, record the failure accurately and investigate the measured path; do not raise limits or bypass original audit checks merely to obtain a green test. The remaining full-scale researcher-confirmed production workflow and native Windows graphical responsiveness must be evaluated independently before AT-22 can be accepted.
