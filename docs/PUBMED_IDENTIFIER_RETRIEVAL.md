# P1-04a — PubMed bounded identifier retrieval

**Status:** initial implementation on `feat/p1-04a-bounded-pubmed-identifiers`; unmerged, pending GitHub Actions and code/security review. Approved `RESEARCH-Y_SPEC.md` remains unchanged.

## Why the limit matters

PubMed Entrez Search (ESearch) permits accessing only the first **10,000** matching identifiers for an individual query. `retstart` and `retmax` cannot safely page beyond that source-specific window. The official National Center for Biotechnology Information documentation recommends subdividing large queries:

- https://www.ncbi.nlm.nih.gov/books/NBK25499/
- https://www.nlm.nih.gov/pubs/techbull/so22/so22_updated_pubmed_e_utilities.html

Our initial bounded collector therefore sets an independently conservative default ceiling of **9,000 source records**. This is **not** a PubMed search filter: groups exceeding the ceiling return `partition_required`, preserving the full intended query for later **reproducible disjoint date partitioning** (SRC-02/03). It never silently downloads only the first available identifiers and declares a complete source result.

## Public API and output integrity

`research_y.pubmed_ids.retrieve_bounded_identifiers(client, exact_query, page_size=200, max_records=9000, on_verified_page=None)` uses the existing `PubMedESearchProbeClient` with the same HTTPS POST, source contact information, rate pacing and redirect refusal.

Workflow:
1. Probe the exact approved query for count and accepted translation. If PubMed changes the query or raises phrase/field warnings, return `query_review_required` before identifier acquisition.
2. Reject oversized group counts with `partition_required`, rather than truncating.
3. For bounded counts, request one page at a time, recording exact `retstart`/`retmax`, reported count, accepted translation, canonical PubMed IDs, UTC time, warnings and original response SHA-256 digest.
4. Reject invalid/noncanonical/duplicate PMIDs, overlap between pages, short responses, unexpected count changes, unexpected translations or page transport errors.
5. Expose the successfully checked pages and clear `incomplete` details if any later page fails. A caller can supply `on_verified_page` to **transactionally persist** a page; callback failure never reports that page as committed.

Even after counts and identifiers reconcile, the outcome is explicitly `identifiers_reconciled_metadata_pending`, with `source_retrieval_verified=False`. Full provider metadata, original payload retention rules, durable job checkpoints, resumption and downstream source/group reconciliation still need their own acceptance tests. No actual publication metadata is fabricated.

## Automated and real-source verification

Offline deterministic fixtures cover a three-page query, true zero matches, >9,000 result deferral, unexpected query translation, count drift, duplicate PMIDs, incomplete/invalid pages, 429/503 network failures, partial-result retention, checkpoint callback failure, UTF-8/error bounds, canonical identifier validation and request-window enforcement.

- Locally: **96 tests passed** with the original PubMed acceptance suite; **97% branch-aware coverage** of the new pagination module. Includes corrected callback exception sanitisation and oversized numeric PMID/count rejection.
- GitHub Actions Windows/Linux Python 3.12/3.13: **pending** on this PR until actual successful jobs are inspected.
- Live NCBI accepted query/ID verification: **not performed** here. An authorised runtime contact is required; no credentials are stored in public source.

**Outstanding gates:** SRC-02/03 >10,000-hit partitioning and non-overlapping union validation, RUN-04/06 persistent checkpoints and resume, SRC-04 actual abstracts/metadata, AT-07 and AT-09, Web of Science Starter source connector and global record deduplication.
