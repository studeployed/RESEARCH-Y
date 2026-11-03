# P1-06f2 — Experimental graphical Research Setup and explicit strategy approval

Baseline: owner-merged PR #56, `main` commit `0511e02b4a4183eb8db0f73feb4d0bf9aee9e726`.
Parents: #41, #43 and #9. The repository `RESEARCH-Y_SPEC.md` is unchanged.
Bounded coverage: SEARCH-01/02/05/06/07/08/09/10/11/12/14,
UI-02/03/04 (partial), ARCH-01/02/03, PROJ-04/07, SEC-04/05,
and scoped acceptance AT-04/05/17/19/21.

## What is now functional in the isolated NiceGUI/pywebview prototype

In an explicitly opened project, the researcher may enter and edit a theme and
approver, add/rename/reorder/remove concept groups, add/edit/reorder/remove
atomic terms, choose individual term origin (researcher, deterministic or
AI-assisted with required rationale), and disable a term without deleting it.
Group/term IDs are created by the trusted Python host; the browser never
submits a filesystem path, project root or source query to the worker.
Group ordering/term ordering are not Boolean operands: all enabled terms and
all named groups form a **logical OR**. No hidden conjunction, exclusion, Medical
Subject Headings (MeSH) expansion or default filters are introduced.

A separate **Preview exact broad-OR source queries** action runs the already
approved deterministic compiler entirely in local memory. The interface
shows exact PubMed `[All Fields]` and Web of Science Starter `TS` group
expressions, a logical overall union, group/term counts, source coverage and
compiler warnings, with explicit unknown provider match counts and
`not_executed` status. Web of Science Starter Topic is *not* article full
text or web-interface All Fields. An invalid term/syntax fails closed; no
query is submitted. In the **preview state all editable controls are hidden**
and the user must click **Revise draft** to return to editing. Edits then
invalidate the preview and prohibit approval until the researcher re-previews
the current draft. Browser input typed but not explicitly saved cannot be
mistaken for a reviewed, approved term.

Only **Approve frozen strategy and create pending run**, a distinct user
button appearing after successful preview, creates a durable version. It
invokes the pre-existing `commit_approved_strategy` through a validated
allowlisted `ApplicationCommand` in the supervised `ApplicationWorker`,
not from the browser or NiceGUI event loop. The worker checks explicit
approval, content, project identity and the query compiler again, then uses
the existing atomic SQLite transaction to freeze a strategy, create one
pending run, plan both primary source queries and journal the actual action.

The host owns an idempotency UUID and an immutable copy of the submitted
draft while an outcome is uncertain. Lost worker reply or failed
post-commit inspection preserves that UUID and the exact approved fields;
the UI offers an explicit retry of that same request. Editing, changing
projects or selecting another run is blocked until the authoritative
storage-backed inventory confirms the new run. A returned worker success
alone is **not** treated as confirmed. On confirmed admission, a fresh draft
appears and the stored run remains unselected until the researcher explicitly
chooses it from the run list. No search retrieval is falsely certified.

## Deliberate scope limits and follow-on work

This is an **isolated feasibility adapter**, not production adoption of
NiceGUI 3.18.0 or pywebview 6.2.1, a distributable Windows application or
completion of full Research Setup. The current section handles researcher
text and approval, **not** objectives editing, persistent draft saving,
term expansion, society-source selection, optional limits, known-relevant
tests, PRESS peer review, pre-run workload estimation, live provider counts,
query-translation checks or actual search execution. It does not alter the
project specification, add a schema, model, hosted service or runtime GUI
dependency. The existing `/ _probe/start` test-only route (without the space)
has no ability to submit terms or trigger setup approval.

The grouped form is currently a modest feasibility interface. Accessibility,
large-table performance, browser reconnection, 100,000-record behaviour and
manual physical Windows acceptance remain separately gated; do not infer
them from a static control or a synthetic fixture.

## Evidence and merge gate

Tests cover drafting/reordering/removing/disabling terms, invalid input and
quotes, proof that previews do not mutate project storage, exact compiled
queries, real supervised-application-worker approval, SQLite audit/query
counts, loss of worker reply, inspection failure, repeated request ID and
whole-workbook export of the new pending run without false source completeness.
Cross-platform Python jobs are mandatory. Existing graphical dependency and
native-lifecycle probes retain their previous acceptance scope; the new
editor's complete user-driven browser click journey has not been claimed
unless it is separately evidenced. Require definitive completed exact-HEAD
Codex code review, then completed exact-HEAD security review, individual
receipts and disposition of findings. Owner authorisation is mandatory
before merging.
