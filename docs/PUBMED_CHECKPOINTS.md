# P1-04c — Durable PubMed checkpoint and recovery protocol

**Status:** feature-branch proposal; not merged, not a completed biomedical
literature-search engine. This increment applies SRC-02/03 and RUN-02/04/05/06/07
with partial AT-07/09/19 acceptance evidence.

## Transactional project format

RESEARCH-Y schema version **3** is additive to version 2. Existing version-2
projects are backed up using SQLite's consistent backup facility into
`backups/researchy-before-v3-*.sqlite3` before any v3 changes. Schema
creation, `PRAGMA user_version` and the migration audit event are atomic;
a failed migration leaves version 2 and its backup unchanged.

The new tables tie each checkpoint to one approved, existing PubMed
`source_queries.query_id`. The immutable plan records original broad OR-only
query, the exact inclusive `[crdt]` partitions (where needed), parent/child
counts and the bounded page size. Every page records the exact partition,
provider response digest, UTC timestamp, accepted translation, reported count,
ordered PMIDs and a separate payload checksum. A linked per-PMID index prevents
silent overlap among pages and partitions. Each page, the unique IDs, and its
audit event commit or roll back **together**.

The SHA-256 checksums detect accidental modification; they are not
tamper-resistant signatures of data controlled by an adversarial database
administrator. The actual source raw payload is not yet retained by this
increment; the digest and validated representation are.

## Operation and recovery

1. The application first checks the approved source query and performs normal
   count/translation and partition validations. It commits the complete
   partition plan **before fetching any identifier page**.
2. Each source-validated page commits once. Duplicate replays are accepted
   only if bytes and provenance match; conflicting offsets or PMIDs fail.
3. On reopen, the project SQLite identity/schema are checked; all saved page
   hashes, offset continuity, unique IDs and partition-plan reconciliation
   are checked. A bad checkpoint is rejected, never silently repaired.
4. Before fetching missing pages, request new source counts and accepted
   translations for the root and each partition. A mismatch returns
   `incomplete` and preserves already committed evidence.
5. Resume from the first **uncommitted** page offset, never advancing past
   unverified pages or repeating committed requests. Unexpected transport
   and checkpoint callback errors are sanitised.
6. Recheck the source root at the end. A reconciled source-ID union becomes
   `identifiers_reconciled_metadata_pending`, while source/query overall
   status remains **incomplete**, not `completed_verified`.

A paused checkpoint persists and can be reopened and recovered by a future
call. Operation while the application is closed is not required in the
approved initial product.

## Tests and limits

`tests/test_pubmed_checkpoints.py` and
`tests/test_schema_migrations.py` exercise multi-page and multi-date
retrieval, immutable replay, change/corruption detection, interrupted audits,
migration rollback, pause/reopen/relocation and count drift, using controlled
local fixtures. Cross-platform CI and independent Codex reviews are
required before the increment is accepted.

Missing functionality remains explicit: live PubMed source testing,
unfreezable PubMed result sets, alternatives for an overlarge single Create
Date, EFetch metadata/abstracts, final master publication reconciliation,
project archives and complete user-interface job scheduling.
