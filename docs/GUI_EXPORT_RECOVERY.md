# P1-06e2f — experimental GUI export failure and recovery truthfulness

Date: 2 November 2026. Parent #43 / #41 / #9. Starts from owner-merged
PR #48 (merge commit `2de2e50b07fd27ff8d5fc9ed95344746ca8e2e69`).
RESEARCH-Y_SPEC.md remains authoritative and unchanged. Scope remains the
**previously approved, isolated NiceGUI 3.18.0 / pywebview 6.2.1 feasibility
experiment**; it is not production GUI adoption or installer approval.

## Motivation and scientific integrity

An export is a durable, append-only workbook publication request, not a
successful search. The earlier graphical adapter assigned an export UUID before
the `prepare_export` worker returned. A failed initial preparation therefore
left a selected-but-nonexistent request and could mislead a researcher about
recoverability. A previous successful file observation also remained visible
when a subsequent publication/observation failed. Both were unacceptable
ambiguities at the user-interface boundary (PROJ-04/07, UI-05/10, COUNT-05,
AUDIT-01/03, EXPORT-01/03/04, SEC-05, scoped AT-09/18/19/21).

## Bounded change

- Generate one tentative export UUID privately, without presenting it as a
  committed request. If `prepare_export` fails or its response is lost, read
  the **authoritative stored request inventory** before deciding whether a
  preparation receipt exists. Reuse the same ID when committed; clear it only
  when a validated inventory proves no matching receipt. If that inventory is
  unavailable, retain the tentative ID in memory and block competing run/export
  selection until a safe retry; no fresh ID or success status is invented.
- Preserve the committed export ID if a later inspection or retained-report
  retrieval fails. A retry uses the saved journal, not a new report capture.
- After a previous observation, any new prepare, resume, cancel or observation
  clears the prior file-verification result *before* work starts. A failed
  operation never leaves the old positive observation in the page state.
- Surface the worker's authenticated, fixed error codes (including
  `destination_conflict`, `artifact_changed`, `cancelled` and
  `worker_interrupted`), not paths, traceback text or generic success.
  Reinspect stored export phases after failure when possible; retain the
  last available evidence instead of inventing a new state.
- Expose real recorded export phases and latest journal error; offer a
  cancellation button only for the pending phases. Cancellation calls the
  existing auditable service and never deletes a file or rewrites another
  request. A cancelled item remains available for explicit selection and
  observation after restart; no Resume control is shown for cancelled items.
- Keep the same trusted host-path policy and guarded loopback boundary.
  No browser-controlled project path, output directory, run UUID or export
  UUID is added. No new dependencies, credentials, external calls or data
  model are introduced.

## Objective verification

The offline tests use genuine on-disk projects and the existing supervised
worker. They check a pre-existing destination file (no overwrite, ghost UUID
or journal receipt), a deliberately lost response after a committed preparation,
an unavailable reconciliation inspection, two concurrent Prepare calls, a
previously verified workbook that is externally altered or removed, and an
audited cancellation followed by reopening the original request.

The existing four-platform graphical lifecycle workflow additionally drives
a cancellation through both the actual local request transport and Windows
native-button interactions, checks the **recorded_cancelled** outcome with
`audited_success=False`, verifies no output workbook exists, then closes and
reopens the GUI and checks the original UUID and journal event count.
Previous positive publication/relocation scenarios remain mandatory.

A green workflow proves only the explicitly asserted scenarios. A final pass
must be based on the actual new HEAD commit, required core/dependency/lifecycle
jobs, completed Codex code and security reviews with matching receipts, and
the disposition of all review findings. Never merge without project-owner
authorization.

## Explicit remaining work

Actual process termination during a database/renderer/file operation; injected
disk-full and permission failures through live native UI; recovery when an
output file is visible but its final receipt is absent; external destination
re-selection; native folder picker/recent projects; adversarial multi-session
reconnection; completion of dependency/licence/source-build review; packaged
offline Windows installation; and the representative 100,000-record
responsiveness gate. No source retrieval, master-results view or complete
product acceptance is claimed by this increment.
