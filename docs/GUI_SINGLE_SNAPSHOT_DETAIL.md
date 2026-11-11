# P1-06k4f — One original SQLite snapshot for provisional detail selection

**Authority:** repository `RESEARCH-Y_SPEC.md` (unchanged). **Baseline:** owner-merged PR #89, `main` merge `11efe7f2584d8fa9bbe27c43a7a617fcca1071a7` (11 November 2026). Parent #9/#41/#43, scoped Phase 1 performance and integration work towards UI-07/08 and AT-09/10/19/21/22.

## Motivating measured problem

PR #89's genuine 100,000-original-source result browser completed on Linux and native Windows, but the entire graphical session took approximately **75.8 seconds (Linux)** and **53.0 seconds (Windows)** on shared hosted runners. These are independent observed totals, not portable performance guarantees. Both workflows retained all 100,000 separately audited **provisional** identities, original source/group memberships and integrity. **No definitive unique publication count** was established.

An ordinary publication detail click previously launched **two sequential independent supervised worker reads**: first a full-run count/identity revision projection to verify the displayed 20-row page, and then *another full-run count/identity revision projection* to load the selected original citation detail. On large projects, both recalculate and audit the original 100,000-record ledger. The 35-second bound applies to each worker operation, but this redundant double scan damages interactive responsiveness.

## Bounded change

- Add `read_publication_page_detail` to the **existing** `publication_results` read service. It validates the input run, cursor, selected publication and exact previous SHA-256 revision; opens **one original read-only SQLite transaction**; computes the existing authoritative `result_counts._snapshot` **once**; regenerates the same 20-row keyset page using the existing original source/identity validators; verifies the requested detail identity is **actually on that page**; and renders the existing bounded citation-only detail from the *same* transaction and source evidence.
- Refactor the two original independent read services to reuse the same small page/detail rendering helpers. Their public results and failure semantics remain unchanged. The newly combined operation adds a provenance-safe wrapper with the same explicitly **incomplete** status and a pair of original `page` and `detail` results; it performs no writes, API requests, caching or background work.
- Expose this through the narrow `ApplicationCommand` allowlist, with strict run/identity/revision/cursor validation. No browser control can provide a path, arbitrary query, work budget, actor, consent, export, source retrieval or credential as part of this operation.
- The existing GUI host continues to check that the regenerated page is exactly equal to the previously displayed page and that the detail is still the selected row. It no longer requests a second independent full-run projection. The existing 35-second worker deadline, user-facing source/privacy safeguards, unknown-global-unique-publications status and explicit researcher-controlled writes are unchanged.

## Verification and limitations

Offline targeted tests verify that the combined operation returns **exactly the same original page and detail structures** as the prior two-service route, calls the full run projection **exactly once**, leaves the original SQLite bytes and audit receipts unchanged, refuses a valid publication not on the displayed page, refuses revisions invalidated by changed source-query state, preserves abstract suppression, and rejects forged actors/credentials/invalid cursors. Existing full-host and real native GUI workflows exercise the unchanged visible interface; the dedicated 100,000-row Linux/Windows workflow should be rerun and compared to the original PR #89 measured values.

This removes **one unnecessary original full-run validation per detail request**, not all expensive validations. Initial results loading and moving to the next page still each validate the original full run. It does not certify real-world usability, latency targets, complete sorting/filtering, all 100,000 simultaneous rendered rows, final deduplication, provider verification or full AT-22. A publication remains an independently created **provisional hypothesis** until explicit reviewed bibliographic decisions and source reconciliation justify otherwise: `global_unique_publications=null`, `source_retrieval_verified=false`, `deduplication_complete=false`, and `verified_complete=false` continue to apply.

## Merge gate

Run the full four-platform Python 3.12/3.13 regression matrix, original graphical dependency/lifecycle tests, native/loopback 132- and 100,000-original-source consent scenarios, and the 100,000-provisional-results native/loopback browsing workflow. Inspect new/old genuine per-platform timings without claiming a reliable speedup merely from noisy shared-runner elapsed time. Obtain definitive completed Codex **code review first** and then **security review** covering the **exact current PR HEAD**, including matching individual receipts and disposition of findings. The owner alone authorises merging.
