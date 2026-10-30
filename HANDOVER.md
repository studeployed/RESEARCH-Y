# RESEARCH-Y handover — 30 October 2026

## Authority, repository and merged state

- [RESEARCH-Y repository](https://github.com/studeployed/RESEARCH-Y); protected `main`. The version-controlled `RESEARCH-Y_SPEC.md`, version `1.0.0-draft.1`, approved 23 October 2026, remains authoritative and **unchanged**.
- Phase 0 and Phase 1 foundational PRs #10, #12, #13, #15–#22 are merged. P1-04d PubMed EFetch metadata merged in PR #21. P1-04e manual-only live PubMed source smoke merged in PR #22.
- **P1-04f** accepted-query outer-parenthesis correction merged 30 October 2026 in [PR #23](https://github.com/studeployed/RESEARCH-Y/pull/23), commit `19ba4d2de7359d9f814858bd90b7f2b46db171b1`. [Post-merge CI run #41072512871](https://github.com/studeployed/RESEARCH-Y/actions/runs/41072512871) passed all four Windows/Linux × Python 3.12/3.13 jobs. This change preserves exact provider translations and still rejects changed terms, fields and operators.
- Deferred security hardening: [Windows junction issue #11](https://github.com/studeployed/RESEARCH-Y/issues/11) remains open until untrusted project archives/import.

## Completed, offline-tested core

- Independent Python application architecture; portable project folders, recoverable SQLite migrations, immutable approved broad-OR strategy snapshots and PubMed All Fields / Web of Science Starter Topic query compilation.
- PubMed ESearch count/translation, safe bounded PMID retrieval, recursive Create Date partitions, strict unique-ID count reconciliation and fail-closed source-drift handling.
- SQLite atomic page/PMID/audit checkpoints, explicit pause, reopen/resume without automatically repeating committed pages.
- PubMed EFetch XML metadata/abstract parser, source identity, missingness/rights flags, atomic query/source metadata links, metadata-batch recovery.
- Existing smoke workflow is **manual-only** and obtains NCBI contact/key values solely from private GitHub Actions secrets. Ordinary CI remains offline.

## Live-source evidence — 30 October 2026

1. [Run #41066478463](https://github.com/studeployed/RESEARCH-Y/actions/runs/41066478463) reached NCBI but rejected the harmless removal of outer parentheses in the accepted query, before record retrieval; fixed by P1-04f.
2. [Successful run #41073931474](https://github.com/studeployed/RESEARCH-Y/actions/runs/41073931474) on commit `19ba4d2d` submitted `("ECMO"[All Fields])` and received accepted translation `"ECMO"[All Fields]`, with no warnings and **19,479** reported matching records (14:42 UTC). It fetched PMID `42958294` with a matching EFetch bibliographic record, present three-section abstract and a copyright notice flag.
3. This is **one-record acceptance evidence only**. `source_retrieval_verified=false` is correct. The source count is a dated observation, not an immutable expected count. No live >10,000-ID union or external process-restart checkpoint verification has yet been performed.

## Current authorised increment — P1-04g proposal

A separate manual GitHub workflow, `pubmed-live-identifiers.yml`, is being prepared to validate source-reconciled full ID retrieval and deliberate SQLite checkpoint interruption/reopen. The procedure uses a fixed public ECMO query and an explicitly recorded disjoint Create Date coverage window, safe request/size ceilings, NCBI off-peak hours, strict source rechecking and independent stage processes. It will not fetch all ~19,000 metadata records and will not mark complete bibliographic retrieval.

- See `docs/PUBMED_LIVE_IDENTIFIERS.md` for the controlled test protocol and evidence schema.
- Offline tests and four-platform CI, completed current-HEAD Codex code and security reviews, and explicit project-owner authorisation are mandatory before **any merge**.
- The new live workflow cannot be invoked until it is merged onto the GitHub default branch; no live run is yet claimed for this increment.

## Open acceptance gaps and next sequence

- **AT-06:** live single term verified; representative phrase, punctuation and broad OR-group translations remain to verify.
- **AT-07:** >10,000 real source PMIDs and disjoint counted union remain unverified.
- **AT-09:** live pause/reopen/recovery remains unverified; offline fixtures alone are partial.
- **AT-19:** full source-level completion and failure handling remain partial; deliberate incomplete statuses are supported.
- Full metadata reconciliation, large-source drift/unsplittable-day recovery, Web of Science Starter P1-05 (#8), global publication deduplication, Excel outputs, GUI, archives and installer remain future milestones.

**Next action:** Review P1-04g PR and its offline CI/reviews, do not merge without owner approval; after merge, perform its controlled off-peak manual live validation and record the observed result, then proceed to P1-05.
