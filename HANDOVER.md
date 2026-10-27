# RESEARCH-Y handover — 27 October 2026

## Authority and merged baseline

- Public repository: https://github.com/studeployed/RESEARCH-Y; protected main and four required Windows/Linux Python 3.12/3.13 tests.
- The version-controlled RESEARCH-Y_SPEC.md v1.0.0-draft.1 remains authoritative. No requirement amendments.
- Merged PRs #10, #12, #13, #15, #16, #17, #18, #19, #20. PR #20 merged 27 October 2026 as 1e22f3fa4dea933b0bb2f207aef2d468ee857fd5; post-merge run 40428051895 passed all four jobs, 282 tests per job. Final Codex code/security reviews were clear.
- Phase 1 P1-04d proposes EFetch metadata, branch feat/p1-04d-pubmed-efetch-metadata. This new increment is NOT merged; explicit project-owner approval is mandatory.

## P1-04d proposed functionality

- Bounded PubMed EFetch XML client sharing the existing HTTPS-only, redirect-rejecting, rate-paced runtime NCBI contact/API-key configuration.
- Strict per-batch PMID identity checks; parsed source fields, multi-section abstracts, authors/affiliations, journal, DOI/PMCID, languages, publication types and MeSH indexing, without adding MeSH to queries.
- Source retrieval and query membership linked only to validated checkpoint PMIDs. Each batch, links and audit persist atomically. Equivalent retries are idempotent; conflicting metadata requires review. Missing metadata resumes after reopen.
- Missing abstracts are labelled as not supplied; original copyright notice and abstract redistribution-rights review flag are retained.
- A private-contact opt-in smoke diagnostic probes actual accepted PubMed query translation and fetches one PMID. It has NOT been executed against live NCBI in this environment.
- Local isolated offline suite for the new components: 35 tests passed against lightweight project/checkpoint stubs; complete repository CI and independent Codex code/security reviews must still run on the actual feature-branch head.

## Limits and next action

- No final source is marked completed_verified. PubMed AT-06, AT-07, AT-09 and AT-19 remain partial/unverified; real NCBI ESearch/EFetch, full metadata reconciliation, changing source snapshots, single-day overflow, Web of Science, conservative deduplication, Excel, GUI and Windows packaging remain future work.
- Post current-head Windows/Linux GitHub Actions, obtain completed code review THEN security review (confirm eyes acknowledgement AND running/completed on the exact head), resolve substantive findings, and present the unmerged PR for owner approval.
- Existing Windows junction security issue #11 remains deferred until untrusted archive import or release.
