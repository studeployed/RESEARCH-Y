# P1-06i1 — Combined PubMed + Web of Science run execution board

**Baseline:** owner-merged PR #67 on \`main\` at \`45c0b44754cd07b04fa447c633bb4b5dbf516dd3\` (4 November 2026).
**Authority:** version-controlled \`RESEARCH-Y_SPEC.md\` version 1.0.0-draft.1; SEARCH-06/12–14, SRC-01–08, RUN-01–07, COUNT-01–05, UI-05/06, DATA-01–06, AUDIT-01 and partial acceptance tests AT-05/09/10/19/21. The specification is unchanged.

## What this delivers

PRs #64–#67 have now connected two distinct provider pipelines to the experimental local graphical application: Web of Science (WoS) Starter page acquisition and independent verification, and PubMed ESearch identifiers followed by EFetch source metadata. Each original service has its own checkpoint, quota/retention constraints, source status and reporting conventions. Until this increment, those pipelines appeared as separate screens, making it difficult to see whether **every approved OR concept group** had actually progressed.

This increment adds a **single offline whole-run execution board**. It reads the original stored group/query inventory and existing **run-count projection** from one validated read-only SQLite transaction. The original PubMed checkpoint validator and the WoS immutable-plan validator underpin the source-specific stages; all groups and both primary sources remain visible. The whole-run count projection supplies existing canonical denominators rather than a second independent count system.

Each query row shows its exact approved source-specific expression, actual stored status, reported matches (including explicit **UNKNOWN**), committed source identifiers, retained metadata, count difference, actual page/verification counts where supported, and a *next-step category*. The board separates:

- PubMed not started, partially collected/paused identifiers, reconciled identifiers awaiting EFetch metadata, EFetch metadata saved, and genuinely verified **zero** identifiers.
- WoS not started, unfinished source pages, pending verification, source enumeration reconciled **with warnings**, cancelled/uncertain requests, and possibly active/stale source ownership.
- Group-by-group source evidence and distinct per-source run unions. A record found in multiple groups is counted **once within its provider's source-record union** rather than using a misleading sum of group hits.

A source can have exact numeric equality without provider acceptance. The board shows **global_unique_publications = null** and **group_unique_publications = null** until cross-source deduplication is objectively established. Existing provisional publication identity counts are explicitly identified as **hypotheses**, not the final global unique-publication count. Even if every PubMed identifier set and every WoS page count reconciles, and every available EFetch record is saved, \`source_retrieval_verified=False\`, \`deduplication_complete=False\`, \`whole_search_verified=False\`, and \`verified_complete=False\` remain invariant. Society/manual source coverage, full abstract completeness, provider snapshot stability and final Preferred Reporting Items for Systematic Reviews and Meta-Analyses reporting remain outstanding. No final count is fabricated.

## Workflow and safety

The interface provides a prominent **Refresh whole-run evidence (offline)** control. This is a read-only command, not a scheduled search. Each displayed row includes a **safe next-step** button which takes the user to an already implemented source **preview or checkpoint inspection**, chosen by the original status. For example, an untouched WoS query opens the existing licensed-retention consent preview; reconciled PubMed identifiers lacking metadata open the existing EFetch source preview. PubMed queries without a checkpoint open their saved identifier view, where existing date-coverage controls are available. Starting any provider request still requires the separate original, explicit source-specific **Confirm** click.

The host re-reads the entire board before responding to a next-step click and rejects a **stale revision** rather than silently changing query, group or intended provider action. Only the allowed source query identifier and exact board revision cross the browser-host boundary. The new \`run_board\` worker operation refuses credentials, external directories, export parameters and unrelated command fields. It cannot issue an application programming interface (API) request, change a stored count, create a checkpoint, complete a search or dispatch an unattended worker.

Read-only source results are inspected on a consistent transaction. If any checked page/identity/metadata/plan evidence is contradictory, the board **fails closed** with a static diagnostic; no invented empty run is displayed. The previous run view remains accessible. A refresh and the next-step route never automatically reissue an unknown provider request or release a quota hold.

## Evidence and remaining work

For run-wide enumeration and metadata coverage, the board recompiles the frozen
approved strategy and compares each expected source/group query with the stored
inventory inside the count snapshot. The same query matcher validates preflight.
A missing query leaves the remaining rows inspectable and adds a plan warning.
Unknown reported counts and failed or cancelled queries keep both coverage
flags false. A fully enumerated two-group fixture can have both flags true
while the final unique-publication count remains unknown.

For a finished Starter query the board replays the independent verification
observations against acquisition page identities, then validates the final count
and its verification-session owner in the same read transaction. A mismatch
refuses the board even when the number of saved verification rows looks right.

Offline, cross-platform regression tests use actual approved two-group OR strategies, original SQLite ESearch identifier pages, EFetch metadata commits, and the original WoS Starter client/runner plus synthetic provider responses. They cover not-started/unknown versus true zero; independent PubMed and WoS stages; successful WoS enumeration without final overall completion; EFetch metadata gaps; repeated group source-record union; read-only checksum preservation; damaged source evidence; strictly allowlisted worker command; credential-free source navigation; stale board revision refusal; and absence of board actions from automated GUI probes. These are **scoped fixtures**, not live external-provider acceptance or 100,000-record performance.

**Not implemented here:** automatic multi-source network scheduling, running entire group sets from one click, verified final source acceptance, a full group/source global deduplicated unique-publication count, automatic conservative cross-source matching/materialisation, final master table, complete reporting workbook, society-site acquisition or Windows product packaging. Those remain Phase 1–3 increments and acceptance gates, not implied accomplishments.

Before merge: four exact-HEAD Python continuous-integration configurations, the applicable graphical dependency/lifecycle matrices, definitively completed Codex **code review first** and then **security review** on the current HEAD SHA with individual receipts, disposition of every substantive finding, and explicit project-owner merge authorisation. Never merge automatically.
