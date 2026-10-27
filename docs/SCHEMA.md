# SQLite schema v3 (P1-04c; additive to v2)

This document describes storage **provided by the current increment**, not a completed literature-search engine. The definitive design constraints are in [the approved specification](../RESEARCH-Y_SPEC.md).

## Entity structure

- `project_metadata` and `audit_events`: the unchanged project identity and append-only audit history from schema v1.
- `strategy_versions` and `strategy_groups`: approved strategy snapshots, named groups and ordered group identities; direct update/delete of approved snapshots/groups is rejected.
- `search_runs`, `source_queries`, `source_retrievals`, `query_retrievals`: version-linked runs, exact source queries, unique provider records within a run/source, and many-to-many source/query/group memberships. Cross-run and cross-source query associations are rejected by composite foreign keys.
- `publications`, `publication_retrievals`: a unique publication separate from its contributing database records. More than one retrieval can be associated with one publication.
- `containers`, `publication_containers`, `organisations`, `publication_organisations`: separate abstract-containing items and authoring/collaborating/endorsing roles.
- `classifications` and `documents`: separate classification provenance and documented file/link entities.

A reported query count is **NULL until a provider supplies it**. Inserting a source record or publication does not constitute verified retrieval or deduplication. No public CRUD interfaces, query compiler, API clients, classification pipeline or exports are included in P1-02a.

## Migration contract

- Newly created projects initialise SQLite schema version **2**.
- Opening a valid version-1 project verifies its identity before upgrading. It first creates a checked SQLite backup under `backups/researchy-before-v2-<unique>.sqlite3`.
- The upgrade then creates all v2 objects, sets `PRAGMA user_version=2` and appends a `schema_migrated` audit event in **one transaction**.
- A failed schema upgrade rolls back and retains the version-1 database and its backup; no silent database reset or guessed repair.
- Opening a current project does not create another migration backup. Unsupported versions fail without modification.

See `tests/test_schema_migrations.py` for legacy-file, rollback, migration-idempotence, source/group-membership and identity-integrity fixtures.

## Deliberate limits

Multi-writer coordination, untrusted project-folder import, archive validation, source-specific retrieval logic, metadata reconciliation and complete provenance APIs remain scheduled for later work. [Issue #11](https://github.com/studeployed/RESEARCH-Y/issues/11) separately tracks Windows junction containment before untrusted project import or release.

## P1-02b operational storage (proposed, not merged)

The `research_y.storage` API uses the existing v2 tables without another schema migration. It serialises approved atomic terms (origin, rationale, enabled state and approval flag) into an immutable **OR-only** strategy snapshot, persists its named/ordered groups and an auditable researcher approval confirmation, and creates run records with initial `pending` status.

The `plan_source_query` helper stores exact **unexecuted** PubMed or Web of Science Starter query text and caller-supplied parameters in association with a group belonging to the run's frozen strategy. Source-reported counts remain `NULL` and execution timestamps remain unset. The helper **does not validate provider syntax, translate terms, send requests or infer hit counts**; those functions belong to later source-specific compiler and connector increments.

Transactions include their audit events. A failed audit write rolls back the associated approved strategy, run or planned query. These limited APIs do not implement public screening, deduplication, metadata processing, automatic model output acceptance or source-wide reconciliation.

## PubMed durable checkpoint schema v3 (P1-04c)

A new source-query-scoped, append-only **identifier checkpoint ledger** extends the v2 database:
- `pubmed_checkpoint_runs`: query_id foreign key, immutable exact root query/count/partition plan, plan SHA-256 digest, explicitly nonfinal checkpoint status.
- `pubmed_checkpoint_pages`: immutable partition index + page offset, bounded size, canonical validated page, digest and source response digest.
- `pubmed_checkpoint_ids`: individual unique PMIDs with foreign-key association to the exact committed page, preventing accidental cross-page/partition duplicates.

Every page is inserted with its PMIDs and append-only audit event in **one `BEGIN IMMEDIATE` transaction**. Failed audit/ID writes roll back all page rows. Reopening validates plan hashes, date splits, offsets, page hashes and index equality before any resume. This is accidental-corruption detection, not a cryptographic authenticity guarantee against an attacker who controls the entire SQLite file.

**Migration and rollback.** Newly created projects start directly at schema v3. Existing v1 projects are backed up and upgraded atomically through v2 definitions to v3; existing v2 projects receive a consistent `researchy-before-v3-*.sqlite3` backup before v3 tables are applied. On migration failure, the original database version/data and verified backup remain intact. No unsupported future schema is silently opened.

**Completeness boundary.** A stored checkpoint can be `paused`, `incomplete` or `identifiers_reconciled_metadata_pending`. The source query is **never** advanced to `completed_verified` by this layer. Actual metadata EFetch, source run reconciliation, Web of Science integration and project archives are separate increments.

## P1-04d — PubMed EFetch records (proposed)

No schema change: the existing source_retrievals and query_retrievals tables support atomic storage of parsed original PubMed metadata, source response digests and query membership, with a matching audit event. These records remain separate from chosen publication metadata and cannot establish completed_verified.
