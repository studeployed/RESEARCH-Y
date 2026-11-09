# P1-06k4a — Candidate-review performance and scale evidence

**Baseline:** owner-merged pull request (PR) #78, `main` `0f0d4ed098cfb2b13293685087b15c3c9db8969a`. The authoritative `RESEARCH-Y_SPEC.md` is unchanged. This is an incremental evidence and bounded optimisation milestone for **AT-22** and the duplicate candidate review parts of **DUP-01–05**, **AUDIT-03**, **UI-09** and **PROJ-04**. It is **not full 100,000-record end-to-end acceptance**.

## Correctness-preserving queue improvement

Before this increment, `publication_candidate_queue` validated the complete, append-only original `publication_candidate_decision_v1` audit stream while constructing its page and again via `publication_candidates._view` for *every displayed pair*. At the 20-row limit, this multiplied one historical audit pass into up to twenty additional passes and repeated historical receipt integrity checks unnecessarily. The count projection also independently reads this history.

The queue now constructs a map from the **already validated full original receipt stream** to each exact source-namespace-key combination (source name, database namespace, source record identifier). Every displayed pair still calls the canonical original `_state` comparison/identity logic. Only the source-key-specific **previously validated** receipts are passed into `_view` in the same SQLite read-only transaction. The standalone review/decision paths continue to invoke the original full `_receipts` validator.

The unchanged checks include receipt sequence/previous-event lineage; original candidate association receipts, source identity, and field comparisons; rejection and confirmation semantics; stale evidence warnings; current publication links; the original audit-derived revision; and an explicit refusal of corrupted receipts. No persistent decision index, new schema, provider request or automatic merge is introduced. For a typical 20-row ready-v6 queue page, the number of complete decision scans is reduced to **two** (one from the existing count projection, one from the queue), regardless of how many candidate rows are displayed. A regression instruments that call count and separately verifies that the grouped and standalone candidate snapshots/revisions agree.

## Reproducible large synthetic benchmark

`scripts/benchmark_candidate_queue.py` creates a **disposable disk-backed SQLite workload**, with production-shaped candidate-index and pair-index table/index definitions. The scripted defaults are:

| Fixture variable | Value |
|---|---:|
| Synthetic source-key records | 100,000 |
| Stored exact-key candidate-pair hints | 100,000 |
| Synthetic, already-validated-shaped decision receipts | 10,000 |
| Repeated index lookups | 40 per query |

Each run checks the SQLite `integrity_check` and exact post-reopen row counts, then measures, in **milliseconds**, indexed first-page retrieval, near-end keyset retrieval with 21-row lookahead, dense-key peer lookup, source-key cursor resume and Python lookup/grouping of synthetic receipts. It records observed query plans, Python allocation peak for grouping, database file size, Python/SQLite/platform versions, repeat sample digests and total wall time in a local JSON file.

Run without internet or provider access:

```sh
python -m pip install -e .
python scripts/benchmark_candidate_queue.py --records 100000 --pairs 100000 --receipts 10000 --repetitions 40 --json-output candidate-queue-100k.json
```

The new GitHub Actions performance workflow executes the same **100,000-record synthetic SQL-kernel workload on Linux and Windows with Python 3.12**, retaining one JSON evidence artifact per platform. The existing four-configuration Python suite runs lightweight (101- and 1,000-record) smoke tests, actual full-journal-once regressions and original evidence-integrity tests. Do not invent/assume an elapsed time or claim a measured result before the relevant workflow finishes.

### Interpretation

The large fixture is explicitly **query/component-level**, not a realistic full project containing 100,000 independently audited publications. The synthetic receipt lookup assumes receipt dictionaries have already passed validation; it **does not measure the full original audit validator**, publication metadata decoding, full run count reconciliation, GUI painting, user input responsiveness, Excel export, or eventual classification. Python `tracemalloc` records Python-managed allocation for the grouping stage, **not** total native SQLite memory or whole-process peak resident memory.

Shared-host Continuous Integration (CI) timing varies with hardware and runner contention; **no hard latency threshold has been approved**. Report observed medians, 95th percentiles, query plans, sample integrity and test environment, rather than extrapolating them into production performance. AT-22 remains **partially implemented/unverified** until a representative 100,000-record end-to-end scenario, including native Windows GUI responsiveness and durability under failure/restart, has been independently exercised and its acceptance thresholds agreed.

## Safety and provenance

No programmatically generated data resembles or incorporates the researcher's private literature searches. The performance workflow uses disposable synthetic identifiers, **no abstracts, credentials, network/provider queries, clinical documents or patient information**. Measurements and aggregate counts do not represent retrieved biomedical literature. No language/species filtering, search Boolean logic, deduplication rule or original publication identity is changed.

Every queue response still declares `global_unique_publications=null`, `deduplication_complete=false`, `candidate_discovery_complete=false`, `source_retrieval_verified=false`, `verified_complete=false`. A completed indexed **pair hint** is not a verified publication or automatically confirmed duplicate.

## Merge acceptance criteria

Require (1) unchanged canonical selected-pair metadata and decision revision in offline regressions, (2) two full historical receipt validations or fewer per indexed page rather than a scan per displayed row, (3) correct 21-row lookahead and late keyset query plan from synthetic workloads, (4) real full-size Linux and Windows performance evidence with no invented timings or passed acceptance claim, (5) exact-commit four-platform Python tests and applicable GUI dependency/lifecycle checks, (6) definitive completed Codex **code review** followed by completed **security review**, with all individual findings resolved, and (7) explicit project-owner approval. **Never merge automatically.**
