# P1-06e2k — Confirmed external workbook destinations (isolated GUI feasibility)

Date: 3 November 2026. Baseline: owner-merged PR #54, main commit
`d6aece67934566e206b31a8c7163179f69b696e6`. Parent issues
[#43](https://github.com/studeployed/RESEARCH-Y/issues/43),
[#41](https://github.com/studeployed/RESEARCH-Y/issues/41) and #9.

## Authority and bounded purpose

The repository `RESEARCH-Y_SPEC.md` remains the authoritative, unchanged
specification. Requirements ARCH-01/02/03/04, PROJ-04/06/07, UI-01/10,
EXPORT-01/03/04, SEC-04/05 and scoped AT-09/18/19/21 apply. The previously
approved **isolated** NiceGUI 3.18.0 / pywebview 6.2.1 experiment is not a
production framework/dependency decision, release, installer, or permission
to invoke live providers.

The core workbook service already journals an external destination's directory
identity without storing its absolute path and requires the exact directory to
be re-supplied to resume, inspect or publish. This increment connects that
existing service to trusted native graphical folder selection and an explicit
confirmation step without adding a browser-controlled filesystem route.

## Operation and trust boundary

1. After explicitly opening a real project and selecting its saved run, the
   native Windows window offers **Choose external workbook folder**. Only the
   Python host calls the native operating-system folder dialog. Its result is
   accepted as a single existing absolute local directory, with no symbolic
   links, junctions, reparse-point ancestors, network/device path or traversal.
   The browser provides no path, file bytes or directory identity.
2. A selection is **pending**, not yet authorised to write. The interface shows
   the proposed local folder as *plain text*. The researcher separately clicks
   **Confirm this external destination**; a missing confirmation blocks
   preparation rather than falling back silently to the project exports folder.
3. Offer and confirmation independently revalidate the guarded directory
   and its filesystem identity. The immutable two-number filesystem identity
   is additionally passed through the allowlisted, supervised Python worker
   command for **preparation**, which compares it while holding the directory
   handle **before** committing a new preparation receipt. The normal target
   validation checks identity again at publishing. This closes the
   host-validation → worker-open swap interval; no client-supplied identity
   or project-stored path is trusted. A replaced folder fails closed.
   Project descendants cannot be selected as external destinations; only the
   ordinary project `exports/` folder or a genuinely external directory is allowed.
4. The existing `ApplicationWorker` executes `prepare_export`,
   `resume_export`, `cancel_export` and `observe_export` on the selected
   **immutable export request UUID**. The original frozen research report,
   receipt chain, staging artifacts, non-overwrite publication and independent
   verification remain authoritative. An external destination's directory
   identity is held in the journal, not its absolute path.
5. Reopening the application never reuses an old path from the project, history,
   a browser cookie or an environment variable. Selecting the retained export
   shows its destination kind; the original folder must be chosen and confirmed
   again for publication/recovery. An unconfirmed published export can be
   observed only as `destination_confirmation_required`, **not** verified
   success. A different folder is rejected using the journal's recorded
   directory identity and cannot silently retarget the request.
6. Selecting a different project, run or stored export clears any previously
   chosen/confirmed external folder. Cancelling a picker is a no-op. Clearing
   the external selection leaves the request intact and retains the original
   receipt; it never deletes a workbook or generates a replacement export ID.
   A project-exports request cannot be converted into an external request.
7. A prepared receipt can commit even if the following inspection fails. The
   active export ID remains selected. On an explicit retry, the trusted host
   rereads the authoritative export inventory *before* checking destination
   kind. If reinspection is unavailable, it refuses the operation as requiring
   reconciliation, preserving the original ID. When inspection recovers, the
   same request is reused without recapturing the research report or adding
   a second preparation receipt.
8. If a preparation response *and* immediate inspection are lost, the pending
   UUID is resolved by a fresh journal inventory check **before** any external
   folder validation. A confirmed prior receipt promotes the same UUID to the
   selected request even if the original path is missing or changed; the
   researcher can then clear the stale selection and explicitly reconfirm the
   original directory at its new location, or leave the request recoverable.
   If the journal definitively contains no receipt for that UUID, the
   uncommitted pending state is released. Failed reinspection leaves the UUID
   retained and blocks ambiguous new requests. No path is silently retargeted.

## Tests and explicit limitations

Disk-backed tests use real SQLite projects, the real supervised worker, the
actual workbook renderer, an external filesystem directory, full publication
and independent workbook observation. They cover two-step confirmation, stable
request IDs, restarted re-selection, wrong-directory rejection, no writes into
the wrong destination, project/run change invalidation, unsafe link rejection
and directory swap between offer/confirm/use, including a swap
**after the host's final check but immediately before the worker opens the
directory**. Other tests inject a transient post-preparation inspection
failure, verify no duplicate receipt or new request ID, and preserve the ID
when successive inventory reads fail. Earlier native-folder tests
exercise the asynchronous pywebview API using a controlled fake window; the
Windows graphical lifecycle test verifies that the external picker button is
actually rendered under an authenticated native session.

**Not claimed:** operating a *physical* Windows modal folder picker in the
automated graphical probe; a manual human-driven Windows dialog acceptance
case remains necessary. No externally targeted workbook scenario has been
independently demonstrated by the native lifecycle driver unless a separately
named scenario records it. An existing local test or rendered button does not
constitute full external save/recovery acceptance on Windows. Real disk-full,
filesystem permission changes, hostile same-user races, clean-machine WebView2
/.NET deployment, whole-product archive/import, installer, provider search,
100,000-record performance and production dependency adoption remain outside
this bounded experiment.

## Mandatory merge gate

Before recommending a merge, re-fetch the **exact current PR HEAD**; verify all
four core Python regression jobs, four graphical dependency jobs, and four
graphical lifecycle jobs, including actual relevant scenario receipts. Obtain
definitive completed exact-HEAD Codex **code** review first and separate
security review with matching timestamps and individual receipts; resolve or
explicitly disposition every substantive finding. A new commit resets
commit-specific review acceptance. Never merge without project-owner approval.
