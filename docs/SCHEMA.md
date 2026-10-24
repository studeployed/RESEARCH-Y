# SQLite schema v2 (P1-02a)

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
