# P1-06c — Read-only source and publication count projections

Implementation for review under issue #35 / #9. Approved specification unchanged.
Requirements: COUNT-01–05, DATA-01/02/04/05, METH-05, RUN-05, PROJ-04,
AUDIT-02 and scoped AT-01/02/09/10/16/17/19/21. Broader acceptance remains partial.

## Contract and denominators

`research_y.result_counts.read_run_counts(project, run_id)` returns a
`RunCountProjection` for the entire named run, using the current publication
associations. It makes no source requests, writes, migrations or repairs. No filter,
completion override or candidate-batch limit is accepted. `as_dict()` returns a
separate serialisable representation. There is no user interface or Excel output
in this increment.

Each query preserves its recorded status and reported count alongside:

- `retrieved_source_records`: the unique identifiers in retained local checkpoint
  evidence, or the materialised query records when no checkpoint exists;
- `metadata_source_records`: records actually saved and associated with that query;
- `identifiers_without_metadata`: retrieved identifiers without query metadata;
- `numeric_reconciliation`: `equal`, `shortfall`, `excess` or `unknown`, and a signed
  `retrieved_minus_reported` value when a source-reported total exists.

A successful identifier stage does not imply saved metadata. Abstract availability
is separately counted by each source's stored state without copying abstract text.
An absent abstract state is `not_recorded`, not a claim that no abstract exists.

Group/source rows count identifier and metadata **unions**, not arithmetic query
sums. A single query preserves its reported count. With multiple query chunks,
`reported_matches` stays unknown and `reported_count_status=union_not_established`:
the present model supplies no proven source-reported union for arbitrary chunks.
Individual query reports are retained, not added into a potentially inflated total.
Internal PubMed partitions belonging to one checkpoint use that root query's report.
A source not planned for a group is explicitly `not_planned`, not a zero-hit search.
The rows include PubMed and Web of Science plus other source names actually stored.

Per-source totals union identifiers across all groups and include queryless saved
records. Queryless records are disclosed separately; group memberships are never
invented. The sum across sources is named `source_record_sum`, not publication count.
Saved records with no publication association remain visible as unmaterialised.

## Publication identity is not completed deduplication

`publication_identities` per group, `global_publication_identities` and
`group_publication_identity_sum` describe **current active identity hypotheses**.
Empty identities retained for reversal are excluded. An identity with multiple
retrievals in the requested run is counted once, even across groups and sources.
Cross-run associations remain attributable to that run's own retrievals.

`group_unique_publications` and `global_unique_publications` remain unknown rather
than mislabelling identity rows as verified deduplicated publications. The count
`identities_with_review_required_links_in_run` describes association-head statuses;
it is not an exhaustive count of undiscovered or unreviewed candidate pairs.

The projection validates the existing candidate receipt journal once, then reports
latest exact-pair confirmations/rejections, stale decisions, disagreement with
current associations, and available prior-run receipts. These are recorded-decision
counts, not candidate discovery. Current evidence/rule/relevant-receipt checks reuse
the existing candidate logic. Automatic matching and prior-decision propagation
remain disabled. The small `_receipts(..., keys=None)` extension returns all
validated receipts; ordinary pair lookup retains its existing behavior.

Container links and source document-type labels do not establish an extracted
individual-abstract count. That denominator is unknown with `not_implemented`, not
zero. Collection records remain source retrievals, never invented abstract rows.

## Consistency and failure behavior

A URI read-only connection with `query_only` reads manifest/database identity,
current schema, foreign-key relationships and all count evidence on one explicit
read transaction. No ordinary writable/migrating project connection is used.
Concurrent commits cannot produce counts from one state and receipts from another.
Missing files are not created. Legacy schemas and a hot rollback journal requiring
write recovery are refused: use the existing explicit project-open/recovery path,
then retry. This layer does not silently repair or change source state.

Local ledger checks reconcile stored plan/page hashes, identifier indexes and
query metadata links. PubMed identifier-only pages are visible before metadata
fetching. Starter acquisition bodies are checked against their descriptor, request
identity, accession index and saved source records. Unsupported/corrupt source,
association, field or receipt evidence fails closed with `CountIntegrityError`.

**This is not full checkpoint validation.** Translation acceptance, partition
geometry, quota behavior, independent verification passes and source completeness
remain the existing connector gates. Accordingly
`full_checkpoint_validation_performed=false` and `source_retrieval_verified=false`
are explicit. Numeric equality is never called whole-source acceptance.

The output always has `status=incomplete`, `verified_complete=false`,
`deduplication_complete=false`, `candidate_discovery_complete=false` and
`export_permissions_verified=false` in this increment. Stored run/query statuses
remain separately visible and unchanged, even if a stored status says verified.

## Reproducibility and rights

`projection_scope=current_identity_projection_for_run` and `historical_snapshot=false`
are explicit. A later association/reversal may change the present-day projection
for an earlier run. The stable revision binds the current source, query, identity,
strategy and relevant decision evidence; unchanged evidence survives reopen and
relocation. This is not an immutable historical report or a digital signature.
Persisted historical report snapshots are future export work.

Returned data contains counts, local identifiers, group labels, status codes and
hashes, not titles, abstract contents, candidate actor/evidence text or credentials.
Group labels are researcher input and still require safe handling in future exports.
The projection does not grant redistribution rights or validate every source term.

## Verification recorded before review

85 targeted disk-backed tests pass locally on Python 3.13.5 / SQLite 3.46.1,
with ResourceWarning treated as errors. Combined branch-aware coverage of the two
new modules rounds to 96%. Fixtures use real project/schema/identity/decision
operations and synthetic local provider evidence, not licensed live records.

Representative outcomes:

| Fixture | Expected and observed |
| --- | --- |
| One identity, two sources and two groups | One global identity, group sum two; each source count stays one |
| Overlapping query chunks | Unique local identifier union; no fabricated reported union |
| Identifier stage ahead of metadata | Both counts and exact metadata gap visible |
| Unknown / zero / failed source | Distinct output; none promotes completion |
| Unmaterialised / queryless / inactive identities | Disclosed or excluded as explicitly defined; no lost source records |
| Confirm, reject, reverse, change context | Current or stale receipt status and identity counts remain consistent |
| Concurrent identity and receipt commit | One old coherent snapshot, then one new coherent snapshot |
| 10,001 stored records | All counted without silent truncation or 32-record review-helper limit |
| Corrupt plan/page/index/link/receipt | Explicit failure; underlying data unchanged |
| Abrupt child exit with hot journal | Count read refuses recovery writes; explicit open recovers prior projection |

Four intentional negative mutations were detected: removing the shared read
transaction, summing overlapping chunks, asserting verified completion, and
coercing unknown totals to zero. Correct originals were restored and all tests
repeated. Syntax compilation and scoped traceability checks passed.

The local workspace reconstructs eight required baseline modules, verified by Git
blob hashes (seven unchanged and the candidate-receipt helper deliberately amended).
It is **not a full repository checkout or Windows validation**. Required full-suite
Windows/Linux Python 3.12/3.13 checks and definitive exact-commit code/security
reviews are separate gates. The 10,001-record fixture is not full product performance
acceptance; large receipt histories and indexed discovery remain issue #33 work.

## Next increment and remaining gaps

Prepare the first genuine Excel search-summary/strategy export, preserving these
denominators and warnings, immutable report provenance, safe untrusted text handling,
source rights and atomic/no-overwrite failure behavior. Do not assume this branch
is merged until verified. Keep issue #35 open for remaining source-union acceptance,
verified publication totals and reporting integration. Source issues #7/#8,
deduplication discovery issue #33 and Windows junction issue #11 remain open.
