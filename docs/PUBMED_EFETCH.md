# P1-04d — PubMed EFetch bibliographic metadata and abstracts

The EFetch service is implemented on main. See the roadmap for the scope of existing live PubMed evidence. Authoritative source: RESEARCH-Y_SPEC.md (SRC-01/04, DATA-03–06, RUN-04/07, AUDIT-01).

## Retrieval and integrity

PubMedEFetchClient uses the existing explicitly configured PubMedESearchProbeClient for runtime NCBI contact, optional API key and common request pacing. It POSTs to the fixed NCBI HTTPS EFetch endpoint, rejects redirects, requests retmode=xml and no language/species/date restrictions. Batches contain at most 20 canonical PubMed IDs and responses at most 8 MiB.
XML parsing accepts the standard external NLM PUBLIC DTD declaration without loading it, rejects internal entity declarations, and bounds the node count. Missing, repeated, unexpected, unsupported or malformed records leave the batch incomplete. Supported records include journal and book citations.
Source metadata includes DOI/PMCID/PMID, titles, authors/affiliations, journal/citation/pagination, dates, structured abstract sections, languages, publication types, keywords and source MeSH indexing (for later classification, not search terms). Absent abstracts are not_supplied_in_response. Supplied copyright notices are kept and all stored abstracts are flagged for redistribution-rights review.
Each batch retains EFetch XML SHA-256, source identity and UTC acquisition time. The complete raw provider XML is not retained in this increment; the structured legally scoped representation is. NCBI abstracts can be copyright-protected.

## SQLite and recovery

Only PMIDs in an identifiers_reconciled checkpoint may have source retrieval metadata stored. The existing source_retrievals and query_retrievals tables link source records to approved runs and queries; each new batch, query membership and audit event commits atomically. Equivalent source records replay idempotently; conflicting metadata is rejected, not overwritten.
Reopening a project resumes from PMIDs without linked metadata, using bounded requests and a finite batch budget. Bad or missing XML, interrupted transport, source pause, changed source metadata, failed audit or unexpected IDs never report completed_verified; previously committed metadata is retained. The strongest possible result here is metadata_acquired_reconciliation_pending: complete only against the committed checkpoint IDs, not against PubMed or the cross-source publication universe.

## Live source acceptance

Ordinary fixture tests do not call NCBI. scripts/pubmed_source_smoke.py requires RESEARCHY_NCBI_CONTACT_EMAIL set privately (optional RESEARCHY_NCBI_API_KEY). It sends one exact approved ESearch query, checks translation, fetches one returned PMID and reports only bibliographic status—not credentials or full abstract text. Developer/contact registration must follow NCBI policies. No successful live query was executed here.
Docs: https://www.nlm.nih.gov/dataguide/eutilities/utilities.html ; https://www.ncbi.nlm.nih.gov/books/NBK25499/ ; https://eutilities.github.io/site/API_Key/usageandkey/ .

## Mixed book and journal responses

The [NLM PubmedArticleSet content model](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-PubmedArticleSet.html)
allows a journal citation and a book citation in the same EFetch response.
The parser accepts both while checking the exact requested PMID set. A conflicting
book PMID refuses the batch before storage. Reopening a project resumes with
the missing identifiers and preserves existing journal-record JSON.

For a [BookDocument](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/el-BookDocument.html),
the contribution title, identifiers and abstract are distinct from its container
title, identifiers, publisher and contributors. If the source gives only a book
title it stays in the container field. Role-labelled editors remain editors.
Stored book abstracts carry the existing redistribution-review flag.

**Phase 1 evidence (#7, #105):** SRC-04, RUN-04/06 and partial AT-09 map to
`tests/test_pubmed_metadata.py::test_mixed_book_and_journal_metadata_reopens_without_refetch`
and `tests/test_pubmed_metadata.py::test_malformed_book_refuses_mixed_batch_without_partial_commit`.
These are synthetic provider responses.

## Bounded OR and metadata recovery sample

The separate manual `pubmed-metadata-recovery.yml` workflow tests a fixed
clinical OR expression (ECMO or extracorporeal membrane oxygenation) with a
count-only translation check. A second compiled OR expression uses the two
public reporting-guideline DOIs `10.1186/s13643-020-01542-z` and
`10.1136/bmj.n71`. The metadata experiment proceeds only for 2–20 IDs, with
one record committed before the process exits. A fresh process rechecks the
source count and fetches exactly the missing IDs. Total budget per dispatch
is ten requests. Only aggregate evidence and the fixed expressions may leave
the runner. This is an opt-in source check for AT-06/09 and SRC-04. Tests in
`tests/test_pubmed_metadata_recovery_validation.py` use a synthetic transport.

On 12 November 2026 the authorized [live run](https://github.com/studeployed/RESEARCH-Y/actions/runs/43300410950)
passed on `90c69d3`. PubMed accepted the clinical OR expression under the
translation checks. The reporting-guideline query returned two identifiers.
A fresh process verified the first committed record and acquired the one
remaining record. Both metadata records reconciled in ten requests across
the two processes. The checked-in aggregate summary records the independently
verified GitHub artifact digest. This covers the fixed phrase-translation
and controlled metadata-restart scenarios in AT-06 and AT-09.

### Evidence used when reopening retained metadata

For a checkpointed query, recovery and the execution board check each linked
PMID against the stored EFetch source, retrieval timestamp, response digest,
abstract-redistribution review flag and availability of original abstract
sections (including alternative-language sections). The response digest must
appear on an immutable record-creating EFetch commit for the same run.
A shared PMID can therefore retain its first response when another group
receives it in a different batch. Inconsistent evidence stops recovery and
prevents the board from reporting acquired metadata. Inspection is read-only.
The ordinary count report still shows an interrupted identifier search's
reported total, committed identifiers, linked local records and shortfall.

These historical batch receipts contain aggregate counts and a response
digest. They support local consistency checks. Verifying each original
response byte independently would require the provider XML.
