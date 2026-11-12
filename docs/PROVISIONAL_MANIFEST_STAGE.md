# P1-06l4 — Recoverable, private staging of approved provisional Excel workbooks

**Authority:** repository `RESEARCH-Y_SPEC.md` unchanged. **Baseline:** owner-merged PR #97, `main` `04066038fa9c0036b8684d92e15df40cb778bd5f` (12 November 2026). Bounded Phase 1 increment under issues #9/#37/#39, limited progress toward AUDIT-01, EXPORT-01/03/04, SEC-03/04 and acceptance tests AT-18/19/21/22.

## Prior validated gates

Owner-merged PR #95 added a rights-restricted **internal-only** original-source/provisional-publication Excel renderer. PR #96 passed both native Windows and Linux 100,000-source all-row original SQLite reconciliation for both 128 independently audited provisional identities/99,872 unmaterialised records and 100,000 independently audited provisional identities. It retained only aggregate evidence, not the workbook. PR #97 added **one append-only, researcher-confirmed consent receipt** for a named run, project, safe filename and precise complete-run SHA-256 original revision. PR #97 had no file rendering, staging, publication or GUI authorisation.

## This increment's precise implementation

A new internal backend module, `src/research_y/provisional_manifest_stage.py`, introduces three services:

- `stage_manifest_workbook(project, export_id)` demands a **valid existing PR #97 explicit approval receipt** and exact current original-run count/revision/denominators. It renders the pre-existing, source-only four-sheet workbook without a provider call; validates the embedded run ID, original revision, counts and incompleteness/rights labels; and recomputes the original count projection **before and after rendering**. Immediately before committing any staging intent it rechecks the same original revision under the project's existing guarded write transaction. If evidence changed at any point, it refuses rather than adopting different source records under old consent.
- Before writing bytes, it commits an append-only `provisional_manifest_stage_v1:<export UUID>` **staging** event with the original approval event/hash, original approved revision and the exact output byte **SHA-256, size and unique private retained filename**. It writes only through the existing hardened `Directory.write_new`, which requires exclusive/no-overwrite creation, limited bytes, ordinary path components and a flushed file. The stage remains in a private project-local `exports/.researchy-manifest-stages/` subdirectory; the approved visible `exports/<filename>.xlsx` destination is **never created, linked or presented as published**.
- `resume_manifest_stage(project, export_id)` is a separate, repeat-safe recovery operation. If a valid staging receipt exists and the exact recorded private stage file is intact, it re-verifies byte identity and filesystem durability, and commits a **staged** event linked to the staging receipt. If the process stopped **after committing the staging receipt but before file creation**, it can regenerate the workbook only for the **same still-current approved source revision** and writes the **same exact byte digest and size** to the original filename. It **never overwrites or deletes** an existing partial or altered file; such a stage fails closed and requires a *new explicit export approval*, preserving the failed original as evidence. A fully staged file is never regenerated if later lost/changed.
- `inspect_manifest_stage(project, export_id)` uses the original **strictly read-only, no-migration SQLite URI**. It authenticates the full original intent and separate staging/staged receipt chain, checks each event's canonical payload hash, previous-event ID/hash, run revision and consent pointer, confirms the current original source revision, and independently verifies any existing private file's type, checksum and length. A missing file after a staging receipt is shown as `staging_interrupted`; an altered artifact is an error, not an inferred success. A stale current source revision invalidates stage readiness.

**Every returned response** explicitly sets `workbook_published=false`, `audited_publication_success=false`, `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false` and `verified_complete=false`. A stage is an internal retained source-only artifact, **not** an approved completed unique-publication `Master Results` output, user download or publication receipt.

The existing audited strategy/count workbook publisher, its journal, native output-path guards, application command allowlist, graphical interface and approved publication model remain unchanged. No new dependencies, schema migration, provider network requests or automatic source identity merges are introduced. The existing 128 MiB artifact bound applies; file/SQL commits are not asserted atomic, and the stage receipt makes the crash gap inspectable.

## Reproducible XLSX bytes across recovery time

The initial Codex code review identified that unchanged original scientific
records are not enough to reproduce **the exact workbook byte SHA-256**:
OpenPyXL's default workbook core properties and its ZIP entry timestamps can
depend on the current clock. An interrupted staging receipt cannot be recovered
against its original checksum unless these non-scientific bytes are stable.

Before the staging checksum is committed, the internal stage service now
repackages only the newly generated, never externally provided XLSX archive.
It sets the core XML `created` and `modified` fields to the **original,
immutable researcher authorisation time** and sets every ZIP entry timestamp
to a fixed conventional ZIP epoch (1 January 1980). It enforces unique,
non-directory, non-traversing paths and preserves the workbook's sheet/data
XML contents, row order, original source revision, rights exclusions, and
`INCOMPLETE/UNKNOWN` labels. It uses only the Python standard library
`zipfile` and `ElementTree`; no new dependencies or local extraction occur.
The same original revision and approval reproduce identical package bytes on
later retries under this pinned renderer/compression environment.

A dedicated test changes **both the OpenPyXL core XML timestamps and every
ZIP entry timestamp** to a simulated later day without relying on wall-clock
sleep, proves byte-identical normalized output, then exercises the real
crash-after-receipt-before-file recovery path and opens the stored workbook
to verify it remains valid. If a different runtime/compression environment
still cannot reproduce the exact original SHA-256, recovery refuses safely,
preserves the original receipt and requires explicit new authorisation;
it never silently accepts a different artifact. Workbook file timestamps
must not be presented as original search execution times.

## Tests and acceptance limits

Real versioned SQLite and actual Excel fixture regressions require:

1. One explicit valid approval produces exactly one private retained file and two original append-only stage receipts. It is independently opened and inspected and remains recoverable after project reopen; no visible named export, original source mutation, formula injection or metadata text release.
2. A process interruption after **staging intent but before byte creation** can recover only the exact previously recorded SHA-256 bytes and then append the staged receipt; duplicate invocations never produce another stage generation or claim publication.
3. A partial or modified retained stage is refused and preserved byte for byte; no destructive replacement or silent adoption occurs.
4. Changed original source/query evidence invalidates the old approved revision before staging, including a deliberate concurrent update between rendering and its staging receipt.
5. Old-schema projects are rejected through the strict original read-only gate; a manifest preview/stage must not migrate or create backups. Original append-only receipt/provenance integrity remains protected.
6. All four normal Linux/Windows Python 3.12/3.13 test configurations, exact HEAD Codex code review then security review, and outstanding failure findings must pass before recommending merge.

The original source count revision is **not** a substitute for a verified provider retrieval checkpoint. A future separately reviewed increment must implement the final destination-side, no-overwrite **publishing and recoverable receipt** workflow, plus appropriate evidence if exposing a GUI control; no output is published by this PR. Fully deduplicated master results, source metadata rights, AT-18 and end-to-end AT-22 acceptance remain outstanding.

## Revision and merge safeguards

The full original `RESEARCH-Y_SPEC.md` is unchanged. New code lives only in internal staging and tests/docs. Any substantive changes to deduplication, retention rights, final output scope or automatic workflow must receive owner approval first. For merge advice, retrieve current HEAD, exact-HEAD Python/workbook checks, completed code/security reviews, individual findings and outstanding acceptance criteria. **Never merge without explicit project-owner authorisation.**
