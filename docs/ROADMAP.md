# RESEARCH-Y milestones and planned GitHub issues

The scope and gates are fixed in section 20 of the approved specification. These tracking units are implemented as GitHub issues, with phases M0–M3 represented in the roadmap. GitHub milestone objects should be linked when an authorised milestone-creation operation becomes available.

## Milestone M0 — Foundation (Phase 0)

- **P0-01:** Record baseline approval verbatim; version-controlled specification and revision history. Pass: approval recorded, requirements unchanged; source-of-truth check.
- **P0-02:** Python project, pinned development dependencies, GitHub Actions on Windows and Linux, minimal maintainability/security guidance. Pass: CI jobs succeed on both operating systems, branch-protection recommendation documented.
- **P0-03:** Requirement-to-test traceability, representative synthetic fixture plan and source-access smoke-test plan. Pass: every numbered requirement has a traceability row, all 22 acceptance tests mapped; no unverified live-source claims.

## Milestone M1 — Durable end-to-end core (Phase 1)

- **P1-01:** Create/open/relocate project with safe versioned index and SQLite transactional metadata. Pass: tests for manifest, persistence, move, corruption, creation collisions, rollback; partial AT-01/02. **Locally implemented; 40 tests passed; pending remote PR/Windows verification.**
- **P1-02:** Versioned schema for strategy versions, runs, source retrieval, publications, memberships and audit. Pass: migration/durability/recovery fixtures.
- **P1-03:** Approved OR-only strategy representation, source-specific query compiler and review. Pass: AT-04/05 fixture checks, planned live PubMed translation smoke test AT-06.
- **P1-04:** PubMed discovery/metadata, complete partitioning and recovery. Pass: AT-06/07/09, successful authenticated live-source smoke test.
- **P1-05:** Web of Science Starter connectivity, quota-aware paging and resumption. Pass: AT-08/09, live-source entitlement verification.
- **P1-06:** Conservative deduplication, reconcilable master results, initial Excel output and minimal application shell. Pass: AT-10/18/19 and end-to-end fixture run.

## Milestone M2 — Specialist processing (Phase 2)

- **P2-01:** AI terminology and classification modes, reproducible biomedical benchmarks. Pass: AT-04/15/20.
- **P2-02:** Conference abstracts, supplements and distinct locators. Pass: AT-11/12.
- **P2-03:** Society guidance workflows, official-page provenance and manual tasks. Pass: AT-13.
- **P2-04:** Classification, manual review, Crossref enrichment. Pass: AT-14/15/16.

## Milestone M3 — Complete workflow and release verification (Phase 3)

- **P3-01:** Full UI, tables, review queues and accessible results.
- **P3-02:** Project archive import/export, migration recovery and complete Excel/bibliographic reporting. Pass: AT-03/18/21.
- **P3-03:** Windows packaging, security review, 100,000-record performance test and complete AT-01…AT-22 evidence. Pass: all mandatory acceptance gates verified and exceptions documented.

## Source-access and fixture test strategy (P0-03)

- Deterministic offline fixtures for counts, partition boundaries, paginated duplicates, missing or contradictory metadata, repeated query membership, abstract/supplement separation, server errors, quota exhaustion and crash/resume.
- Real-source smoke tests on permitted credentials: PubMed ESearch/translation/metadata and partition behaviour; Web of Science Starter entitlement, 50-record pages and quota consumption; record results without leaking keys or licensed response content.
- No live credentials or networking are required in ordinary pull-request CI. Any external verification is separately reported with date, source and limitations.
