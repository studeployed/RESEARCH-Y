# P1-06a — Publication identity and source provenance

Implementation for review against the approved specification, not full deduplication
or release acceptance. Parent issues #30 and #9. The baseline is merged PR #31,
`90ae817b69d2d85ee9aab14bde7f5d83f557f0db`; its post-merge run #41320722923 passed
all four Windows/Linux Python 3.12/3.13 configurations. No source requests are made.

## Bounded contract

`publication_identity.materialise_retrieval(project, retrieval_id, actor=...)`
creates one provisional publication for an existing source retrieval. It returns
an existing association unchanged on replay, including a previously confirmed
association. Two retrievals with identical identifiers, titles or supplement
metadata remain separate until an explicit researcher decision. This is not an
automatic match, a unique-publication count, or proof that an abstract is distinct.

`read_publication` returns a consistent snapshot with the original source metadata,
all query/source/group/strategy/run memberships, each query's reported count and
status, current association evidence, and separately chosen fields. It does not
modify source records, source counts, query memberships, strategies or run status.
Original missingness and rights fields remain intact. No source value is inferred.

`associate_retrieval` moves one retrieval to an active target publication only with
literal `same_publication_confirmed=True`, an actor, evidence and current source
and target revision tokens. This is a researcher assertion, not an independently
validated bibliographic match. Revision tokens cover current association events,
source data, memberships and chosen-field state; changed evidence requires a new
review. A repeat of the still-current identical request is a no-op. A superseded
request fails rather than undoing a later decision.

`reverse_association` appends the inverse of the current association decision,
with fresh review tokens and an explanation. The prior publication identity is
retained even when empty; it is not an active result row. A reversal records a new
audit event rather than erasing history or restoring an obsolete revision token.
`read_retrieval_history` exposes the chronological decision chain and reversals.

These are retrieval-level association operations, not a publication-wide merge or
arbitrary split engine. Reversals apply to the current association decision; older
decisions cannot bypass later changes. Reassociation is rejected when a chosen
field depends on the moving retrieval until that choice is explicitly cleared.
Source-publication classifications, documents, container and organisation links
also block reassociation pending a dedicated annotation-aware merge/split workflow.
They are not silently moved, discarded or stranded.

## Source-backed chosen fields

`publication_fields.select_source_field` takes an explicit field name and a bounded
path into an associated source record. It selects the exact existing value without
normalising, enriching or inventing it. Missing/empty values and invalid paths are
rejected. Selection needs a current revision token, actor and reason; all original
alternatives remain visible even when titles differ. This increment does not
provide automatic field mapping, conflict adjudication or enrichment.

The stored choice contains audit references, not another licensed-text copy. The
immutable audit records the source retrieval, source checksum, path, actor, reason,
time and method version. The returned value is resolved against its original
source. `clear_source_field` removes the current choice while preserving its audit
and original data. Later choices do not make old review tokens valid again.

Selecting a field does not authorise its redistribution. Snapshots explicitly have
`export_permissions_verified=False` and `deduplication_complete=False`. The local
source records retain their existing retention/rights boundary. There is no export
or external transmission in these modules; a future export must enforce source
terms separately. Actor/evidence text is local researcher input, not authenticated
identity or independently verified scientific evidence.

## Storage, atomicity and integrity

The existing schema-v4 `publications`, `publication_retrievals` and append-only
`audit_events` are sufficient: no schema migration, new dependency or duplicate
membership journal is introduced. Association/field pointers resolve audit events
by primary key. Mutations use the project's existing single identity-checked
connection and `BEGIN IMMEDIATE`; audit, association and chosen-field writes share
one commit/rollback boundary. Reads use one explicit transaction for a consistent
snapshot. No journal, synchronous-write, backup, timeout or provider guard is relaxed.

Unsupported legacy association/chosen-field provenance is rejected for review,
not silently converted or overwritten. Invalid source objects, duplicate JSON keys,
non-finite values, changed source checksums and missing/mismatched audit references
fail closed. Checksums detect inconsistency, not authenticity against a writer able
to rewrite an entire database. Existing project trust boundaries and deferred
Windows junction issue #11 remain unchanged.

## Verification and scope

62 disk-backed synthetic cases pass locally on Linux Python 3.13.5, with
ResourceWarning treated as errors and 92% combined branch-aware coverage of the
two new modules. The five baseline modules (project creation and schema v2/v3/v4,
plus package initialisation) were reconstructed and verified against their Git blob
hashes. This is a targeted production-module workspace, not a complete checkout;
full four-configuration repository continuous integration remains required.

Cases cover idempotent creation/replay, source/group/run preservation, conflicting
titles, same-container abstracts and abstract/full-paper separation, explicit
confirmation, stale source/target reviews, reversal/history, field paths and rights,
audit/link-write rollback, reopened/relocated projects, unsupported provenance,
concurrent process creation and a child terminated after uncommitted dirty pages
spill to a rollback journal. These are offline persistence fixtures, not repeated
live source retrieval or a performance/release acceptance test.

Traceability: DATA-01/02/04/05/06, DUP-01/03/04/05, COUNT-01/05, AUDIT-03 and
PROJ-04; scoped AT-01/02/09/10/11/17/19/21. Broad requirements remain partial.
Automatic candidate matching and `automatic_high_confidence`/`rejected_match`
workflows, annotation-aware publication merge/split, propagation to new run
retrievals, final master counts, exports and the interface remain follow-on work.
Existing source-acceptance gaps are neither closed nor weakened by this increment.

## Next ready increment

Prepare P1-06b conservative candidate generation and explicit match/rejection
receipts against these identities. First define fixtures for normalised identifier
agreement, conflicting identifiers, distinct abstracts sharing a container,
publication-format disagreement, repeated runs and prior researcher decisions.
Do not select an automatic confidence threshold without validation. Keep candidate
evidence separate from applied associations. Subsequent increments add reconciled
master counts, first genuine Excel output and the minimal application flow.
