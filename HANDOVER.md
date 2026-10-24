# RESEARCH-Y handover — 24 October 2026

## Authoritative state

- Repository: **public** https://github.com/studeployed/RESEARCH-Y (visibility changed by owner on 24 October 2026). Source/history/issues visible; no new write access granted to outside users.
- Specification: `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved 23 October 2026, unchanged and authoritative.
- Phase: Phase 1 — core literature search foundation.
- Merged PRs: [#10](https://github.com/studeployed/RESEARCH-Y/pull/10), [#12](https://github.com/studeployed/RESEARCH-Y/pull/12), [#13](https://github.com/studeployed/RESEARCH-Y/pull/13) (merge `deb2b735f12f06fc2ecb8fcc6b40640f746265d2`).
- Open [PR #15](https://github.com/studeployed/RESEARCH-Y/pull/15), branch `feat/p1-03a-broad-or-query-compiler`, unmerged. Owner approval required.
- Active branch ruleset **RESEARCH-Y - Protect main** (`25788555`): default branch only; requires pull requests and resolved review threads, blocks force-pushes and deletion, zero mandatory approvals, empty bypass. **Required status checks remain absent; owner must add four Windows/Linux checks.**
- Known deferred issue [#11](https://github.com/studeployed/RESEARCH-Y/issues/11): Windows directory-junction containment, required before untrusted project import/release.

## Functionality and test evidence

- P1-01: project create/open/relocate, transactional storage and audit.
- P1-02a: SQLite version 2, distinct publication/retrieval identities and recoverable version-1 migration.
- P1-02b: immutable approved strategy snapshots, pending runs, unexecuted source queries and audit rollback.
- P1-03a (unmerged PR #15): deterministic offline broad-OR PubMed All Fields/Web of Science Starter Topic compiler, tested with controlled fixtures; **no live source verification or search execution yet**.
- GitHub Actions on the private repository exhausted its minute allocation; source code had no demonstrated Python regression. After becoming public, [PR #15 run 40100711005](https://github.com/studeployed/RESEARCH-Y/actions/runs/40100711005), attempt 2, passed on all four Windows/Linux Python 3.12/3.13 jobs. A rerun of the former `main` run [40097664003](https://github.com/studeployed/RESEARCH-Y/actions/runs/40097664003), attempt 3, passed all four jobs. Logs show 74 tests passed and 93% coverage in every matrix job.

## Open blockers and further work

- Configure mandatory GitHub Actions status checks in the active ruleset; instructions in `docs/REPOSITORY_CONTROLS.md`.
- Issue [#14](https://github.com/studeployed/RESEARCH-Y/issues/14) documents original no-runner failures from exhausted private Actions minutes. The `main` rerun now passed; issue can be closed with evidence.
- Codex code and security reviews at PR #15's last checked head found no findings. Confirm PR head/checks before merge recommendation.
- Source connectors, PubMed accepted translation, Web of Science entitlement, large-retrieval completeness, master results, GUI, packaging and export are unimplemented.

## Next recommended development action

1. Required status checks are not yet configured. The owner should require all four matrix checks under the active ruleset.
2. Present PR #15 for owner review, leaving it unmerged until explicit authorisation.
3. Then implement real source-query acceptance/translation checks and the PubMed/Web of Science connectors per issues #6–#8; preserve broad OR-only semantics and honest incomplete status.
