# P1-05b: provider restrictions and terminal failures survive user controls

This amendment to PR #28 addresses review comments 4435369198,
4435418627 and 4435418629 on `738bdb1c935ae6504e56d9db7bb8d53b28ca5598`.
It implements existing SRC-05/06/08 and RUN-02/04/05/06 requirements.
No specification, schema, credential, dependency or workflow change is made.

## Project-wide provider gate

Before claiming a Starter worker, the same database transaction now checks
all persisted Starter deadlines in the project, including deadlines retained
by cancelled and completed queries. The longest deadline wins. A fresh client,
another group/query, explicit revalidation or cancelling the original query
cannot shorten it. This conservatively shares pacing and backoff as well as
Retry-After across the project's Starter jobs; no credential is stored to
partition or bypass the guard.

After that deadline, a recorded exhausted quota still requires explicit
revalidation. The existing immutable request journal supplies this evidence:
a later failed or unknown quota observation does not prove a reset. Only a
later successful response carrying observed usable quota releases the shared
exhaustion restriction. An untouched query receives an auditable provider-hold
pause without reserving a request. Existing query-specific failure reasons
are not overwritten by the shared gate.

This is a per-project coordination rule, not a claim of a global lock across
separate projects, computers or external programs using the same account.
Those can still consume provider allowance; returned quotas remain authoritative.

## Preserve blocking source failures

User pause is a no-op for an already-incomplete checkpoint or a checkpoint
with a blocking source-consistency reason, including a failure received while
an in-flight request was being paused. Cancellation remains terminal but keeps
the underlying failure reason. Explicit stopped-worker recovery releases stale
ownership without erasing a known failure. The claim guard uses the same
blocking-reason predicate; count drift, identity drift, duplicate accessions,
conflicting metadata and exhausted failure budgets cannot be cleared by a
pause/recovery/revalidation sequence. A genuinely interrupted request still
retains its unknown-outcome handling.

## Longest quota and server delay

For a successful response with zero daily allowance, the response transaction
now saves the maximum of request pacing, Retry-After and the existing
3,600-second exhausted-quota probe cooldown. This happens before any subsequent
pause, cancellation or final-completion branch can skip the loop's quota check.
A short Retry-After cannot reduce that cooldown; a longer one is preserved.
The hour is a conservative revalidation delay, not an assumed daily reset.

A genuinely reconciled final response can remain completed while preserving
its quota restriction for other queries. A successful transport response never
changes the established limits on source completeness or abstract enrichment.

## Regression evidence

`tests/test_wos_provider_guard_regressions.py` adds 32 offline cases. They use
the repository's existing project/database/client fixtures in continuous
integration and synthetic provider responses only. Coverage includes cross-query
successful/error/malformed/credential-echo Retry-After responses, cancellation,
completion, ordinary pacing, short and long exhausted-quota delays, failed and
successful quota revalidation, and pause/recovery/cancel after each source
consistency failure. No private credentials or live source calls are used.

Locally, the actual store, runner, parser, client and checkpoint schema were
reconstructed and verified against their repository Git blob hashes. An isolated
SQLite harness with simplified project initialization reproduced 31 failures
in these 32 cases on the old store/runner; all 32 pass with the correction.
This harness does not test the full application project/migration layer. The
unchanged repository fixtures, complete Linux/Windows test matrix, and completed
code/security reviews must validate the amended commit before merge clearance.
