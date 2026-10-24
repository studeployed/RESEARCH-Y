# RESEARCH-Y handover — 24 October 2026

## Authoritative state

- **Repository:** private https://github.com/studeployed/RESEARCH-Y.
- **Specification:** `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved 23 October 2026; no substantive requirements changed.
- **Current phase:** Phase 1 — core retrieval/search foundation.
- **Merged:** PR #10 (`e2a645dc0da5`), PR #12 (`c3355ac735c6`), and [PR #13](https://github.com/studeployed/RESEARCH-Y/pull/13) merged **24 October 2026 at 13:19 UTC**, `main` commit `deb2b735f12f06fc2ecb8fcc6b40640f746265d2`.
- **Open feature branch:** `feat/p1-03a-broad-or-query-compiler` for issue [#6](https://github.com/studeployed/RESEARCH-Y/issues/6). No merge without project-owner approval.
- **Open infrastructure blocker:** [#14](https://github.com/studeployed/RESEARCH-Y/issues/14): `main` [Actions run 40097664003](https://github.com/studeployed/RESEARCH-Y/actions/runs/40097664003) failed in all four jobs **before a runner or test step started**, twice. Job `steps=[]`, no logs; exact GitHub annotation inaccessible to connector. Do not attribute failure to Python code without evidence.
- **Deferred Windows security issue:** [#11](https://github.com/studeployed/RESEARCH-Y/issues/11) junction containment, due before untrusted project import/release.

## Last verified functionality and evidence

- Merged P1-01: portable projects, SQLite identity, recoverable hot-journal handling, transactional setup/audit; reviewed and tested.
- Merged P1-02a: schema v2, query/publication/membership relationships, recoverable v1→v2 migration; four-platform testing succeeded.
- Merged P1-02b: frozen researcher-approved OR-only strategy snapshots, pending runs, exact unexecuted source-query plans and auditable rollback. PR #13 [run 40096491782](https://github.com/studeployed/RESEARCH-Y/actions/runs/40096491782) passed 74 tests on each Windows/Linux × Python 3.12/3.13 combination, 93% branch coverage. **The merge commit has no successful post-merge CI check; see #14.**
- P1-03a proposed: pure source query compiler from approved stored snapshots. PubMed per-term quoted `[All Fields]`; WoS Starter `TS`; group-wide OR and global OR; optional explicit UTF-8 byte-cap partition preserving complete union; human-review warnings and refusal of unsupported literal operators. **39 tests passed locally, Python 3.13.5/Linux**, no full matrix claims until CI actually starts.

## Remaining work and limitations

- P1-03a currently **does not connect to PubMed or WoS** and does not validate accepted translations, source limits, provider hit counts or completeness. Those are forthcoming provider-specific acceptance checks; AT-05 remains partial, AT-06 unverified.
- User-interface review, PRESS checklist, online connectors, metadata and publication reconciliation, deduplication services, Excel export and Windows packaging remain unimplemented.
- Existing source-query persistence stores unexecuted text; integration with compiled preview is a future small increment. Do not claim executed queries or successful searches.

## Next recommended action

1. Review latest P1-03a branch/PR, code/security reviews and deterministic tests. Request user approval before merging; no automatic merge.
2. Obtain GitHub Actions failure annotation from [run 40097664003](https://github.com/studeployed/RESEARCH-Y/actions/runs/40097664003) via GitHub UI and resolve issue #14. Rerun actual Windows/Linux jobs and record outcomes before a merge recommendation.
3. Then continue issue #6 provider acceptance/translation validation, and PubMed/Web of Science connectors per issues #7–#8. Avoid scope expansion unrelated to working end-to-end retrieval.
