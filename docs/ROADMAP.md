# RESEARCH-Y milestones and planned GitHub issues

The scope and gates are fixed in section 20 of the approved specification. These tracking units are implemented as GitHub issues, with phases M0–M3 represented in the roadmap. GitHub milestone objects should be linked when an authorised milestone-creation operation becomes available.

## Milestone M0 — Foundation (Phase 0)

- **P0-01:** Record baseline approval verbatim; version-controlled specification and revision history. Pass: approval recorded, requirements unchanged; source-of-truth check.
- **P0-02:** Python project, pinned development dependencies, GitHub Actions on Windows and Linux, minimal maintainability/security guidance. Pass: CI jobs succeed on both operating systems, branch-protection recommendation documented.
- **P0-03:** Requirement-to-test traceability, representative synthetic fixture plan and source-access smoke-test plan. Pass: every numbered requirement has a traceability row, all 22 acceptance tests mapped; no unverified live-source claims.

## Milestone M1 — Durable end-to-end core (Phase 1)

- **P1-01:** Create/open/relocate project with safe versioned index and SQLite transactional metadata. **Merged PR #10 (24 October 2026)**; 44 tests passed on Windows/Linux Python 3.12/3.13, 95% coverage at merge. AT-01/AT-02 remain partial.
- **P1-02:** Versioned research storage and migrations. **P1-02a merged PR #12** (schema v2 and recoverable migration); **P1-02b merged PR #13** (approved strategy snapshots, pending runs and exact unexecuted query plans). Pre-merge checks: 74 tests and 93% branch-aware coverage across Windows/Linux and Python 3.12/3.13. Post-merge runner allocation recovered when the repository became public; issue [#14](https://github.com/studeployed/RESEARCH-Y/issues/14) is resolved. Advanced provenance APIs and multi-writer controls remain separate.
- **P1-03:** Approved broad OR-only strategies and source-specific compilation. **P1-03a merged in PR #15**; deterministic PubMed All Fields / Web of Science Starter Topic compiler verified across Windows/Linux. **P1-03b merged in PR #17** (24 October 2026): opt-in PubMed ESearch count/translation probe, conservative phrase/mapping checks, controlled fixture tests, no IDs or false completion. Real-source contact/translation verification remains an independent mandatory gate (AT-06 unverified), as do Web of Science Starter acceptance and PRESS/pre-run interface. AT-05 remains partial.
- **P1-04:** PubMed discovery, metadata, complete partitioning and recovery. **P1-04a merged in PR #18** (24 October 2026): bounded source identifier paging, strict count/translation/PMID reconciliation and explicit incomplete or partition-required status. **P1-04b proposed** on `feat/p1-04b-crdt-date-partitioning`: recursive inclusive Create Date (`crdt`) partitioning when source counts exceed 9,000, reconciliation of every parent/child count and the final unique PMID union, with fail-closed date coverage and source-change detection. Durable checkpoint/resume, one-day overflow alternatives, metadata EFetch and live-source validation remain separate milestones. AT-07 is still partial and AT-09 pending.
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
