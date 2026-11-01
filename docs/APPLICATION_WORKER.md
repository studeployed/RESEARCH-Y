# P1-06e2a — Supervised local operations

Parent #43 / #41 / #9. This is the framework-independent worker part of the
minimal application, NOT the graphical user interface (GUI), a launcher or an
installer. The repository specification is unchanged. Initial parent is merged
PR #42, `bc4666fa7aaefe8082ad7ea21a1918f0ac4187f1`.

## Contract

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
with `worker_busy`. Completed operations are not cached as current observations.

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

83 local worker/command cases passed on Linux/Python 3.13.5. These include real spawn,
large pipe messages, concurrent/double submissions, shutdown during startup, child
crash, abrupt parent death, bounded-size rejection and explicit unconfirmed cleanup.
Command adapter tests deliberately substitute existing service boundaries. Combined
branch-aware coverage of the two new modules: 92% rounded; child-process coverage
is not presumed from execution alone.

15 additional full-repository integration cases are committed for continuous
integration (CI), not claimed locally executed. They use actual projects, count/report
capture, real Excel saving, original report reuse, relocation, current file damage,
external re-selection, immutable journals, a busy database, two abrupt child deaths
and explicit shutdown after committed preparation. The local environment could not
resolve github.com for cloning, so no complete local checkout or full regression
is claimed. All four repository CI configurations and exact-commit code/security
reviews remain mandatory. No old tests or workflow gates are changed.

No browser interaction, Windows native window/installer or 100,000-record
responsiveness acceptance is established here. Keep #43/#41 and broader source,
deduplication, count, archive and export acceptance open. Next work is the dependency
feasibility/approval and thin graphical adapter; see GUI_DEPENDENCY_PROPOSAL.md.

## Primary implementation reference

Python 3.13 multiprocessing documentation (consulted 1 November 2026):
https://docs.python.org/3.13/library/multiprocessing.html
It documents spawn, daemon restrictions, parent process/sentinel handling, bounded
byte-message receive and the risks of terminating a process using shared pipes.
