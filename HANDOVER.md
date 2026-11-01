# RESEARCH-Y handover — PR #36 merged; P1-06d report capture/rendering

## Authority and baseline

`RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 remains authoritative and unchanged.
Independent Python implementation; no imported project assumptions or code.

PR #36 is merged at `9a91e905a40a89c86193d68677f2f95cfb4bf7b5`, 1 November 2026
at 19:59 Coordinated Universal Time (UTC). Verify the current post-merge checks
rather than treating this merge statement as evidence that they passed.
The baseline includes read-only count projections, explicit identity/field provenance,
reversible associations, guarded match/rejection receipts, and atomic project creation.

Standing owner direction: at each completion step, begin instituting the next step.
Proceed during active work without routine continuation prompts. This does not permit
merging, scope changes, waived checks, bypassed live-retention consent or background
monitoring claims. Owner approval and exact-commit reviews remain mandatory.

## Current review increment — P1-06d capture and renderer, not complete export

Read `docs/STRATEGY_WORKBOOK.md` and its scoped requirement mapping supplement.
`capture_strategy_report` freezes counts, approved strategy and query/partition
information using the SAME validated read-only transaction. Canonical immutable JSON
and hashes retain report provenance; this is a current projection, not reconstruction
of the original historical identity state. Unsupported filters/parameters fail closed.

`render_strategy_workbook` returns genuine formatted Excel bytes: summary, source and
identity totals, approved terms, exact queries, partition plans, warnings, methods and
reconstructable canonical report input. Long cells use lossless ordered continuations.
Text stays literal; no generated formulas, macros, external hyperlinks or connections.
Unknown, zero, identifier progress, metadata and provisional identity counts remain
separate. All sheets state INCOMPLETE. Original licensed record text is not included.

This is an internal renderer. No user-selected file is published and no database
export receipt is created. Do not expose a fake successful Export control. Audited
saving, destination protection and failure/recovery remain the immediate next work.
The backend may create its own temporary files while rendering.

The branch proposes the specification's openpyxl backend as an optional `excel` extra:
openpyxl 3.1.5 and et-xmlfile 2.0.0, with matching test pins. Core dependencies remain
empty. Dependency adoption remains part of owner PR approval, not an assumed main
change. No untrusted workbook import is implemented or security-approved.

Initial local verification: 48 renderer/contract tests passed on Linux Python 3.13.5;
98% renderer and 81% combined branch-aware new-module coverage. The database capture
integration tests are committed for full repository CI, not claimed locally tested
against a reconstructed baseline. No full checkout was available in the local runtime.
Current-commit four-platform checks and both definitive reviews remain required.

## Immediate next step — finish #37 before the application flow

Implement frozen-snapshot persistence, prepared/published export receipts, atomic
no-overwrite publication, safe destination handling and explicit interrupted-export
recovery. Define/test the gap between a database commit and a filesystem action rather
than pretending both are one transaction. Test audit/disk/permission failure, process
termination, cancellation, concurrent exports, retry and Windows reparse points.
Retain earlier reports even when research evidence changes. See the concrete contract
in `docs/STRATEGY_WORKBOOK.md`. Then proceed to a minimal usable application flow.

Keep #37 open; rendering is not complete export acceptance. Keep #35 open for broader
reported-union/verified publication count acceptance, #33 for project-wide candidate
discovery and scaling, and #11 for Windows junction handling before untrusted imports.
The 2–32-record helper limit is NOT a source retrieval or counting limit. Annotation-
aware publication-wide merge/split and automatic rerun decision propagation remain open.

## Preserved counts and source boundaries

Read `docs/COUNT_PROJECTIONS.md`, `docs/PUBLICATION_CANDIDATES.md`,
`docs/PUBLICATION_IDENTITY.md` and `docs/PUBLICATION_RUN_STATUS.md`.
Counts read one transaction without migration/repair/status writes. Source-reported
unknown, explicit zero, retrieved identifiers and saved metadata stay distinct.
Arbitrary multi-query reported unions are not summed. Publication identities are
hypotheses; verified-publication and extracted-abstract denominators remain unknown.
Queryless/unmaterialised records and current/stale/conflicting decisions remain visible.
Local ledger consistency is not full connector translation/partition/quota validation.

PubMed run #41235232458 (31 October 2026): 19,483 unique identifiers, 43 pages, six
disjoint leaves and controlled pause/reopen. Scoped AT-07/identifier-stage AT-09 passed;
full metadata, broader queries/failures and whole-product acceptance remain partial.
See `docs/evidence/pubmed-41235232458-summary.json`.

Starter sample #41254004073: observed 5,000/day allowance, 19,574 reported matches,
two adjacent 50-record pages, no returned abstracts. Full run #41306953908 (1 November
2026, 12:46 UTC): 19,584 reported/committed records, 392 acquisition and 392 verification
pages, 786 requests, zero failures/unknown outcomes. Separate-process restart preserved
first-page acquisition; 4,214/5,000 quota remained. Scoped enumeration/recovery success
is not a frozen snapshot, full abstracts, live quota reset, multi-day or product-wide
acceptance. Aggregate/hash evidence is not an independent record-level audit.
Read `docs/WOS_LIVE_ACCEPTANCE.md`; #7/#8 remain open. The working Starter key is already
configured; never request it in chat or repeat source access for documentation alone.

## Safeguards and reviews

Retain transactional creation, recoverable schema-v4 migrations, full durability,
immutable plans/metadata, query memberships, request journals and worker fencing.
Explicitly recover stopped workers; keep failure budgets, unknown request outcomes,
malformed/missing quota distinctions and provider-wide longest Retry-After delays.
Local budgets are normal pauses; never assume quota reset. Final Starter verification
must fit one uninterrupted session and available quota. Keep all four full-suite
checks, compact test labels and current Windows/Linux timeout bounds.

Before merge advice retrieve current HEAD, required checks, review summaries, individual
receipts and all findings. Definitive exact-HEAD code review first; security afterwards
unless a valid automatic review already exists. Do not duplicate requests. New commits
invalidate old acceptance. Missing timestamps, mismatches or contradictions mean
unverified. Never merge without explicit owner authorisation. At a blocker report the
actual evidence and required action; do not claim asynchronous monitoring.
