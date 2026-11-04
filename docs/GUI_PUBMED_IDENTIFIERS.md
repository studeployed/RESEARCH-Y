# P1-06h1 — Supervised PubMed identifier retrieval in the isolated GUI

**Baseline:** owner-merged PR #65 on main \`bd4c0070c4c474d142314ffc0d5dd57162aee1bc\`, 4 November 2026.
**Authority:** version-controlled \`RESEARCH-Y_SPEC.md\`, notably SEARCH-06–14, SRC-01–04, RUN-01–07, DATA-03–06, COUNT-01/03/05, UI-04/05, SEC-01/03–05 and partial acceptance tests AT-07/09/19/21. The scientific specification has not been changed.

## Scope and scientific boundary

This increment exposes the **existing** National Center for Biotechnology Information (NCBI) PubMed ESearch count, translation-validation, disjoint Create Date partitioning and transactional identifier-checkpoint services in the isolated, trusted-host graphical interface. It provides the first explicitly confirmed **PubMed identifier retrieval** from the GUI. It does not invent a new paging algorithm, modify search terminology, automatically include Medical Subject Headings, introduce language/species exclusions or equate an identifier list with a complete bibliography.

The source plan is reconstructed from the originally frozen, researcher-approved **OR-only** strategy, cross-checked against exact stored PubMed All Fields queries and the full run version, even if another independently executable group has advanced. Initial checkpoint creation revalidates the frozen source/run preflight hash **inside the same database write transaction** as the first immutable plan and audit receipt. No browser may provide its own source query, file path or provider credentials. Read-only original-checkpoint inspection remains possible without a configured NCBI contact or API key.

## Explicit session, quota and coverage

1. Select a project and approved run, enter a **calendar-date range** for administrative Create Date partitioning, and click Preview for one existing PubMed query. A default is displayed but never submitted automatically. The range does not intersect or filter terms in the scientific search. It is used only if the unfiltered root query exceeds the conservative **9,000-ID** single-window ceiling.
2. Inspect the original exact OR query, group identity, request budget and date interval, then click a separate **Confirm bounded PubMed identifier retrieval** button. Up to **128 ESearch requests** may be made in this explicit session, including count-only translation probes and 200-ID pages. No automatic second session, background run or retry is triggered by project reopening, passive polling or a successful previous session.
3. If the source contains over 9,000 hits, the original partitioner checks the Create Date coverage count against the **unfiltered root count**, recursively splits only disjoint intervals, and verifies no gaps, overlap or count drift. If the chosen administrative range misses any hits, or the probe budget is exhausted, the source is **incomplete**, not silently narrowed. The GUI never turns an incomplete count into a fictional zero.
4. Identifier pages are committed to the original authoritative project transactionally, with exact source query, request dates, partition evidence, unique identifiers, page checksums and pause/recovery status. A session that exhausts its local budget returns incomplete without deleting previously committed pages. A separately confirmed resumed session uses the original stored plan and does not fetch already-committed offsets.

The NCBI contact email and optional key are loaded from trusted Python-host configuration, passed transiently to the separate supervised child, and omitted from the browser state, result envelope, worker representation and project audit. Requests use the existing fixed HTTPS POST endpoint, original 0.4-second minimum pacing, no implicit retry and a 15-second HTTP timeout. An explicit session budget is not a source count cap: larger valid projects may require multiple confirmed sessions. Full source records and abstracts will be retrieved later using the existing separately bounded EFetch metadata collector.

## Responsive progress, pause, and recovery

A separate \`ApplicationWorker\` supervises each long PubMed identifier session while the existing read-only worker inspects progress without blocking the GUI. The interface shows the actual reported match count (or UNKNOWN), committed page count, number of stored identifiers, verification status and worker state. A passive two-second timer does **read-only inspection**, never provider requests.

The researcher may request a cooperative pause after the first durable plan exists; the previous successful page remains preserved, and an in-flight page may finish before the worker observes the pause. A pause requested before there is a checkpoint is refused rather than claiming to have interrupted an unjournalled count-planning phase.

The GUI requires a **terminal supervised child** before reconciling its exact result with the original database checkpoint. Worker interruption/failure is not interpreted as a completed search or as proof of zero provider calls. The application does **not** continue running source work after it closes; interrupted, missing or inconsistent pages require manual inspection and a fresh explicit resume confirmation. This slice does not establish a durable provider-wide in-flight request reservation for the pre-checkpoint count-only phase, a cross-machine exclusive source writer, or automated recovery of ambiguous HTTP outcomes; those safeguards remain explicit limits and follow-up requirements rather than implied successful recovery.

A reconciled ESearch identifier checkpoint remains **\`identifiers_reconciled_metadata_pending\`** and **\`source_retrieval_verified=False\`**. No EFetch bibliography, abstracts, cross-source unique publications, whole-run verified count or completed project archive is claimed.

## Validation and acceptance limitations

Offline regression tests use the real compiled versioned run and SQLite project, original PubMed ESearch parser, checkpoint writing, partitioner and resume mechanism, with synthetic controlled HTTPS transport. The tests cover preview/cancel with no network; strict source identity; date validation and absent date coverage; count-only budget exhaustion versus genuine zero; page preservation across pause and resume; a fully reconciled small-ID search with metadata still absent; no plaintext credentials or source IDs returned in browser status; exact supervisor terminal/result reconciliation; restart inspection without credentials; and a read-only automated GUI route.

No new dependency or schema version. Native Windows graphical click-journey validation, live-source rate/entitlement checks, large partition count plans, complete EFetch bibliographic metadata, peer review of actual search translations and full end-to-end Phase 1 acceptance remain outstanding. All normal pull-request and push continuous integration (CI) is offline.

Before merge, require all four Windows/Linux Python configurations, applicable graphical dependency and lifecycle checks, completed exact-HEAD Codex code review followed by security review, disposition of all substantive findings, and explicit project-owner authorisation.
