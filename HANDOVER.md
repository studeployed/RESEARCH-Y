# RESEARCH-Y handover — 24 October 2026

## Authoritative repository and scope

- Repository: **public** https://github.com/studeployed/RESEARCH-Y; visible source, development history, issues and pull requests. The owner has authorised this visibility; outside users were not given push or merge rights.
- Specification: `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved 23 October 2026; requirements unchanged and authoritative.
- Current phase: Phase 1 — durable search foundation and source-specific query processing.
- Merged: PR #10 (`e2a645dc0da5`), #12 (`c3355ac735c6`), #13 (`deb2b735f12f`) and [#15](https://github.com/studeployed/RESEARCH-Y/pull/15) on 24 October 2026 (merge `19b6c7d1d44d5e4e14686de139509de33d976e44`).
- Open **[PR #16](https://github.com/studeployed/RESEARCH-Y/pull/16)**, branch `docs/public-repository-governance`, updated against merged `main`. It corrects public-repository governance documentation and removes duplicate feature-branch push workflows. **It is unmerged; owner authorisation is required before merging.**
- Active branch ruleset `RESEARCH-Y - Protect main`, ID `25788555`, targets `main` only with no bypass. Requires pull requests, resolved review conversations, all four Windows/Linux × Python 3.12/3.13 GitHub Actions checks, and up-to-date branches; blocks deletion and force-push. Zero mandatory human approvals avoid blocking the sole maintainer, but owner approval remains required.
- Known deferred Windows directory-junction security finding: [issue #11](https://github.com/studeployed/RESEARCH-Y/issues/11), before untrusted imports/release.

## Verified completed functionality and evidence

- Self-contained portable projects, versioned SQLite schema/migrations and backups, atomic audit records, immutable researcher-approved broad-OR strategy snapshots, pending runs and source-query plans.
- Offline query compiler generating transparent PubMed All Fields and Web of Science Starter Topic queries; optional OR-boundary chunking, no hidden narrowing or fabricated result counts.
- [PR #15 checks](https://github.com/studeployed/RESEARCH-Y/actions/runs/40100711005): all four Windows/Linux × Python 3.12/3.13 jobs passed, **113 tests per job, 92% branch-aware overall coverage**; Codex code and security reviews found no issues.
- [Post-merge `main` checks](https://github.com/studeployed/RESEARCH-Y/actions/runs/40116828421): all four jobs succeeded on merge `19b6c7d1d44d`.
- GitHub Actions minutes issue [#14](https://github.com/studeployed/RESEARCH-Y/issues/14) resolved by moving to public; previously failed runs were rerun successfully. No underlying Python code fault was identified.
- PR #16: new workflow trigger config and two regression assertions prepared on this feature branch. **Do not represent its tests or code/security review as passed until this PR's current head has been checked.**

## Remaining work and limitations

- No actual PubMed or Web of Science retrieval yet, no verified provider-side accepted query translation/quotas, no deduplication service, final-count reconciliation, Excel export, graphical interface or Windows installer.
- AT-05 remains partial and AT-06 unverified; a successfully compiled query is not evidence of source acceptance or completed retrieval. See issues #6–#8.
- Keep credential handling and nonpublic research content out of public Git history and automated test fixtures.

## Next action

1. Inspect PR #16's current head for all four successful status checks, scope-limited code-quality and security review, and preserved compiler documentation. Present to project owner **without merging**.
2. After owner's explicit merge approval, develop the smallest provider acceptance and translation verification increment under issue #6, followed by PubMed and Web of Science connectors (#7–#8). Prefer working end-to-end functionality over further disconnected infrastructure changes.
3. Maintain this handover and requirements-to-tests mapping at each substantive checkpoint. Do not expand scope or alter the approved specification without project-owner approval.
