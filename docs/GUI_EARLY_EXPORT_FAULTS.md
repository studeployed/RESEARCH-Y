# P1-06e2h — Early workbook rendering/staging fault recovery

Date: 2 November 2026. Continues #43 / #41 / #9 on the authoritative
repository RESEARCH-Y_SPEC.md and the owner-merged PR #50 baseline,
commit `65c38049f68112e936450a87583d877937e91488`.

This remains within the previously approved **isolated NiceGUI 3.18.0 /
pywebview 6.2.1 feasibility experiment**. It is not an approval to adopt
the graphical framework in production, ship an installer, make live provider
requests, or change search methodology. No new third-party dependency,
schema, credentials, provider call or production publication algorithm is
introduced.

## Why this increment matters

The original report is frozen when the `prepared` audit event commits. Later
renderer or staging-write errors must neither destroy that snapshot nor
create a new export request. No output may be called "verified" merely because
some bytes or an audit record exist.

The local application must distinguish the **recorded journal phase** and
original error from the **latest observed file outcome**, with unknown source
counts and an INCOMPLETE research status preserved. A subsequent retry
must operate on the **same export universally unique identifier** and must
not delete or overwrite incomplete, mismatched staging evidence.

Relevant specification requirements: ARCH-02/03, PROJ-04/06/07, AUDIT-01/03,
EXPORT-01/03/04, SEC-04/05, UI-05/10 and scoped acceptance tests
AT-09/18/19/21.

## Bounded, reproducible fault injection

All exceptions below are injected **only in a disposable test subprocess**
before the real graphical host is launched. This is not evidence that the
runner's physical drive was exhausted, Windows access-control lists were
modified or an actual GUI-owned worker was killed.

1. **Renderer access denied.** A renderer callback raises a Python
   `PermissionError` with an injected `EACCES` condition. The existing
   publication service records `render_failed` and retains the original
   `prepared` receipt. No staging file or final workbook should exist.
   Independent file observation is `not_yet_staged`, not verified.
2. **Partial staging write / injected disk full.** A guarded
   `Directory.write_new` call writes an owned, intentionally incomplete
   retained-stage file using the real exclusive-create and flush behavior,
   then raises `OSError(ENOSPC)`. The service records `storage_failed`
   while retaining its `staging` journal event. Independent observation
   must report `retained_artifact_changed`. The partial file must remain
   unmodified even after a successful retry.

The subprocess uses an allowlisted environment. It cannot receive research
source credentials and does not expose private exception text, project
paths, corpus material or log files in uploaded artifacts.

## Real application and graphical test contract

- The first graphical session opens an actual project, explicitly selects
  its saved run/export ID and **observes** the durable negative state.
  It shows a RECOVERY REQUIRED message and the recorded failure code.
  This inspection is read-only: no new audit events, export UUIDs,
  publications or successful status are created.
- The graphical process closes and a fresh instance reopens the original
  request. **Resume publication** invokes the existing supervised worker
  without client-supplied filesystem paths. It renders from the retained
  report and publishes a real formatted Excel workbook with a committed
  `published` receipt.
- A separate **Verify workbook** observation must report
  `published_verified` with `audited_success=True`. The independent
  research search remains INCOMPLETE, with no invented provider counts.
- The initial error and negative observation are not overwritten to pretend
  success before recovery. The abandoned partial stage remains untouched,
  and there is one canonical export ID throughout.
- Tests cover both the authenticated local transport and the actual
  Windows native-window buttons on Python 3.12/3.13, without weakening the
  pre-existing lifecycle, loopback, document-safety or worker teardown
  checks. All earlier publication, cancellation, missing-final-receipt,
  relocation and restart cases remain in the suite.

## Explicit outstanding scope

Representative *real* operating-system disk exhaustion and permission/ACL
failures; GUI-owned worker death while writing; simultaneous independent GUI
sessions; native folder picking and external export destination selection/
reconfirmation; dependency and embedded-frontend licensing review;
offline packaged launch; production framework adoption; the 100,000-record
performance gate; broad publication browsing, retrieval and full exported
workbook scope all remain open under #43/#41 and later milestones.

The initial Windows 3.12 native-startup intermittency observed during PR #50
is separately recorded in #43. Passing this experimental test does not close
that reliability concern.

## Merge protocol

Inspect the current PR HEAD, all four jobs in each required core, dependency
and graphical-lifecycle matrix, and the actual scenario evidence. Verify
definitive exact-HEAD Codex code-review status, completion time and individual
receipt; then verify the corresponding security review, whether auto-triggered
or requested. Explicitly disposition substantive findings and revalidate
after every new commit. Do not recommend or perform a merge until all gates
are verified and the owner authorises it.
