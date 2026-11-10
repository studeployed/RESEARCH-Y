# P1-06k4b2 — One-pass validation of original source records

**Baseline:** owner-merged pull request (PR) #80, `main` `5aac186e7bef9ccd7393bd903048cf77d9568fe3`, 10 November 2026. The version-controlled `RESEARCH-Y_SPEC.md` remains authoritative and unchanged.

This is an incremental optimisation of the **original source-based candidate-review fallback**, which PR80 measured at approximately **3.32 seconds on Linux** and **4.22 seconds on Windows** for its 100,000-retained-source, 128-materialised-identity synthetic workload. These times are full original queue read times, not the cached keyset SQL timings from PR79. This increment does **not** claim full end-to-end acceptance test AT-22.

## What is changed

Previously, the fallback implementation first selected 100,000 source retrieval IDs, then for **each original retrieval** made a separate source-row lookup, a separate parent-run-status lookup and a separate publication-association lookup. Historical records that had not yet been materialised therefore incurred repeated indexed SQLite round trips despite having no association or eligible review pair.

The updated `_original_index` uses **one ordered, read-only SQLite source stream** joining:

- **Every** original `source_retrievals` row, including records outside the selected run and unmaterialised records.
- Its current `search_runs.status`, with a **LEFT JOIN** so a missing parent run is not silently dropped.
- The presence of its current `publication_retrievals` link, also with a **LEFT JOIN**.

A central `publication_identity._source_from_row` decoder is used by both the original individual-source reader and the new stream. It retains the full original source field tuple, strict JSON-object decoding (including rejection of duplicate JSON keys/non-finite data), exact original SHA-256 evidence digest, and current parent-run status. The existing PubMed identifier / Web of Science accession-vs-original-metadata check still runs for **every** retained applicable record, even those without an identity link.

If a source **has** a publication link, the stream invokes `publication_identity._link(db, retrieval_id)`, preserving the authoritative association-provenance audit checks, the original source SHA-256 comparison and all current identity/reversal safeguards. If it **does not** have a link, the scanner records it as unmaterialised without a pointless point lookup. Linked source records are still individually revalidated. The selected-run count projection still validates original counts, source records, group/query memberships and recorded candidate decisions.

The original inverted exact-key buckets, reviewer-receipt overlay, selected-run-only actionable scope, 20-pair keyset navigation, work caps, stale-revision hashing of all historical source/run/query/membership evidence and explicit incomplete/full-count flags are **unchanged**. No persistent source or identity data are changed by reading. A ready PR74/76 source/pair cache continues to take precedence when validated; only the original-source fallback is optimised.

## Verification evidence

Offline SQLite tests compare the streamed evidence to `identity._source` for linked, historical, manual and unmaterialised source records, including **identical source digests and run-status fields**. A regression inserts 420 original historical records with no provisional identity and verifies that the candidate page still accounts for all 422 original sources and preserves matching-field evidence, while causing **zero historical per-record source lookups**. A deliberately corrupted unmaterialised original source still raises a safe error instead of silently disappearing. An `EXPLAIN QUERY PLAN` regression checks the single ordered source scan and indexed parent-run/link joins.

The existing [100,000-original-source performance workflow](../.github/workflows/original-project-100k.yml) runs the **same PR80 project, selected-run size, original metadata, memberships, audited identities, spawned graphical worker and reopen/integrity checks** on Linux and Windows. That direct workload parity is required before describing any observed speed change; new timings must be recorded with precise workflow/commit references. The comparison is not a paired hardware-controlled experiment: shared runners and independent times can vary.

## Limits

Performance of the **unindexed fallback** is improved only by removing redundant SQL lookups, *not* by skipping original evidence validation. Actual licensed articles, full provider retrieval, all 100,000 materialised publication identities, complete deduplication, Graphical User Interface (GUI) browser paint responsiveness, all-worker combined memory and the final unique-publication master list remain unverified.

The original research requirements of conservative duplicate review, auditable researcher decisions, preserved source/group/run memberships, and unknown counts are unchanged: `global_unique_publications=null`, `candidate_discovery_complete=false`, `source_retrieval_verified=false`, `deduplication_complete=false` and `verified_complete=false`. Shared conference supplement Digital Object Identifiers (DOIs) remain hints and are never automatically merged into individual abstracts.

## Merge gates

Exact HEAD SHA, four required Windows/Linux Python 3.12/3.13 tests, two 100,000-original-source performance jobs, applicable graphical checks, completed exact-HEAD Codex **code review first**, followed by completed exact-HEAD **security review**, individual receipt/findings disposition, and explicit project-owner authorisation. Do not merge automatically. **AT-22 remains unverified** after this incremental improvement.
