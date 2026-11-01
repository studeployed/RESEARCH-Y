# RESEARCH-Y handover — PR #40 merged; application inspection foundation

## Authority and verified baseline

Repository `RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 is authoritative and unchanged.
Independent Python implementation; no imported project assumptions.
Owner-merged PR #40 is `730d5c8e2c4b220e69d4c9807581ca59b3634955`, merged
1 November 2026 at 22:15 Coordinated Universal Time (UTC). All four post-merge
configurations in run #41356206017 passed. This validates that baseline, not the
new application-inspection branch.

Standing owner direction: begin the next ready approved task at each completion
step without another routine continuation prompt. This does not authorise
automatic merges, substantive scope/dependency changes, waived gates, live-source
retention consent or asynchronous monitoring claims.

## Current increment — P1-06e1 read model and export inventory

Parent #41 / #9; read `docs/APPLICATION_INSPECTION.md` and the scoped
`docs/application-inspection-traceability.csv`. New `application_inspection.py`
provides a current project/run catalogue, optional selected-run strategy/count
snapshot, durable export-request inventory, retained export reports and explicit
current artifact observations. It reuses production count/capture, journal
validation, read-only identity/schema checks and PR #40 path guards.

One application snapshot reads its project setup, runs, export inventory and
selected report on the same read transaction/handle. Separate calls are separate
observations. No implicit newest-run selection, invented run-name column,
progress percentage or fictional empty master table. Unknown counts remain
unknown and group sums remain distinct from global publication identities.

Every inventory request is retained, including failures/cancellations, with its
original stable ID and report hash. Inventory is not file verification or worker
liveness: `audited_success=False`, `files_checked=False`, `worker_status=unknown`.
Explicit observation distinguishes missing/changed original or output files,
external destinations needing confirmation, an owned visible output missing its
final receipt, and a genuinely verified published artifact. Observation neither
repairs receipts nor writes, flushes or removes files. Successful file verification
never promotes source/search completeness. A last audit event is NOT a source
checkpoint; checkpoint verification remains explicitly not performed.

Corrupt/unsupported journals and invalid project evidence fail with static errors,
not an empty list. Reads do not migrate/recover; use the existing explicit project
open service when needed. The source data is untrusted plain data for a future
renderer, not HTML or a claim of browser-injection defence.

Local validation: 74 isolated contract tests pass on Linux/Python 3.13.5, 99%
rounded branch-aware coverage of the new module. These use real SQLite for
catalogue operations but replace existing project/capture/receipt/filesystem
boundaries. No complete local checkout was available. Thirty-five additional
repository integration cases use actual project/count/capture/workbook services,
current files, concurrent committed changes and two actual child-process deaths.
They require full repository continuous integration (CI); they are not counted
as locally passed. Cross-platform checks and exact-commit reviews remain gates.

No graphical interface, network server, worker orchestration, launcher, installer,
new dependency, source request, credential access, schema migration, workflow
change or specification amendment is included. This is the first bounded #41
increment, not completion of the minimal application.

## Immediate next step

Prepare the framework/dependency feasibility and minimal graphical adapter under
#41: real new/open project and named-run selection, the inspected catalogue/counts,
export request inventory, verified save/recovery actions and clear unavailable
features. Evaluate the specification's preferred NiceGUI/native lifecycle option;
material dependencies require explicit owner approval before adoption on main.
Do not silently choose a hosted/shared application or require end-user Python setup.

Capture/render/save/recovery must run off the interface event loop with serialized
conflicting actions and honest shutdown/restart handling. Stable request IDs must
survive accepted requests, double clicks and restarts. External locations require
explicit local selection; browser parameters cannot become arbitrary paths.
Session/origin/request enforcement, untrusted text rendering, real browser tests,
Windows launch/interaction and lifecycle evidence are mandatory before claiming
UI acceptance. A read model does not establish responsiveness or AT-22 performance.
Dependent implementation must use a freshly verified owner-merged baseline.

## Preserved implementation and scientific limits

PR #40's workbook publication retains independent original bytes and an immutable
report, uses append-only receipts and no-overwrite publication, and distinguishes
filesystem work from database commits. Windows directory guards now request
FILE_LIST_DIRECTORY rather than zero access while forbidding delete sharing.
Read `docs/WORKBOOK_PUBLICATION.md` and `docs/WINDOWS_EXPORT_GUARD.md`.
No destructive fallback/automatic cleanup, universal power-cut guarantee or
hostile same-account sandbox is claimed. Unicode output names, Windows network/
device paths and unsupported hard-link filesystems remain explicit limitations.
The 128 MiB artifact bound refuses rather than truncates. Broader #11 remains open.

Read count/publication documentation for provisional identity versus verified
unique-publication totals, queryless/unmaterialised records, stale decisions,
manual reversible associations and the 2–32-record candidate-helper limit.
That helper is not a retrieval or count cap. Project-wide duplicate discovery,
automatic rerun propagation, full master/conference/guideline workbooks and
portable archives remain outstanding. Keep #33, #35 and #37 open as applicable.

PubMed run #41235232458 observed 19,483 unique identifiers, 43 pages, six disjoint
leaves and controlled restart; full metadata and broader acceptance remain partial.
Starter run #41306953908 observed 19,584 reported/committed records, 392 acquisition
and 392 verification pages, 786 requests, separate-process restart and
4,214/5,000 quota requests remaining. No frozen snapshot, full abstract enrichment,
live multi-day quota-reset acceptance or whole-product completeness is inferred.
Retained aggregate evidence is not an independent record-level audit. Keep #7/#8
open. Never request configured credentials in chat or repeat live calls merely
for documentation.

Preserve transactional creation, recoverable schema-v4 migrations, durability,
immutable source/plans, memberships, request journals, worker fencing and genuine
failure budgets. Provider-wide longest Retry-After and unknown request outcomes
remain binding. Local budgets are resumable pauses, not source errors. Final
Starter verification needs an uninterrupted session with available quota.

## Review and merge protocol

Before merge advice re-fetch current HEAD, all four required CI configurations,
code/security summaries, completion timestamps, matching individual receipts and
outstanding findings. Verify code first; then security unless a valid automatic
current-commit review exists. Do not duplicate running reviews. A reaction or clean
older review is not completion evidence. New commits invalidate prior acceptance.
Never merge without explicit owner authorisation; no asynchronous work claims.
