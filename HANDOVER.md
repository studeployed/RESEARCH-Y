# RESEARCH-Y handover — 23 October 2026

## Authoritative state

- Specification: `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved on 23 October 2026. Approval recorded without substantive requirement changes.
- GitHub private repository: https://github.com/studeployed/RESEARCH-Y, owner `studeployed`.
- `main` includes Phase 0 foundation (commit `965ecafe27d85d4bcf77a93f08b9dab8ff3d3788`).
- Phase 1 P1-01 storage implementation is on `feat/project-storage-increment-1`, **unmerged**.
- GitHub Actions matrix and issue links should be checked live; never infer a CI pass from local tests.

## Last implemented and locally verified

- Portable versioned `project.ryproj` project manifest and SQLite store with matching unique identifiers and initial audit schema.
- Create, reopen, relocate, persist theme/objectives, safely handle partial creation, corrupt/missing data, and roll back failed transactions.
- Offline test suite: 40 passed on Python 3.13.5/Linux; 96% branch-aware coverage. See `docs/REVIEWS.md`.
- Acceptance tests AT-01/02 remain **partial**, because the finished application has further persistence/interface behaviours to implement.

## Issues and reviews

- Project roadmap and acceptance gates: `docs/ROADMAP.md`; authoritative requirements: `RESEARCH-Y_SPEC.md`.
- Feature branch requires a pull request and owner approval before merging.
- No implementation of search connectors, GUI, AI, full export, archive or packaging.

## Outstanding blockers and next recommended work

1. Inspect remote Python 3.12/3.13 Windows/Linux workflow results, fix any failing jobs and record evidence.
2. Review first storage pull request for correctness and security; **do not merge without approval**.
3. Start next incremental issue P1-02: versioned data schema and recoverable migrations, with failure/recovery tests.
4. Live PubMed and WoS smoke tests require appropriate credentials/entitlement and are not yet performed.

## Important decisions

- Python only; development wholly independent of RESEARCH-X.
- Preserve broad OR-only searches, no automatic narrowing, auditable provenance, immutable search history and truthful incomplete status.
- Keep credentials in machine-level secure storage when implemented; never in projects, logs or repository.
