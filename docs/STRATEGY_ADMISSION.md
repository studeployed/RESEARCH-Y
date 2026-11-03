# P1-06f1 — Atomic researcher-approved strategy admission and pending query plans

Date: 3 November 2026. Owner-merged PR #55 is the baseline:
`63978e3832f20b91dcfd2e9b7d993212909073bc`.
Parent [#41](https://github.com/studeployed/RESEARCH-Y/issues/41),
[#9](https://github.com/studeployed/RESEARCH-Y/issues/9),
[#6](https://github.com/studeployed/RESEARCH-Y/issues/6).
The repository `RESEARCH-Y_SPEC.md` remains authoritative and unchanged.
Relevant requirements include SEARCH-01/02/05–14, ARCH-01/03, PROJ-04/06,
AUDIT-01/03, RUN-01/05, SEC-04/05, and partial AT-04/05/17/19/21.

## Why this is a separate bounded increment

The initial graphical proof can open/create projects, inspect frozen runs, and
audited-export workbooks, but its run fixture is constructed by a developer
instead of an actual researcher. Existing lower-level storage operations each
commit separately: approval, run creation, and per-group source plans can be
interrupted between independent transactions. Before exposing an **Approve**
button and a real Research Setup GUI, this service provides a single safe,
replayable, atomic admission boundary.

## Trusted service contract

The `research_y.strategy_admission.commit_approved_strategy` function takes:
a real validated project, a fresh stable **caller-owned canonical UUID**,
an explicitly reviewed research theme, ordered groups of atomic approved
terms (including origin, reason and enabled flag), researcher attribution,
and an approval boolean which MUST be `True` as the result of a genuine
researcher action. The service **does not** provide or infer this approval
itself. An unapproved or invalid term is rejected before any research mutation.

It uses the existing immutable snapshot format and existing PubMed `[All Fields]`
and Web of Science Starter `TS` **OR-only** compiler. There are no Medical
Subject Headings, hidden AND/NOT, default language/species/study exclusions,
new operands, inferred provider byte limits, or fabricated counts. For every
group with at least one enabled approved term, it plans **both** initial
primary sources. A disabled/empty group is preserved for transparency but
does not get a fictitious executable query. This is not selection of optional
supplementary/society sources.

All approval, group, run, unexecuted query and audit writes take place in
one SQLite `BEGIN IMMEDIATE` transaction under the existing project
identity/path guard. A failed audit insert, invalid compiler literal, corrupt
evidence or concurrent interference rolls the entire transaction back.
Created strategy versions remain immutable, with deterministic version
ordering and an explicit `pending` run. Provider hit counts remain
**unknown**, never `0`, and no search execution/EFetch/quota use occurs.

An admission request UUID is stable across worker retry/restart and maps to
deterministic, domain-separated strategy/run/query UUIDs. A lost response
followed by an identical retry returns the original, verified identifiers
without adding another version, run, query or audit event. Reusing a request
ID with different approved content fails `admission_conflict` without edits.
An inconsistent partial/altered pre-existing request fails closed as
`admission_evidence_invalid` rather than being silently reconstructed.
The request UUID is an idempotency key, **not** a substitute for researcher
approval or a browser authentication token.

## Next graphical increment

Expose a genuine Research Setup/Terminology Review screen that accepts theme,
objectives and a practical number of named groups/atomic terms, distinguishes
provenance, and shows both source-specific exact query previews **before**
an explicit confirmation. The GUI must generate and retain one request UUID
across uncertain worker replies, then call this service through an allowlisted
supervised worker command. After a successful response it may inspect and
explicitly select the new pending run. User editing of a draft must invalidate
prior approval/preview. Do **not** automatically execute searches or interpret
an accepted strategy as a completed retrieval. Reuse actual stored counts and
warnings, not a simulated progress bar or extra database.

This increment deliberately does **not** implement that GUI, pilot source
calls, term-expansion models, provider validation or full search retrieval.
Production NiceGUI/pywebview adoption, Windows packaging and the 100,000-record
acceptance remain separate owner decisions and gates.

## Verification

Cross-platform offline pytest fixtures exercise exact PubMed/WoS expressions,
multi-group OR semantics, provenance and disabled groups; verified NULL hit
counts; two-version history; invalid/unapproved input; duplicate request
conflicts; lost-response idempotency; audit failure rollback; corrupted
pre-existing evidence and simultaneous writers (same and distinct request IDs).
No external data or credentials are exercised. A green test does not certify
provider syntax acceptance under every live research expression. The owner
must approve any merge after exact HEAD four-configuration Python tests,
completed Codex code review then completed security review with individual
receipts and all substantive findings resolved.
