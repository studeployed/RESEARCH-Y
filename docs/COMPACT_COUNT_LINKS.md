# P1-06k4j — Compact validated count-link witnesses at 100,000 original sources

**Baseline:** owner-merged pull request (PR) #93, main merge commit `7820a554bce5f7b2923a93fd9e4ec591c8852f9e` on 11 November 2026. **Authority:** unchanged repository `RESEARCH-Y_SPEC.md`. This is a bounded Phase 1 original count/performance optimisation under parent #9/#35/#41/#43, with partial COUNT-01/02, DUP-01/04, AUDIT-01, AT-10/17/19/21/22 evidence.

## Problem and the prior evidence

PRs #91–93 validated real original SQLite fixtures containing **100,000 source retrievals, 100,000 query/group memberships and 100,000 individually audited *provisional* publication identity links**. PR #93's final same-run Linux acceptance benchmark observed approximately **607 MiB peak parent memory**, **7.71 seconds for full-run count projection**, and **8.62 seconds for its first provisional results page**. These are independent hosted-runner observations; they are not reproducible product-level latency or memory guarantees.

The existing full-run count path still retained **every original identity association's complete audit-event dict** in a separate `links` map, despite the count arithmetic only needing its validated **publication identifier** and **decision status**. The original full event, its positive audit event ID and current source/group membership remain necessary while computing the exact canonical publication revision, but are **not** used by the final group, unmaterialised-source or review-required count calculations.

## Bounded implementation

- The original `publication_identity._link` (small runs) and `publication_identity._link_from_evidence` (large streamed runs) still read and fully validate original source SHA-256, publication linkage, original audit event type/ID/time, pointer version, decision status, and recorded source state. Existing SQLite transaction and foreign-key guards are unchanged.
- In the **read-only count projection only**, replace the retained three-part link tuple `(publication_id, original_event_id, full_audit_event_dict)` with a frozen, two-field `_ValidatedCountLink(publication_id, status)` (a tuple-compatible named witness). The witness is created **after** full original verification and cannot be forged by the graphical client, user-supplied evidence or a cross-run comparison.
- In high-cardinality singleton revision calculation, the **original full validated link** remains locally available until the source dictionary with its complete `association_event_id`, `decision`, and original query/group memberships has been passed through the **unchanged canonical SHA-256 revision builder**. Complex/multi-source and selected-field publications still pass through the full original `identity._snapshot` validator.
- The original count projection changes only its final review-required status check to read `link.status` from a previously validated witness. The group publication union uses the original publication identifier unchanged.
- Source record storage, original association/audit records, query compilation, identity rules, chosen metadata, provider retrieval, checkpointing, user consent, export, result-field projection, graphical controls, source schemas and dependencies are not modified. No cache is introduced, no validation is skipped, and an audit-corrupt source cannot become an apparent unlinked/missing record.

## Verification

Existing tests cover same-publication/group memberships, cross-run associations, reversals, chosen-field evidence and malformed pointers. New tests explicitly compare both witness fields with independent canonical original `_link` reads after an authorised `confirmed_match`, including three separately retained originals and reviewer-required statuses; verify the complete count and SHA-256 projection exactly match the unchanged canonical small-run path; and reject a tampered original link event with no project mutation.

The existing fully materialised 512-source fixture now asserts **all 512 witnesses** retain exactly two immutable fields, all current provisional identities have their exact original revision and status, and the original SQLite project is unchanged after reopening. The full four-platform Python test matrix plus original 100,000-source, audited identity, supervised worker, native Windows graphical and Linux guarded-transport acceptance workflows are required before any merge advice. Compare observed timing/parent memory against PR #93 final-commit evidence; performance improvement is **not** assumed from the representation alone.

## Explicit limits and merge gate

A total of 100,000 **independent provisional identity links** is not proof of 100,000 truly distinct biomedical publications. Neither automatic deduplication, verified source retrieval, entire-run exported master data, category filters, complete user-interface usability, combined host-plus-worker memory, nor full AT-22 acceptance is established. As before: `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false`, and `full_AT_22_acceptance=false`.

For every HEAD, require four Windows/Linux Python 3.12/3.13 test jobs and relevant original 100,000-row/graphical and recovery workflows. Confirm definitive completed Codex **code review first** and **security review second** for the exact HEAD; inspect both the review summary and individual findings. Never recommend merging while a mandatory gate is unverified, and never merge without explicit project-owner authorisation.
