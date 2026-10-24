# RESEARCH-Y handover — 24 October 2026

## Current state

- **Authoritative specification:** `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved 23 October 2026; requirements unchanged.
- **Private repository:** https://github.com/studeployed/RESEARCH-Y.
- **Phase:** Phase 1 — durable data foundation.
- **Merged:** [PR #10](https://github.com/studeployed/RESEARCH-Y/pull/10) on 24 October 2026, merge commit `e2a645dc0da5dc7fb1536c4ce634e1ae754a7750`; issue #4 closed.
- **In progress:** issue [#5](https://github.com/studeployed/RESEARCH-Y/issues/5), P1-02a on `feat/p1-02a-schema-migration`. **Unmerged; owner approval required.**
- **Known deferred risk:** [#11](https://github.com/studeployed/RESEARCH-Y/issues/11), Windows directory-junction containment, to be handled before untrusted imports/release rather than expanding P1-02a scope.

## Verified functionality and evidence

- Previously merged P1-01: self-contained project create/open/move, versioned manifest and initial SQLite storage, transactional research setup/audit; GitHub Actions Windows/Linux Python 3.12/3.13 passed.
- P1-02a **locally implemented and tested**: schema version 2, approved strategy snapshots, runs, source queries/records/memberships, separate unique publications and supporting entities; one-time version-1 migration with consistent SQLite backup and rollback.
- Local Linux Python 3.13.5: **53 tests passed**, 93% branch-aware coverage; source compilation and requirement traceability checks passed.
- GitHub Actions for P1-02a: **pending publication / review of results**, do not claim a pass until verified on the current head.
- These are storage contract tests, not actual source searches or end-to-end acceptance of AT-01…AT-22.

## Open work and limitations

- Full query processing and approved-term persistence APIs, search execution, PubMed/Web of Science connectivity, recovery jobs, deduplication decisions, classification services, Excel export, GUI and installer are not implemented.
- Multi-writer management and complete project archive/restore remain separate increments. Windows junction hardening remains #11.
- Branch protection and native GitHub milestones are not asserted to be configured (see `docs/REPOSITORY_CONTROLS.md`).

## Important decisions

- Python-only, independent codebase, local-first, no paid or new runtime dependencies introduced in P1-02a.
- Group union is OR-only; search execution must never silently narrow, invent source counts or declare incomplete retrieval verified.
- Project-relative files, non-creating SQLite opens and identifiable/consistent backups before schema migration.
- No merges, releases, destructive operations or substantive specification changes without explicit owner approval.

## Next recommended action

1. Check the P1-02a pull request and GitHub Actions Windows/Linux test evidence; review code-quality and security findings within the increment's scope.
2. Present the PR for explicit owner merge approval; do not merge automatically.
3. After merge, continue issue #5 with small operational persistence APIs that exercise the versioned research entities, then build the query compiler and connectors according to the approved phase order.
