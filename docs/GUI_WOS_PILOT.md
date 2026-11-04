# P1-06f7 — Host-confirmed Web of Science Starter pilot in isolated GUI

Date: 4 November 2026. Authority: the version-controlled
`RESEARCH-Y_SPEC.md` (SEARCH-06–14, SRC-05–08, RUN-01/03–05,
COUNT-01/03/05, AUDIT-01/03, UI-04/05, SEC-01/03–05;
partial AT-05/08/17/19/21).
Baseline: owner-merged PR #61, `main`
`3b2e9ffc998024bb18dcaeaed2b40a16e02e504f`.

## Function and consent boundary

This increment connects the already-reviewed
`research_y.wos_starter_pilot.probe_wos_starter_once` service to the
existing supervised, spawn-isolated worker and *experimental*
NiceGUI/pywebview local GUI. The researcher must open an actual local
project, select a pending immutable run, explicitly inspect its exact
source plan, click **Preview** for a stored Web of Science (WoS) Starter
Topic (`TS`) group query, and separately click **Confirm**. Only the last
action can contact Clarivate. No automatic, scripted or page-load
request is authorised. Cancelling the preview leaves no request receipt.

**The Starter minimum page size is 1, not zero.** The locked preview
states that confirmation makes one Starter HTTPS GET for page 1/limit 1
and can transiently return one licensed record. Core code discards that
record; only source count/quota, hash and audit-method evidence persist.
This is NOT PubMed's zero-record count-only ESearch, not final source
retrieval, not the whole OR-union count, and not a completed PRESS peer
review. Starter Topic does not search article full text or the browser
All Fields index. A provider-reported count of zero differs from an
unknown/failed count. Neither changes ordinary source query/run counts.

## Host-only credentials and source protection

The isolated **trusted Python host** may consume
`RESEARCHY_GUI_WOS_API_KEY` only from its preexisting startup
environment. The key is popped before the GUI/bootstrap is created.
Its exact value is validated locally, hidden from repr, never accepted
from a browser action, and transferred transiently only in the
allowlisted `wos_pilot_sample` command to the supervised worker.
That worker constructs a `WoSStarterClient` with **request_budget=1**;
there are no automatic HTTP retries. Browser state exposes only
`wos_profile_configured`. No key, licensed response or contact string
is persisted in project data, audit, recent-project history or ordinary
diagnostics. This is feasibility-only configuration, **not** the final
Windows installer or operating-system credential-store design.

An explicit **quota revalidation preview** is a distinct first action.
It sets `revalidate_quota=True` for that particular UUID after the
researcher confirms it. This does not bypass a server Retry-After, a
running worker, an unresolved prior Starter provider reservation or the
project's minimum spacing rule. Observed entitlement/quota and static
provider failure codes are displayed, without assuming a 5,000/day
tier or a reset deadline.

## Lost replies and recovery

The GUI retains the original attempt UUID, exact query and plan hash
while a worker result is uncertain. It blocks incompatible project/run
mutations and provides **Inspect original Starter receipt (no network)**.
This fetches the immutable audit receipt by UUID through the ordinary
worker. It must match the frozen identifiers/query, sample-only and
no-retained-record flags before the attempt can be cleared. If no
request was journalled, display `not_recorded`. A committed request
without an outcome remains `requested_indeterminate`: **no retry on
that UUID**, and the shared project quota guard may remain blocked
until a separately designed, explicitly authorised recovery procedure
safely dispositions the unknown attempt. A new authorised preview
cannot bypass that guard. A failed journal read leaves the original
UUID locked.

The published result states sample_only=true, count_only=false,
bibliographic_records_persisted=0, execution_authorized=false,
search_completed=false and source_retrieval_verified=false. There
is no historical-pilot browser, account-wide quota coordinator,
credential installer, live automated smoke, full source pagination
from the GUI, or accepted physical Windows click journey in scope.
The pre-existing PubMed pilot stays independently count-only.

## Verification

Offline regressions use real SQLite projects, the real supervised worker
for inspection/recovery, and synthetic Starter HTTPS transport for the
sole network-capable call. They cover cancellation, exact-query
authorization, profile isolation and malicious input, genuine zero and
positive counts, quota evidence, explicit revalidation, rejected
provider holds, failed receipts, lost responses, shared guard
invariants, absence of licensed and secret data, and no hidden network
call on browser-probe routes. This is not permission for live Starter
requests during continuous integration.

Before merge, require all four Python CI matrix jobs and any relevant
GUI checks on the exact HEAD, completed Codex code review first, then
completed security review with individual receipts and resolved findings.
Explicit project-owner authorisation is still required to merge.
