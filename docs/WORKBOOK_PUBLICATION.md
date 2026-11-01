# Audited strategy-workbook publication

P1-06d follow-on, issues #39 / #37 / #9. Based on owner-merged PR #38, commit
`edce22ca63bc55322f31e183c8421413759b0e15`. The approved specification is unchanged.
This increment saves the existing strategy/count workbook; it does not add full
master-results export, source acceptance, a graphical interface or an installer.

## Public operations

`prepare_workbook_export(project, run_id, output_name, export_id=..., directory=None)`
captures the report and appends its prepared receipt in one identity-validated
SQLite transaction. Generate a canonical UUID once for a new request and retain it
for retries. The same export identifier/run/name/destination returns the existing
request without recapturing changed research data. Changed request fields are
rejected. No filename is normalised or silently changed.

`resume_workbook_export(project, export_id, directory=None)` stages, publishes or
reconciles the retained export. `inspect_workbook_export` distinguishes the recorded
phase from observed success. `cancel_workbook_export` records cancellation without
deleting files. A user interface must retain the export identifier and report errors;
it cannot infer successful export from the mere existence of a workbook.

The default destination is the project-relative `exports/` directory. An external
existing local directory can be supplied explicitly and must be supplied again on
resume/inspection. Its filesystem identity, not its absolute path, is journalled.
Network/device Windows paths are refused. Inside the project only its designated
exports directory is accepted. Filenames are bounded ASCII single components ending
in `.xlsx`, excluding reserved device names and path syntax; Unicode filenames are
not yet supported. These are output-path constraints, not search restrictions.

## Journal and filesystem contract

Use the existing append-only `audit_events` table, without a schema migration or new
dependency. Event types are namespaced `workbook_export_v1:<export UUID>` so loading
one export does not decode every other report payload. Each receipt binds its previous
event identifier/hash, version, method, timestamp, action and data. Hashes detect
inconsistency; they are not an authenticity signature against a database administrator.
The canonical captured report appears once, in the prepared receipt. It includes the
existing project/run/strategy identifiers, software/report version and count revision.

| Committed phase | Filesystem state and restart behavior |
| --- | --- |
| prepared | Frozen report persisted; no artifact promised. Render only this report. |
| staging | Intended retained filename, checksum and size persisted before writing. An interrupted complete file is verified/flushed and accepted; a partial/missing generation may be replaced by a NEW named generation rendered from the same report, never by overwriting it. |
| staged | Retained workbook is complete, flushed and checksum-verified. Later corruption/missing data is an error, not permission to regenerate silently. |
| publishing | Copy name and destination intent persisted before creating the visible final name. A complete destination-side copy is linked to the final name using no-overwrite semantics. |
| published | Final receipt committed. Success additionally requires the current retained artifact and final file to match the committed checksum. |
| cancelled | Terminal audited cancellation; partial files retained, never blindly removed. |

A failure appends a static diagnostic where the journal remains writable and preserves
the last committed phase. Journal failure may prevent even that diagnostic; the last
committed phase, not an optimistic success, remains authoritative. A file visible after
a crash before the published receipt is **not yet an audited success**. Resume accepts
it only when it is the same file as that export's recorded destination-side copy and
its checksum matches. An unrelated byte-identical file is not adopted. Cancellation
refuses already-visible output pending reconciliation and refuses completed exports.

The final workbook is a hard link to its destination-side temporary copy, but **not**
to the independent retained workbook under `exports/.researchy-exports/`. Editing the
export therefore does not modify the retained original. Its next inspection reports
changed output rather than overwriting the edit. Retained files and destination-side
copies are deliberately kept, including cancelled/failed generations. Automatic
cleanup is not implemented. The copies are evidence, not successful exports themselves.

SQLite commits and filesystem operations are not one atomic transaction. A write lock
serializes application export transitions; durable intents bridge the crash gaps.
Other application writers may receive a bounded busy error during capture/rendering;
interface work must run this service off its event loop. No responsiveness benchmark
is claimed here. External-drive copies stage on the destination filesystem, avoiding
a cross-device hard-link requirement. Unsupported hard links fail explicitly; there
is no fallback to a destructive replace or a partly visible direct write.

## Path safety and durability boundaries

POSIX file operations use an opened directory descriptor and refuse symlink ancestors.
Windows retains non-delete-sharing directory handles for the ancestor chain, opens
reparse points themselves for inspection and refuses them. New files use exclusive
creation. Reads verify ordinary file type, file identity, length and digest; the
published name must refer to the staged file. Known junction cases are actual Windows
tests, not assumed accepted because Linux tests pass.

This is a trusted local-project workflow, not a sandbox against a hostile concurrent
process with the same operating-system account or an administrator. POSIX directory
handles anchor operations but do not prevent a hostile namespace rename. The guards
do not establish safe arbitrary archive import; broader Windows issue #11 remains open.
Existing project identity/migration checks and foreign-key integrity checks remain in
force before journal operations.

Files are flushed before acceptance; directories are flushed on supported POSIX paths.
Windows directory/power-failure durability is not universally guaranteed. Automated
process-termination recovery does not constitute hardware power-cut or all-filesystem
acceptance. Copying an in-progress project without preserving hard links can make
unreceipted final output unreconcilable; use the original destination to recover it.
Completed reports survive normal project copying because content hashes remain usable.

There is an explicit 128 MiB workbook-byte safety bound, with refusal rather than
truncation. Existing renderer row/cell limits and 64 MiB report-input bound are unchanged.
No record counts, source states, identities, terms or metadata are rewritten. All
INCOMPLETE labels and source/identity limitations remain in the unchanged workbook.
No provider calls, credentials, licensed record-text fields, new dependencies or
untrusted workbook imports are introduced.

## Verification and next step

The isolated protocol tests use real SQLite files and filesystem operations but
substitute application capture/rendering. The separate integration tests use actual
project creation, frozen strategies, counts, renderer and immutable audit triggers.
Both include interruption/failure scenarios; only CI can establish the Windows cases
in this Linux authoring environment. Do not treat isolated tests as a full checkout.

Read `docs/export-publication-traceability.csv` alongside the existing renderer and
master mappings. Broad acceptance remains partial. After reviewed, owner-approved
merge and validation, initiate the minimal usable application flow: new/open project,
run/count inspection and this audited export service, without fake search or export
controls. Keep outstanding source, deduplication, full-export and release gates open.

Implementation reference points (verified during this increment):
- https://docs.python.org/3.13/library/os.html (exclusive creation, hard links and fsync)
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew (share modes and reparse-point handles)
