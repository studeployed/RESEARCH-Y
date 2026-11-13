# Targeted Crossref enrichment

Inspect one materialised publication by its internal ID with
`python -m scripts.enrich_publication PROJECT PUBLICATION_ID inspect`.
The read-only view shows the exact DOI from the retained sources, its
supporting paths, the expected revision and the free Crossref Works URL.
A missing, malformed or conflicting DOI gives an explicit gap.

To look up the displayed DOI, use the same arguments followed by
`lookup --contact EMAIL --actor NAME --revision REVISION --confirm`.
Crossref receives the DOI and the configured contact email. The client
requests one work using HTTPS at api.crossref.org. It stores separate
enrichment evidence and never changes the original provider metadata,
publication records, query memberships or hit counts. Use `--refresh` to
request newer data after a cached successful or not-found response.

The project records a bounded reservation before a request, honours a
reported rate interval and Retry-After and exposes the next allowed time
when the shared guard is active. A network interruption has an unknown
outcome. An unavailable service or a 404 remains visible. Error bodies
and contact details are excluded from receipts. Positive evidence preserves
the source URL, retrieval time, response digest, available work fields and
gaps, with rights review required for redistribution.

The regression corpus uses an injected local transport. No researcher
credentials or project data are required for these tests. The public/polite
interface and operator contact convention follow [Crossref's access documentation](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/).
