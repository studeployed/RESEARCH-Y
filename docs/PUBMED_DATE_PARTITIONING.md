# P1-04b — Auditable PubMed date partitioning

**Implementation status:** proposed in feature branch
`feat/p1-04b-crdt-date-partitioning`; unmerged. This is a controlled fixture
and bounded identifier-retrieval increment, **not final source completeness**.

## Scope and provenance

NCBI PubMed ESearch has a roughly 10,000-identifier accessible window for a
single query. The approved specification (SRC-02/03) requires exact disjoint
partitioning rather than silently retrieving the first 10,000 records. This
increment uses PubMed's indexed **Create Date (`crdt`)** field for inclusive
calendar-day ranges. It does **not** use publication date as a proxy for when
a PubMed record was created.

An approved broad concept query remains an OR-only union. For
partitioning purposes only, RESEARCH-Y constructs a temporary
date-constrained source subquery such as:

```text
(("right ventricle"[All Fields] OR "ECMO"[All Fields])) AND (2025/01/01:2025/06/30[crdt])
```

That single provider-specific administrative date constraint does not
introduce user-facing AND between concept groups. The original approved
query and every exact generated subquery are preserved. Unexpected
PubMed-accepted translations, warnings or extra operators require manual
review. A deliberately matching date-partition `AND` is not incorrectly
treated as unintended concept narrowing.

The calling workflow must supply **explicit absolute date boundaries**.
No arbitrary default lookback or earliest/latest date is inferred. The
unfiltered query is counted first, then the complete supplied Create Date
interval is counted; **the counts must agree**. If they do not, the interval
may have missed matching records, so retrieval stops as incomplete.

## Algorithm and safe limits

1. Count the original approved query using ESearch, capturing translation
   and warnings. Do not continue if source interpretation requires review.
2. If its reported count is at most 9,000, use the already-tested bounded
   ESearch pagination implementation on the original query without adding
   an administrative date constraint.
3. For larger counts, inspect the caller-supplied inclusive Create Date
   interval; recursively split intervals in two at whole calendar-day
   boundaries until each leaf contains at most the 9,000-record ceiling.
4. At each split, verify that left and right counts sum to the parent's
   reported count. Retain exact subquery, parent index, dates, depth,
   count and decision (split/collect/empty/unsplittable).
5. A single day still above the ceiling, an exceeded count-query budget,
   unsupported translation, missing date coverage or inconsistent count
   stops with **incomplete** or **query_review_required**. It never
   truncates a leaf.
6. Fetch each safe leaf using the verified bounded ESearch ID collector.
   Recheck source counts and accepted translation for each page, reject
   duplicates within/across leaves, and compare the final union to the
   original root count.
7. Re-count the original query at the end to detect source-side changes.
   If its count has changed, do not claim reconciliation.

All source requests use the existing fixed HTTPS endpoint, reject
redirects, pace calls and leave contact credentials outside the project
and repository. The number of count probes is bounded (default 255).
Original completed leaves remain in the returned evidence if a later
leaf fails; partial results are **never labelled complete**.

## Status and limitations

Successful **identifier** reconciliation yields
`identifiers_reconciled_metadata_pending`, with
`source_retrieval_verified=False`. It is NOT a claim that bibliographic
metadata or abstracts were downloaded, source identity remained perfectly
stable, or a publication-level master result is verified.

Even if every child count reconciles, an unstable PubMed database may
change records between requests. This increment checks initial/final
counts and leaf counts but does not guarantee a frozen provider snapshot.
Long-term durable checkpoints, resumable jobs, alternative partition
keys for overcrowded single days, original metadata EFetch and real PubMed
smoke verification are tracked under issue #7 and later increments.

## Test evidence

`tests/test_pubmed_partition.py` contains 30 controlled fixtures,
including 10,003 identifiers across two days, leap-day partition boundaries,
count/coverage mismatches, duplicate IDs, provider translation warnings,
single-day overflow, count-budget exhaustion, interrupted leaf retrieval,
final root-count drift and date formatting. The existing PubMed unit and
page-collector suites also run to protect previously merged behaviour.

**Local Linux Python 3.13.5:** 127 targeted tests passed; the new module
achieved 93% statement coverage. GitHub Windows/Linux results and Codex
code/security review are pending publication. No live PubMed request has
been executed in this project session, so AT-07 remains **partial** and
AT-09 remains unverified.

Provider references:
- PubMed date fields and Create Date:
  https://pubmed.ncbi.nlm.nih.gov/help/
- NCBI ESearch field and date parameter descriptions:
  https://www.ncbi.nlm.nih.gov/books/NBK25499/
