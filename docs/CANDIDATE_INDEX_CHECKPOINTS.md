# P1-06k2a — Durable and recoverable derived candidate-key index

**Baseline:** owner-merged PR #73, repository `main` `a98ed94636015e695fbdd06927f62de20d997bf1`, 8 November 2026. The authoritative `RESEARCH-Y_SPEC.md` is unchanged. Parent #9/#33/#35/#41/#43. Bounded partial DATA-01/02/04/05, DUP-01–05, AUDIT-03, PROJ-04, COUNT-01/05 and AT-01/02/09/10/11/17/19/21. This increment is **index construction only**, not the application consuming the index.

## Why a separate incremental stage?

PR73's original project-spanning queue builds an in-memory inverted index and enumerates exact-key candidate pairs on each read. It safely refuses a very large/dense queue instead of truncating or claiming complete bibliographic deduplication. A durable, incremental source-key projection is the first step toward an indexed, repeatable queue for larger retained projects. This is not a change to search OR logic, matching thresholds, or the approved specification.

The v5 migration adds **`candidate_index_state`**, **`candidate_index_records`**, and **`candidate_index_keys`** to the original project SQLite file. Source records and group memberships remain the authoritative originals. Cached keys contain only a SHA-256 digest of the accepted canonical source field, field name and this project's random project identifier, **not original title/abstract text**; even equality of digests remains an evidence hint and is not a publication match. The original `publication_match_evidence.project_source` controls extraction of exactly four fields: title, Digital Object Identifier (DOI), PubMed identifier (PMID) and Web of Science accession. Missing/malformed/ambiguous fields do not receive invented keys.

An insert, update or delete of an original `source_retrievals` row atomically increments a source epoch and changes any `building` or `ready` generation to **`stale`** in the *same source transaction*. A stale generation cannot continue or be treated as a valid source snapshot. A changed publication association or reviewer decision does not require rebuilding the **source-only key** cache: review correctness will continue to depend on the original current decision/identity services. An index marked ready is **not** a verified bibliographic deduplication or search completion.

## Explicitly confirmed, revision-fenced operations

- `preview_candidate_index(project)` is read-only. Reports validated state, project source-row total, source epoch, generation ID, progress, cached key count, unsupported count, and a SHA-256 revision. Exposes no original citation text, query credentials or source bodies.
- `start_candidate_index(project, expected_revision=..., actor=..., confirmed=True)` is a deliberately initiated rebuild. Under `BEGIN IMMEDIATE`, it verifies the exact preview, deletes **only derived cache rows**, allocates a new generation, initialises the rolling source/key evidence hash and writes an audit receipt. A failure rolls the entire start back. No source, publication, group membership, candidate decision or existing audit record changes.
- `advance_candidate_index(project, generation_id=..., expected_revision=..., actor=..., confirmed=True, max_records=128)` commits **at most 128** original source records' derived index rows/keys and an appended batch audit receipt in one SQLite transaction. A failed transaction commits **none** of the batch. The canonical source retrieval ID is the keyset cursor; `processed_records` and `indexed_keys` are checked against the actual cached rows before the next batch. The rolling evidence SHA-256, last source ID and source epoch are recorded for recovery.
- At the last source, the index moves to **`ready`** only after all originally counted source records are represented, with `source_epoch` unchanged. An empty project finishes with a zero-key cache only after an explicit bounded completion step; neither it nor any other ready index establishes complete retrieval or a final publication count.

A separate process can reopen a project and resume from the **durably stored revision**. A lost worker result is not permission to replay an old confirmation: inspect the current durable state first. All source-provider operations and third-party model calls are absent.

## Migration and risk controls

New projects start at schema **v5**. Existing v1–v4 projects receive a **verified pre-migration SQLite snapshot** before a single atomic additive migration; v4 uses `researchy-before-v5-<unique>.sqlite3`. A failed backup prevents DDL; failed DDL or audit insertion rolls back the original schema and preserves the recovery snapshot. Source, approval, retrieval checkpoint, publication and decision records are retained unchanged. Unknown future versions, mismatched identities and unsafe project paths still fail closed.

The v5 schema doesn't add new network access, cloud processing, download or export authority, and doesn't store normalized title strings or abstracts in derived index tables. A 10,000-character upper bound on a *single normalized matching field* fails explicitly instead of silently truncating that field. Index state corruption or source-identity drift fails closed. This cache is **not** a security boundary against a fully malicious project database, and a SHA-256 checksum is not a cryptographic signature.

The v5 source triggers add small write overhead to every retained source-record insertion/update/delete. Release performance at 100,000 source records and the full index lifecycle is **not yet certified**; benchmarks and failure/recovery evidence are required before shipping or invoking automatic indexing in the user interface.

## Offline verification

The added synthetic disk-backed tests cover:

- v4→v5 snapshots, identity verification, rollback on injected partial DDL, backup failure and repeated open;
- explicit confirmation, unchanged original source records, hashed citation-only keys and no automatic same-DOI/supplement merge;
- 128+3 record batches, process reopen/resume, empty projects, invalid/stale/forged generation and incomplete evidence;
- source changes during construction and after completion (including in-transaction trigger invalidation);
- aborted batch-write trigger and exact audit/cache rollback; missing cache rows and malformed source metadata fail closed;
- unsupported input layouts remain counted rather than being treated as a negative match.

All existing project initialisation and v1/v2/v3/v4 migration tests must remain passing across Python 3.12/3.13 on Windows and Linux. The mandatory exact-HEAD code review and subsequent security review, including all individual findings and explicit owner merge authorisation, still apply.

## Deliberate remaining work

**This pull request does not change PR73's existing GUI queue or `read_candidate_queue` retrieval path.** The new durable index is not yet used to produce candidate results and no stage is scheduled asynchronously. The subsequent bounded increment must implement a validated cache-backed queue with direct indexed key lookups, source/identity/decision revision checks, dense-key work budgets, and a safe UI consent/progress path. Cross-run user-confirmed association, near-duplicate/fuzzy discovery, full performance acceptance and final Excel/master-result publication completeness remain separate gates.

`candidate_discovery_complete=false`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false`, `global_unique_publications=null` are unchanged.
