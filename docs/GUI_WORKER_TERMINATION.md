# P1-06e2i — GUI-owned worker termination during workbook staging

Date: 2 November 2026. Parent #43 / #41 / #9.
Baseline: owner-merged PR #51 at `1c60dc380f5e33f7b6bc53d235e329f369eb1420`.
The repository `RESEARCH-Y_SPEC.md` remains authoritative and unchanged.

## Scope

This increment addresses a different failure boundary from PRs #49–#51.
Those increments exercised controlled service faults and independently crashed
fixture subprocesses. Here, the **actual ApplicationWorker spawned by a live
NiceGUI project host** is externally terminated after it has committed a
`staging` receipt and written an incomplete retained workbook.

A terminated worker must not fabricate search completeness, lose the export
identifier, overwrite a partial file, or be reported as an audited publication.
A separately reopened GUI session must resume that same request from its
durable journal using the existing, unmodified publication service.

This is still **only an isolated feasibility experiment** under approval of
NiceGUI 3.18.0 and pywebview 6.2.1. Neither framework is adopted for the
production application. No new third-party dependencies, project schema
changes, additional browser filesystem routes, provider requests, credentials
or RESEARCH-Y specification revisions are introduced.

## Mechanism and boundaries

1. The trusted runner creates a real local research project, approved strategy,
   saved run and prepared export with a canonical UUID. No source requests run;
   the incomplete, unknown-count report is genuine.
2. In the special `worker_killed` test scenario only, the GUI host substitutes
   a top-level, importable **test-only callable** when it creates its normal
   ApplicationWorker subprocess. Normal project inspection commands still use
   the real production services. The browser cannot select the callable or
   supply a marker path or process ID.
3. When the ordinary workbook engine reaches its real `Directory.write_new`
   retained-stage call, the test-only callable delegates to the existing
   exclusive-write and flush method to write a prefix of the **actual rendered
   workbook**. It writes its own PID to an exclusive, private runner marker
   and blocks before the stage write would otherwise complete.
4. The GUI host writes an **independent private owner marker** containing
   its actual Python interpreter PID before it launches the worker. An
   independent parent-side monitor reads both markers and requires that the
   target worker is a **direct child of that actual GUI interpreter** (using
   Windows Toolhelp or Linux procfs). It separately verifies the GUI owner
   against the exact process the runner started: either the same PID, or on
   Windows a direct child of the launched virtual-environment Python
   redirector. Arbitrary descendants, unrelated processes and unverified
   process identities remain forbidden. Only then does it terminate the
   validated worker. Invalid/missing markers, failed parentage checks or
   unsuccessful termination fail the test. The GUI server remains alive.
5. The real worker supervisor recognises interrupted child execution.
   The on-screen request reports `worker_interrupted` and **RECOVERY
   REQUIRED**. Only the original `prepared` and `staging` receipts
   exist. The truncated owned stage is independently observed as
   `retained_artifact_changed`, not as a successful workbook; its bytes
   and inode/file identity are retained.
6. After normal window shutdown and worker reaping, a **new GUI process**
   explicitly selects the same run and export. Its unmodified worker
   executes `resume_export`: a fresh retained stage is rendered from
   the immutable original report, the damaged stage is not overwritten,
   and one actual `.xlsx` is published. Independent observation then
   returns `published_verified`. No new export UUID, recaptured research
   counts or automatic search-complete status are allowed.

The only killable target is the supervisor's owned child; the test runner
never kills arbitrary user processes. Private process markers, filesystem
paths, credentials and raw project content are not included in uploaded
diagnostic artifacts.

## Windows process-identity follow-up (PR #52)

The first exact-HEAD Windows graphical lifecycle run
[#41496704660](https://github.com/studeployed/RESEARCH-Y/actions/runs/41496704660)
failed 2/2 Windows native jobs (20/22 real-project scenarios in each), while
the 4/4 core regression and dependency jobs passed. A bounded diagnostic
commit produced the same failures in both Windows versions: the worker
PID marker **was present**, but the monitor stopped at
`worker_parent_mismatch` before delivering a termination signal. The host
therefore reported `worker_timeout`. This rules out an absent stage marker
or failed rendering as the immediate failure.

The likely cause is the Windows virtual-environment `python.exe` redirector:
the runner's `Popen.pid` can identify the launcher, while the actual Python
GUI interpreter (which directly owns the worker) has a separate PID.
The correction records the actual GUI owner in a second exclusive private
marker and **verifies both links through operating-system process ancestry**.
It does not treat an arbitrary grandchild of the launcher as a directly owned
worker. Neither marker's raw path or PID is uploaded as test evidence.
Status labels are fixed, non-sensitive diagnostics.

The first diagnostic commit also exposed two pre-existing unit tests that
asserted an exact two-field result dictionary. Updated tests assert the
expected diagnostic phase *in addition* to their original no-unrelated-kill
and valid termination results. Actual Windows validation is required before
claiming the parentage correction has succeeded.

## Acceptance evidence

- Deterministic offline integration tests exercise the real spawned
  ApplicationWorker, externally terminate its exact child midway through a
  retained-stage write, then validate file evidence, audit event counts,
  original report preservation, replay and teardown.
- The existing four-platform graphical lifecycle workflow tests actual
  authenticated local HTTP transport on Ubuntu/Python 3.12 and 3.13 and
  native Windows button interactions on Python 3.12 and 3.13.
  Its new `worker_killed` and `worker_recovered` cases are appended
  to all prior publication, relocation, cancellation, missing final receipt,
  renderer-permission and partial-stage disk-error scenarios.
- The expected initial worker error is a **correct negative test outcome**.
  The runner must prove that the failure was shown as a failure, and the
  later independently verified workbook belongs to the original request.
- No action is considered tested by mere workflow creation. Review the
  actual completed test results, their evidence and all failures.

## Explicit limitations

This is not a physical low-disk-space test, a real operating-system
access-control-list denial, abrupt death of the *whole* GUI host, arbitrary
WebView2 suspension, or evidence that all possible crash points are
recoverable. The case uses a deliberate test-only pause to make the
mid-write termination deterministic; normal application logic does not
contain such a pause.

Remain open under Issue #43: startup/reconnection intermittency, independent
multi-session adversarial testing, actual native filesystem selection,
external export re-selection, exact native/frontend licensing and supply
chain approval, offline packaging, large-data responsiveness, full
research workflow and production framework adoption.

## Mandatory pull request merge gates

Review the **current HEAD** and all four Python regression, four dependency
and four graphical lifecycle jobs. Code review must be definitively completed
on that exact SHA, with summary, completion timestamp and individual receipt;
security review follows, whether already automatically triggered or explicitly
requested, and needs the same exact-commit evidence. Resolve or formally
disposition every finding and revalidate on any new commit. A successful-looking
reaction or old review is not sufficient. **Never merge without explicit
project-owner authorisation.**
