# P1-06k4h — Compact, source-validated revision witnesses for large-run counts

**Authority:** version-controlled `RESEARCH-Y_SPEC.md` (unchanged). **Baseline:** owner-merged PR #91 (`main` merge `3724d48819313163bac769f9879d5cfde9a8c1e6`, 11 November 2026). Parent issues #9/#35/#41/#43; a bounded Phase 1 performance/integrity increment contributing only *partial* AT-10, AT-17, AT-19, AT-21 and AT-22 evidence.

## What PR #91 measured

The actual 100,000-original-source, 100,000-independent-provisional-identity benchmark measured the original unmodified complete count projection as follows (one hosted-runner sample per operating system, **not** repeatable performance or usability guarantees):

| Original validation stage | Linux (ms) | Windows (ms) |
| --- | ---: | ---: |
| Source original record validation | 2,106.736 | 3,126.419 |
| **Identity link, audit and snapshot reconstruction** | **4,163.334** | **6,131.687** |
| Query/membership validation | 124.206 | 190.699 |
| Existing review receipt validation | 425.560 | 522.037 |
| Other full projection processing (unattributed) | 937.293 | 1,450.437 |
| **Complete original count projection** | **7,757.129** | **11,421.279** |

The graphical action timings showed that selecting the run and browsing each 20-row page or original-source detail repeated the whole-run proof. This PR does **not** introduce any revision cache, loosen integrity rules, assume unchanged data or remove the full original scan. The immediate, measurable target is the identity stage's **unnecessary retention of complete publication snapshots for every independently linked singleton**.

## Bounded implementation

The existing original `_streamed_identity_rows` in `src/research_y/result_counts.py` already reconstructs each source/association snapshot from **original SQLite rows and their immutable audit event**, validates pointer version, source SHA-256 and status, and verifies query/group memberships. It then computes a canonical publication SHA-256 revision from the exact original `[publication_id, (created_at_utc, chosen_metadata_json), [source]]` structure.

For the common case of an independently linked **single-source publication with no selected fields**, the complete, validated source dictionary was unnecessarily retained inside a second `PublicationSnapshot` for the rest of the count projection. The count code only consumes the per-publication `.revision`, alongside the separately retained original validated source and link dictionaries.

This change retains **a frozen, slotted internal `_ValidatedRevision` object with only the exact canonical revision** for those simple singleton links. It still creates the original source dictionary, verifies every original source SHA-256 and original association audit record, reconstructs original query memberships, computes the **exact same canonical revision bytes**, and continues to include every publication's revision in the authoritative complete run digest. The temporary source structure becomes eligible for collection when its digest is complete, reducing memory retained for large runs without replacing or bypassing original evidence.

**Complex cases are deliberately unchanged:** any publication linked to multiple source records (including other historical runs) or possessing researcher-chosen fields still invokes the original `publication_identity._snapshot` and retains the full canonical `PublicationSnapshot`. Individual publication browsing, researcher decisions and field provenance continue to use the canonical full snapshot service, not the internal revision witness. The small-run route (under 2,048 sources), write path, source connectors, classification, export, schema, dependencies and user interface remain unchanged.

## Explicit evidence and acceptance checks

- Existing small/cross-run/chosen-field source fixtures compare every revision against independent original `identity._snapshot` and assert complex publications remain full snapshots, while an ordinary singleton uses the compact witness.
- A separate fully materialised **512-source, single-run** fixture checks all 512 individually audited identity links, all distinct SHA-256 revisions, selected individual canonical sample parity, byte-for-byte immutable original SQLite, unchanged full-run count projection after reopen, and **unknown** true unique publication count.
- Existing malformed pointer, mismatched event, corrupt source record, candidate receipt, page-cursor, revision-stale and researcher decision tests remain applicable. Native Windows/Linux 100,000-result browsing and earlier 100,000-original-source and 100,000-materialised source workflows must run and pass. Compare prior PR #91's original identity-stage timing and any retained resident-memory measurements with new same-workload results; do **not** claim a universal speedup from a single noisy hosted runner.
- Any original source/audit violation remains an explicit failure, never an unlinked/zero record, successful page, completed source or fake verified count. No database write, external provider call, model call, cloud transmission, licensing change or passive user consent occurs.

**Limit:** This is a narrow in-memory representation reduction for an already validated high-cardinality count path, not a final global uniqueness/deduplication decision. `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false` and `verified_complete=false` are unchanged. It does not satisfy full AT-22, resolve page-scanning latency universally, render all records at once, or establish end-user usability.

## Exact-commit merge gate

Verify current HEAD and all required four-platform Python tests, relevant read/worker benchmarks, both 100,000-record result-browsing Windows/Linux jobs and applicable graphical/finite-window workflows. Require a **definitively completed** Codex code review for that same exact HEAD **first**, followed by a completed security review for the same HEAD; reconcile the summary, individual receipts and all findings. No merge without explicit project-owner authorisation.
