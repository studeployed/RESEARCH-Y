# P1-04d — PubMed EFetch bibliographic metadata and abstracts

Status: feature-branch proposal, not merged or verified against live NCBI. Authoritative source: RESEARCH-Y_SPEC.md (SRC-01/04, DATA-03–06, RUN-04/07, AUDIT-01).

## Retrieval and integrity

PubMedEFetchClient uses the existing explicitly configured PubMedESearchProbeClient for runtime NCBI contact, optional API key and common request pacing. It POSTs to the fixed NCBI HTTPS EFetch endpoint, rejects redirects, requests retmode=xml and no language/species/date restrictions. Batches contain at most 20 canonical PubMed IDs and responses at most 8 MiB.
XML parsing accepts the standard external NLM PUBLIC DTD declaration without loading it, rejects internal entity declarations, and bounds the node count. Missing, repeated, unexpected, non-journal or malformed records cause an explicit incomplete batch—not a silently shortened result.
Source metadata includes DOI/PMCID/PMID, titles, authors/affiliations, journal/citation/pagination, dates, structured abstract sections, languages, publication types, keywords and source MeSH indexing (for later classification, not search terms). Absent abstracts are not_supplied_in_response. Supplied copyright notices are kept and all stored abstracts are flagged for redistribution-rights review.
Each batch retains EFetch XML SHA-256, source identity and UTC acquisition time. The complete raw provider XML is not retained in this increment; the structured legally scoped representation is. NCBI abstracts can be copyright-protected.

## SQLite and recovery

Only PMIDs in an identifiers_reconciled checkpoint may have source retrieval metadata stored. The existing source_retrievals and query_retrievals tables link source records to approved runs and queries; each new batch, query membership and audit event commits atomically. Equivalent source records replay idempotently; conflicting metadata is rejected, not overwritten.
Reopening a project resumes from PMIDs without linked metadata, using bounded requests and a finite batch budget. Bad or missing XML, interrupted transport, source pause, changed source metadata, failed audit or unexpected IDs never report completed_verified; previously committed metadata is retained. The strongest possible result here is metadata_acquired_reconciliation_pending: complete only against the committed checkpoint IDs, not against PubMed or the cross-source publication universe.

## Live source acceptance

Ordinary fixture tests do not call NCBI. scripts/pubmed_source_smoke.py requires RESEARCHY_NCBI_CONTACT_EMAIL set privately (optional RESEARCHY_NCBI_API_KEY). It sends one exact approved ESearch query, checks translation, fetches one returned PMID and reports only bibliographic status—not credentials or full abstract text. Developer/contact registration must follow NCBI policies. No successful live query was executed here.
Docs: https://www.nlm.nih.gov/dataguide/eutilities/utilities.html ; https://www.ncbi.nlm.nih.gov/books/NBK25499/ ; https://eutilities.github.io/site/API_Key/usageandkey/ .
