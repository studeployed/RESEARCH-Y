# P1-04g — Controlled live PubMed >10,000-ID recovery acceptance

**Status:** Proposed, unmerged validation workflow. Offline tests are not
evidence that the live >10,000-ID test has succeeded.
**Specification:** SEARCH-07, SRC-01–03, RUN-04–07, COUNT-01/03/05,
AT-07/09/19 in the unchanged authoritative `RESEARCH-Y_SPEC.md`.

## Confirmed baseline

[Live run #41073931474](https://github.com/studeployed/RESEARCH-Y/actions/runs/41073931474)
on 30 October 2026 at 14:42 UTC reported **19,479** matches for the fixed
`("ECMO"[All Fields])` query, and obtained one PMID (42958294) with
matching EFetch bibliographic XML and three abstract sections. A one-record
smoke does **not** establish complete source retrieval.

PubMed ESearch exposes only the first 10,000 matching identifiers for
a single query. A source count exceeding that ceiling requires
non-overlapping, count-reconciled partitions before any completeness
claim. This increment tests the existing production implementation.

## Opt-in bounds and source etiquette

The new `.github/workflows/pubmed-live-identifiers.yml` is manual
`workflow_dispatch` only: **no push, pull-request, schedule or automatic
credentialled calls**. It shares the original PubMed smoke concurrency
group. The exact fixed public query is compiled from an approved
diagnostic term (ECMO) using the normal broad OR-only compiler.
The source contact and optional key remain private GitHub Actions
repository secrets.

The intended Create Date ([crdt]) **administrative** interval is fixed at
1900-01-01 through the UTC execution date plus one day, inclusive, and
is explicitly recorded. This is only a controlled diagnostic interval,
not a scientific date filter/default. The range count must equal the
unfiltered root count or the run fails incomplete, avoiding silent
loss of older/out-of-window records.

- The live source count must be strictly greater than 10,000 and no
  greater than **30,000**. This is a safety budget for this diagnostic,
  not a product search limitation.
- The production safety ceiling remains **9,000 per partition**;
  diagnostic page size **500**, up to **64 partition count probes** and
  **160 network requests per process**. Existing 0.4-second pacing
  remains below the unauthenticated NCBI 3 requests/second limit.
- Only weekends or weekdays **21:00–05:00 America/New_York** are
  permitted for large runs, reflecting NCBI's usage guidelines.
  A weekday daytime attempt is rejected before network contact.
- No parallel provider calls, unbounded retries, artificial rate-limit
  errors, undisclosed query restrictions or full metadata downloads.

## Two independent process stages

**Stage 1:** Create an isolated, ephemeral SQLite research project
using the authorised fixed term. Count the exact root query, recursively
count disjoint Create Date partitions, validate the complete interval
against the unfiltered root and durably store the immutable partition
plan. During the first real identifier page fetch, request a pause.
The normal production callback validates and atomically commits that
page's PMIDs and audit event. The process ends with **one persisted
page**, a `paused` checkpoint and no source-complete status.

**Stage 2:** A separate Python process reopens the manifest and SQLite
file, validates the committed page digest, and resumes through the
existing checkpoint-recovery implementation. The request transport
rejects attempts to refetch that first committed page. It rechecks the
source root and every leaf count, obtains only missing pages, checks
all unique PMIDs and counts, then rechecks the root count. A pass
requires every expected page, no duplicate identifiers, exact union
size equal to the source count, unchanged first page and truthful
`identifiers_reconciled_metadata_pending` status. Full metadata or
`completed_verified` are deliberately **not claimed**.

Any count drift, translation warning, out-of-coverage record,
overfull single-day interval, page/PMID overlap or transport
failure results in `incomplete`, preserving the verified subset.
The provider cannot guarantee a truly frozen snapshot merely because
counts and identifiers reconcile; that limitation remains explicit.

## Auditable, public-safe evidence

A successful or incomplete second stage writes an
`identifier-evidence.json` with run commit/time, exact fixed query,
date range, partition geometry/counts, pagination offsets,
source-reported accepted translations, provider-response SHA-256
digests, SQLite page checksums, **public canonical PMIDs on every page**,
total unique PMID count and a hash of the sorted PMID union. The included
PMIDs allow independent recomputation of the entire count and union. It records
`source_retrieval_verified=false` and
`metadata_acquired=false`. GitHub uploads **only** this credential-free
JSON artifact (retained 14 days); no SQLite database,
source XML, protected abstracts, contact address or API key are uploaded.
The diagnostic query and canonical PMIDs are publicly available literature
identifiers and have no proprietary research-specific terms.

This GitHub runner project is temporary. The evidence JSON does
**not** make it possible to resume the project on a different day,
and the test must not be presented as multi-day persistent-run
verification. Offline fixtures separately test count drift,
transport interruption and recovery after already committed pages.

## Running the controlled test

After four required tests and completed exact-HEAD code/security reviews,
and only after explicit project-owner authorisation to merge:

1. Open GitHub Actions and select **PubMed live >10k identifier
   checkpoint validation (manual)** on `main`.
2. Dispatch only within the recommended US Eastern weekend/off-peak
   window. The NCBI secret values are already configured.
3. Inspect the two stage logs and public-safe JSON evidence. Compare
   the *current* count and checksum to the new run, not the historical
   19,479 count as if it were a frozen expected value.
4. Record exact run ID/date/commit and classify AT-07/09 using
   observed reconciliation and failure evidence, not CI alone.

**Later work:** full metadata for all retrieved IDs, cross-source
publication reconciliation, persistent multi-day provider drift,
alternative overfull single-day splits and Web of Science Starter P1-05.

## Provider references

- https://www.ncbi.nlm.nih.gov/books/NBK25499/
- https://eutilities.github.io/site/API_Key/usageandkey/
