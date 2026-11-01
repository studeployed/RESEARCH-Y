# RESEARCH-Y handover — PR #29 merged; database initialisation correction

## Authority, progression and merged baseline

Repository: https://github.com/studeployed/RESEARCH-Y. The approved version-controlled `RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 remains authoritative and unchanged. Independent Python implementation; no imported assumptions or code from another research project.

**Merged baseline:** PR #29 / P1-05c, commit `5b7ca06def03dff748c97231c5b70fcf07cb4711`, merged 1 November 2026 at 14:53 UTC. Its exact-HEAD pre-merge run #41316526667 passed all four Windows/Linux Python 3.12/3.13 checks, and both reviews completed with matching receipts. Those passes do not validate the new correction described below.

**Standing owner direction, 1 November 2026:** "at each completion step, begin instituting the next step". Follow `CONTRIBUTING.md`: record verified completion and immediately initiate the next ready, in-scope task during active work. Do not repeatedly ask for routine continuation. This is not authority to merge, weaken checks, change the specification, bypass live-retention consent or claim background monitoring. Required approvals and exact-commit reviews remain unchanged.

## Current focused correction — before extending P1-06a

The database-initialisation correction is implemented on a separate review branch based on merged PR #29. Read `docs/PROJECT_INITIALISATION.md`. `_create_database` now starts `BEGIN IMMEDIATE` inside its initial script so schema, header values, identity and audit share one commit. It does not disable journalling/synchronous writes or alter schema version, existing migrations, queries, retries, timeouts, dependencies or credentials.

The 16 new disk-backed regression cases in `tests/test_project_initialisation.py` reproduced 13 failures on the old code and pass locally after the correction, including injected schema/header/insert/commit failures, public cleanup/retry, unchanged logical contents and an abruptly exited child with a rollback journal. Source modules were hash-verified; local verification is a focused reconstruction, not a full checkout. Full Windows/Linux tests and completed exact-HEAD code/security reviews remain required. The isolated Linux creation benchmark is not a Windows/full-suite speedup or AT-22 acceptance claim.

Once this bounded correction is verified, proceed directly with publication identity/provenance in **issue #30**, under #9. The first operation must preserve immutable source evidence and every source/group/run membership. It must not silently merge uncertain cross-source records, treat a container identifier as an abstract identifier, or turn partial retrieval into completed-source status. No deduplication or master-results implementation is claimed by this correction.

## Verified live boundaries

- PubMed [run #41235232458](https://github.com/studeployed/RESEARCH-Y/actions/runs/41235232458), 31 October 2026: 19,483 unique identifiers, 43 pages, six disjoint leaves and controlled pause/reopen. Scoped AT-07 and identifier-stage AT-09 evidence passed. Full metadata, broader queries and product-wide completion remain partial. See `docs/evidence/pubmed-41235232458-summary.json`.
- Starter [sample run #41254004073](https://github.com/studeployed/RESEARCH-Y/actions/runs/41254004073), 31 October 2026: actual 5,000/day allowance, 19,574 reported matches and 100 sample records across two pages. Abstract text was not returned in that sample. Safe sample evidence is in `docs/evidence/wos-starter-41254004073.json`.
- Starter [full-enumeration/recovery run #41306953908](https://github.com/studeployed/RESEARCH-Y/actions/runs/41306953908), 1 November 2026 at 12:46 UTC: **19,584 reported and committed records, 392 acquisition pages, 392 verification pages, 786 requests, zero recorded failures/unknown outcomes**. A separate process resumed after the first 50 records; first acquisition page unchanged and acquired once. Remaining quota: 4,214 of 5,000.
- That result is `completed_with_warnings` / `enumeration_reconciled=true` / `durable_recovery_tested=true`, not a frozen snapshot, full abstracts, live quota reset, multi-day recovery or full multi-source retrieval.
- `docs/WOS_LIVE_ACCEPTANCE.md` records expected/actual outcomes and scoped requirement disposition. `docs/evidence/wos-recovery-41306953908-summary.json` retains the aggregate audit and checksums, not the original page-hash artifact or licensed record dataset. Its 16 aggregate checks are not a record-level independent audit.

The working **`RESEARCHY_WOS_STARTER_API_KEY`** is configured. Do not ask for it in chat, repeat the resolved provider setup, or rerun a live smoke merely to update documentation. This correction makes no live provider requests. Broad AT-08/09/19/21 and parent issues #7/#8 remain open where evidence is outstanding.

## Existing implementation safeguards

Read `docs/WOS_CHECKPOINTS.md`, `docs/WOS_PROVIDER_GUARDS.md` and PR #28. Schema v4 provides recoverable upgrades, immutable source plans, journalled attempts, original metadata, query memberships and accession-verification receipts. Atomic commits retain records and audits. Recovery acquires only missing pages; a lost uncommitted response may be refetched with uncertainty recorded. Explicit stopped-worker confirmation and ownership fencing remain required after a crash.

Preserve real failure budgets across replayed verification prefixes and Retry-After even on rejected responses. Distinguish malformed from missing quota. Pause at the smaller client/worker request budget without inventing source failure. Provider cooldowns and observed quota exhaustion apply across the project's Starter jobs, including cancelled/completed jobs. Pause/cancel/recovery cannot erase source-consistency failures. The longest applicable delay remains binding; no reset time is assumed.

Acquisition can span days in the fixture-tested design. **Final identity verification must fit one uninterrupted session and available quota.** Old receipts are not a current frozen snapshot. Count/identity/metadata conflicts remain incomplete. Master counts, initial Excel output and a minimal application flow remain separate P1-06 increments after identity/provenance and conservative decisions. Deferred Windows junction issue #11 must be addressed before untrusted archive import/release.

## Historical Windows runtime incident

PR #29's original run #41309516675 cancelled both Windows jobs at the former 15-minute boundary: 569 passed/1 skipped on Python 3.12; 517 passed/1 skipped on 3.13. No failed assertion was recorded, and all six new evidence tests passed. The merged workflow now allows 30 minutes on Windows and 15 on Linux, with full discovery/coverage, verbose progress, short tracebacks and the 20 slowest durations. Keep compact parameter labels. Required check names, permissions and offline-only execution are unchanged.

The subsequent exact-HEAD run #41316526667 passed; Windows test steps took 10m37s and 12m46s. The timeout amendment was containment, not a performance fix. The current initialisation correction targets a demonstrated source of repeated durable writes, without claiming it explains every runner slowdown.

## Review and stop conditions

For every pull request, fetch current HEAD, all four required continuous integration results, code/security summaries, individual receipts and outstanding findings. Verify code completion before requesting security review unless a valid automatic review exists. New commits invalidate earlier acceptance. Missing timestamps, mismatched commits or contradictory evidence remain unverified. Do not request duplicates or bypass protections. **Never merge without explicit owner authorisation.**

At an external review/approval blocker, report the exact verified state and required action. Continue independent preparation where justified, but do not represent a queued review, issue or proposed pull request as completed functionality.
