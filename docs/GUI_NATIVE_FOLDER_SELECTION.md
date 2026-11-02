# P1-06e2i — Native folder selection (isolated feasibility)

Date: 2 November 2026. Parent issues #43 / #41 / #9. Based on the
owner-merged PR #51 at `1c60dc380f5e33f7b6bc53d235e329f369eb1420`.
The version-controlled `RESEARCH-Y_SPEC.md` is unchanged.

## Authority and purpose

The specification requires a Windows desktop Project Launcher that can create
a project in a user-chosen parent directory and open an existing project
(PROJ-01, PROJ-03/04/07; UI-01/10; ARCH-01/02/04; SEC-04/05).
Earlier graphical feasibility increments selected paths only through
a parent-process test fixture. This increment introduces an **actual native
operating-system folder chooser** into that experimental window.

NiceGUI 3.18.0 and pywebview 6.2.1 remain approved **for isolated feasibility
only**. Their use here is not permission to add them to the production package,
alter the database or specification, make source queries, use credentials, or
merge automatically.

## Selection trust boundary

- In Windows native mode, the real NiceGUI window exposes two additional
  buttons: **Choose project folder** and **Choose new-project parent folder**.
  The first opens an existing project; the second creates a new project under
  that selected parent using the separately validated project-name input.
- An authenticated browser event can **ask for the native dialog**, but
  the operating-system path is returned only to the trusted Python host via
  `app.native.main_window` and pywebview's asynchronous
  `create_file_dialog(dialog_type=webview.FileDialog.FOLDER,
  allow_multiple=False)`. No path string is accepted from an HTTP request,
  query parameter, cookie, Socket.IO argument or arbitrary JavaScript.
- The picker accepts exactly one absolute, existing local directory.
  Cancellation returns no selection or write. Relative, malformed, multiple,
  missing, non-directory and embedded-NUL choices are rejected with static
  error codes.
- The native result is checked using the existing guarded `Directory`
  implementation, including symlink/junction/reparse ancestor checks.
  The host-controlled project open/create path is revalidated and retained
  inside a guarded directory context during core `open_project` or
  `create_project`. No silently followed, untrusted link target is accepted.
  These protections are not an operating-system sandbox against a hostile
  concurrent process running under the same local account.
- The core project service—not the GUI—remains responsible for immutable
  project identity, compatible schema/migration, exclusive project creation,
  and refusing an existing directory. A failure leaves the displayed project
  unchanged. Switching away while a tentative export request remains
  unreconciled is refused rather than silently discarding its identity.
- The pre-existing **launcher-provided** project-directory or
  `project.ryproj` file workflow remains available. The new native
  picker is deliberately folder-only; it does not remove file-based opens
  from the trusted launcher.
- Ordinary browser/transport feasibility mode does not present an active
  chooser, and does not acquire filesystem access. It explains that the
  chooser is only available inside the native desktop window.
- The current project path is visible as an ordinary local label to the
  researcher, but no secret, raw exception or untrusted path is included in
  a diagnostic error message.

## Tests and what they mean

Core Python tests on Windows/Linux 3.12/3.13 use a **stubbed asynchronous
window** to verify the exact native folder dialog call and cancellation.
Disk-backed real project tests exercise both existing-project opening and
new-parent project creation, including invalid selections and the unchanged
project identity on failure. A native-window lifecycle probe checks that both
controls really render in the Windows window and remain inside the existing
authenticated, loopback-only host/origin/session boundary; the older
publication/recovery cases remain mandatory.

**Limitation:** Continuous integration does not automatically click through
the operating-system file-picker window or verify manual directory navigation,
selection and cancellation with a human on a clean Windows installation.
A mocked dialog response and a rendered button do **not** constitute a full
native-dialog end-to-end acceptance pass. Actual user interaction, relevant
WebView2/.NET prerequisites, unavailable engine errors, permissions, race
conditions, dialog interruption, path changes and real-world supportability
remain manual/target-hardware acceptance criteria.

The approved implementation still lacks a recent-project index, full project
archive import, external workbook destination selection/reconfirmation, and a
packaged Windows installer. No live retrieval, master-publication browsing,
large-data latency gate or complete product acceptance is asserted.

## Merge gate

Current exact PR HEAD, four core regressions, four graphical dependency jobs,
four graphical lifecycle jobs, and actual per-platform evidence must be checked.
Complete Codex code review (including individual receipt) and security review
for the **same HEAD**, verify timestamps and resolve findings, revalidating
after any change. Never merge or adopt production dependencies without
explicit project-owner authorisation.
