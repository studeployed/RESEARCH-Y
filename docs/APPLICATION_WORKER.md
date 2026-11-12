# P1-06e2a — Supervised local operations

Parent #43 / #41 / #9. This is the framework-independent worker part of the
minimal application, NOT the graphical user interface (GUI), a launcher or an
installer. The repository specification is unchanged. Initial parent is merged
PR #42, `bc4666fa7aaefe8082ad7ea21a1918f0ac4187f1`.

## Contract

### Inspect a provisional workbook (P1-06l7, issue #9)

For a project already opened by the trusted host and a known manifest export
UUID, submit `ApplicationCommand.for_project(project, "inspect_manifest_publication",
export_id=export_id)` through the worker. The child calls the read-only
publication inspector from PR #99. It verifies the consent, stage, publication
receipts and files against the current source revision. The returned state
distinguishes an interrupted save, an artifact awaiting a receipt, a current
verified artifact and a historical one. A missing or changed published file
yields a static error code.

The command accepts only the export UUID in addition to the expected project
identity. Inspection leaves incomplete publications available for explicit
recovery. The host must keep the artifact verification flags separate from
source retrieval and scientific completeness. See
`PROVISIONAL_MANIFEST_PUBLICATION.md` for the full state contract.

### Preview and record workbook consent (issue #102)

The trusted host can submit `preview_manifest_intent` with the selected run UUID.
In a confirmation interface, show the returned original revision, denominators
and incomplete status before asking the researcher to confirm a project-local workbook name.
`prepare_manifest_intent` takes the same run, the host's stable export UUID,
`output_name`, the displayed `manifest_revision`, `manifest_actor` and
an explicit boolean `manifest_confirmed=True`. The existing consent service
rechecks the revision inside its writer transaction. Keep the UUID on retry.

After reopening, `inspect_manifest_intent` takes just the export UUID. Its
receipt and an exact preparation replay report either `consent_current` or
`stale_reapproval_required`. These states describe researcher consent.
For a staged artifact, use `inspect_manifest_publication` to determine its
file and publication status. All three consent commands leave the export
directory untouched.

In the local graphical prototype, select a run and expand **Provisional source
workbook**. Enter the basename and researcher, preview the original counts and
revision, then record consent or cancel. After an uncertain response, **Inspect
pending consent** reads the same UUID before offering any retry. A fresh host
derives the same request UUID for the same project, run, revision, basename
and actor. Each displayed preview uses a fresh confirmation token. A fresh host
can use **Find saved consents** and **Older consents** for the selected run.
The worker's `manifest_intent_history` operation reads up to 20 validated consent
receipts in descending audit-event order. Selecting one rechecks its current
revision.

**Save or resume this workbook** starts a supervised save for the displayed
receipt. The command accepts its run, export UUID and original revision.
Staging and publication independently revalidate the original source revision
and verify the file and durable receipts. A long render runs in the child while
the interface polls its status. After reopening, select the saved consent and
use **Check workbook and publication receipt** to distinguish an unfinished
save, a current verified workbook, a historical revision or changed files.
Retrying the same request preserves the no-overwrite and checksum checks.

### Worker lifecycle and project identity

`ApplicationCommand.for_project` accepts an already-opened project from trusted
host code. Only inspection, retained-report reading, export preparation, resume,
explicit cancellation and current file observation are supported. No search,
credential, shell, arbitrary import/callable or browser endpoint is provided.
External destinations must come from a trusted native selection; these commands
must never be constructed directly from browser parameters.

The child reconstructs the EXPECTED project identity, not a newly accepted one.
Existing services validate it against the manifest/database and enforce the
existing directory/reparse, journal, snapshot and publication rules. Inspection
never calls the migrating/recovering project opener. New/open project orchestration
remains separate. Result text is still untrusted display data, not safe markup.

`ApplicationWorker.submit` performs lightweight validation and starts a supervisor
thread. That thread owns one explicitly spawned child process and a fresh private
pipe. Database reads, capture, rendering and file work run in that child. There is
one active operation per worker, no persistent second queue and no unbounded backlog.
Identical in-flight requests return the same operation ID. Conflicting requests fail
with `worker_busy`. Completed operations are not cached as current observations. Public terminal status
is released only after the supervisor thread exits. `poll` and `submit` share that
same readiness check; no private thread join is required to begin the next action.

