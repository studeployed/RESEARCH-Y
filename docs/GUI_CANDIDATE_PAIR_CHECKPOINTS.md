# P1-06k3c — Supervised graphical pair-index checkpoint controls

**Baseline:** owner-merged PR #77, `main` `18e031ebe841e0291da0b2dab0daa3d46cffc5c4`. Version-controlled `RESEARCH-Y_SPEC.md` remains authoritative and unchanged. This is a bounded milestone P1-06 increment concerning reproducible duplicate *candidate* discovery, not accepted automatic deduplication or final result completeness.

## Researcher workflow

The experimental project Graphical User Interface (GUI), after a researcher explicitly selects a search run, shows a **Run-specific durable potential-duplicate PAIR index** panel separate from the existing project-wide source-key index and potential-duplicate review queue.

1. **Inspect selected-run pair checkpoint (READ-ONLY, OFFLINE)** calls the original PR76 `preview_pair_checkpoint(project, run_id)` through the allowlisted supervised application worker. Reports `not_started`, `building`, `ready_keys_only`, or `stale`, original source-key index readiness, processed source-field keys, examined matching-key hints, and distinct stored candidate pairs. All are provisional, not unique-publication totals. No write or provider call occurs.
2. **Preview a NEW pair-index generation** is enabled only once the original v5 source-key cache is ready. A new generation explicitly clears **only derived candidate-pair hints for the selected run**. Original PubMed/Web of Science source data, association/provenance, group memberships and reviewer decisions are never erased.
3. **Preview ONE bounded continuation batch** is available only for a `building` generation whose original source-key index is still ready. The approved PR76 service processes **at most 64 source/field keys and 128 matching-key hints** in one original SQLite transaction, including a resumable peer cursor inside a dense title/identifier bucket.
4. A separate, plainly labelled **CONFIRM** button identifies the researcher and authorises exactly one bounded transaction. A pair generation does not auto-start when a project opens, a run is selected or a candidate page is viewed; no timer or background source operation is introduced.
5. Immediately after a successful-looking worker response, the trusted host independently rereads the **original durable SQLite checkpoint** via a new worker operation. It compares exact project and run identities, generation UUID, source-index generation and epoch, cursor, committed counters, rolling SHA-256 evidence digest, revision and status. The UI only displays a completed, reconciled receipt if both observations agree.

The original core service remains the only writer. Browser actions specify only `inspect`, `start`, `advance`, `dismiss`, or the researcher's confirmation text, **never a run ID, generation, source pair, SQL query, filesystem path, credential, key, or work budget**. The host derives the selected run and any immutable digest tokens; the application command validates all fields again across the trusted worker process.

## Failure, reopen and recovery

- **Lost or inconsistent response after commit:** the host consumes the one-time confirmation *before* dispatch. It clears the provisional offer and current review queue and displays `candidate_pair_reinspect_required`. An unacknowledged worker may already have committed. The researcher must choose **Inspect** to recover current durable progress; the previous request may not be replayed.
- **Source-key index stale/unfinished:** the panel discloses that prerequisite and refuses new pair-index work. Source, association and recorded candidate decision mutations already invalidate prior pair checkpoints through approved v6 database triggers. An explicit new generation is required after restoring source-key readiness.
- **Project or run switch:** all pending run-specific pair-index offers, progress and last receipts are cleared, preventing an earlier confirmation from being used for a different project/run. The project-wide source-key cache retains independent state, but that never authorises pair work in an unselected run.
- **Restart mid-batch/after commit:** progress remains in original SQLite, including the specific peer cursor, and can be recovered by an explicit preview. No automatic retry, network request, model inference, duplicate merge or publication-count promotion occurs.
- **Bounded workload overflow or malformed record:** the core PR76 worker refuses and rolls back its entire current transaction; the review queue continues to report the relevant incomplete/stale evidence rather than silently truncating potential matches.

## Interaction with existing candidate review

PR77 already reads a **`ready_keys_only`** pair cache using original-source validation and an overlay of previously recorded confirmed/rejected candidate decisions, including prior receipt-only pairs with no current equal citation key. The existing candidate-review queue remains unchanged and available when the pair checkpoint has not been built, is building, or has become stale.

The GUI identifies the distinct pair-index status but never says the key-only cache independently represents all reviewer history. It preserves the original decision comparison and warning acknowledgement on opening an actual pair. A shared container Digital Object Identifier (DOI), title, or supplement does not cause automatic matching of two distinct abstracts. Cross-run candidate pairs remain **read-only**, and no library database or user metadata is exported.

All responses and UI warnings retain **`candidate_discovery_complete=false`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false`, `global_unique_publications=null`**. A `ready_keys_only` index is a finished *exact-key hint generation*, not a completed biomedical duplicate discovery or publication master list.

## Validation boundaries

Offline real-SQLite tests cover two-source review separation and cache-backed display, explicit inspection and one-use confirmation, non-ready source-key prerequisites, a worker response lost **after** a committed batch, stale source evidence after an offered continuation, run switch discarding unsubmitted consent, forged command arguments, and the existing all-commands dispatch fixture. Existing PR76/77 tests additionally exercise 20-row keyset pages, historical reviewer receipt overlay, mid-dense-bucket restart, transactional failure/rollback, migrations and invalidation.

This increment is deliberately **not** a native Windows release, all-source deduplication acceptance or 100,000-record performance certification. Further gates: large-scale wall-clock/memory tests, additional historical receipt scaling and original source completeness, cross-run user-confirmed matching, classification, exports, and native packaging.

**Mandatory merge protocol:** verify exact current pull-request HEAD SHA; all four Python Continuous Integration (CI) configurations (Windows/Linux 3.12/3.13) and applicable GUI dependency/lifecycle checks; recorded **completed** Codex code review followed by **completed** security review on that same commit; all individual receipt/findings resolved or explicitly dispositioned; explicit owner authorisation before merge.
