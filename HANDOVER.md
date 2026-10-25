# RESEARCH-Y handover — 25 October 2026

## Authority and repository status

- Public GitHub repository: https://github.com/studeployed/RESEARCH-Y.
- Approved, authoritative specification: `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved 23 October 2026. **No substantive changes**.
- `main` is protected: pull requests, resolved review threads and four required GitHub Actions Windows/Linux × Python 3.12/3.13 checks; explicit project-owner approval is required before merging.
- Merged increments: PRs #10, #12, #13, #15, #16, #17, #18 and [#19](https://github.com/studeployed/RESEARCH-Y/pull/19); current integration baseline `088c60ec0719d3794d30a587685ac628591b2b6d`, with all four post-merge CI checks passing.
- **Open/unmerged:** [PR #20 — P1-04c durable PubMed checkpoints and recovery](https://github.com/studeployed/RESEARCH-Y/pull/20), branch `feat/p1-04c-durable-pubmed-checkpoints`, [issue #7](https://github.com/studeployed/RESEARCH-Y/issues/7). Do not merge without the owner's explicit approval.
- Deferred security item [#11](https://github.com/studeployed/RESEARCH-Y/issues/11): Windows junction handling before untrusted project import/release.

## Implemented, tested and deliberately bounded

- Merged foundation: portable project directory and SQLite identity; recoverable schema migrations; immutable approved OR-only strategies; PubMed/Web of Science Starter query previews; fixed-HTTPS PubMed count/translation probing; paginated PubMed PMIDs and count-reconciled disjoint Create Date partitions.
- P1-04c **in PR #20, not yet merged**:
  - Add schema v3 to the same authoritative project SQLite file, with consistent pre-upgrade snapshots and transactional v1/v2 migration, audit recording and rollback.
  - Freeze exact approved PubMed query and partition counts in an immutable checkpoint plan before page one; atomically commit each validated page, its individual PMIDs and an audit event.
  - Validate hashes, page offsets, partition geometry and a separate PMID index on reopen. Replaying the same page is idempotent; conflicts or corruption are refused.
  - Resume only uncommitted pages after fresh source root/partition count and accepted-translation checks. Preserve previously committed pages following a crash, interrupted HTTP request, failed audit or source drift.
  - Honour explicit user pause, including during in-flight requests and during the final SQLite status transition. Full publication/source completion is **never** inferred from PMIDs alone.
- [GitHub Actions run 40177202413](https://github.com/studeployed/RESEARCH-Y/actions/runs/40177202413) at code-bearing commit `e55dd72bd934`: **all four jobs passed, 282 tests each, 89% overall branch-aware coverage**. Traceability and source compilation also passed. Controlled fixtures cover migration rollback, checkpoints and audit atomicity, interrupted process/reopen/relocation, corrupt indexes, source drift, missing-page recovery and concurrent pause timing.
- Six scoped code review findings were addressed with tested fixes. Code rereview at `e55dd72bd934` completed with no remaining findings. Latest security rereview was requested in the correct sequence after 👀 acknowledgment; consult PR #20 for its final result. All review threads were answered; see PR discussion for current resolution status.

## Outstanding scientific and delivery gates

- **No live National Center for Biotechnology Information (NCBI) PubMed translation/count/identifier verification has been performed**. AT-06 and AT-07 remain partial. AT-09 has offline crash/recovery evidence but is not accepted end-to-end with a live source; AT-19 remains partial.
- Identifier checkpoint reconciliation returns `identifiers_reconciled_metadata_pending`. It is **not** `completed_verified` and does not include fetched bibliographic metadata/abstracts.
- Stable provider snapshot guarantees, single-day >9,000-hit alternative partitioning, EFetch metadata, full source and cross-source reconciliation, WoS Starter API, conservative deduplication, Excel, GUI and Windows packaging remain future increments. Never invent unknown counts, fields or completeness.

## Next action

1. Confirm required current-head GitHub Actions and final Codex code/security reviews, resolving substantive findings if any. Present **PR #20 unmerged** for project-owner review and approval.
2. Following authorised merge, complete permitted live PubMed accepted-query/translation checks, then implement bibliographic metadata retrieval and source reconciliation as approved in issues #6–#8.
3. Maintain an auditable handover, explicit incomplete statuses and requirements-to-tests traceability without unrelated scope expansion.
