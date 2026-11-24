# Version 0.1.7 usability changes

The later installed 0.1.8 audit found that Continue callbacks and offscreen comparisons were not adequately covered by the original acceptance checks. See [the 0.1.9 follow-up](USABILITY_019.md) for the fixes and strengthened viewport/real-button verification; the original U02/U03 verification claims below are not sufficient on their own.

Issue #194 follows the owner's approval of the twelve findings from the full Windows usability evaluation. The release simplifies everyday work while preserving the authoritative scientific specification, immutable saved strategies, source consent, quotas and export permissions.

| Finding | Delivered behaviour | Verification |
| --- | --- | --- |
| U01 Saved-plan continuity | Draft groups, terms, suggestions and scope persist. Approved plans remain visible; Edit a copy and Start a blank search are explicit. Concurrent stale edits cannot overwrite a newer draft. Interrupted approval keeps its original request identity. | test_usability_continuity; test_gui_strategy_setup; native acceptance |
| U02 Action results visible | Candidate comparison opens its result; review queues stay open after filtering. | native acceptance |
| U03 Collection guidance | Database cards show counts, status and the next existing source step. Advanced recovery remains available. Continue opens a preview or progress view; existing confirmation and budget gates still authorise requests. | test_run_execution_board; existing provider flow tests; native lifecycle |
| U04 Article-first Results | Results loads a saved snapshot automatically, with a wide article table, search and row Open actions. | native acceptance; native_master_release_check |
| U05 Direct selection | Ticking a row updates selection immediately; page updates preserve selections elsewhere. Deselect wording states its scope. | test_usability_continuity; native acceptance; native_master_release_check |
| U06 One export entry | Scope, filename, destination and abstract permissions precede one save-and-verify action. Verified files can be opened; existing reports can be continued without overwriting output. | test_usability_continuity; test_master_exports; native acceptance; native lifecycle |
| U07 Readable information | Routine errors and timestamps use readable wording, everyday groups use names, technical identifiers and advanced manifests are secondary. | native acceptance; native lifecycle; visual inspection |
| U08 Responsive feedback | Working/success/error status is visible. Controls are inactive while an action runs; failed question/term entries stay available. Unknown outcomes retain existing reconciliation gates. | native lifecycle; test_usability_continuity; existing interruption tests |
| U09 Contextual checks | Frozen question, terms, limits and source coverage stay beside review choices on wide screens. Narrow screens have one content scroll. Recorded unchecked items are not described as passed. | test_search_review_screen; native acceptance; native lifecycle |
| U10 Stage-aware navigation | Compact sticky project navigation remains visible; search-start milestones appear only on Plan and Run. | native acceptance; native lifecycle |
| U11 Researcher and decisions | Saved researcher name prefills review forms. A classification form saves all choices in one transaction; retry is idempotent and stale reviews are rejected. | test_usability_continuity; test_study_classification; native lifecycle |
| U12 Progressive help | Query bytes and specialist recovery remain secondary. Credential setup has numbered Windows instructions. The bundled first-search guide follows the revised workflow. | native lifecycle; visual inspection |

## Evidence and boundaries

The native acceptance tool creates an isolated fixture, traverses planning, review, results, selection, export and comparisons, and writes an acceptance JSON plus screenshots. No credentials are loaded and no source requests are made. The existing desktop lifecycle covers creating, saving, reopening, relocation and workbook verification. Windows installer CI checks clean installation, reinstall, upgrade and project preservation.

The application does not mark a search scientifically complete merely because a form was saved. PubMed indexed All Fields and Web of Science Starter Topic coverage remain explicit; neither represents article full text. Pilot evidence is tied to the exact saved plan. Source permissions, interrupted-request handling and non-overwriting publication remain in their existing services.

Draft search-check answers remain in the current window until confirmed. Refreshing the result snapshot clears its selection. Optional model proposals still require individual researcher review. Mobile app-store delivery is outside this Windows release.
