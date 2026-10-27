# RESEARCH-Y handover — 27 October 2026

## Repository authority and merged status

- Public repository: https://github.com/studeployed/RESEARCH-Y, protected `main`.
- Authoritative specification: `RESEARCH-Y_SPEC.md` version `1.0.0-draft.1`, approved 23 October 2026; **unchanged**.
- Merged PRs: #10, #12, #13, #15, #16, #17, #18, #19, #20 and **[#21](https://github.com/studeployed/RESEARCH-Y/pull/21)** on 27 October 2026, commit `a91af6ee2217b27e8a73e7f46c05c59d901d2ba0`.
- [PR #21 post-merge Actions](https://github.com/studeployed/RESEARCH-Y/actions/runs/40506608637): all four Windows/Linux × Python 3.12/3.13 jobs passed, 321 tests per job. Security review of the PR final head found no issues; prior code review's five findings were fixed, threads resolved. A redundant later code review stalled after the completed acceptance reviews.
- **Current proposal, unmerged:** P1-04e `feat/p1-04e-optin-live-pubmed-smoke` to make live PubMed smoke acceptance manually executable in GitHub Actions with private repository secrets. Explicit owner approval required for its PR merge.
- Independent issue [#11](https://github.com/studeployed/RESEARCH-Y/issues/11): deferred Windows junction hardening before untrusted archives/release.

## Completed in merged implementation

- Portable local projects, versioned SQLite schemas with recoverable migrations, immutable approved broad-OR strategy snapshots and exact query compilation for PubMed All Fields and WoS Starter Topic.
- PubMed ESearch count and accepted-translation probe, bounded identifier pages, recursively partitioned disjoint Create Date intervals, strict counted unique-PMID union and durable page checkpoints with pause/reopen recovery.
- PubMed EFetch metadata/abstract XML parser and original source-retrieval/link persistence, explicit missingness and source rights flags, bounded/credential-safe HTTP transport, and incomplete metadata-batch recovery.
- Source-wide final completion status is **not** claimed from counted/identifier-only responses or a single EFetch response.

## Live-source verification blocker and P1-04e scope

- **No successful real NCBI ESearch/EFetch source request was executed here.** On 27 October 2026 the local environment failed DNS resolution for the NCBI E-utilities hostname; the web retriever also could not access ESearch. The runtime private `RESEARCHY_NCBI_CONTACT_EMAIL` is not configured. Do not assert AT-06, AT-07 or live AT-09 passed.
- Existing `scripts/pubmed_source_smoke.py` is read-only, requires a private contact, checks exact ESearch query translation, one bounded ESearch PMID page and matching EFetch bibliographic XML; prints no raw abstract text or API keys.
- P1-04e introduces **manual-only** GitHub Actions workflow `.github/workflows/pubmed-live-smoke.yml`, a private-secret presence gate, fixed public `("ECMO"[All Fields])` query, a strict no-network-in-normal-CI regression test, and public-source-safe evidence protocol in `docs/PUBMED_LIVE_VALIDATION.md`.
- GitHub dispatch needs the workflow on the default branch; this proposal cannot be run from an unmerged PR. After owner approval and merge, set `RESEARCHY_NCBI_CONTACT_EMAIL` as a private repository Actions secret and run manually. Optional private `RESEARCHY_NCBI_API_KEY`; never commit either.

## Still outstanding

- AT-06: verified live accepted PubMed translations across representative approved terms and phrases.
- AT-07: controlled actual >10,000-hit complete partition-ID union with disjoint coverage, source drift and unsplittable-day handling.
- AT-09: actual interruption and resumability under live provider conditions; fixtures alone are partial.
- Full source metadata and abstract reconciliation, rights compliance, Web of Science Starter entitlement/pagination (#8), conservative master publication deduplication, Excel export, GUI and Windows installer.

## Next review action

1. Review P1-04e against approved scope. Four required Windows/Linux Actions jobs must pass on its final commit; request Codex code review, wait for 👀 **and completion**, then request security review and verify its `running` and `completed` status for the same head. Resolve substantive findings.
2. Present P1-04e **unmerged** for explicit owner approval.
3. After merge and authorised secret configuration, perform the controlled real-source smoke and record accurate evidence; do not claim anything executed while network/contact requirements are unmet.
