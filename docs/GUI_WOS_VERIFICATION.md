# P1-06g2 — Supervised multi-page Starter verification and read-only GUI monitor

**Baseline:** owner-merged PR #64 at `main` `d1cbe4137175846deb6a818b06b56bcd94316f61`, 4 November 2026.
**Authority:** version-controlled `RESEARCH-Y_SPEC.md`, SEARCH-12–14, SRC-05–08, RUN-01–07, COUNT-01/03/05, AUDIT-01/03, UI-04/05, SEC-01/03–05, with only partial AT-08/09/19/21 evidence.

## Scope and why this follows PR #64

PR #64 added an experimental local graphical workflow for explicit Web of Science (WoS) Starter metadata-retention consent, then separately confirmed three-request acquisition sessions. The original checkpoint runner records every returned page, but it requires **one uninterrupted verification epoch**: a fresh count/first-accession probe, every acquired page rechecked in order, and a final source-count/first-accession probe. PR #64 deliberately refused further short sessions once a multi-page query reached the `verify` or `final` stage, preventing an endless cycle of repeated first-page verification and wasted quota.

This increment admits **only an already prepared, GUI-authorised, fully acquired source query** to a distinct longer-running supervised verification worker. It is NOT another acquisition engine, an API browser endpoint, a separate research project runner, an archive export, or a completed two-source literature search.

## Session plan, limits and consent

The read-only `wos_acquisition_verify_plan` worker operation reads the original immutable checkpoint, confirms the exact run/source identity and graphical retention admission, verifies the query has all captured pages and no unresolved request/worker reservation, and computes an **exact required request budget** from original durable source evidence:

`1 resume probe + N verification pages + 1 final probe = N + 2 requests.`

For the experimental long worker this must be at most **512** total HTTP requests, meaning no more than 510 50-record verification pages. This is a **bounded protocol budget, not a search-size restriction, hidden filter, provider entitlement claim or scientific completeness threshold**. A larger checkpoint is preserved as incomplete with an explicit unsupported-in-this-slice response, pending a future scalable/longer-running workflow. The GUI shows the frozen exact query, page count, request budget, warning about licensed content and institutional quota, and requires a **separate explicit Confirm** click. A distinct quota-revalidation preview does not bypass provider Retry-After, shared quota holds, unresolved pilots, worker fencing, or observed daily entitlement.

Only the trusted Python host obtains the existing Starter key, passes it transiently to the allowlisted child and constructs a fresh `WoSStarterClient` with 512 hard requests and a 10-second per-request timeout. The service independently rechecks original plan SHA-256 and required budget immediately before any provider call. Browser actions cannot supply credentials, source text, local paths, raw budgets, extra fields or licence assertions.

## Responsive monitoring and failure semantics

The existing `ApplicationWorker` supervises a **separate spawned child process**. Unlike the ordinary 35-second command wrapper, starting long verification returns immediately; the GUI event loop remains responsive. A second existing supervised worker performs read-only checkpoint inspection while the source child is running. The GUI displays worker state and the durable ledger's actual recorded matches, retrieved records, verified pages, request counts, quota and uncertainty markers. A two-second host timer performs **read-only polling only**. It never triggers provider calls, retries, result fabrication or cancellation.

The user may explicitly request a **graceful pause** through the existing `pause_wos_checkpoint` service, which cannot issue a provider request and is refused before durable worker ownership is established. An already in-flight source request can still finish before the child observes the saved pause. The host reports only a cooperative request until the supervisor definitively terminates.

On any completion, failure or interruption, the GUI **must reconcile a terminal supervisor receipt against the original durable source checkpoint**. It does not equate a returned Python dictionary or a successful HTTP response with a verified search. Project/run changes remain locked until reconciliation. A stale active worker token, unknown source request, altered plan/response or contradictory ledger remains blocked; there is **no automatic reissue** and no automatic clearing of stale worker ownership. Closing the application uses the supervised child process shutdown/reaping contract and may leave explicit stopped-worker recovery necessary before another request. This increment does not claim crash recovery from an arbitrary previous owner or physical Windows click-journey acceptance.

A successfully reconciled Starter enumeration retains `completed_with_warnings`, `enumeration_reconciled=True`, and `source_retrieval_verified=False`. It proves only the recorded accession/page consistency under the observed provider behaviour. It **does not** imply an atomic provider snapshot, complete abstracts, a reconciled global OR union, cross-source publication deduplication, or a whole-run verified-complete search.

## Tests, integration, and outstanding acceptance

Offline synthetic source tests exercise the real WoS client, parser, quota-aware runner and disk-backed SQLite ledger through a three-page acquisition followed by a five-request uninterrupted verification and final recount; they check no duplicate acquisition/metadata, preserved original records, no leaked licensed titles/keys and unchanged incomplete whole-run status. Further tests check stale/fabricated receipts, exact-budget rejection, invalid types/consent, source-volume cap, read-only progress, one confirmation per worker operation, worker interruption/unknown owner fencing, original event-loop display controls and cooperative pause. Tests use a deterministic supervisor double for the GUI state machine; existing platform-native worker/process lifecycle suites remain authoritative for actual spawn and reaping.

**Not completed in this increment:** full-length real-source live verification, source quota resets across days, provider snapshot guarantees, account-wide quota coordination, long-session reliability at 510 pages, direct native Windows click acceptance, terminal stopped-worker recovery without independently proven shutdown, user-visible full-master results, full metadata/abstract enrichment and whole-run acceptance. Continue Phase 1 with supervised PubMed retrieval, multi-source run orchestration and comprehensive failure/recovery evidence.

Merge requires four exact-HEAD Python regression configurations, applicable graphical dependency/lifecycle checks, definitive completed exact-HEAD Codex code review followed by security review with individual receipts and dispositioned findings, and explicit project-owner authorisation. No automatic merge, source credential use or live provider call in CI.
