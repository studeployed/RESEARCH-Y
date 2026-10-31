# RESEARCH-Y milestones and planned GitHub issues

The scope and gates are fixed in section 20 of the approved specification. Tracking units are GitHub issues. Staged implementation does not waive full acceptance criteria.

## Milestone M0 — Foundation (Phase 0)

- **P0-01:** Record baseline approval verbatim; version-controlled specification and revision history. Pass: approval recorded, requirements unchanged; source-of-truth check.
- **P0-02:** Python project, pinned development dependencies, GitHub Actions on Windows and Linux, maintainability/security guidance. Pass: CI on both operating systems; repository controls documented.
- **P0-03:** Requirement-to-test traceability, synthetic fixtures and source-access test plan. Pass: every requirement and all 22 acceptance scenarios mapped; no unsupported live-source claims.

## Milestone M1 — Durable end-to-end core (Phase 1)

- **P1-01:** Create/open/relocate project with safe versioned index and SQLite transactional metadata. Merged PR #10 (24 October 2026); 44 tests passed on Windows/Linux Python 3.12/3.13, 95% coverage at merge. AT-01/02 remain partial.
- **P1-02:** Versioned research storage and migrations. P1-02a merged PR #12 (schema v2 and recoverable migration); P1-02b merged PR #13 (approved snapshots, pending runs and exact query plans). Historical pre-merge 74 tests/93% coverage. Post-merge allocation issue #14 resolved. Advanced provenance and multi-writer controls remain separate.
- **P1-03:** Broad OR-only strategy/source compilation. P1-03a merged PR #15; PubMed All Fields and Web of Science Starter Topic compiler. P1-03b merged PR #17; count/translation probe. A generic live PubMed query is accepted; broader phrase/OR cases, Starter live interpretation and PRESS/pre-run interface remain partial.
- **P1-04:** PubMed complete retrieval/recovery. P1-04a–d merged PRs #18–21: bounded identifiers, disjoint Create Date partitioning, transactional SQLite checkpoints and bounded EFetch metadata persistence. P1-04e–h merged PRs #22–25: manual live smoke, outer-parenthesis compatibility, large-ID/restart workflow and count diagnostic. P1-04i merged PR #26: context-bound Create Date alias compatibility. [Run #41235232458](https://github.com/studeployed/RESEARCH-Y/actions/runs/41235232458) passed the **19,483 unique-identifier, 43-page, controlled pause/reopen** scenario on 31 October 2026. The scoped AT-07 live scenario and identifier-stage AT-09 scenario are passed; full metadata, broader queries/failures and product-level acceptance are still partial. See `docs/evidence/pubmed-41235232458-summary.json` for precise boundaries and hashes.
- **P1-05:** Web of Science Starter connectivity, quota-aware paging and resumption ([issue #8](https://github.com/studeployed/RESEARCH-Y/issues/8)). Full gate: AT-08/09 plus real-source entitlement and completeness checks.
  - **P1-05a — current proposed increment:** fixed-origin transport, observed institutional daily quota, strict 1–50-record page validation, exact source-record preservation/missingness, safe errors and maximum-three-request manual entitlement/two-page smoke. No durable job state yet. See `docs/WOS_STARTER.md`.
  - **P1-05b — next:** recoverable SQLite schema/storage, atomic record/page/audit commits, quota-aware pause and cross-day reopen without repeating committed pages, bounded retry scheduling, source drift handling and full count/unique-accession reconciliation. Build against the observed live source contract, not fixture assumptions.
  - **P1-05c — acceptance:** controlled live pagination/recovery and provider-limit evidence with actual institutional credentials; no exhaustive-source claim without reconciliation.
- **P1-06:** Conservative deduplication, reconcilable master results, initial Excel output and minimal application shell. Pass: AT-10/18/19 and end-to-end fixtures.

## Milestone M2 — Specialist processing (Phase 2)

- **P2-01:** AI terminology/classification and reproducible biomedical benchmarks. Pass: AT-04/15/20.
- **P2-02:** Conference abstracts, supplements and distinct locators. Pass: AT-11/12.
- **P2-03:** Society guidance workflows, official provenance and manual tasks. Pass: AT-13.
- **P2-04:** Classification, manual review and Crossref enrichment. Pass: AT-14/15/16.

## Milestone M3 — Complete workflow and release verification (Phase 3)

- **P3-01:** Full UI, tables, review queues and accessible results.
- **P3-02:** Archive import/export, migration recovery and complete Excel/bibliographic reporting. Pass: AT-03/18/21.
- **P3-03:** Windows packaging, security review, 100,000-record performance and complete AT-01–22 evidence. Pass: all mandatory acceptance gates verified and exceptions documented.

## Source-access and fixture strategy

Offline fixtures cover counts, boundaries, duplicates, metadata gaps, repeated memberships, abstract separation, source errors, quota and recovery. Real-source checks use authorised credentials and retain dated evidence without publishing keys or licensed content. Normal pull-request and push CI is offline. A source sample or success HTTP status is never equivalent to a complete literature search.

**Current live boundary, 31 October 2026:** PubMed one-record EFetch and the full identifier/restart scenario passed. Complete metadata acquisition and broad recovery acceptance remain outstanding. **No live Starter access or quota result has been verified in P1-05a.**