The interface-facing caller supplies and retains the export ID. The worker never
creates a replacement export ID. `prepare_export` is a separate operation: only its
committed receipt establishes a durable request. The operation ID is ephemeral and
is not an export identity. A crash before preparation commits can leave no request;
a crash after commit can leave a request even if the caller receives no success.
Use the existing inventory to reconcile that uncertainty on reopen.

Operation state `returned` means the service returned a result, NOT that an export,
retrieval or literature search succeeded. Inspect `audited_success`, observation
outcome and source-completeness fields in the returned domain object. A missing or
changed file can be a successfully returned NEGATIVE observation. No state/count
promotion is added. Polling a worker result is not repeated current file verification.

## Lifecycle and interruption

A context-manager exit or explicit `close` stops new submissions. It allows a bounded
grace period, then signals termination, escalates to kill if needed and reaps the
owned process. Call close from a lifecycle thread, not the GUI event loop. If stopping
cannot be proved, `shutdown_unconfirmed` is raised and ownership is retained for a
subsequent close attempt. It is never treated as a clean stop.

A child daemon thread watches the parent's multiprocessing sentinel and exits the
child after abrupt parent death. The worker process is also daemonic and cannot
launch multiprocessing descendants. This is not a sandbox or a guarantee against
hostile/native code holding the interpreter indefinitely, kernel failure or hardware
power loss. Future native-window/server ownership still needs its own tests.

An interrupted operation is NOT a cancelled export. The supervisor neither changes
research status nor appends fictitious cancellation/failure receipts. Existing
service transactions and the export journal remain authoritative; reopen/recover
through the existing services. A newly created worker resumes the original ID.

Each invocation has its own pipe. Terminated/corrupt channels are not reused.
Response transport is bounded JavaScript Object Notation (JSON) bytes, with explicit
schema, operation-identity and duplicate/nonfinite checks. A 32 MiB response limit
fails explicitly, never truncates, and is NOT a search-result or workbook-file limit.
The existing report and workbook limits are unchanged. Spawn's internal pickling
is only between trusted host code and its owned child, never from network input.
No result/error payload is printed. Known errors use static codes; payload reprs
exclude project paths/names and result content. No provider credential is accessed.

## Evidence and remaining gates

89 local worker/command cases passed on Linux/Python 3.13.5. These include real spawn,
large pipe messages, concurrent/double submissions, shutdown during startup, child
crash, abrupt parent death, bounded-size rejection and explicit unconfirmed cleanup.
Command adapter tests deliberately substitute existing service boundaries. Combined
branch-aware coverage of the two new modules: 93% rounded; child-process coverage
is not presumed from execution alone.

15 additional full-repository integration cases are committed for continuous
integration (CI), not claimed locally executed. They use actual projects, count/report
capture, real Excel saving, original report reuse, relocation, current file damage,
external re-selection, immutable journals, a busy database, two abrupt child deaths
and explicit shutdown after committed preparation. The local environment could not
resolve github.com for cloning, so no complete local checkout or full regression
is claimed. All four repository CI configurations and exact-commit code/security
reviews remain mandatory. No old tests or workflow gates are weakened. Six completion-boundary regression
cases were added after review; three deterministically failed against the initial
implementation and passed after correction. The integration helper's private-thread
join workaround was removed.

No browser interaction, Windows native window/installer or 100,000-record
responsiveness acceptance is established here. Keep #43/#41 and broader source,
deduplication, count, archive and export acceptance open. Next work is the dependency
feasibility/approval and thin graphical adapter; see GUI_DEPENDENCY_PROPOSAL.md.

## Primary implementation reference

Python 3.13 multiprocessing documentation (consulted 1 November 2026):
https://docs.python.org/3.13/library/multiprocessing.html
It documents spawn, daemon restrictions, parent process/sentinel handling, bounded
byte-message receive and the risks of terminating a process using shared pipes.
