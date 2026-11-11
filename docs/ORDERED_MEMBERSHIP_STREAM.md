# P1-06k4i — Ordered source/membership streaming for original count projections

**Authority:** current repository `RESEARCH-Y_SPEC.md` (unchanged). **Baseline:** owner-merged pull request (PR) #92 at `main` commit `0c9087e68e7a9e30e68d69927c591ac969a69c10` on 11 November 2026. Scoped Phase 1 work under issues #9/#35/#41/#43, with only partial evidence for requirements DATA-01/02, COUNT-01/03, DUP-01/04 and acceptance tests AT-09/10/17/19/21/22.

## Remaining measured bottleneck

PRs #91–92 measured an actual Windows and Linux 100,000-original-source results workflow and reduced memory retained for simple **independently audited, provisional** publication identities. The full original run projection and every results-page/detail operation still validate all original source, association, query and audit evidence. A representative PR #92 Linux single-run performance artifact observed **680 MB peak parent-process memory**, **10.80 seconds** for full-run counts and **10.95 seconds** for the first page (hosted runner; neither a fixed baseline nor a performance guarantee).

The current high-cardinality `result_counts._streamed_identity_rows` still made several simultaneous large Python structures, even after PR #92's compact revision witnesses: a `publication_data` map, a publication-to-source map and a project-wide `defaultdict(list)` of per-source query/group membership dictionaries. It populated these dictionaries for every original source, then traversed the full set again to compute each canonical SHA-256 revision.

## Bounded implementation

For original selected runs containing at least 2,048 source records, the high-cardinality path now uses **two original SQLite cursors in the same read-only transaction**, each ordered by canonical `retrieval_id`. The source/association stream still joins the original source record to its publication identity, original chosen-field state and immutable identity audit event. The query/membership stream still uses the original `query_retrievals`, `source_queries` and parent `search_runs` joins. A linear merge by original `retrieval_id` consumes all membership rows, including unmaterialised sources; it temporarily retains **only the current source's** membership dictionaries to form the exact original revision.

For each linked source, the existing `identity._link_from_evidence` still validates the pointer and audit event type, event ID, source SHA-256, source ID and status. Unlinked source rows remain unlinked, not silently lost; memberships with missing/mismatched source IDs fail closed. All original source/metadata/key checks, foreign-key checks, subsequent query/count reconciliation and the whole-run SHA-256 revision are unchanged.

**Simple independent single-source identities** retain only the exact canonical `_ValidatedRevision` witness established in PR #92. A multi-source publication (including historical-run links) or any researcher-chosen field still uses the original `identity._snapshot` validator for the **complete** original publication. Once this full snapshot has been constructed and validated, subsequent links to the same publication continue to have **their own source-audit events checked**, but the same full snapshot need not be reconstructed twice. The canonical JSON representation, membership ordering, publication revision and user-visible result fields do not change. No persistent cache, index schema, new dependency, provider call, field-selection rule or user-controlled operation is introduced.

The existing small-run canonical path and publication detail/decision services are untouched. The revised high-cardinality route cannot weaken source validation when metadata is malformed, audit pointers are stale/invalid, a membership references a different run, or a database integrity constraint fails; no partial result is treated as verified complete.

## Validation and limits

Offline regressions use actual versioned SQLite fixtures to compare every streamed revision with the unmodified original `identity._snapshot` for multi-group query memberships, duplicate query chunks, unmaterialised originals, queryless sources, source-backed title decisions, researcher-chosen fields, cross-run associations, prior review receipts and malformed audit pointers. The 512-source independently audited fixture must complete the streaming path **without any per-publication full-snapshot fallback**, and its source bytes, complete count projection, restart and original audit journal must remain unchanged.

Dedicated Windows/Linux 100,000-original-source benchmark workflows and both real native-Windows/guarded-Linux 100,000-provisional-results browsing jobs must pass with the **same original source counts, original audit evidence and unknown true unique-publication count**. Record actual timing and peak parent-process memory next to PR #92's previous per-platform evidence; do not assert a guaranteed improvement based on a single shared runner or conflate parent memory with combined host + worker memory.

This remains **partial** acceptance only. The entire run still undergoes exact original data validation on every browse request, source retrieval remains incomplete/unverified, no final deduplicated publication count is inferred, the source population is synthetic and full accessibility, installer, exports and full AT-22 remain outstanding. `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false`.

**Merge gate:** inspect current PR HEAD and all relevant GitHub Actions tests, completed matching-commit Codex **code review first**, then completed matching-commit **security review** (recognising automatic starts), individual findings and project-owner authorisation. Never merge automatically.
