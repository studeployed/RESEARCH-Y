# RESEARCH-Y handover — 24 October 2026

## Authoritative repository and development state

- Repository: public https://github.com/studeployed/RESEARCH-Y; active
  `main` branch ruleset requires pull requests, resolved review
  conversations and four Windows/Linux Python 3.12/3.13 checks.
- Specification: `RESEARCH-Y_SPEC.md` version `1.0.0-draft.1`,
  approved 23 October 2026. No substantive requirement changes.
- Phase: Phase 1 — PubMed retrieval/recovery.
- Merged PRs: #10, #12, #13, #15, #16, #17 and **[#18](https://github.com/studeployed/RESEARCH-Y/pull/18)**,
  merged 24 October 2026, commit
  `6d8d385fc90549d5dfea3f19651b01bfa83ec353`.
- Current proposed feature: `feat/p1-04b-crdt-date-partitioning` under
  [issue #7](https://github.com/studeployed/RESEARCH-Y/issues/7). Open its
  pull request, inspect Windows/Linux test results and Codex code/security
  reviews, then request owner approval. **Never merge without explicit authorisation.**
- Deferred issue #11: Windows junction containment before untrusted
  project archives/release.

## Verified implementation

- Existing: portable self-contained projects, SQLite v2 and migrations,
  frozen approved OR strategy/run storage, source-query compiler, count-only
  PubMed ESearch and bounded identifier page retrieval.
- [PR #18 CI](https://github.com/studeployed/RESEARCH-Y/actions/runs/40125761062):
  four matrix jobs passed with 214 tests each and 93% overall coverage.
- **P1-04b locally implemented only**: count-reconciled recursive PubMed
  Create Date `[crdt]` partitions for >9,000-ID queries, exact inclusive
  range provenance, final unique PMID union, explicit incomplete/review
  states and final baseline recount. Existing transport and page validator
  reused; no external runtime dependencies.
- **Local Python 3.13.5/Linux:** 127 targeted PubMed tests passed;
  new partition module 93% statement coverage. Cross-platform result
  pending this feature's current GitHub Actions run.

## Unresolved acceptance gates

- No real PubMed NCBI count/translation/ID live-source verification; AT-06
  remains partial. The new date-partition feature is fixture tested only,
  so AT-07 is **partial**, not complete.
- Durable checkpoints/resumable retrieval, single-date over-cap alternatives,
  publication metadata/abstract EFetch, Web of Science Starter access,
  source count reconciliation, deduplication, Excel exports, GUI and Windows
  packaging remain to be developed. AT-09 remains incomplete.
- A successful ID union is returned as
  `identifiers_reconciled_metadata_pending`, **not** full source-retrieval
  completion.

## Next recommended development action

1. Publish and review the P1-04b pull request with actual Windows/Linux
   CI and both code-quality/security reviews; present to owner unmerged.
2. After approval and merge, implement durable page/partition checkpoints
   and recovery with failure-injection and interrupted-process tests.
3. Conduct permitted live PubMed acceptance/translation smoke checks and
   add metadata EFetch. Then progress to Web of Science Starter and a
   conservative master publication list as specified.
