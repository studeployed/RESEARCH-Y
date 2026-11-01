# RESEARCH-Y handover — PR #38 merged; audited workbook publication

## Authority and verified baseline

The repository `RESEARCH-Y_SPEC.md` version 1.0.0-draft.1 remains authoritative and
unchanged. Independent Python implementation; no imported project assumptions.
Owner-merged PR #38 is commit `edce22ca63bc55322f31e183c8421413759b0e15`, merged
1 November 2026 at 20:38 Coordinated Universal Time (UTC). Its post-merge Python
test run #41347875891 completed successfully. This validates the baseline, not
this new export-publication branch. The optional Excel dependencies are unchanged
from that owner-merged baseline; this increment adds none.

Standing owner direction: at each completion step begin instituting the next step.
Proceed during active work without another routine continuation prompt. This does
not authorise automatic merges, scope changes, waived gates, live-retention consent
or asynchronous monitoring claims.

## Current review increment — P1-06d saving and recovery

Read `docs/WORKBOOK_PUBLICATION.md`, `docs/STRATEGY_WORKBOOK.md` and their scoped
traceability supplements. Issues #39 / #37 / #9 remain the relevant parents.
New `workbook_exports.py` captures a report and journals preparation in one validated
transaction, retaining its original canonical payload for every retry. New
`export_files.py` guards local paths, exclusively creates files and publishes via a
no-overwrite hard link. No replacement fallback is allowed on unsupported filesystems.

The append-only journal uses existing audit_events with per-export event types, not
a new schema or an unsynchronised second research database. Prepared, staging,
staged, publishing, published and cancelled are distinct committed phases. Failure
preserves the last phase and appends a static diagnostic when possible. SQLite and
filesystem operations are NOT one atomic transaction. A visible file without its
published receipt is not an audited success; recovery requires matching file identity
and digest rather than adopting an unrelated byte-identical file.

The original retained workbook is independent of the exported copy. Editing a saved
workbook cannot alter it; later inspection detects changed output and never overwrites
the edit. Stages/cancelled generations are retained, not automatically cleaned up.
Default outputs are project-relative. Explicit external local directories are supported
with recorded filesystem identity, not persisted absolute paths. Unicode output names,
Windows network/device paths, automatic cleanup and unsupported link filesystems remain
explicit limitations. Reopening/copying completed projects preserves content provenance;
copying an unreceipted in-progress publication can require original-location recovery.

POSIX uses directory descriptors; Windows holds directory handles and refuses reparse
points. This is a trusted local-project workflow, not a sandbox against a hostile
same-account process. Windows junction tests must actually run before platform claims.
No full power-cut durability or universal Windows directory flush guarantee is made.
Broader issue #11 and untrusted archive/import acceptance remain open.

Local targeted verification: 71 filesystem/protocol cases passed on Linux Python
3.13.5, ResourceWarning treated as errors; 83% rounded combined branch-aware coverage
of the two new modules. Windows-specific branches and actual application integration
are not counted as locally passed. Protocol tests use real SQLite and files but
substitute capture/renderer/project-opening boundaries; the existing StrategyReport
module was reconstructed and Git-blob-hash verified. Eleven additional full-repository
integration cases are committed for CI, using actual projects/counts/capture/rendering,
immutable audit triggers and two real application-process crash cases. No full checkout
was available locally. Full four-configuration checks and exact-commit reviews remain
required; current review-branch functionality is not merged or accepted.

The existing renderer is unchanged: literal-safe genuine Excel, full exact query text
with continuations, explicit unknown versus zero, provisional versus verified totals,
INCOMPLETE labels, and exclusion of original licensed record text. Saving does not
promote research completeness or change source records, counts, identities or statuses.
No provider requests, credential changes, schema migration, dependency, workflow or
specification amendments are introduced.

## Next ready work

Initiate minimal usable application-flow preparation while this increment is reviewed:
new/open project, current project/location, named run inspection, count warnings and
this audited export service with explicit incomplete/failed/recovery states. Evaluate
the specification's preferred Python interface/packaging choices before proposing
material dependencies. Keep network work and workbook work off the interface event
loop, retain request identifiers for retries, and never expose fake working controls.
Implementation must start from a freshly verified owner-merged baseline.

Keep #37 open for full workbook/export acceptance, #35 for broader source-union and
verified publication counts, #33 for project-wide duplicate discovery/scaling, and
#7/#8 for outstanding live-source acceptance. A prepared issue is not a completed
interface. Annotation-aware publication-wide merge/split, automatic rerun propagation,
full master/conference/guideline exports and packaged installation remain open.

## Preserved source and scientific boundaries

Read `docs/COUNT_PROJECTIONS.md`, `docs/PUBLICATION_CANDIDATES.md`,
`docs/PUBLICATION_IDENTITY.md` and `docs/PUBLICATION_RUN_STATUS.md`.
Unknown, zero, identifiers and saved metadata are different denominators. Arbitrary
multi-query reported unions are not sums. Publication identities are hypotheses;
verified-publication/extracted-abstract counts remain unknown. Queryless/unmaterialised
records and stale/conflicting decisions stay visible. A 2–32-record candidate helper
is NOT a source acquisition or count limit. Local ledger checks are not source acceptance.

PubMed run #41235232458: 19,483 unique identifiers, 43 pages, six disjoint leaves and
controlled restart; full metadata and broader live acceptance remain partial.
Starter full run #41306953908: 19,584 reported/committed records, 392 acquisition and
392 verification pages, 786 requests, zero failures/unknown outcomes, separate-process
restart and 4,214/5,000 quota requests remaining. This does not prove a frozen snapshot,
complete abstracts, live multi-day/quota-reset recovery or whole-product acceptance.
Aggregate evidence is not an independent record-level audit. Existing credentials
are configured; never request them in chat or repeat source calls for documentation.

## Safeguards and reviews

Preserve transactional creation, recoverable schema-v4 migrations, full durability,
immutable plans/source metadata, memberships, request journals and worker fencing.
Explicit stopped-worker recovery; retained real failure budgets/unknown outcomes;
malformed-versus-missing quota distinctions; provider-wide longest Retry-After delays.
Local session budgets are pauses, not provider errors. Never assume quota-reset time.
Final Starter verification requires one uninterrupted session and available quota.
Keep all four required test configurations and existing bounded timeouts/reporting.

Before merge advice retrieve current HEAD, required checks, code/security summaries,
completion timestamps, individual receipts and outstanding findings. Definitive
exact-HEAD code review first; then security unless a valid automatic review exists.
Do not duplicate reviews or infer completion from a reaction. New commits invalidate
old acceptance. Never merge without explicit owner authorisation. Report blockers
and verified evidence without promising asynchronous monitoring.
