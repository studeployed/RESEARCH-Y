# RESEARCH-Y handover — 27 October 2026

## Repository authority and merged status

- Public repository: https://github.com/studeployed/RESEARCH-Y, protected `main`.
- Authoritative specification: `RESEARCH-Y_SPEC.md` version `1.0.0-draft.1`, approved 23 October 2026; **unchanged**.
- Merged PRs: #10, #12, #13, #15, #16, #17, #18, #19, #20 and **[#21](https://github.com/studeployed/RESEARCH-Y/pull/21)** on 27 October 2026, commit `a91af6ee2217b27e8a73e7f46c05c59d901d2ba0`.
- [PR #21 post-merge Actions](https://github.com/studeployed/RESEARCH-Y/actions/runs/40506608637): all four Windows/Linux × Python 3.12/3.13 jobs passed, 321 tests per job. Security review of the PR final head found no issues; prior code review's five findings were fixed, threads resolved. A further code-review request was made because previous final-head completion evidence was ambiguous; that request stalled.
- **Merged:** P1-04e PR #22 on 27 October 2026 (`bafdc073dadbc33acc0af4534102b1c0b7f48c19`) introduced a manually triggered real PubMed acceptance workflow. Post-merge checks passed all four jobs.
- Independent issue [#11](https://github.com/studeployed/RESEARCH-Y/issues/11): deferred Windows junction hardening before untrusted archives/release.

## Completed in merged implementation

- Portable local projects, versioned SQLite schemas with recoverable migrations, immutable approved broad-OR strategy snapshots and exact query compilation for PubMed All Fields and WoS Starter Topic.
- PubMed ESearch count and accepted-translation probe, bounded identifier pages, recursively partitioned disjoint Create Date intervals, strict counted unique-PMID union and durable page checkpoints with pause/reopen recovery.
- PubMed EFetch metadata/abstract XML parser and original source-retrieval/link persistence, explicit missingness and source rights flags, bounded/credential-safe HTTP transport, and incomplete metadata-batch recovery.
- Source-wide final completion status is **not** claimed from counted/identifier-only responses or a single EFetch response.

## Live-source verification baseline

- The P1-04e manual workflow is already on main; a real NCBI ESearch response was received on 30 October 2026 (see next section). No real PMID page or EFetch record has yet passed the smoke workflow.
- The live workflow uses a deliberately generic fixed query; ordinary CI runs remain offline. Credentials are provided separately in GitHub Actions repository secrets and are not committed.
## P1-04f — First real ESearch failure and proposed correction

On 30 October 2026, [manual run #41066478463](https://github.com/studeployed/RESEARCH-Y/actions/runs/41066478463) contacted NCBI successfully. PubMed accepted the fixed query '("ECMO"[All Fields])' as '"ECMO"[All Fields]' with no warnings. The client incorrectly required identical parentheses and exited query_review_required (3) before ID or EFetch retrieval; the source count was not printed.

P1-04f proposes a shared, conservative whole-expression outer-parenthesis equivalence check in count probes, ID pages, and checkpoint persistence/reopen. Raw NCBI translations stay unchanged; other field, term or operator differences remain review-required. Offline tests and exact-HEAD code/security review are required; no live acceptance is claimed until a new manual run after merge.

## Still outstanding

- AT-06: verified live accepted PubMed translations across representative approved terms and phrases.
- AT-07: controlled actual >10,000-hit complete partition-ID union with disjoint coverage, source drift and unsplittable-day handling.
- AT-09: actual interruption and resumability under live provider conditions; fixtures alone are partial.
- Full source metadata and abstract reconciliation, rights compliance, Web of Science Starter entitlement/pagination (#8), conservative master publication deduplication, Excel export, GUI and Windows installer.

## Next review action

1. Verify cross-platform CI for P1-04f on its final HEAD and obtain completed commit-specific Codex code and security reviews, resolving material findings. Do not merge without explicit owner authorisation.
2. After merge, rerun the P1-04e manual workflow and record the accepted translation, NCBI reported count, one PMID page and EFetch metadata or explicit failure.
3. Continue full AT-06/07/09 source acceptance without conflating one-record smoke evidence with complete retrieval. Next planned connector is P1-05 Web of Science Starter.
