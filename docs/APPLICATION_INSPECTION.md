# P1-06e1 — Application inspection and export recovery inventory

Parent: #41 / #9. Baseline: owner-merged PR #40,
`730d5c8e2c4b220e69d4c9807581ca59b3634955`.
The repository `RESEARCH-Y_SPEC.md` is unchanged and authoritative.

## Bounded implementation

`application_inspection.py` is a headless read model for the future local
application. It is not a graphical user interface (GUI), a network server,
a worker manager, a launcher, or an installer. It introduces no dependency,
schema, source request, credential access, export write or specification change.

The first UI foundation is deliberately independent of framework adoption.
Creating/opening projects and exporting still use the existing production
services. This increment does not wrap them in fake controls or expose them over
a browser. Scope #41 remains open.

## Entry points

- `read_application_snapshot(project, selected_run_id=None)`: current project
  setup, every stored run with its actual identifier/date/strategy version,
  validated export-request inventory, and optional full-run strategy/count report.
  No run is implicitly selected. A missing run is an error, not a zero result.
- `list_export_requests(project)`: every supported validated request, ordered by
  latest committed event, including failed and cancelled requests. No directory
  scan, artifact read, request-ID regeneration, or implicit resume.
- `read_export_report(project, export_id)`: original canonical report retained by
  the prepared receipt, not newly captured research data.
- `observe_export_request(project, export_id, directory=None)`: explicit current
  artifact observation. It never completes or repairs a receipt, flushes files,
  creates a staging directory, appends failure events or deletes anything.

The snapshot payload is canonical immutable text. `as_dict()` returns a fresh
copy. `location` is separate transient local display context, not persisted report
provenance. Run labels are not invented as stored names: the schema supplies run
identities, timestamps, strategy version numbers and strategy themes.

## Evidence and status distinctions

Inventory `recorded_state` and `last_error` come from the existing production
journal validator. The immutable report, supported method, predecessor checks,
transition rules and project/run identities must validate. Index timestamps must
match their receipt bodies. Unsupported export-journal versions, malformed keys,
corrupt chains and unreadable project evidence fail explicitly; they never turn
into an empty inventory or silently disappear.

Inventory always has `audited_success=False`, `files_checked=False` and
`worker_status='unknown'`. A committed phase does not prove that its worker is
running, stopped or interrupted. The GUI must not infer those states from it.

Explicit observation distinguishes:

| Observed outcome | Meaning |
|---|---|
| `not_yet_staged`, `staging_receipt_required` | Preparation/retention has not acquired all required receipts |
| `ready_to_publish`, `publication_pending` | No final output has been observed; use the existing resume service |
| `published_receipt_missing` | Matching owned output exists but its final receipt is missing; NOT audited success |
| `published_verified` | Valid committed published receipt plus matching retained and final artifact bytes, as observed |
| `recorded_cancelled` | Terminal recorded cancellation, without deleting retained files |
| `retained_artifact_missing`, `retained_artifact_changed` | Original retained artifact cannot be accepted |
| `published_file_missing`, `destination_changed` | Published output is absent or cannot be verified |
| `destination_conflict` | Existing output cannot be adopted; unrelated identical bytes are insufficient before the final receipt |
| `destination_confirmation_required` | External location must be explicitly supplied again |
| `destination_directory_changed`, `destination_unavailable`, `storage_unavailable` | Directory identity/access or storage observation failed |

An observation is time-specific, not ongoing monitoring. Filesystem observation
and database reads are not one atomic snapshot. Observations preserve the
recorded journal state even when output has been deleted or edited. Repeated
observations recheck files rather than reusing an earlier success flag.

Successful artifact verification never promotes source acceptance, verified
publication counts, or search completion. Unknown counts remain unknown; group
sums are not global unions. The selected report reuses the existing capture and
count code on the same read transaction, including its parameter-export policy,
licensed-text exclusions and INCOMPLETE status.

The latest audit event is labelled only `last_recorded_audit_event`. It is NOT a
successful source checkpoint. The latter remains explicitly unknown with
`checkpoint_verification='not_performed'` until a validated checkpoint projection
is implemented. No progress percentage or fake empty master list is supplied.

## Read boundaries and recovery

Existing project path guards and the existing read-only identity/schema/foreign-key
validator remain binding. Reads use a five-second SQLite busy timeout inherited
from that validator. Busy/locked errors are distinct static `project_busy`
outcomes. Other raw paths, SQL, source payloads and exception messages are not
returned. Reads do not migrate or perform explicit hot-journal recovery; opening
the project through its existing service is required first when recovery is needed.

Project setup, run catalogue, export inventory and selected report in one
`ApplicationSnapshot` use one read-only database transaction and handle. Separate
API invocations are separate observations, not a historical reconstruction.
Concurrent committed changes cannot mix the inventory with a newer selected
report within one snapshot.

External directories are trusted local caller selections checked by the existing
export service's directory identity guards. This is NOT authorisation to accept
arbitrary browser paths. The future browser adapter must enforce session, origin,
request and local-selection boundaries before connecting any operation.
All researcher/source labels remain untrusted plain data. No HTML rendering or
browser-escaping acceptance is claimed here.

Full receipt validation currently uses the production per-request journal loader.
This is deliberately not an unvalidated cached index; inventory cost grows with
export history. No source-result truncation or hidden inventory cap is introduced.
Representative 100,000-record interface performance remains AT-22 work, not a
claim established by these small fixtures.

## Validation and outstanding work

74 isolated contract tests pass locally on Linux/Python 3.13.5; the new module has
99% rounded branch-aware coverage in that isolated harness. Those tests use real
disk-backed SQLite for catalogue queries but replace project, capture, receipt
and filesystem service boundaries. They do NOT establish full application
integration or native Windows behaviour.

The 35-case repository integration suite uses real projects, counts, report
capture, genuine workbook saving, immutable receipts, current filesystem checks,
concurrent commits and two actual child-process deaths. Full four-configuration
continuous integration is required; these cases are not claimed locally passed.
The container could not clone/download the repository, so no full local checkout
or complete local regression result is claimed.

Next: framework/dependency feasibility and the minimal browser/native adapter,
with background work, create/open/run selection, export inventory, explicit
verification/recovery and lifecycle tests. That dependency proposal still needs
owner approval. Do not expose enabled actions before they are wired and tested.
Keep #41, #37, #35, #33, #7, #8 and #11 open where their broad acceptance is unmet.
