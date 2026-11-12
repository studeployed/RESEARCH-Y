# P1-06l3 — Audited, explicitly authorised provisional workbook export intent

**Authority and baseline.** The approved version-controlled `RESEARCH-Y_SPEC.md` remains authoritative and unchanged. This increment follows owner-merged PR #96, merge commit `396d156bee8532de66fae158c526a06498f4bf19` on 12 November 2026. It is a bounded preparatory service toward EXPORT-01/03/04, AUDIT-01, COUNT-01/05, SEC-03/04 and AT-10/18/19/21; none is accepted as complete.

## Evidence from owner-merged PR #96

The original versioned SQLite project contained **100,000 source records** and **100,000 original query/group memberships**. Separate real Windows and Linux Python 3.12 workflow jobs successfully rendered and independently parsed every workbook row for both (a) **128 provisional identities + 99,872 unmaterialised originals** and (b) **100,000 separately audited provisional identities**. Workbook bytes were not published. Retained source-free evidence measured:

| Synthetic workbook state | Linux rendering | Windows rendering |
|---|---:|---:|
| 128 provisional, 99,872 unmaterialised | 93.059 seconds | 61.390 seconds |
| 100,000 independently provisional | 172.798 seconds | 122.202 seconds |

The original source and query/membership hashes, complete row counts, rights exclusions and explicit incompleteness statuses passed in both test jobs. These are shared-runner observations, not runtime service-level guarantees. No final deduplicated unique-publication count was inferred, and **neither** 100,000 identity materialisation step was researcher-authorised production behaviour.

## New internal preparation service — no published file

`src/research_y/provisional_manifest_intent.py` provides three **internal-only** operations:

- `preview_manifest_intent(project, run_id)` checks the entire selected run through the existing canonical `result_counts._snapshot` on an identity-checked read-only SQLite transaction. It returns the exact SHA-256 revision, original source/identity/unmaterialised denominators, `INCOMPLETE`, `global_unique_publications=null`, and explicit rights and approval boundaries. It performs no writes or provider calls.
- `prepare_manifest_intent(project, run_id, output_name, *, export_id, expected_revision, actor, confirmed)` requires a canonical researcher-supplied export UUID, valid named-run UUID, an **exact** 64-character lowercase original revision, a safe Windows-compatible `.xlsx` filename, a printable nonempty researcher label, and **`confirmed is True`**. Under the same guarded original SQLite **immediate write transaction**, it recomputes the entire canonical run projection, refuses a changed revision and visible filename conflicts, then appends a single, checksum-bound `provisional_manifest_intent_v1:<export ID>` preparation receipt to the existing immutable `audit_events` table. The receipt contains **only original project/run/revision IDs, denominators, target filename, researcher authorisation and incomplete/rights declarations**, not original title/abstract/DOI/provider content or workbook bytes. This is **approval to attempt a later controlled export**, not evidence that a file exists, is rights-cleared, or was published.
- `inspect_manifest_intent(project, export_id)` replays and verifies the original append-only receipt (including exact canonical JSON, checksum, event timestamp, run identity and schema). It recalculates the full original run revision in the **same** read-only transaction, exposes only `authorised_not_rendered` if unchanged or `stale_reapproval_required` if sources, original memberships, current identities or other count-affecting evidence changed. The view always says `workbook_rendered=false`, `workbook_published=false` and `output_bytes_written=false`.

**Idempotency:** Retrying preparation with the same `export_id`, run ID, original revision, filename and actor returns the original immutable receipt. No new approval or recapture is inferred, and the reinspection clearly indicates if the project changed. Reusing the ID with a different run/name/revision/actor fails with `intent_conflict`. Failed or unconfirmed preparations leave **no** consent receipt, and original research content is never modified. Absent or corrupted receipts fail explicitly; receipt hashes are integrity references, **not** signatures against a privileged database administrator.

**Strict no-migration read boundary:** The preview and inspection services now use `result_counts._read_connection`, which opens the original SQLite database with a **read-only URI**, checks the current schema/application identity and rejects legacy projects instead of migrating or writing backups. The preparation service also performs this strictly read-only schema check **before** opening its guarded audit writer. A project requiring migration must be opened/recovered through the existing explicit project workflow; consenting to an export is not implicit consent to schema migration. The dedicated offline legacy-`user_version` test confirms these three operations cannot alter SQLite bytes, schema version, source audit count or backup directory.

**Authority boundaries:** Only the project-relative existing `exports/` destination is considered during preparation; no arbitrary absolute path, external folder or browser-supplied location is accepted. The existing filename/path and project-identity protections apply. Filename absence is checked again by a future publisher: the preparation check is not a reservation. All operations are backend services, **not added to the graphical interface or `ApplicationCommand` allowlist** in this increment. No file is staged, no `.xlsx` bytes are generated, no export-journal receipt is shared with the existing strategy/count workbook publisher, and the existing audited strategy/count export implementation remains unchanged.

## Automated failure/recovery evidence

Real original SQLite fixtures cover explicit confirmation, original revision fencing, source-count honesty, source-text exclusion from journal receipts and public views, immutable receipt integrity, exact same-ID replay, stale reinspection after adding source records, refusal of conflicting reuse, unavailable run/invalid UUID/unsafe filename/actor/false confirmation, destination collisions and reopen persistence. One disposable test temporarily circumvents only the **test fixture's** append-only trigger to simulate on-disk corruption and restores that trigger *before* asserting that the service fails closed; the production schema and audit protections are never modified.

All user-facing filenames, actions and status messages are static and bounded. Every incomplete source remains incomplete; no automatic duplicate merge, inferred global publication total or provider network call occurs. **This is not a functioning export button** and does not satisfy full EXPORT-01, AT-18, AT-21 or AT-22.

## Next bounded increment

Only after validated merging of this preparation service should a separate increment implement an approved manifest **stage/publish/recover** flow using original immutable evidence, no-overwrite guarded local files and durable source-revision checks. It must fail closed rather than silently regenerate a workbook from revised source evidence. A later graphical button would require explicit researcher confirmation and trusted-host path selection. Production reader/editor metadata rights, final deduplicated master results and complete source retrieval acceptance remain outstanding.

## Exact-HEAD merge gate

Before recommending merge, verify the current PR HEAD SHA, all four required Windows/Linux Python 3.12/3.13 CI test jobs, **completed** exact-HEAD Codex **code review first**, then completed matching-commit **security review** (including any automatic review), individual review receipts and disposition of findings. Every new commit invalidates earlier acceptance. **Never merge without explicit owner authorisation.**
