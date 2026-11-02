# P1-06e2e — trusted real-project graphical slice (experimental)

2 November 2026. Follows owner-merged PR #47 at
`7772a37082d0513e8376dd2a3d0dda28267e3c0c` and continues #43/#41.
The specification is unchanged. NiceGUI 3.18.0 and pywebview 6.2.1 are approved
**only for the isolated experiment**; production adoption and merge still require
separate owner authorization.

## Scope and scientific truthfulness

This slice reuses the real `create_project`, `open_project`, frozen strategy/run,
`read_application_snapshot`, `ApplicationWorker`, export journal and workbook
renderer. It does not introduce a second count calculation, another workbook
writer or a separate mutable copy of a scientific report.

The graphical page shows a saved project name and path as plain labels, requires
an **explicit** stored run/version selection, and renders the exact saved query,
reported matches (including `unknown`), the current global unique publication
denominator (including `unknown`) and INCOMPLETE status. A prepared/published
journal entry is not shown as independently verified output: the owner must
explicitly observe the actual file. Source retrieval is never promoted to
verified merely because the workbook was saved.

The owner may create a new project in a host-selected parent directory or open
an existing host-selected project. The initial browser/native feasibility fixture
provides those paths from a trusted parent-process environment—not an HTTP
body, query string, JavaScript argument, cookie or user-supplied browser path.
**A real interactive native directory picker and recent-project directory
are not yet implemented or accepted.** The browser may supply a project *name*
for new creation; the production project service validates that name and
allocates a new directory without replacing anything.

The `RealProjectFlow` adapter accepts run and export identifiers only after
matching them against the storage-backed snapshot. An export must also belong
to the **currently selected run**; a saved request from another run cannot be
selected or shown alongside a different run's report. The graphical list
likewise offers only requests belonging to that selected run.
All durable services run
through `ApplicationWorker` off the interface event loop. Each run receives a distinct, Windows-safe default output name
`strategy-summary-<canonical-run-UUID>.xlsx`, preventing a saved workbook from
one run from blocking publication of another run through this thin interface.
A request's original universally unique identifier remains stable across retries
and restarts.
Opening a saved project never silently selects its most recent run, and an
existing matching export requires an explicit saved-request selection instead
of generating an accidental second request.

The page now has **separate current-run and retained-export report sections**.
After selecting a validated export request, the adapter reads the original
frozen report with the existing `export_report` command, verifies its run
identity, and displays its original query/counts as exported. It does not
silently relabel fresh counts as the workbook's historical counts when the
underlying research state has changed since preparation. Selecting another run
clears the retained report until an export belonging to that run is explicitly
selected. A regression changes source counts after preparation and proves the
current/retained values remain distinct following restart and publication.

## Real-world-sized boundary of the evidence

The first four-platform runner attempt exposed a missing approved workbook
backend: the graphical-only isolated environment contained NiceGUI and
pywebview but not `openpyxl`. The amended lifecycle workflow installs the
repository's already-declared `.[excel]` extra **after** separately validating
the graphical dependency graph, records that additional pip installation
report and verifies exact `openpyxl==3.1.5` and `et-xmlfile==2.0.0` versions
and `pip check`. This does not add a new graphical dependency or claim a
complete licence/vulnerability audit for the combined environment.

The following amended matrix exposed a separate problem **before** the real
project scenario on Windows/Python 3.12: the prior synthetic abrupt-host-death
probe passed its six ordinary cases but intermittently raised `TimeoutExpired`
during the process-tree check. Its original implementation launched a new
PowerShell/CIM query on every 50 ms poll, an unnecessarily heavy global
process-enumeration dependency. The next amendment uses a native Windows
Toolhelp process snapshot instead. The same exact descendants, host-only
termination, 15-second descendant-exit deadline and failure-on-missing-cleanup
requirements remain unchanged; no failure is skipped or timeout extended.
A native child/parent enumeration assertion and a no-CIM regression protect
the replacement. No production code changes.

The dedicated runner seeds a **real disk-backed project** with a frozen, approved
one-group OR strategy and a planned but unexecuted PubMed query. This is a
synthetic *source fixture* deliberately producing `unknown` reported hits and
`unknown` global unique publication count—not a fake provider response or
a completed literature retrieval. The child GUI launches in a separate native
Windows window or actual local HTTP transport under the pre-existing
`PrototypeGuard` session/origin/path policy.

The experiment performs real project open, explicit run inspection, two
preparations with one original export ID, publication of a genuine ZIP-based
`.xlsx` workbook and independent file observation. The host then closes,
moves the project folder, starts another instance, selects the saved run
and export explicitly, verifies the output again and checks no new export
journal entry was added on reopening.

On Windows the native scenario clicks the actual corresponding NiceGUI
buttons rather than synthesizing worker responses. Linux tests the real
loopback transport with fixed actions. Test HTML-like project names must stay
literal; source text is never rendered through a markup interpreter. No
browser client can select arbitrary filesystem paths through the test route.
Child scripts are run in disposable environments with provider credentials
removed; screenshots, account data, secrets and absolute paths are not
included in uploaded feasibility observations.

Core project creation and migration are independently tested. The adapter's
own failure codes are static; raw exceptions that may embed local paths never
become browser errors. The contract tests exercise missing/invalid projects,
empty new projects, no implicit run selection, genuine workbook structure,
rerun/reopen/relocation, exact identity and retained request IDs.

## Bounded action-response behaviour

The read-only health probes retain their short three-second HTTP timeout. The
experimental `/_probe/start` route, however, awaits actual completed workbook
commands: preparation may run up to three supervised operations of 35 seconds
each. Its **fixed-loopback, fixed-path-only** driver uses a 115-second bounded
HTTP response timeout, with the original one-megabyte response limit. This does
not alter worker deadlines, NiceGUI controls, security permissions or protocol
paths. The GUI button itself runs the work off the event loop. Regression tests
verify the longer bound only applies to this action, and that oversized output
still fails explicitly.

## Gates still open

- Genuine native folder selection and recent-project index; user-visible
  create/open failures, new project names and migration handling require more
  adversarial interaction tests before production GUI adoption.
- Real disk-full, permission, write-interruption and visible-but-unreceipted
  workbook recovery need GUI-level end-to-end assertions, even though the
  underlying storage services have separate integration coverage.
- The loopback protocol's browser-session/reconnection adversarial coverage,
  native process-tree cleanup in the eventual production topology, source-build
  and licence review, offline assets/installer prerequisites, accessibility,
  representative 100,000-record performance and full output formats remain open.
- No actual live source request, search submission, credentials, local language
  model, society/conference discovery or master result viewing is included.

The framework's browser/native integration is still an experiment. Passing
these tests is **not** production adoption, a working distributable desktop
application or confirmation of complete source retrieval.

## Validation

Use the added steps of `.github/workflows/gui-lifecycle-probe.yml` (Windows and
Linux, Python 3.12 and 3.13) in addition to the unchanged core and dependency
gates. The workflow's real-project artifact records bounded boolean results;
the actual workbook and research data remain in the disposable runner.
A green workflow alone does not supersede the current exact-commit code review
and security review protocol. Never merge without owner approval.
