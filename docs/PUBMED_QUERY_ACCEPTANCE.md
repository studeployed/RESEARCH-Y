# P1-03b — PubMed ESearch count/translation acceptance probe

**Status:** Merged in [PR #17](https://github.com/studeployed/RESEARCH-Y/pull/17) on 24 October 2026. Its post-merge GitHub Actions matrix passed Windows/Linux Python 3.12/3.13. **Live PubMed acceptance verification remains outstanding**, and AT-06 is not complete.

## Purpose

The approved RESEARCH-Y specification requires PubMed All Fields queries to be
tested against the translation that the source *actually accepted*. Building
a quoted `[All Fields]` query does not by itself prove PubMed preserved the
intended phrase: an unindexed quoted phrase may be split, remapped or generate a
warning. Therefore the tool **never calls a count-only probe a verified full
retrieval**.

`research_y.pubmed_probe.PubMedESearchProbeClient` accepts exact source-query
text (typically supplied by the approved query compiler) and submits a
**single-source, count-only** request using the official ESearch endpoint.
It returns:

- Exact submitted query and PubMed's `querytranslation`;
- Source-reported count, distinct from any count of retrieved records;
- UTC timestamp, source warnings, phrase-index/errors and conservative
  `review_required` reasons;
- Explicit `retrieval_verified=False` and zero retrieved IDs.

No journal articles or bibliographic records are downloaded. Source query
status cannot become `completed_verified` based on this count probe.

## Confirmed live translation edge case (P1-04f)

On 30 October 2026, live NCBI ESearch returned the accepted translation
'"ECMO"[All Fields]' for submitted '("ECMO"[All Fields])', with no
provider warnings. The original exact-string comparator flagged review
and stopped before any PMID or EFetch request.

The P1-04f correction treats only balanced parentheses surrounding the
**entire** expression as equivalent. It does not ignore field substitutions,
altered terms, introduced Boolean operations, unexpected internal-group
changes or provider warnings. The raw accepted translation stays auditable.
Tests using this real response shape remain offline until the manual
provider workflow is rerun. Acceptance test AT-06 stays partial.
## Reliability and scientific interpretation

- Only the fixed NCBI HTTPS ESearch endpoint is used, with **all redirects refused** (including cross-host and HTTPS-to-HTTP downgrade), via Python's standard
  library. Requests are POSTed with `db=pubmed`, `term=<exact query>`,
  `retmode=json` and `retmax=0`, with no language/species/date exclusions.
- The caller supplies an E-utilities contact email at runtime; `tool=RESEARCHY`
  by default. Optional API keys are carried in the in-memory POST body, not
  query-string URLs, log files or project manifests.
- Consecutive calls using one client are paced at **0.4 seconds apart or
  slower**, within the unauthenticated default **3 requests/second** limit.
- HTTP errors, including 429, and network failures do not produce a fictional
  zero count. Retryability is signalled to later managed job code; no unbounded
  retry loop is introduced in this increment.
- Embedded ESearch application-level errors despite HTTP 200, a missing count,
  missing translation, malformed JSON, unexpected returned IDs or bad warning
  shape cause explicit failure.
- PubMed warnings, unexpected query translations, introduced Medical Subject
  Headings (MeSH) terms and unexpected unquoted AND/NOT operators require
  researcher review. A matching string with no warning is evidence that the
  translation matched the submitted preview, **not proof of complete retrieval**.
- A group split into multiple OR chunks retains each independent source count.
  Chunk counts are **not summed** into a group total; only later retrieval of
  unique PubMed identifiers can establish the union.

## Offline tests and real-source gate

`tests/test_pubmed_probe.py` runs without network or secret access, including an integration fixture from the **actual approved query compiler** into the ESearch probe. It
covers: count 0 versus unavailable count; embedded errors; translated AND/MeSH;
phrase warnings; malformed payload; source error; bounded response size;
POST form/credential separation; 429/transport errors; rate pacing; group
chunk count integrity; disabled groups and wrong-source rejection.

A single diagnostic call is available through `scripts/pubmed_smoke.py` only
after explicitly supplying a private contact email:

```powershell
$env:RESEARCHY_NCBI_CONTACT_EMAIL = "your-contact@example.org"
python scripts/pubmed_smoke.py --query '("right ventricle"[All Fields])'
Remove-Item Env:RESEARCHY_NCBI_CONTACT_EMAIL
```

The diagnostic prints only query/translation/count/flags, not API keys. Its
nonzero exit status means no accepted result or review required. If it is run,
record the date, exact query, accepted translation and warnings in an
appropriate permitted audit record without credential values or unwarranted
search-completeness claims. This project's isolated development environment
cannot resolve the NCBI hostname, so **no live run can be claimed here**.

## Future increments

Full ESearch identifier retrieval (>10,000 partitioning), reproducible
search-run history, retries/checkpoint recovery, Web of Science Starter
authentication and pagination, and source-count reconciliation remain in the
approved Phase 1 scope. A count-only probe does not fulfil these tasks.

## Authoritative external documentation

- NCBI E-utilities ESearch documentation:
  https://www.ncbi.nlm.nih.gov/books/NBK25499/
- NCBI E-utilities usage/pacing:
  https://eutilities.github.io/site/API_Key/usageandkey/
- PubMed phrase translation/phrase-index behaviour:
  https://pubmed.ncbi.nlm.nih.gov/help/

These links document provider behaviour; the scientific and product
requirements remain in `RESEARCH-Y_SPEC.md`.

The HTTPS redirect issue was corrected and covered by a regression test before PR #17 merged. The full GitHub Actions matrix passed. Live query translation still requires a permitted provider request.
