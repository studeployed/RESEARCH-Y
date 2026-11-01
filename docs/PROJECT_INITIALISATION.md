# New-project database initialisation — transactional performance correction

**Status:** implemented for review after PR #29; full Windows/Linux checks and exact-commit reviews remain required. This is a focused prerequisite to the database-heavy publication-identity work in issue #30, not implementation of deduplication.

## Requirement and scope

The approved `RESEARCH-Y_SPEC.md` is unchanged. The correction supports PROJ-04 and the new-project portions of AT-01/09/21. It does not close those broad acceptance tests or the 100,000-record performance gate AT-22.

Only `_create_database` changes production behaviour. New project schema, application/schema header values, identity and initial audit now share one explicit `BEGIN IMMEDIATE` transaction. The existing connection context commits on success and rolls back on error. `BEGIN` is placed inside the first `executescript`, because starting it immediately before that call would permit an implicit pre-script commit under the supported legacy transaction mode.

Schema version 4, all table/index/trigger definitions, source settings, migration functions, credential handling, retention gates, request budgets and continuous integration workflows are unchanged. Journalling and synchronous writes are not disabled. No network request is involved.

## Defect and deterministic verification

On merged baseline `5b7ca06def03dff748c97231c5b70fcf07cb4711`, tracing actual creation showed 58 schema statements outside a shared transaction. The surrounding `with connection` did not begin a transaction for those statements. Repeated project creation in integration tests multiplied this work.

`tests/test_project_initialisation.py` adds 16 offline, disk-backed tests:

- All creation writes, including header assignments, are inside one transaction; exactly one explicit begin and successful commit; no durability-setting changes.
- Logical database dump and application/schema header values match the pre-fix statement sequence.
- Database errors and Python interruption after each schema stage roll back the whole initialisation.
- Base-table, final schema-version, metadata insert, audit insert and commit rejection leave an empty, internally consistent database rather than partially committed schema.
- Public creation failure removes only its newly allocated folder, preserves another project's bytes and data, and permits a clean retry.
- A real child process exits abruptly after spilling uncommitted pages. SQLite recovers its rollback journal without leaving partial schema. No manifest is fabricated, and the unfinished directory is not accepted as a valid project.

The baseline produced **13 failures and 3 passes**. With the correction, **16/16 passed** locally on Linux, Python 3.13.5, SQLite 3.46.1 and pytest 9.0.2; ResourceWarning was treated as an error. The fetched production modules were verified against Git blob hashes. This local workspace contained the relevant modules and focused tests, not a complete repository checkout. Full repository tests, including existing migration and connector regressions, remain the four-configuration CI gate.

## Measurement, not a release-performance claim

An isolated 20-sample-per-version, alternating-order comparison on the same local Linux filesystem measured median database creation of approximately **236 ms before / 8.4 ms after**. Both produced equal logical contents and passed integrity checks with rollback journalling and full synchronous writes retained. The trace changed from **58 schema statements outside a shared transaction to zero**.

These figures are environment-specific. They do not predict the complete Windows suite's runtime or explain all runner/storage variability. No wall-clock threshold is asserted by the tests. Compare the required Windows jobs and existing slow-test reports after this change; do not claim a speedup merely because a timeout was extended.

## Acceptance and next task

Before merge advice, verify all four Windows/Linux Python 3.12/3.13 checks, exact-HEAD code-review completion then security-review completion (recognising valid automatic reviews), individual receipts and disposition of findings. Owner merge approval remains mandatory.

After validation, continue issue #30 / P1-06a: publication identity and provenance over existing immutable source retrievals, without fuzzy automatic matching, source-count changes, or conflating publications, studies and containers. Existing live-source and product acceptance gaps remain open.

## Primary reference

Python 3.13 sqlite3 documentation, connection context manager, `executescript` and transaction control: https://docs.python.org/3.13/library/sqlite3.html . The context manager commits/rolls back an existing transaction; it does not implicitly open one. Reviewed 1 November 2026.
