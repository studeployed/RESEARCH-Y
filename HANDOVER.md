# RESEARCH-Y handover — PR #31 merged; P1-06a identity implementation

## Authority and baseline

Repository: https://github.com/studeployed/RESEARCH-Y. The approved version-controlled
`RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 remains authoritative and unchanged.
Independent Python implementation; no assumptions or code from another research project.

**Merged baseline:** PR #31, commit `90ae817b69d2d85ee9aab14bde7f5d83f557f0db`,
1 November 2026 at 15:20 UTC. Its post-merge run #41320722923 passed all four
Windows/Linux Python 3.12/3.13 configurations. This establishes the baseline, not
acceptance of the new identity modules. PR #29's evidence/traceability and bounded
Windows test-timeout/reporting changes are included.

**Standing owner direction, 1 November 2026:** "at each completion step, begin
instituting the next step". During active work, initiate the next ready in-scope
task without another routine continuation prompt. This does not authorise merging,
scope changes, waived tests, live-retention consent or background monitoring.

## Current increment — P1-06a, implementation for review

Read `docs/PUBLICATION_IDENTITY.md`; parent issues #30 and #9. The new modules
`publication_identity.py` and `publication_fields.py` use the existing schema-v4
publication/source associations and append-only audit. No schema migration, dependency,
source call, credential change or workflow change is introduced.

Implemented: idempotent provisional identity creation, consistent source/group/run
projections, explicit researcher-confirmed retrieval reassociation with stale-review
guards, append-only reversal and readable decision history, and source-backed chosen
fields with separate provenance. Empty retained identities are inactive. Equal
identifiers/titles/containers never automatically merge records. Source metadata,
missingness/rights, memberships, reported counts and source/run status stay unchanged.

Field choices retain references rather than duplicate licensed text. A chosen field
must be cleared before its contributing retrieval is reassociated. Specialist
annotations block reassociation until a later annotation-aware merge/split workflow
can disposition them. Unsupported existing provenance fails closed. Returned fields
are not redistribution permissions or verified unique-publication counts.

Local targeted verification: 62 disk-backed cases passed, including separate-process
concurrency and abrupt-exit rollback, with ResourceWarning treated as errors and
92% combined branch-aware new-module coverage. Baseline project/schema modules were
reconstructed and Git-blob-hash verified; this was not a full repository checkout.
All four full-suite configurations and completed exact-HEAD code/security reviews
remain required before merge advice. Do not call review-branch work merged/accepted.

**Next ready step:** P1-06b candidate generation/explicit match-rejection evidence,
then annotation-aware decisions, reconciled master counts, genuine Excel export and
minimal application flow. Start with fixtures for identifier and bibliographic
conflicts, container/abstract separation, repeated runs and prior confirmed/rejected
decisions. No unvalidated fuzzy/automatic threshold. The current increment is not
full deduplication, automatic propagation across runs, or a completed interface.

## Verified live boundaries — unchanged

PubMed run #41235232458 (31 October 2026): 19,483 unique identifiers, 43 pages, six
disjoint leaves and controlled pause/reopen. Scoped AT-07/identifier-stage AT-09
passed; full metadata, broader queries/failures and whole-product acceptance remain
partial. See `docs/evidence/pubmed-41235232458-summary.json`.

Starter sample run #41254004073 (31 October 2026): observed 5,000/day allowance,
19,574 reported matches, two adjacent 50-record pages; abstract text not returned.
Starter full-enumeration/recovery run #41306953908 (1 November 2026 at 12:46 UTC):
19,584 reported/committed records, 392 acquisition and 392 verification pages,
786 requests, zero recorded failures/unknown outcomes. A second process resumed
after 50 records; first acquisition page unchanged/acquired once; quota remaining
4,214/5,000. `completed_with_warnings` / `enumeration_reconciled=true` /
`durable_recovery_tested=true` are scoped observations, not frozen-snapshot, full
abstract, live quota-reset, multi-day or whole-source/product acceptance.

`docs/WOS_LIVE_ACCEPTANCE.md` and the retained aggregate audit preserve evidence and
limitations. Exported aggregate/hash evidence is not an independent record-level
audit. Source issues #7/#8 and broad AT-08/09/19/21 remain open where applicable.
The working `RESEARCHY_WOS_STARTER_API_KEY` is configured; do not request it in chat
or repeat live access tests simply to update documentation.

## Existing safeguards

PR #31 made new-project schema/header/identity/audit creation one transaction without
disabling journalling or synchronous writes. Read `docs/PROJECT_INITIALISATION.md`.
Its isolated Linux benchmark is not a Windows/full-suite performance guarantee.

Preserve schema-v4 backup/upgrade atomicity, immutable source plans and payloads,
query memberships, request journalling, worker fencing and explicit stopped-worker
confirmation. Acquire only missing committed pages; record uncertain lost responses.
Preserve real failure budgets, malformed/missing quota distinctions, Retry-After,
project-wide provider restrictions and the longest applicable delay. Local session
budgets are normal pauses, not source failures. Never guess a quota-reset time.

Final Starter identity verification must fit one uninterrupted session/available
quota; older receipts do not prove an atomic snapshot. Count/identity/metadata
conflicts remain incomplete. Keep the complete offline test suite, four required
check names, compact test labels, verbose/short-trace reporting and current bounded
30-minute Windows/15-minute Linux budgets. Deferred Windows junction issue #11 must
be addressed before untrusted archive import/release.

## Review and approvals

Before merge advice, retrieve current HEAD, required checks, code/security summaries,
individual receipts and all findings. Verify exact-HEAD code completion before
requesting security review unless a valid automatic review already exists. Do not
duplicate running reviews. New commits invalidate older acceptance. Missing timestamps,
mismatched commits or contradictory evidence remain unverified. Never merge without
explicit owner authorisation. At a review/approval blocker report the verified state;
independent preparation is allowed, not claims of asynchronous monitoring.
