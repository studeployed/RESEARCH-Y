# P1-06f3 — Verifiable frozen pre-run plan and auditable PRESS review (isolated GUI)

Date: 3 November 2026. Verified owner-merged PR #57 baseline:
`7cafa1541504cbffcc82397c64b60405594bd4bc`.
Parents: #41, #43, #9 and #6. The repository version-controlled
`RESEARCH-Y_SPEC.md` remains authoritative and unchanged. Scoped requirements:
METH-01/02/03/04/05, SEARCH-06–14, UI-04, ARCH-01/02/03, AUDIT-01/03/04,
SEC-04/05 and partial AT-04/05/17/19/21.

## Purpose and prerequisites

After a researcher approves a strategy through the preceding GUI, the
researcher can explicitly select its existing **pending** run and ask the host
to **Verify saved exact source plan**. It uses the existing read-only project
connection/path guard, parses the frozen strategy snapshot, compares every
indexed group with its snapshot, recompiles both sources deterministically,
and validates that each active group has **exactly one stored pending query
for PubMed and Web of Science**, with exact matching syntax. Any additional,
missing, modified, duplicate, already-executed or explicitly parameterised
query fails closed. No provider call is made.

The verified evidence reports the immutable strategy/run/version, stable
SHA-256 fingerprint of the strategy and exact query inventory, group and
active-term counts, source-by-source field coverage, each exact stored query,
and the documented limits. The **only** accepted unparameterised plan in this
slice has no specified source restrictions; it does not silently add language,
species, date, publication type, Medical Subject Headings or Boolean AND/NOT.
For Web of Science Starter, `TS` Topic remains narrower than the web
interface's All Fields and is **not full article text**. For PubMed, the
accepted translation/phrase-index behaviour is explicitly **not checked**.

The interface **does not fabricate** a provider hit count or estimate:
`provider_counts: null`, `estimated_workload: null` and
`workload_status: unknown_until_pilot_counts`. A general caution about
potentially wide searches is not a numerical estimate or a reason to
automatically narrow an approved strategy. Terms/reasons remain frozen;
pre-run review never edits them or starts an actual database retrieval.

## PRESS checklist and evidence provenance

The host shows seven named checklist dimensions: research objective,
terminology coverage, Boolean logic, provider syntax, spelling, search
fields, and limits. Each is independently `reviewed`, `not_reviewed`, or
`needs_revision`, as explicitly reported by the named researcher or
independent peer. Known-relevant identifiers can be **listed**, but are
clearly labelled *not tested against the provider*. A review note can retain
warnings and methodological limitations.

To prevent unsaved changes or inadvertent attestation, the UI first
**locks a fully visible candidate** after the researcher clicks Review and
lock checklist answers. Only a separate **Confirm and record** action
appends an audit receipt. A Revise button discards the candidate without a
write. The role `independent_peer_reported` is a *user assertion* and is
never independently verified by software. Even a fully checked list is
not a successful search, verified PRESS peer review or evidence that the
scientific strategy is fit for purpose. Outstanding items are preserved
verbatim and are never silently re-labelled as passed.

A receipt uses the existing append-only `audit_events` table with event
`pre_run_review_v1`, no schema migration, under project identity/path
checks and a `BEGIN IMMEDIATE` transaction. It binds the actual reviewer
name/role, timestamp, item statuses, note, known-relevant inputs,
`run_id`, exact plan hash and a host-owned idempotency UUID. The worker
*revalidates the current plan hash inside the write transaction* before
recording. A stale plan fails without changes. A lost response is
reconciled by replaying the **same immutable candidate and UUID** and by
independently reading back the original audit receipt. A changed replay
is a conflict, not a second review. The host blocks run/project switching
until any uncertain review attempt is reconciled.

Both automated and recorded reviews have
`execution_authorized: false`,
`peer_review_verified: false` and
`source_retrieval_verified: false`; the run remains **pending**.
These are methodology-preparation records, not execution authorisations.
The code never interprets a selected checklist item as proof of actual
peer-review completion, automatic correctness or completed PRISMA-S reporting.

## Security, verification and limits

Worker commands `preflight_read` and `preflight_record` are strictly
allowlisted and revalidated across the child process boundary; browser
controls do not send paths, database IDs or queries directly to provider
services. Python fixtures cover legitimate OR plans, missing/forged source
rows, unreviewed query parameters, changed run state, null counts, invalid
reviewer/checklist inputs, audit rollback, cross-process replays, concurrent
writers, reopened projects, loss of worker response and intact earlier
run/export state. The original graphical lifecycle tests are preserved.
No real network provider is invoked in tests or interactive review.

**Open work:** real pilot/count-only source queries, accepted PubMed query
translation checks, source-specific workload estimates, known-relevant
record matching, selected limitations, prospective independent PRESS review
confirmation, a complete PRISMA-S methods checklist, true execution
monitoring and full GUI/Windows installation. The current GUI remains the
already-approved **isolated** NiceGUI 3.18.0 / pywebview 6.2.1
feasibility prototype; this change is not a production adoption or
distributable app. A full manual physical Windows review journey remains
unverified unless independently evidenced.

Before merging: exact HEAD; all four Linux/Windows Python 3.12/3.13
regressions, four graphical dependencies and four graphical lifecycle
configurations with actual scenario receipts; completed Codex code review
then completed security review on the same HEAD, matching individual
completion receipts; substantive findings resolved and explicit
project-owner merge authorisation. No merge is automatic.
