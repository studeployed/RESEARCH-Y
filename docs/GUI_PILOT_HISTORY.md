# P1-06f8 — Restart-visible, read-only source-pilot audit history

**Baseline:** owner-merged PR #62 at main d78a35990fe64905591025a504bb413a9a7f15e0, 4 November 2026.
**Authority:** version-controlled RESEARCH-Y_SPEC.md (SEARCH-12–14, RUN-03–06, COUNT-01/03/05, AUDIT-01/03, UI-04/05, SEC-01/03–05, partial AT-01/05/17/19/21).

## Purpose and sequence

The PubMed ESearch zero-record count-only and Web of Science (WoS) Starter one-record minimal-page pilots write immutable request/outcome audit evidence. Their immediate graphical-interface state is transient; previously reopening a project could not display those historical attempts. A crashed Starter pilot can leave the shared quota guard blocked indefinitely pending a separate authorised recovery mechanism.

This increment introduces **read-only recovery visibility**. It does not release indeterminate reservations, retry either provider, change source counts, or promote any pilot into verified retrieval.

## Persistence and audit integrity

The new read_pilot_history service reads one consistent SQLite transaction, with newest request events first and 25 events per page. A strict positive-integer event-ID cursor exposes older requests. The global denominator is **request events**, not successful HTTP transmissions or matched publications. A request receipt may have committed before network transport occurred. A true observed match count of zero is distinct from an unknown outcome.

Before displaying history, the service checks the project-wide topology of both known source-pilot journals, rejecting orphan outcomes, duplicate identifiers, malformed JSON and out-of-order outcome events. Every visible row is revalidated with its source's existing strict audit parser and derived view. Results omit query text, provider translations, keys and licensed payloads; separate detail inspection uses the existing original-ID read operation. No other project path or SQL expression is accepted through browser actions.

## GUI restart and recovery

On project reopen, the trusted host reads saved pilot history through the supervised, network-free worker operation. No PubMed contact or Starter key is needed for this read. The GUI displays both sources and earlier runs, with an explicit warning on requested_indeterminate. Refresh, older-page and historical-detail operations cannot issue provider calls. If historical audit data is invalid or unavailable, project/workbook access remains usable while the pilot history shows an explicit unavailable warning—not an invented empty ledger.

Historical detail is refreshed by the original source receipt reader. If a provider outcome changes between listing and detail lookup, the interface refuses the mixed view and requires another history read. The original WoS quota guard continues to prevent unsafe new requests independently of this interface.

## Verification and limits

Offline regressions cover empty/zero/unknown distinction, mixed sources, request pagination without loss, malformed/duplicate/orphan events, worker command validation, close/reopen with no credentials, stale snapshot refusal and preservation of unknown provider holds. No live database call is authorised in normal continuous integration.

This is not full source execution, archival export, abstract metadata collection, background work, product credential management, comprehensive history performance benchmarking, manual physical Windows click acceptance, or complete AT-01/09/19/21. It adds no schema migration or external dependency.

Before merge require all four core Windows/Linux Python tests, applicable GUI checks, definitive exact-HEAD Codex code review followed by security-review verification, individual review finding dispositions and explicit owner authorisation.
