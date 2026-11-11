# P1-06k4g — Phase-by-phase 100,000-source GUI latency evidence

**Baseline:** owner-merged PR #90, `main` `d03ee37a4b3b09a93757d9aaf56bee9060b45327` (11 November 2026). **Authority:** version-controlled `RESEARCH-Y_SPEC.md`, unchanged. Bounded Phase 1 evidence increment for UI-07/08 and AT-22, not final graphical or scientific acceptance.

## Why this is the next bounded step

Previous original-project tests proved that the experimental native Windows graphical user interface (GUI) can navigate two separate 20-row publication pages and citation-only detail in a versioned project containing **100,000 original source retrievals, 100,000 original query/group memberships and 100,000 independently audited provisional identity hypotheses**. PR #90 removed a duplicate *full-run* validation from the detail action by executing the page-and-detail checks in one original SQLite transaction.

Nevertheless, the observed completed GUI session on PR #89 took approximately **75.8 seconds on Linux** and **53.0 seconds on native Windows**; the later PR #90 Linux session took approximately **61.3 seconds**. These are single hosted-runner observations, not comparable controlled trials or product latency acceptance. The individual slow stage has not been isolated sufficiently to justify changing source/audit validation.

## Exact measurements added

The existing **disposable synthetic workload test**, not the production application, now records:

1. A *separate genuine complete original run count projection* on the 100,000-record SQLite fixture, timed as `whole_run_ms` with instrumented components:
   - `original_source_validation`: reading, decoding and validating original source records;
   - `original_identity_link_validation`: validating/reconstructing original publication identity associations and individual audit receipts;
   - `query_membership_validation`: mapping original query records, source/group memberships and available source-reconciliation evidence;
   - `original_review_receipt_validation`: checking append-only candidate-review receipt evidence.
   
   The residual `other_validation_ms` is measured wall time less the measured stages, bounded at zero for measurement rounding. It is **not** a claim that the unmeasured part is dispensable, nor a standalone source-reconciliation stage.

2. The **five fixed real host operations** in both environments, measured from the start of the actual original application action to receipt of its verified return: `open`, `select_run`, `publication_refresh`, `publication_next`, `publication_detail`.
3. On Windows only, separate native pywebview **visible button-click to completed-action** timings for the same five actions, including GUI event/painting overhead. Linux uses a guarded loopback test transport and therefore does *not* claim native-rendering measurements.
4. The existing fixture preparation and whole-GUI-session elapsed intervals. Do not conflate them: synthetic bulk identity construction is separate from the user-facing browsing sequence.

All measurements are elapsed times from the same process-side monotonic clock within their respective test, not a claim of cross-platform comparability. The standalone profiling projection occurs **before** GUI process launch. It invokes the exact original `read_run_counts` validator and uses temporary wrapper instrumentation around the original functions; the wrappers are removed in a `finally`-safe context, including on failure. The actual original 100,000-row input, source SHA-256, identity audits, query/group membership and revision checks are never skipped or promoted to source-complete status. All results remain provisional.

## Auditable verification and privacy

- The dedicated Linux/Windows native-results workflow checks that **all four named phases** were observed and that the timings are finite, bounded numeric values. No target speed or speedup is imposed until the measurements and user-experience goals are approved.
- The real GUI evidence checks the five exact allowed action names and source-free bounded durations before retaining them. Browsers cannot supply source IDs, project paths, database revisions, SQL, fault injection, consent or timing data.
- Offline fast tests verify the original count projection and row counts, byte-for-byte source/membership immutability, no original function left patched, and explicit failure when the original count validator rejects bad evidence.
- The workflow retains only bounded timing, count, status and integrity evidence. It does **not** upload source titles, abstracts, clinician/user material, credentials, original records, full logs, file paths, browser state, unpublished database copies or unapproved metadata.

## What is **not** established

This is a profiling/instrumentation increment to support a subsequent *measured and provenance-preserving* performance repair. It does **not** itself optimise the production count implementation, establish a durable cache, introduce unattended processing, implement 100,000-row bulk GUI confirmation, make the application release-ready or validate AT-22. A total of 100,000 *provisional identities* is not a final deduplicated publication count: `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false` and `full_AT_22_acceptance=false` remain mandatory.

Before any merge advice: verify exact HEAD and every required four-platform Python regression, graphical dependencies/lifecycle, native Windows and Linux 100k browsing, unaffected earlier windows/materialisation benchmarks, definitive **completed** exact-HEAD Codex code review followed by security review, and every individual finding. Never merge without explicit owner approval.
