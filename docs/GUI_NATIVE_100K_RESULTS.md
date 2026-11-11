# P1-06k4e — Actual native Windows browsing of 100,000 provisional publications

**Authority:** unchanged version-controlled `RESEARCH-Y_SPEC.md`. **Baseline:** owner-merged pull request (PR) #88, `main` `92c0b4c56474f0c3978010cab1558898fa5dcbbc` (11 November 2026). This is a bounded Phase 1 graphical acceptance increment, not a claim that the finished RESEARCH-Y application satisfies AT-22.

## Missing evidence after PR #88

PR #88 drove real native Windows confirmation and recovery against **100,000 retained original source records**, but it materialised only **256** provisional publication hypotheses. PRs #82–83 measured actual **100,000 fully materialised** source records, including a single 100,000-record selected run and 20-row publication/candidate reads, but did **not** interact with rendered native Windows publication pages.

This increment combines those separate paths in a **read-only GUI browsing scenario**, using existing data services with no new source connector, query rule, scientific filter, deduplication policy, production database schema, dependency or user-facing automatic processing.

## Scenario and trust boundaries

The original `_large_fixture` creates a valid approved synthetic broad-OR strategy, exactly 100,000 original source retrievals, 100,000 original query/group memberships and 128 independently audited provisional identities, all in one selected run. The already-tested **fixture-only** `materialise_remaining_fixture` then adds 99,872 independent provisional identity links using bounded original-validating SQLite transactions and the production audit writer. This helper is never an application command and cannot be invoked by any browser action.

The test opens the resulting original versioned SQLite project through the existing host-selected project interface and explicitly selects the run. Its original graphical controls are then exercised in this fixed order:

1. Click **Refresh provisional results (OFFLINE)**: inspect the first **20** real original-source-linked rows; **100,000** provisional identities; zero currently unmaterialised original sources; **unknown** unique-publication count.
2. Click **Next 20**: the original worker validates the previous cursor and revision; the second **20** identities must be distinct, sorted and in the same run/evidence revision.
3. Click **Inspect original source evidence** on the first visible second-page row. The original source/metadata projection, group membership, rights indicators and provenance must be displayed, with abstract text and redistribution rights **not** assumed.

On Linux, the guarded authenticated local transport executes the actual fixed host operations. On Windows, automated real pywebview controls are clicked in the native window and the resulting **rendered** 20-row state, source details, incomplete/unknown notices and correct status are checked. The HTTP test endpoint does **not** accept publication IDs, cursors, paths, source text or work amounts: the disposable host derives the next-page cursor and selected source ID exclusively from its last verified page. Browser controls remain the original production-hardened flow, with original 35-second per-worker bound unchanged.

The test runner independently reopens the real SQLite file and verifies all original source, membership, publication, source-link and audit counts; individual publication identities, unchanged original SHA-256 digests, `integrity_check` and foreign keys before and after the GUI interaction. Only bounded aggregate evidence and elapsed benchmark intervals are stored in uploaded workflow artifacts—no source text, licence-restricted metadata, personal content, paths, cookies, identifiers or original databases.

## Acceptance boundaries

This gives **partial** evidence for `UI-07`, `UI-08`, `AT-10`, `AT-19`, `AT-21` and `AT-22`, not their completed acceptance.

- The native window **does not render all 100,000 rows at once**; it renders one 20-row bounded page at a time and measures that genuine interaction. It does not prove complete usability, sorting, faceted filters, search, accessibility, memory tolerance on all hardware, or installer support.
- The **100,000 provisional publication identities are not proven distinct real publications**: the fixture intentionally contains equal-title and equal-digital-object-identifier cross-source reports, with no automatic merge. `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false`, and `full_AT_22_acceptance=false`.
- All bulk materialisation is test-only; researcher-authorised production materialisation retains its original finite two-batch consent. No provider API requests, AI model, classification, licence redistribution, export or background processing is exercised.
- Timings are observed on ephemeral GitHub hosted runners, not guarantees. A failed, timed-out or incomplete original worker/page makes the acceptance **fail**, not pass with warnings.

## Review and merge gate

A new `.github/workflows/native-100k-results.yml` runs native Windows and guarded Linux tests on Python 3.12 with the pinned approved **experimental** NiceGUI/pywebview candidates. Ordinary four-platform Python tests assert non-overlapping pages and explicitly reject false-unique/incorrect totals. Preserve existing original 132- and 100k-window GUI workflows and graphical dependency/lifecycle checks.

Before recommending merge verify exact current HEAD, all required Python/graphical/new workflow jobs, definitive completed Codex **code review first** then **security review** matching the same exact commit (automatic security reviews count only when definitively completed), all individual receipts and disposition of substantive findings. No merge without explicit owner authorisation.
