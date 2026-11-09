# P1-06k2b — Consent-controlled candidate index and source-backed queue

**Baseline:** owner-merged PR #74, `main` `bb6b045d73869ccfac942be5f12294d867c0ab92` on 8 November 2026. The version-controlled `RESEARCH-Y_SPEC.md` is unchanged. Parent #9/#33/#35/#41/#43. Scoped partial DATA-01/02/04/05/06, DUP-01–05, RUN-04/05/06, AUDIT-03, UI-07/09 and AT-01/09/10/11/17/19/21.

## Current researcher workflow

The experimental real-project graphical application provides an explicit **Inspect current index status (READ-ONLY)** action, followed by a distinct **Preview NEW index** or **Preview ONE continuation batch** and a separate researcher-confirmed write. Index creation does not begin when the app or results page opens. Each click of **CONFIRM** authorises exactly one original project SQLite transaction:

- **Start:** rechecks the exact inspected generation revision, clears only derived candidate-index rows, writes a new generation and immutable audit event;
- **Continue:** rechecks original source epoch, generation, cursor and immutable revision and adds at most **128** original source records' derived hashes in one transaction. No network requests, source changes, automatic deduplication or publication count promotion occur;
- **After either commit:** the host independently reads the original project index state in a fresh worker request, verifies generation/source epoch, progress, hash and revision against the write receipt, and only then displays a reconciled outcome. If the worker crashes after commit or receipt verification fails, the consent has already been consumed; the user must re-inspect the durable state, **never blindly resend**.

Source changes during construction invalidate the generation through PR74's source-table triggers. The UI identifies `empty`, `building`, `ready`, and `stale` distinctly. A stale generation may require explicit rebuild. Project change clears all transient index state and any unsent confirmation; switching selected runs clears unsent approval. A completed index is a **source-key cache only**, not evidence of a completed search.

## Exact-key queue consumption

`publication_candidate_queue.read_candidate_queue` now checks the validated v5 index state in the original read-only SQLite transaction:

- **Only `ready`** uses persisted `candidate_index_keys` (project-salted hashes of original title, Digital Object Identifier [DOI], PubMed identifier [PMID] and Web of Science accession). The key scan is ordered and built from joined source-retention/identity links; it avoids re-decoding and re-normalising all original licensed provider records for every queue page.
- **`empty`, `building`, or `stale`** never contribute cached hints. The earlier PR73 original-source projection remains available offline, subject to its existing 100,000-source and 100,000-pair explicit refusal thresholds. The returned page identifies the actual backend and current cache status; a fallback is not portrayed as a ready cache.
- Cached key equality is a **hint**. The researcher sees original citation-field comparison results, machine warnings, all stored source/group provenance and historical candidate decisions through the existing audited `publication_candidates` and `publication_review_gui` services. Each *displayed* matching field is checked against the actual canonical original comparison. A forged/mismatched key on the returned page fails closed. No automatic merge, source identity promotion, eligibility inference, abstract redistribution or cloud model calls.
- Candidate pairs must touch the chosen run. Historical cross-run pairs remain **read-only**. Existing reviewer-confirmed/rejected pairs appear even when they have no matching current keys. The original candidate review/reversal commands still enforce independently reconstructed source evidence, explicit researcher confirmation, source links and fresh audit revisions.

The output preserves PR73's 20-pair keyset navigation and exact candidate totals within its declared budget, with a revision now binding index generation and source epoch **plus** original run statuses, queries, group memberships, every original current association and the full validated candidate receipt history. Changed evidence invalidates stale cursors, even if the derived keys remain valid. The `unsupported_project_records` denominator remains *linked* unsupported original source records, separate from unmaterialised records.

## Limits and deferred work

This increment is **not** full 100,000-record performance validation. Although indexing normalized fields happens only once per explicitly approved generation, the queue currently re-enumerates bounded exact-key candidate pairs and original review receipts on each read. Dense repeated metadata keys fail with an explicit `candidate_queue_over_limit` instead of silent truncation; no unbounded pair materialisation, fuzzy matching or validated automatic high-confidence merging is introduced. Full source completeness, Society/Guideline cross-source coverage, abstracts and legal reuse, document classifiers, cross-run match admission, publication-ready Excel output and Windows installer acceptance remain outstanding.

Ready-cache integrity checks detect missing rows, source-epoch drift, and key-count disagreements, and displayed exact matches are verified against original source records. The cache isn't an adversarially signed data structure: direct hostile rewrites of the SQLite file may require a full rebuild or separate integrity audit. Normal source mutations through SQLite always trigger invalidation in the same transaction.

Every response still declares **`global_unique_publications=null`**, **`deduplication_complete=false`**, **`candidate_discovery_complete=false`**, **`source_retrieval_verified=false`**, **`verified_complete=false`**. No count of candidate pairs, cached keys or provisional identities is equated with unique publications.

## Verification and merge gates

Offline disk-backed tests compare the cache-backed queue directly against PR73's original source-backed results: cross-run hints, same-title/same-DOI **nonmerging**, prior negative reviewer decisions with no current matching fields, 20+2 page navigation, interrupted/incomplete cache fallback, source mutation and cursor invalidation, bad cache rejection, command forging, explicit preview/confirmation, independent post-commit reconciliation, worker-loss recovery and project switching. Existing PR74 migration, rollback and >128 record restart tests remain part of the full suite. No external provider credentials are needed.

This is an **experimental GUI** increment and not a production Windows release. Before merge: verify exact HEAD SHA, all four Python Windows/Linux continuous-integration jobs, applicable GUI dependency/lifecycle checks, **completed Codex code review first**, then **completed exact-commit security review**, each substantive finding and final owner approval. Never merge automatically.

**Next development boundary:** paginate candidate matching via durable keyed candidate-pair checkpoints and demonstrated 100,000-record latency/recovery performance; enable cross-run decisions only after separate audited original-evidence validation. UI test coverage of the new buttons does not alone prove native Windows acceptance.
