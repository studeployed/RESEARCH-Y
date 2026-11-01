# RESEARCH-Y handover — P1-05c evidence and P1-06a initiation

## Authority, progression and merged baseline

Repository: https://github.com/studeployed/RESEARCH-Y. The approved version-controlled `RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 remains authoritative and unchanged. Independent Python implementation; no imported assumptions or code from another research project.

**Merged baseline:** PR #28 / P1-05b, commit `a4bb2b308aa96fe4076cde31efef668c23199173`, 1 November 2026. Post-merge test run #41306431736 passed all four Windows/Linux Python 3.12/3.13 configurations. Keep compact test parameter labels and the 15-minute ordinary test-job timeout introduced after the earlier PR #27 reporting defect.

**Standing owner direction, 1 November 2026:** "at each completion step, begin instituting the next step". Follow `CONTRIBUTING.md`: record verified completion and immediately initiate the next ready, in-scope task during active work. Do not repeatedly ask for routine continuation. This is not authority to merge, weaken checks, change the specification, bypass live-retention consent or claim background monitoring. Required approvals and exact-commit reviews remain unchanged.

## Verified live boundaries

- PubMed [run #41235232458](https://github.com/studeployed/RESEARCH-Y/actions/runs/41235232458), 31 October 2026: 19,483 unique identifiers, 43 pages, six disjoint leaves and controlled pause/reopen. Scoped AT-07 and identifier-stage AT-09 evidence passed. Full metadata, broader queries and product-wide completion remain partial. See `docs/evidence/pubmed-41235232458-summary.json`.
- Starter [sample run #41254004073](https://github.com/studeployed/RESEARCH-Y/actions/runs/41254004073), 31 October 2026: actual 5,000/day allowance, 19,574 reported matches and 100 sample records across two pages. Abstract text was not returned in that sample. The original safe sample evidence is in `docs/evidence/wos-starter-41254004073.json`.
- Starter [full-enumeration/recovery run #41306953908](https://github.com/studeployed/RESEARCH-Y/actions/runs/41306953908), 1 November 2026, 12:46 UTC: **19,584 reported and committed records, 392 acquisition pages, 392 verification pages, 786 requests, zero recorded failures/unknown outcomes**. First process paused after 50 records; a separate process resumed. First acquisition page was unchanged and acquired once. Observed quota remaining: 4,214 of 5,000.
- The latter result is `completed_with_warnings` / `enumeration_reconciled=true` / `durable_recovery_tested=true`. It does **not** establish a frozen provider snapshot, full abstracts, live quota-exhaustion/reset, multi-day recovery or full multi-source retrieval. Those flags remain false.
- `docs/WOS_LIVE_ACCEPTANCE.md` records expected/actual outcomes and scoped requirement disposition. `docs/evidence/wos-recovery-41306953908-summary.json` retains the unchanged aggregate audit and checksums. It is not the original page-hash artifact or a record-level independent audit; licensed data and the database were not exported. All 16 aggregate checks were rechecked when preparing this evidence update.

The working **`RESEARCHY_WOS_STARTER_API_KEY`** is already configured. Do not ask for the key in chat, repeat the resolved Elsevier/Clarivate setup, or rerun a live smoke merely to update documentation. No new provider requests are made by P1-05c.

## Existing implementation safeguards

Read `docs/WOS_CHECKPOINTS.md`, `docs/WOS_PROVIDER_GUARDS.md` and the review history in PR #28. Schema v4 provides recoverable upgrades, immutable source plans, journalled attempts, original metadata, query memberships and accession-verification receipts. Atomic commits retain records and their audits. Recovery reopens approved plans and acquires only missing pages; a lost uncommitted response may be refetched with uncertainty recorded. Explicit stopped-worker confirmation and ownership fencing remain required for crash recovery.

Preserve real failure budgets across replayed verification prefixes; preserve Retry-After even on rejected responses; distinguish malformed from missing quota; pause at the smaller client/worker request budget without inventing source failure. Provider cooldowns and observed quota exhaustion apply across the project's Starter jobs, including cancelled/completed jobs. Pause/cancel/recovery cannot erase source-consistency failure reasons. The longest applicable pacing, server delay and exhausted-quota cooldown is binding. No reset time is assumed.

Acquisition can span days in the tested design. **Final identity verification must fit one uninterrupted session and available quota.** Old verification receipts are retained but are not a current frozen snapshot. Count/identity/metadata conflicts remain incomplete. No matching result set is promoted to full abstract enrichment or whole-run completion.

## Current evidence update and next ready work

P1-05c records the scoped live result and updates handover, roadmap and traceability. Broad AT-08/09/19/21 statuses stay **partial**, and parent issue #8 stays open. New offline evidence-regression tests preserve the historical report identity, accounting and limitations; they do not replace live or record-level validation. This documentation/evidence increment requires its own reviewed, owner-approved merge.

**P1-06a initiation:** prepare the first bounded publication-identity/provenance increment under issue #9. Consult DATA-01–06, DUP-01–05, COUNT-01–05 and AT-10/11/19 before implementation. Preserve source records, all source/group/run memberships, separate original/chosen metadata and explicit incomplete states. Define conservative matching and anti-false-merge fixtures before coding; reversible decisions and no container/study conflation are mandatory. This preparatory step is not implemented deduplication. Master counts, initial Excel output and a minimal application flow follow as separate reviewable increments.

Do not let next-stage work hide the open source-acceptance gaps: broader PubMed queries, complete PubMed metadata, live Starter multi-day/quota-reset scenarios and full provider-limit behaviour remain open. Deferred Windows junction issue #11 must be addressed before untrusted archive import/release.

## Review and stop conditions

For every pull request, fetch current HEAD, all four required continuous integration results, code/security summaries, individual receipts and outstanding findings. Verify code review completion on that HEAD before requesting security review unless a valid automatic review already exists. New commits invalidate earlier acceptance. Missing timestamps, mismatched commits or contradictory evidence remain unverified; do not generate duplicate reviews or bypass protections. **Never merge without explicit owner authorisation.**

At an external review/approval blocker, report the exact verified state and the next required action. Continue independent preparation where justified, but do not represent a queued review, a created issue or a proposed pull request as completed functionality.
