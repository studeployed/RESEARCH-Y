# P1-06k3a — Recoverable exact-key candidate-pair checkpoints

**Baseline:** owner-merged PR #75; `main` `22587a9003db82585ca05e1d2e8e1a17e666d227`, 9 November 2026. The version-controlled `RESEARCH-Y_SPEC.md` remains authoritative and unchanged. This increment covers only the *derived exact-key pair-hint foundation* of P1-06, not completion of DUP-01–05 or acceptance of the master list.

## Why checkpoint candidate pairs?

PR74 created a recoverable project-salted title/Digital Object Identifier (DOI)/PubMed identifier (PMID)/Web of Science (WoS) accession key cache; PR75 made the original review queue consume it when ready. That queue still enumerates every exact-key candidate pair on each read. Dense, historically repeated titles/identifiers can exceed its explicit pair-workload cap, and a resumed queue must not claim absent pairs were reviewed or excluded.

Schema **v6** adds `candidate_pair_builds` (one explicit, run-scoped generation) and `candidate_pair_hints` (deduplicated source-pair keys, exact-field bit masks). A pair hint is **not** a publication identity, confidence score, automatic high-confidence match or legal permission to redistribute a source.

## Explicit transactional workflow

A researcher/approved trusted host can invoke these standalone Python services:

1. `preview_pair_checkpoint(project, run_id)` reads the current source-key index and existing run checkpoint without writes; the output declares unknown final unique-publication count and explicitly false full candidate discovery.
2. `start_pair_checkpoint(project, run_id, expected_revision, actor, confirmed=True)` refuses a non-ready v5 key cache, verifies the exact read revision, clears **only derived pairs for the selected run**, allocates a generation, records the v5 source generation/epoch and emits an append-only start audit receipt. Failed DDL/SQL/receipt work rolls back the full transaction.
3. `advance_pair_checkpoint(project, run_id, generation_id, expected_revision, actor, confirmed=True)` processes **at most 64 indexed selected-run source/field keys and 128 matching key hints** in one SQLite `BEGIN IMMEDIATE` transaction. The source-key and peer lookups use indexed range queries; historical-to-historical pairs never enter this selected run's workload. A canonical tuple of source retrieval IDs forms the pair key, and distinct equal matching fields are combined into its bit mask.
4. A dense matching key can be stopped *partway through its peer list*. The durable cursor retains the selected retrieval ID, field and last matched peer ID, so a subsequent explicitly confirmed transaction continues without repeating or skipping a pair. The cursor, processed-key count, emitted-hint count, distinct-pair count and rolling SHA-256 evidence hash commit atomically with derived rows and an append-only batch receipt. A worker interruption may have committed: **read the current stored receipt before continuing; never replay a stale confirmation**.
5. `read_pair_hint_page(project, run_id, after_pair, expected_revision)` reads at most 20 source-pair hints using an indexed keyset, with a 21st row used only to establish whether more pages exist. Changed/stale/missing cursor evidence fails closed.

The exact-key method is limited to **100,000 distinct candidate source pairs per run** in this increment. If a bounded transaction would exceed this cap, it is **rolled back and reports an explicit workload error**; no partial page may masquerade as exhaustive discovery. The 64-key/128-hint caps are real transactional budgets, not a hidden publication filter.

## Conservative scope and invalidation

Only previously materialised source retrievals with a supported v5 citation-key projection can enter pair hints. Source-only records without a publication identity are not silently classified as negative matches. A source insert/update/delete, a publication retrieval association change, or an explicit `publication_candidate_decision_v1` audit event marks all building/ready pair generations **stale in the same original SQLite transaction**. A rebuilt/replaced or stale v5 source-key cache also invalidates the derived pair generation. A new generation is required before reuse.

Neither building nor reading a hint changes original source metadata, run/group memberships, chosen citation fields, reviewer decisions, original publications or existing audit events. Exact DOI/title agreement is **not** permission to merge distinct conference abstracts sharing a supplement. Source permissions and abstracts remain untouched.

**This is deliberately `ready_keys_only`, not `ready_for_full_review`.** It does not yet materialise *prior-receipt-only pairs* that have no current matching exact key; those previously reviewed/rejected source pairs remain in the original PR73/75 queue. Therefore this stage **does not replace the existing researcher-facing queue**. The next increment must integrate receipt-only pair evidence and independently compare a completed pair checkpoint against canonical candidate decisions before switching review pagination to this cache. Cross-run researcher decisions remain unimplemented.

All service outputs explicitly retain `historical_receipt_only_pairs_included=false`, `candidate_discovery_complete=false`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false`, and `global_unique_publications=null`.

## Recoverable schema migration

New projects initialise schema v6 directly. A v5 project is identity-checked and backed up to a separately readable `researchy-before-v6-*.sqlite3` snapshot, then upgraded with additive tables and all seven same-transaction invalidation triggers. Failed snapshot/DDL/audit insertion leaves original v5 records unchanged. Earlier v1–v4 projects reach v6 in their existing atomic original migration. No new dependency, API credential, network worker or installer change is needed.

## Verification scope

Offline SQLite tests cover source-index readiness and required confirmation, separated conference abstracts with a shared supplement DOI, canonical pair ID ordering, selected-to-historical but not historical-only pairing, dense-key mid-bucket interruption/reopen, exact 20+5 keyset pages, zero-source and unmaterialised sources, original source/association/review invalidation, batch failure and rollback, workload overflow refusal, stale cursors, migration backup/identity/rollback and indexed-query-plan evidence.

These tests do **not** certify 100,000-record end-to-end latency, native GUI lifecycle, full methodological completeness or deduplication acceptance. Performance benchmarking and persisted receipt-only review pair integration remain outstanding.

**Merge protocol:** verify exact current HEAD, all required Linux/Windows Python continuous-integration checks and applicable Graphical User Interface (GUI) lifecycle checks, definitively completed current-HEAD Codex code review followed by current-HEAD security review, every individual receipt/finding disposition, and explicit owner merge authorisation.
