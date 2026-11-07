# P1-06k1 — Project-wide, read-only potential-duplicate queue

**Baseline:** owner-merged PR #72, repository `main` at `45a29baa15297bac8e84bfb0daaf0ac381f3adf9`, 7 November 2026. The authoritative repository `RESEARCH-Y_SPEC.md` remains unchanged. Parent issues #9/#33/#35/#41/#43; bounded partial DATA-01/02/04/05/06, DUP-01–05, COUNT-01/05, AUDIT-02/03, UI-07/09 and AT-01/09/10/11/17/19/21. This is **not** final deduplication acceptance.

## Researcher workflow

The experimental local desktop results screen offers a **Refresh potential duplicates (READ-ONLY, OFFLINE)** action. It builds a temporary inverted index over all materialised, retained PubMed and Web of Science (WoS) source records in **every run of the current project**. Only candidate pairs involving at least one retrieval from the researcher-selected run are shown, avoiding irrelevant earlier-run pairs.

The index uses the existing, explicitly defined source projections and exact normalised digital object identifier (DOI), PubMed identifier (PMID), WoS accession number and title. Missing, malformed, ambiguous/multiple values are never treated as agreement. The interface displays *which* fields matched; it does not return abstracts, full raw metadata or a claim that a matching identifier belongs to the individual abstract rather than its supplement.

The previously recorded `publication_candidate_decision_v1` audit receipts remain review hints even when no current exact key matches. Current candidate status and warnings come from the original candidate service. A previous rejection is not deleted, and an apparent new match never automatically overrides a past researcher decision. Confirmed links, rejected matches and stale/prior receipt warnings remain visible as distinct states.

A 20-pair keyset queue page requires a complete source/identity/decision **revision** on subsequent pages. This revision covers current-run count evidence, every original project's retained source record, current identity links, prior-run statuses and source query/membership context, and original review receipts. If evidence changes, continuation fails explicitly and requires a first-page refresh. No provider call or persistent duplicate index is created. All result-count denominators continue to originate in the original storage and run-count projection.

An explicitly displayed pair whose **both** retrievals belong to the selected run can open PR72's existing researcher-confirmed comparison/decision form. The trusted host re-reads the same original queue page before opening the pair, then separately validates the candidate and selected run via their original services. It never accepts an arbitrary pair ID, query or filesystem path from the browser. Pairs spanning different runs are displayed but **read-only** pending a separately validated cross-run decision workflow; they cannot be silently adopted as reviewed.

## Resource and scientific limitations

The discovery bound is **100,000 retained project source records** and **100,000 distinct candidate pairs** per requested queue; exceeding either fails with a fixed `candidate_queue_over_limit` error and does **not** return a partial page disguised as complete. Unsupported source layouts and unmaterialised retrievals are reported separately and not silently treated as negative candidates. A higher-cost project requires a later durable, incrementally indexed discovery worker and explicit 100,000-record performance benchmarks. This initial index is rebuilt on every offline read; the index is temporary, not persisted.

`exact_rule_coverage_complete=true` refers **only** to the recorded exact-key-and-existing-receipt method inside its stated resource bounds. It does not claim exhaustive bibliographic duplicate discovery, validated high-confidence automatic matching, no missing metadata, or identity resolution across original source constraints. **`candidate_discovery_complete=false`**, **`exhaustive_duplicate_discovery=false`**, **`deduplication_complete=false`**, **`source_retrieval_verified=false`**, **`verified_complete=false`**, and **`global_unique_publications=null`** remain explicit and immutable-by-convention in every result.

A title or DOI shared by two different conference abstracts is only a **review hint**. The engine never invents an abstract identifier, automatically merges full article/conference/supplement records, infers language/species eligibility, downloads or redistributes metadata. Previous confirmed decisions remain untouched. Underlying original source queries, records, and query/group memberships never change during queue reads. Prior decisions are traceable to their existing immutable event identifiers, not an invented synthetic index event.

## Tests and remaining gates

Disk-backed synthetic PubMed/WoS fixtures cover duplicate DOI without automatic merge, repeated groups, two-run discovery with cross-run refusal, 20+3 keyset continuation, re-opened project, historical researcher rejections with no current matching field, explicit unmaterialised/unsupported counts, invalid/forged cursor or credential fields, stale source-query/run evidence, corrupted source records, a dense candidate-key over-limit refusal, and a trusted-host same-run review with post-commit receipt reconciliation. The existing exhaustively parametrised command-dispatch test covers the new queue operation.

The initial local graphical application remains a feasibility prototype, not an accepted Windows installer. Full 100,000-record latency/memory, fuzzy/near-duplicate discovery, durable multi-pass indexing, cross-run decision admission, specialist manual import/society fields, exports and final publication verification are **outstanding**.

**Next planned increment:** move beyond a transient exact-key index to a tested, incremental and indexed project-wide discovery/review pipeline, especially large/dense candidate sets, historical-run decision compatibility and validated performance, before claiming any final deduplicated master list. Keep issues #33/#35 and broader source/release acceptance open.

**Merge rule:** confirm exact current HEAD, all four Windows/Linux Python jobs and applicable graphical dependency/lifecycle checks, definitively completed exact-HEAD Codex code review **first**, then exact-HEAD security review, every individual receipt/finding disposition, and explicit project-owner authorisation. Never merge automatically.
