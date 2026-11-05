# P1-06j2 — Local provisional-publication results and provenance

**Baseline:** owner-merged PR #70, `main` `c1c5d7b4c7812c72441e533af0faa33b82d08a69`, 5 November 2026. **Authority:** repository `RESEARCH-Y_SPEC.md` unchanged. Phase 1 parent #9/#30/#33/#35/#41/#43. Partial DATA-01–06, DUP-01–05, COUNT-01/02/03/05, UI-05/06/07/08/09, AUDIT-03 and AT-01/09/10/11/17/19/21. Nothing here satisfies final Master Results, final counts, 100,000-record performance or full publication reporting.

## What is available

The experimental real-project graphical application adds a **local-only** provisional publication results section for the explicitly selected run.

- `publication_results.read_publication_page` returns at most **20** current publication-identity hypotheses per page with **keyset/cursor navigation**, current run group/source memberships, source-record multiplicity, individual review-required/confirmed retrieval links and a stable count-evidence SHA-256. A linked publication can have records from earlier runs, but current-run source and group denominators remain separate. The page always distinguishes **saved source records without a publication link**.
- An explicit **Refresh** starts at the first page. The **Next 20** operation uses the saved cursor and the same original count revision. After source-count, group, identity, field-choice or relevant audit decision changes, the old revision is rejected; the user must refresh. No offset-based skipped pages or apparent silent truncation. The browse flow has no network capability.
- A per-row **Inspect original source evidence** view exposes the chosen-field provenance (when present), bounded per-source bibliographic alternatives and field paths, original provider IDs, source type, abstract **availability status** (not abstract body), rights flags, source-query status and all original group memberships for the selected run. A source title shared across records is a **display observation**, not independent proof of one publication. Conflicting unchosen source titles remain unresolved rather than picking one.
- To avoid an empty results screen for a run with retained source metadata, **Preview** and a separate explicitly clicked **CONFIRM** create up to **64 independent review-required** identities via PR70's unchanged, transactional and revision-fenced materialisation service. No network or automatic duplicate candidate association occurs. After a lost worker reply, the old consent cannot be replayed against a different batch; re-preview the durable database. The source-record store, query memberships and original counts remain untouched.
- All commands pass through strict trusted-host allowlisting and the existing supervised `ApplicationWorker`, not a direct arbitrary browser file/SQL endpoint. Untrusted text is presented only with NiceGUI text widgets. The source identifiers, cursor and selected-row revision are validated by both host and child; the host checks that a detail row was actually in the displayed page before opening it. Project selection and run selection clear previous browse state.

## Scientific and rights safeguards

**`global_unique_publications=null` always remains true** in this increment; `verified_complete=false`, `source_retrieval_verified=false`, `deduplication_complete=false`. The word **provisional** is displayed prominently. A researcher-confirmed pair association can reduce the number of current identity hypotheses, but it does not establish exhaustive duplicate discovery or published unique-publication counts.

This interface does **not** download, export, redistribute, or render abstracts or full original licensed records. It displays only bounded local citation fields and explicit source-rights/absence notices. Fields too long to display are flagged, **never silently shortened**. No field is inferred to be English, human-only, a specific design or eligible. A source record describing a conference abstract must still be independently verified; a supplement DOI is not a safe merge rule. Researcher-selected field values retain their exact original source and auditable field-selection event ID.

## Scope limitations

This is deliberately a **read-only inspection and identity-preparation** increment; a browsed item cannot be arbitrarily merged or split through this interface. The already-implemented explicit candidate comparison, decision and reversal services remain separate and require further tested GUI integration. No automatic cross-run decision propagation, sophisticated search/filters, full abstract display, all-sheet Excel export, cached 100,000-record UI performance, source acceptance promotion, archive packaging or Windows installer is claimed.

The current count validation reads the entire authoritative run before showing a page. This prioritises consistency but does not prove acceptable latency on very large repositories. User-facing paging is bounded even when counts are much larger than 20; full AT-22 performance remains unresolved.

## Validation and merge gate

Offline tests in `tests/test_publication_results.py` exercise saved-record visibility, exact title/DOI non-merging, explicit association and competing titles, rights-safe detail, 20+3 paging, stale revisions, linked earlier-run sources, non-HTML titles, invalid IDs, trusted command confirmation/forged extras and read-only SQLite checksums. Tests rely on synthetic PubMed and Web of Science Starter record shapes and real SQLite transactions.

Completion is conditional on all four Python Windows/Linux versions, applicable experimental GUI/dependency/lifecycle checks, definitive Codex code and security reviews covering the **exact current HEAD** with individual receipts and findings dispositioned, and explicit project-owner authorisation to merge. Never merge automatically.

**Next increment:** integrate the already-defined **read-only comparison and explicit user-confirmed match/reject/reversal** workflows with fresh evidence tokens in the results GUI; preserve both original records and every previous decision. Later implement indexed project-wide duplicate discovery, non-destructive title/abstract search, richer filters, reference-manager and publication-ready exports and final acceptance.
