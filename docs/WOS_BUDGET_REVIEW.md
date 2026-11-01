# P1-05b: local request budgets are session boundaries

This amendment addresses PR #28 review comment 4435128702 on commit
`8cb6fcd81d5852d09f10648d026d65219e22306d`. It implements existing
RESEARCH-Y_SPEC.md requirements SRC-06 and RUN-02/03/04/06. No approved
requirements, schema, credentials, query breadth or workflow limits change.

## Cause and narrow correction

The Starter client defaults to three requests while the checkpoint worker
defaults to 1,000. Previously the worker checked only its own limit, reserved
another request, and classified the client's unsent `request_budget_exhausted`
exception as a source failure. Ordinary resumption then required an unrelated
quota-revalidation override, and repeated attempts could exhaust the source
failure budget despite successful provider responses.

`WoSStarterClient.requests_remaining` now exposes the remaining **local**
allowance read-only. It is not the provider's daily quota or permission to
retry. The worker computes the smaller of its configured session maximum and
the fresh client's remaining allowance, then uses that ceiling for its existing
pre-request pause check. The resume probe consumes one unit as before.

On a local ceiling, the worker persists `paused` / `session_budget_reached`,
releases ownership, preserves committed pages, and does not reserve an unsent
request or increment source failures. Existing real failures are not erased.
The client hard guard and both default limits are unchanged. Provider quota,
Retry-After, authentication errors, cancellation and completed status retain
their existing precedence; no provider error is broadly converted into a pause.

Normal resume with a fresh client is sufficient after the saved pacing delay.
If the verification sweep cannot fit the available session budget it remains
paused, not verified: choose an explicit adequate budget for that later session.
The independent single-session verification requirement is unchanged, and
previously acquired pages are not downloaded again as acquisition work.

## Regression coverage and evidence boundaries

`tests/test_wos_budget_regressions.py` adds 25 offline cases using the existing
real project/database/client fixtures and a synthetic provider. They cover
both budget orderings, the actual defaults, repeated pauses and ordinary
reopen/resume, probe-only sessions, persisted failure counts, exact completion
boundaries, real HTTP 401/429/503, actual quota exhaustion, Retry-After,
cancellation, the read-only allowance and unchanged transport hard limit.
No test uses real credentials or contacts Clarivate.

Before publishing, both original source files were reconstructed locally and
matched their exact repository Git blob hashes. An isolated execution of the
actual worker function with storage/transport test doubles reproduced the
original three-sent/four-reserved false failure; 34 patched control-flow cases
passed. Syntax compilation passed for both amended modules and the new tests.
These are **isolated control-flow checks**, not full database integration or
cross-platform acceptance. The 25 real-fixture cases and full repository suite
must pass in the amended-commit Linux/Windows continuous integration run.

Completed code and security reviews must cover the amended commit; prior
commit reviews do not clear it. Live full-source retrieval/recovery remains a
separate, consent-gated post-merge acceptance task. No merge is authorised by
this amendment.
