# SQLite schema v6 — P1-06k3a (additive to v5)

The approved [specification](../RESEARCH-Y_SPEC.md) remains authoritative. The current implementation stores reproducible local evidence; it is not a declaration of a completed search product.

## Existing entities retained

Schema v1 introduced `project_metadata` and append-only `audit_events`. Schema v2 added immutable approved `strategy_versions` / `strategy_groups`; `search_runs`, `source_queries`, `source_retrievals`, `query_retrievals`; separate `publications` / `publication_retrievals`; containers, organisations, classifications and documents. Source counts are NULL until observed. Composite foreign keys prevent cross-run/source associations. Original source metadata is separate from chosen publication metadata.

The `research_y.storage` interface freezes explicitly approved atomic terms and OR-only groups, creates pending runs and stores exact unexecuted query plans. These operations include audit events in their transaction; they do not establish source acceptance or inferred counts.

Schema v3 added `pubmed_checkpoint_runs`, `pubmed_checkpoint_pages` and `pubmed_checkpoint_ids`: disjoint counted plans, immutable pages/identifiers, checksums and transactional page/index/audit writes. P1-04d stores EFetch records through the v2 source-retrieval/membership tables. These PubMed structures are unchanged by v4. Their status remains distinct from full bibliographic retrieval.

## Version 4 additions

See [durable Starter design](WOS_CHECKPOINTS.md) for operational contracts.

| Table | Purpose |
|---|---|
| `wos_checkpoint_jobs` | Immutable approved query/collection plan; source baseline; progress, quota/backoff, ownership and truthful status |
| `wos_checkpoint_attempts` | Reservation before network access; observed response/error/unknown outcome and attempt purpose |
| `wos_checkpoint_observations` | Locally permitted raw response, context and checksums, including retained rejected observations |
| `wos_checkpoint_pages` | Contiguous, immutable acquisition-page ledger and ordered accession digest |
| `wos_checkpoint_ids` | Unique query/accession index, page position and source-retrieval identity/metadata digest |
| `wos_checkpoint_verifications` | Independent identity-pass receipts per verification epoch; old epochs remain auditable |

A page, source records, group/query memberships and audit commit together in `BEGIN IMMEDIATE`. Network calls occur outside database transactions. Immutable-history triggers reject mutation/deletion. A project permits only one active Starter worker; ownership tokens prevent a stale worker from committing after explicitly confirmed crash recovery.

Validated acquisition metadata uses the existing `source_retrievals` / `query_retrievals` tables. Identical source records may belong to more than one query; conflicting original metadata is not overwritten. Retention requires explicit confirmation of source permissions. No secret, publication deduplication or inferred abstract is added.

## Version 5 additions: derived candidate-key indexing

See [candidate index checkpoints](CANDIDATE_INDEX_CHECKPOINTS.md) for its explicit, bounded source-only build contract. This version adds:
- `candidate_index_state`: singleton generation status (`empty`, `building`, `ready`, `stale`), source-mutation epoch, cursor, rolling evidence hash and progress;
- `candidate_index_records`: source-retrieval references and original source hashes for each committed generation;
- `candidate_index_keys`: indexed **project-salted digests only** for canonical exact title/DOI/PMID/accession fields; source values and abstracts are not duplicated into this cache;
- Source insertion/update/deletion triggers that atomically invalidate a building or ready generation.

These structures have no effect on original source queries, publication-identity matching decisions or search completeness. A ready derived index is not a completed search or verified publication count.

## Version 6 additions: source-backed exact-key candidate-pair checkpoints

See [pair checkpoint protocol](CANDIDATE_PAIR_CHECKPOINTS.md). Schema v6 adds `candidate_pair_builds` (run-scoped generation, source index epoch, key-and-peer cursor, progress, rolling checksum, status) and `candidate_pair_hints` (unique canonical source-pair ID and field agreement bit mask). This is derived **review evidence only**; it does not merge publications or certify a completed search.

Seven triggers mark any building/ready pair generation stale if the original source retrievals, publication-retrieval links or explicit candidate decision history change. A source-key index rebuild also invalidates the recorded generation through validation. The pair builder handles at most 64 source/field keys and 128 matching-key hints per confirmed transaction, including resumable partial dense-key buckets. It refuses workloads beyond its stated pair limit without silently omitting records. Existing PR73/75 researcher-facing review remains authoritative until historical receipt-only pairs and original-source confirmation are integrated.

## Recoverable migration

New projects initialise schema **6**. Opening an older supported project validates its identity before creating a consistent, independently checked backup. Names reflect the old version's next step: `researchy-before-v2-*` for v1, `researchy-before-v3-*` for v2, `researchy-before-v4-*` for v3, `researchy-before-v5-*` for v4, and `researchy-before-v6-*` for v5. The actual migration audit records the old version and target **6**, with all needed additive definitions applied in one transaction.

Schema changes, `PRAGMA user_version=6` and the migration audit are atomic. A failed backup prevents migration; failed DDL or audit rolls back the original database, leaving the pre-upgrade backup intact. Reopening a current project creates no repeated backup. Unknown future versions and identity mismatches are rejected without migration. Existing source records, PubMed checkpoints and research setup are preserved.

Tests: `tests/test_schema_migrations.py`, `tests/test_wos_migration.py`, `tests/test_candidate_index_migration.py`, `tests/test_candidate_index_build.py`, `tests/test_candidate_pair_migration.py`, `tests/test_candidate_pair_checkpoints.py`, `tests/test_wos_checkpoints.py`. These are fixtures until execution evidence is recorded; schema presence alone never proves data retrieval.

## Acceptance and security boundary

Reconciliation uses source count, contiguous acquisition pages, accession uniqueness, source-record/membership integrity, a separate full ordered-accession pass and a final count probe. The strongest current Starter result is `completed_with_warnings`: enumeration observed consistent, provider snapshot unavailable, abstract enrichment and parent run completion pending. Changes/errors stay incomplete or paused/cancelled with durable evidence.

Checksums detect accidental/inconsistent modification, not malicious wholesale rewriting of a database. Broad multi-writer orchestration, untrusted archives, full provenance UI, enrichment and exports remain later gates. [Windows junction issue #11](https://github.com/studeployed/RESEARCH-Y/issues/11) remains open before untrusted imports/release.
