# P1-06e2g — Missing final workbook receipt: real crash and GUI recovery

Date: 2 November 2026. Parent issues #43 / #41 / #9.
Baseline: owner-merged PR #49, `0d64712d32be9fbda360024d0565f810d7392f38`.
The repository `RESEARCH-Y_SPEC.md` remains authoritative and unchanged.

## Why this increment exists

A genuine workbook may be fully visible on disk before its final publication
receipt commits. In that interval, **the file is not an audited successful
export**; the source search is also not verified. Merely detecting a
well-formed Excel file or a matching checksum does not establish that its
publication journal is complete. This is a concrete crash-recovery requirement
under PROJ-04/06/07, ARCH-02, AUDIT-01/03, EXPORT-01/03/04, SEC-05, UI-05/10
and scoped acceptance tests AT-09/18/19/21.

## Controlled, real fault

The test fixture prepares a normal on-disk project and export with the
existing production service and exact immutable export identifier. A separate,
non-privileged Python **subprocess** invokes the actual workbook-publication
engine. Its test-only hook terminates the process with `os._exit(73)` *after*
the final no-overwrite hard link is created and flushed, but *before* the
`published` audit event can commit. SQLite rolls back that uncommitted
transaction. The earlier `publishing` journal event remains durable and the
original Excel workbook is visible.

This deliberate process death is not a simulated worker return value, and the
unmodified application's publication engine runs in both the parent GUI and
its supervised worker. No production source, schema, dependency, credential,
literature provider or GUI route is modified to inject the fault. The
crash-fixture subprocess receives only a small allowlisted environment.
Neither its process stderr nor any research data or absolute paths are
uploaded as public workflow evidence.

## Required observable behaviour

1. On first opening the project, the researcher must explicitly choose the
   same stored run and export request; neither is selected implicitly.
2. The real observer reports `published_receipt_missing` with
   `audited_success=False` and recorded state `publishing`. The graphical
   page displays a prominent **RECOVERY REQUIRED** message explaining that
   the visible file is *not verified* and that the same request should be
   resumed. Inspection makes no audit changes and never starts a new export.
3. A fresh graphical session reopens the project, selects that original run
   and export ID, and invokes the existing `resume_export` worker. Its
   no-overwrite, same-file and digest checks must reconcile the already
   visible file before writing the final receipt.
4. Independent `observe_export` then reports `published_verified`.
   The workbook's digest and file identity are unchanged; the journal gains
   **exactly one** final `published` event, with no new request or recapture
   of the retained scientific report.
5. If a file is altered while its final receipt is missing, observation
   remains negative. Recovery must refuse altered content, preserve the
   original request and record an appropriately auditable failure rather
   than overwriting the altered file or claiming successful publication.

## Automated evidence

- Deterministic disk-backed tests prove the real subprocess crash,
  retained report/snapshot distinction, unchanged journal on observation,
  same-ID recovery after reopen, repeat-safe publication and refusal of
  a tampered file on Windows and Linux.
- The existing four-platform graphical lifecycle runner is extended with
  `receipt_missing` and `receipt_recovered` scenarios in both actual
  loopback transport and Windows native-window button interactions.
  Successful runs must show all existing publish, relocate, cancel,
  cancel-reopen and these two new scenarios; expected negative outcomes
  are *tested as negative*, not counted as successful publications.
- No new external service, model, cloud storage, live PubMed/Web of Science
  request, browser-controlled path or arbitrary export identifier is added.
  A Native WebView2 window and loopback server retain their existing
  authenticated owner/session/origin and lifecycle protections.

## Status and boundaries

This is an isolated feasibility experiment under the owner's earlier approval
of NiceGUI 3.18.0 and pywebview 6.2.1, **not production framework adoption**.
Successful CI is not assumed until actual current-HEAD jobs are inspected.
Current-HEAD Codex code review and security review need matching completion
timestamps and receipts, with all substantive findings addressed. The user
must explicitly approve any merge.

Still open in #43: representative disk-full and permission failures through
the actual native interface; interruption of a live GUI-owned worker at
other durable phases; explicit native folder selection, external destination
confirmation and re-selection; multi-session reconnection adversarial testing;
complete native/frontend licence and dependency review; offline packaging,
100,000-publication responsiveness and full workflow acceptance. No study
retrieval, search completeness or full product acceptance is claimed.
