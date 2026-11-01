# RESEARCH-Y handover — PR #32 merged; bounded P1-06b candidate review

## Authority and verified baseline

The repository `RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 remains authoritative and
unchanged. Independent Python implementation; no imported project assumptions.

**Merged baseline:** PR #32, commit `87f6d087b6273ccaf2377179113380664e2a2568`,
1 November 2026 at 16:04 UTC. Its post-merge run #41324431002 completed successfully.
The baseline includes PR #31 atomic project initialisation and P1-06a publication
identities, reversible retrieval associations and source-backed field choices.
Read `docs/PUBLICATION_IDENTITY.md` and `docs/PUBLICATION_RUN_STATUS.md`: parent-run
status and query status both affect review revisions, without changing source hashes.

**Standing owner direction:** "at each completion step, begin instituting the next
step". Initiate the next ready in-scope task during active work without another
routine prompt. This does not authorise merging, scope changes, waived tests,
live-retention consent or claims of asynchronous monitoring.

## Current implementation for review — first bounded P1-06b increment

Read `docs/PUBLICATION_CANDIDATES.md`; parent #33 under #9. New modules
`publication_match_evidence.py` and `publication_candidates.py` provide read-only
explicit-pair comparisons, an intentionally bounded 2–32 retrieval candidate batch,
and immutable confirmed-match/rejection receipts. Missing or contradictory values
never silently agree. Identifiers are source-reported, not registration-verified;
container scope stays unverified. No automatic matching threshold is enabled.

Confirmed decisions reuse the existing retrieval association guards via a shared
caller-owned transaction helper. Identity/link/receipt writes are atomic. Rejection
never splits an already combined identity. Exact current retries are no-ops; changed
context, new relevant receipts or reversals require fresh review. Previous-run
namespaced source-pair decisions are visible but never automatically propagated.
Source records, all source/group/run memberships, rights, reported counts and statuses
remain unchanged. Receipts contain generated comparison paths/hashes rather than
copied titles or abstracts; researcher actor/evidence remain explicit assertions.

81 targeted disk-backed local cases pass, with 97% rounded combined branch-aware
coverage of the two new modules; four intentional negative mutations were caught.
This used seven hash-verified reconstructed baseline modules, not a full checkout
or Windows run. Full repository checks and exact-commit reviews remain outstanding
until actually verified; no merge is authorised. No new dependency, schema change,
provider request, credential or workflow change was needed.

## Next ready work

Prepare P1-06c reconciled count projections: source denominators versus group unions
and global identity unions; unmaterialised/unreviewed records must stay visible;
provisional identity counts must not be labelled verified unique-publication counts.
Define queryless records, repeated groups/runs, inactive retained identities,
confirmed associations/reversals and partial-source fixtures before implementation.

Keep #33 open for indexed project-wide candidate discovery, large-history performance,
validated automatic rules and fuller rerun decision propagation. Annotation-aware
publication-wide merge/split, genuine Excel export and the minimal application flow
remain separately reviewed work. A prepared issue is not implemented functionality.

## Verified live boundaries — unchanged

PubMed run #41235232458 (31 October 2026): 19,483 unique identifiers, 43 pages, six
disjoint leaves and controlled pause/reopen. Scoped AT-07/identifier-stage AT-09
passed; full metadata, broader queries/failures and whole-product acceptance remain
partial. See `docs/evidence/pubmed-41235232458-summary.json`.

Starter sample run #41254004073: observed 5,000/day allowance, 19,574 reported matches,
two adjacent 50-record pages, no returned abstracts. Full-enumeration/recovery run
#41306953908 (1 November 2026 at 12:46 UTC): 19,584 reported/committed records, 392
acquisition and 392 verification pages, 786 requests, zero recorded failures/unknown
outcomes. Separate-process restart preserved the first page; 4,214/5,000 quota remained.
`completed_with_warnings`, `enumeration_reconciled=true` and `durable_recovery_tested=true`
are scoped observations, not frozen-snapshot, complete abstracts, live quota-reset,
multi-day or whole-product acceptance. Exported aggregate/hash evidence is not an
independent record-level audit. Read `docs/WOS_LIVE_ACCEPTANCE.md`.

Source issues #7/#8 and broad AT-08/09/19/21 remain partial where evidence is outstanding.
The working `RESEARCHY_WOS_STARTER_API_KEY` is configured; do not request it in chat
or rerun source access just to update documentation.

## Preserved safeguards

Retain transactional project creation, recoverable schema-v4 upgrades, full durability,
immutable source plans/payloads, query memberships, request journalling, worker fencing
and explicit stopped-worker confirmation. Acquire only missing committed pages; record
uncertain lost responses. Preserve failure budgets, malformed/missing quota distinctions,
Retry-After, project-wide restrictions and the longest applicable delay. Local session
budgets are normal pauses; never guess a quota-reset time. Final Starter verification
must fit one uninterrupted session/available quota; conflicts stay incomplete.

Keep all four full-suite check names, compact test labels, verbose/short-trace reporting,
and bounded 30-minute Windows/15-minute Linux jobs. Isolated database benchmarks are not
whole-application performance acceptance. Windows junction issue #11 remains a release
blocker before untrusted archive import.

## Review and approvals

Retrieve current HEAD, required checks, code/security summaries, individual receipts
and all findings before merge advice. Verify exact-HEAD code completion first, then
request security review unless a valid automatic one exists. Do not duplicate reviews.
Any new commit invalidates previous acceptance. Missing timestamps, mismatched commits
or contradictory evidence remain unverified. Never merge without explicit owner approval.
At an external review/approval blocker, report the verified state and next action.
