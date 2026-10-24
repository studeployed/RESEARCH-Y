# RESEARCH-Y handover — 24 October 2026

## Repository and authoritative requirements

- Repository: **public** https://github.com/studeployed/RESEARCH-Y.
- Approved specification: `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`,
  approved 23 October 2026; no substantive requirements changed.
- Current phase: **Phase 1 — core biomedical search**.
- **Merged PRs:** [#10](https://github.com/studeployed/RESEARCH-Y/pull/10)
  (projects), [#12](https://github.com/studeployed/RESEARCH-Y/pull/12)
  (schema/migration), [#13](https://github.com/studeployed/RESEARCH-Y/pull/13)
  (approved strategy/run persistence), [#15](https://github.com/studeployed/RESEARCH-Y/pull/15)
  (offline OR query compiler), and [#16](https://github.com/studeployed/RESEARCH-Y/pull/16)
  (public governance and CI triggers). Latest verified merged `main`:
  `d30a02158eee303c8a045f66a86915304248ad48`.
- Active ruleset `RESEARCH-Y - Protect main` (ID `25788555`):
  pull requests and resolved conversations mandatory; all four current-branch
  Windows/Linux × Python 3.12/3.13 checks mandatory; force-pushes/deletion
  restricted. **Never merge without the owner's explicit approval.**
- **Open development branch:** `feat/p1-03b-pubmed-translation-probe`
  for [issue #6](https://github.com/studeployed/RESEARCH-Y/issues/6).
  Its initial code and tests are local and under GitHub review, **unmerged**.
- Security issue [#11](https://github.com/studeployed/RESEARCH-Y/issues/11)
  (Windows junctions) remains separately deferred until untrusted import or
  release. Hosted Actions quota issue #14 was resolved by public visibility.

## Last implemented and verified functionality

- Merged: self-contained portable projects; versioned SQLite schema and
  recoverable migration; frozen approved OR-only strategies; pending runs and
  query plans; deterministic PubMed All Fields/WoS Starter Topic query previews.
- [PR #16 post-merge workflow 40120157266](https://github.com/studeployed/RESEARCH-Y/actions/runs/40120157266)
  passed all four Windows/Linux Python 3.12/3.13 jobs.
- P1-03b: count-only PubMed ESearch client with source-reported counts,
  accepted translation/warnings, conservative semantic review flags,
  NCBI-compatible pacing and secret-safe error handling. Also an opt-in live
  smoke diagnostic requiring private contact settings.
- **P1-03b offline local evidence:** 38 unit/fixture tests passed Python
  3.13.5/Linux; 90% branch-aware coverage of the new module. Windows CI
  and GitHub security/code review **not yet verified at this checkpoint**.
- **Live provider evidence:** no public NCBI ESearch call completed in this
  execution environment due to disabled DNS; PubMed AT-06 remains **partial/
  unverified**, rather than marking this source fully validated.

## Outstanding and next action

1. Check P1-03b PR current-head CI on Windows/Linux and code/security review.
   Address only substantive scoped defects. Present the PR for owner approval;
   do not merge automatically.
2. Complete a permitted real PubMed ESearch smoke check using the runtime
   contact setting and compare submitted versus accepted translation. Keep
   warnings and unresolved phrase issues visible; **AT-06 not complete yet**.
3. Continue PubMed full ID retrieval/partitioning and recovery (#7), Web of
   Science Starter entitlement/pagination (#8), source reconciliation,
   deduplication and initial Excel export, rather than more disconnected
   infrastructure work. Update this handover after each verified milestone.
