# P1-06j1 — Explicit run-wide provisional publication materialisation

**Baseline:** owner-merged PR #69, `main` `479956e23338b016d336e49c39e59840cb083398`, 5 November 2026. **Authority:** the repository `RESEARCH-Y_SPEC.md` is unchanged. Parent issues #9, #30, #33 and #35; partial DATA-01/02/04/05, DUP-01/03–05, COUNT-01/05, AUDIT-03, PROJ-04 and AT-01/09/10/11/17/19/21.

## Why this is the next bounded increment

PubMed EFetch and Web of Science Starter now persist their original source records. An existing identity service can make a **single** retrieval into a review-required publication hypothesis, but nothing prepares a whole run for the eventual master results screen. It would be scientifically wrong to call the retained source-record count a distinct-publication count or to merge two records just because their titles, DOI or supplement identifier agree.

`preview_run_materialisation(project, run_id, batch_size=64)` is an **offline, read-only** view over the original identity-checked SQLite store. It uses the existing canonical full-run count projection, validates current source/identity evidence, and reports retained records, existing provisional identity count, unmaterialised retrieval count and a SHA-256 revision binding the exact next batch and full-run evidence. It does not expose licensed metadata, queries, provider credentials or titles. No provider calls are possible.

`materialise_run_batch(project, run_id, expected_revision=..., actor=..., confirmed=True, batch_size=64)` requires an explicit literal confirmation and the **current** preview. It rechecks all evidence under a single SQLite `BEGIN IMMEDIATE` transaction before writes, then creates at most **64** distinct one-retrieval identities using the existing `publication_identity._record_link` audit service. It is **not** an automatically merged publication list. Every new decision has status `review_required`. Previously associated records, confirmed merges, field choices, annotations and rejected pairs are never reinterpreted. The source records, query/group memberships, source reported counts and approved search strategies are not modified. The 64-record transaction limit is not an acquisition or export limit.

A failed batch rolls back all its new identities and audit events. After a successful commit or process termination, a newly opened project can preview the **remaining** unassociated records and continue. Reusing a consumed or stale revision is rejected instead of silently acting on a different batch. An empty run reports a true zero remaining identities but refuses a fabricated successful batch. Corrupt metadata or damaged identity evidence fails closed.

## Deliberate limitations

This is a core processing service, **not yet a GUI button**, unattended operation or final result. It creates conservative initial hypotheses for existing stored metadata; it does not fill missing PubMed EFetch data, identify missing source pages, verify source completeness, discover all duplicate candidates, make automatic identity decisions, or calculate verified global unique publications. `global_unique_publications` stays `null`; `deduplication_complete`, `source_retrieval_verified` and `verified_complete` remain `false`. Source rights are not expanded, and the new interface has no metadata export permission.

The full-run integrity projection is intentionally revalidated on each small transaction, which prioritises safety over throughput in this first increment. No 100,000-record performance claim, live source call, native Windows interaction, graphical command exposure or multi-user concurrency acceptance is made. Separate source and interface gates remain open.

## Offline verification and next step

The committed disk-backed tests cover same-title/same-DOI **non-merging**, repeated concept-group memberships, source-only versus queryless retrievals, cross-run isolation, strict confirmation and batch-size bounds, stale previews after another association/query change, reopen-and-resume, empty/no-op behavior, a transaction-aborting audit trigger, damaged stored metadata and 64+3 bounded work. The complete Windows/Linux Python continuous integration matrix and exact-HEAD Codex reviews are mandatory before merge; this document does not claim them passed.

**Next:** a paginated, read-only master-publication inspection interface with alternative source fields, memberships, provisional identity status and access to existing explicit candidate/association review. This next GUI stage must retain rights boundaries, count caveats and stale-review fencing. Project-wide duplicate discovery and final publication verification remain separate acceptance work.

**Merge rule:** no automatic merge. Verify the exact current HEAD, four Python platform/version checks plus applicable GUI/lifecycle checks, definitively completed code review then security review and every substantive finding, followed by explicit project-owner authorisation.
