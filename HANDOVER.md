# RESEARCH-Y handover — 24 October 2026

## Current state and authority

- Repository: **public** https://github.com/studeployed/RESEARCH-Y, with active ruleset requiring four GitHub Actions Windows/Linux checks, pull requests, resolved review conversations and current branch checks on `main`.
- Authoritative specification: `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved 23 October 2026. **No substantive changes.**
- Current phase: Phase 1 — source retrieval and recovery.
- Merged: PRs #10 (projects), #12 (schema/migration), #13 (approved strategies/runs), #15 (OR query compiler), #16 (public governance and non-duplicative CI), and **[#17](https://github.com/studeployed/RESEARCH-Y/pull/17)** (count-only PubMed ESearch, merged 24 October 2026 at 19:05 UTC, commit `3baa12e5ed2d3a51c9aed05bf86631b9ec1b4c32`).
- **Open/unmerged:** P1-04a on `feat/p1-04a-bounded-pubmed-identifiers`; review and owner approval required before merge.
- Related issues: [#7](https://github.com/studeployed/RESEARCH-Y/issues/7) PubMed complete retrieval and recovery, [#6](https://github.com/studeployed/RESEARCH-Y/issues/6) outstanding real accepted-query verification, [#11](https://github.com/studeployed/RESEARCH-Y/issues/11) deferred Windows junction containment before untrusted import/release.

## Completed and tested

- Project creation/opening/relocation and recoverable versioned SQLite storage.
- Immutable researcher-approved OR-only strategies, pending runs and exact unexecuted query plans with audit trail.
- Offline PubMed All Fields / Web of Science Starter Topic query compiler.
- Count-only PubMed ESearch client: accepted translation, actual source-reported count, warnings/review flags, credential-safe fixed-endpoint HTTPS POST.
- **PR #17 post-merge GitHub Actions run [40123717086](https://github.com/studeployed/RESEARCH-Y/actions/runs/40123717086): all four Windows/Linux Python 3.12/3.13 jobs passed.** Pre-merge suite had 156 tests per environment.
- **P1-04a locally tested, not merged:** paginated bounded PubMed ESearch identifiers, page/count/translation integrity, explicit partition-required and incomplete outcomes. Local Python 3.13.5/Linux: 96 PubMed probe/ID tests passed; updated new module 97% branch coverage. Two code-review P2 failure cases corrected: checkpoint exception redaction and unusually long decimal PMIDs.
- GitHub Actions for the P1-04a head must be inspected before claiming cross-platform verification.

## Unfinished / verification gates

- No real NCBI query acceptance smoke test has been conducted with a private runtime contact. AT-06 remains incomplete.
- **No source-wide PubMed completeness claim:** large query disjoint partitioning, source index movement reconciliation, durable checkpoint/resume, original metadata/abstract download, full deduplication and accurate global counts are not yet implemented. AT-07/09/19 remain pending or partial.
- Web of Science Starter API entitlement and paging, master results, Excel export, GUI and Windows installation remain future work.
- A callback permits a caller to store validated ID pages but is **not itself durable checkpoint management**.

## Next action

1. Present and review the P1-04a pull request with Windows/Linux CI, code quality and security review; do not merge without the project owner's explicit approval.
2. Add durable page checkpoints and interrupted-run recovery, then reproducible non-overlapping date partitioning for >10,000 PubMed records, with objective failure/recovery tests (issue #7).
3. Complete permitted real PubMed translation/count/ID verification and proceed with the Web of Science connector, then master-list deduplication and initial Excel export. Keep scientific completeness claims conservative.
