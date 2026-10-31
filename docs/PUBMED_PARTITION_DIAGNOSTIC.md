# P1-04h — Count-only PubMed Create Date partition diagnosis

**Status:** Proposed manual-only diagnostic, not yet merged or run live.
**Authoritative specification:** `RESEARCH-Y_SPEC.md`, particularly SEARCH-07,
SRC-01–03, METH-05, RUN-04–06 and AT-07/09/19. No changes to approved
requirements, search breadth, source connector or retrieval algorithm.

## Specific observed failure

The 31 October 2026 manual [live >10,000-identifier test
#41207501975](https://github.com/studeployed/RESEARCH-Y/actions/runs/41207501975)
on merge commit `d08402931d5e4cc23d662b71c0da65a30931afeb` failed in its
first stage. Its safely retained evidence reported **19,483** root matches,
**three** source requests, **zero committed PMID pages** and **zero**
retrieved identifiers, with:

`A complete checkpoint plan could not be established`.

The resume process never ran. The three requests are consistent with an
initial root count, a retrieval baseline count and the initial whole-window
Create Date count. Crucially, the existing script suppressed the decisive
partition response before persisting evidence. We **cannot determine** from
that failed run whether the partition query was rewritten by PubMed,
produced warnings, failed in transport/parsing, or returned a different
count. These possibilities must not be conflated.

## Diagnostic scope

The new `.github/workflows/pubmed-partition-count-diagnostic.yml` is
**manual workflow_dispatch only**. It uses the same private repository
Actions secrets `RESEARCHY_NCBI_CONTACT_EMAIL` and optional
`RESEARCHY_NCBI_API_KEY` and the same fixed NCBI HTTPS ESearch endpoint,
rate pacing, no-redirect policy and concurrency lock. It is not invoked by
push, pull request or schedule.

The script `scripts/pubmed_partition_count_diagnostic.py` performs:

1. A count-only ESearch request using the **fixed, public, approved-style**
   query `("ECMO"[All Fields])`.
2. Provided the source count is in the already approved diagnostic bounds
   **10,001–30,000** and no query review is needed, one count-only ESearch
   request for the **exact first administrative date partition** generated
   by the existing `DateWindow.query_for` implementation:
   1900-01-01 through the current UTC day + 1 inclusive.

There can be **at most two source requests**; both have `retmax=0`, and
an internal request guard rejects any identifier request, unapproved query
or unexpected endpoint. The date interval is recorded exactly and is
**not** a scientific publication-date filter or assumption that PubMed
contains no older entries.

The diagnostic reuses the production `PubMedESearchProbeClient.probe`
and its unchanged conservative accepted-translation validator. It does
**not** normalise or auto-accept any unexpected date translation.
Any source rewrite or warning requires manual scientific/technical review.

## Evidence retained on success or failure

Each available count probe is separately recorded in
`pubmed-partition-count-diagnostic.json` with:

- Exact fixed submitted query, **actual accepted PubMed translation**,
  source-reported count and UTC timestamp.
- All parser-available provider warnings and review reasons, without
  converting an error into a zero-hit result.
- Translation-equivalence flag; a precise indicator of whether the
  root and partition counts reconcile, with signed count difference.
- Safe transport/response failure category and HTTP status where known,
  rather than raw exception messages.
- Explicit `identifier_pages_requested=0`, `retrieved_unique_pmids=0`,
  `identifiers_reconciled=false`, `source_retrieval_verified=false`
  and `metadata_acquired=false`.

Evidence is saved before failure exits and is uploaded as a small GitHub
Actions JSON artifact (14-day retention). Known contact/key strings in
provider-controlled translations or warnings are replaced with
`[REDACTED]`; no credentials, raw HTTP request POST bodies, PMID lists,
abstracts, protected source text, project database or full provider
response payloads are uploaded.

### Interpretation table

| Reason code | Meaning | Next investigation |
|---|---|---|
| `partition_translation_or_warnings` | PubMed returned a count but the first partition query requires review | Inspect exact accepted translation, errors and field mapping before any code changes |
| `create_date_coverage_count_mismatch` | PubMed accepted the partition syntax but its count differed from the unrestricted root | Determine whether the date coverage interval excludes source records or the backend changed |
| `partition_count_request_failed` | HTTP/network, invalid source response or another count-probe failure | Review safe error category/status, not the search total |
| `root_translation_or_warnings` / `root_count_request_failed` | Root query itself cannot be verified | Diagnose source access and accepted root query first |
| `root_count_outside_diagnostic_safety_bounds` | Provider count changed beyond intended diagnostic limits | Stop before partitioning; confirm scope |
| `no_first_partition_count_discrepancy` | Two count-only probes were accepted and their reported counts match | Useful preliminary evidence only. **Not** proof that recursive partitions, PMID retrieval or recovery work |

Even the last outcome must never be presented as completion of AT-07 or
AT-09. These remain open until the full count/unique-identifier/recovery
workflow succeeds with real source evidence.

## Execution procedure after reviewed and owner-authorised merge

Open **GitHub Actions → PubMed Create Date count diagnostic (manual) →
Run workflow** on `main`. The previously configured NCBI repository secrets
are reused; no fresh credential entry is needed. Run once, inspect
the safely retained JSON artifact and log, record the exact count/
translation/reasons and decide **which narrowly scoped correction is
actually supported**. Do not rerun the larger identifier workflow
unchanged or remove conservative translation checks.

The result is a diagnostic measurement, not a software or scientific
conclusion. Any substantive change in source field coverage, date
partition scheme or search logic must be separately approved and tested.
