# RESEARCH-Y handover — 25 October 2026

## Authoritative state

- Repository: public https://github.com/studeployed/RESEARCH-Y; `main` protected by required four GitHub Actions Windows/Linux Python 3.12/3.13 jobs, pull requests and resolved conversations.
- Specification: `RESEARCH-Y_SPEC.md` v`1.0.0-draft.1`, approved 23 October 2026, unchanged.
- Phase: Phase 1 — durable core biomedical retrieval.
- Merged: PRs #10, #12, #13, #15, #16, #17, #18, and **[#19](https://github.com/studeployed/RESEARCH-Y/pull/19)**, merged 24 October 2026 at 20:50 UTC as `088c60ec0719d3794d30a587685ac628591b2b6d`.
- [PR #19 merged-main CI](https://github.com/studeployed/RESEARCH-Y/actions/runs/40131614118): **all four required jobs passed**. Its code and security reviews at the final commit completed with no findings.
- Current increment: **P1-04c** branch `feat/p1-04c-durable-pubmed-checkpoints`, implementing version-3 project migrations and transactional PubMed page/partition persistence with recovery under [issue #7](https://github.com/studeployed/RESEARCH-Y/issues/7). **Do not merge without explicit owner authorisation.**
- Separate security item [#11](https://github.com/studeployed/RESEARCH-Y/issues/11): Windows junction validation before untrusted project archives/release.

## Completed features

- Portable local projects and versioned SQLite schema v2 with immutable approved strategies, runs and unexecuted query plans.
- Broad OR-only PubMed All Fields and WoS Starter Topic query compilation and conservative query-translation review.
- Count-only PubMed ESearch and validated bounded PMID paging with exact source counts.
- Recursive non-overlapping Create Date partitions, unique PMID reconciliation and explicit incomplete state for unsplittable/unproven searches.

## Proposed P1-04c scope (unmerged and not yet CI-verified)

- Schema v3 with independent pre-upgrade SQLite snapshots; atomic page + indexed PMID + audit commit, immutable checkpoint plan, digest checks, validated safe replay and relocation-safe storage.
- Persist partition plan **before** fetching page one; on interruption recover from committed offset after verifying fresh source counts/translations. Do not re-download verified committed pages or disclose credentials in exceptions.
- No source query or run may be labelled `completed_verified` on identifier-only data. Final outcome remains `identifiers_reconciled_metadata_pending`.
- Offline test suite covers migrations, failed audits, interrupted writes, source drift, duplicate PMIDs, corrupt pages/index, date partition continuity, pause/reopen/relocation.
- **Current-head GitHub Actions evidence and Codex dual review are pending.**

## Unresolved acceptance

- Real PubMed ESearch/translation and partition-window smoke tests remain unperformed with authorised runtime credentials; AT-06/07 not final.
- True provider record snapshot stability, alternative splitting when one Create Date exceeds 9,000, bibliographic metadata/abstract EFetch, complete source reconciliation, Web of Science, master deduplication, Excel, GUI and packaging remain outstanding.
- AT-09 recovery is partial until checked across failure modes and accepted against live source. No fabricated completeness or zero counts.

## Next action

Review this feature branch in CI and with Codex code review **followed by security review after 👀 acknowledgement**. Correct scoped defects, then present the PR to the owner **unmerged**. After explicit approval and merge, continue live PubMed validation and metadata acquisition instead of recurring infrastructure hardening.
