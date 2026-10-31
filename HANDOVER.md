# RESEARCH-Y handover — 31 October 2026

## Authority and merged baseline

- Repository: https://github.com/studeployed/RESEARCH-Y; protected `main`. Authoritative approved specification: `RESEARCH-Y_SPEC.md`, version `1.0.0-draft.1`, unchanged.
- Independent Python project; no RESEARCH-X assumptions, code or dependencies.
- Core increments through **P1-04h (PR #25)** are merged. Current base for P1-04i is `cccb6b4d37ce0c5df02c9a545fd6c38b58188098`.
- P1-04g (PR #24) added the controlled manual >10,000-identifier and checkpoint-recovery workflow. P1-04h (PR #25) added the two-request count-only diagnostic to capture the first partition failure precisely. No routine continuous integration uses live credentials.
- Deferred [Windows junction hardening #11](https://github.com/studeployed/RESEARCH-Y/issues/11) remains relevant before untrusted archives/import.

## Existing implementation

Portable project folders, recoverable SQLite migrations, immutable approved broad-OR strategy snapshots, PubMed All Fields and Web of Science Starter Topic query compilation; PubMed count/translation checks, bounded identifier pagination, recursive disjoint Create Date partitions and counted unique-identifier union; transactional page/index/audit checkpoints and pause/reopen recovery; EFetch bibliographic metadata/abstract parser, source provenance, missingness/rights flags and recoverable metadata persistence. Offline fixtures do not establish complete live literature retrieval.

## Live source evidence

1. [Run #41073931474](https://github.com/studeployed/RESEARCH-Y/actions/runs/41073931474), 30 October 2026: successful one-record ESearch/EFetch smoke. Source count 19,479; PubMed identifier 42958294; matching metadata and structured abstract. This is **one-record evidence only**.
2. [Run #41207501975](https://github.com/studeployed/RESEARCH-Y/actions/runs/41207501975), 31 October: 19,483 matches but failure during initial partition planning; zero committed pages or identifiers and no live recovery evidence.
3. [Count-only diagnostic #41216318046](https://github.com/studeployed/RESEARCH-Y/actions/runs/41216318046), 31 October at 15:45 UTC: unrestricted and date-partition counts both **19,483**, no provider warnings or transport error. The client rejected the actual source translation:

```text
Submitted: (("ECMO"[All Fields])) AND (1900/01/01:2026/11/01[crdt])
Accepted:  "ECMO"[All Fields] AND 1900/01/01:2026/11/01[Date - Create]
```

This establishes the immediate validator incompatibility: redundant clause wrappers and the documented Create Date field alias. It does **not** prove complete identifier retrieval or guarantee every future provider translation.

## Current authorised corrective increment — P1-04i

See `docs/PUBMED_DATE_TRANSLATION.md`. The proposed correction uses a restricted, quote-aware, iterative grammar to recognise the exact observed administrative date translation **only with explicit internal partition context**. It requires an unchanged ordered All Fields OR clause, one administrative AND and identical valid date boundaries; it rejects changed fields, terms, bounds, warnings, extra operators and ambiguous grouping. It preserves the original submitted/accepted text and stored checksums.

The same context-aware comparator is used in count parsing, existing identifier-page review, checkpoint-restart recounts, page commit and stored-page validation. Checkpoint context is derived from its immutable plan. No source request construction, schema, dependency, workflow, field coverage, search scope or completion rule changes.

Tests: `tests/test_pubmed_date_translation.py` (55 focused parser cases executed locally before submission), and `tests/test_pubmed_date_translation_integration.py` (offline production parser/checkpoint paths; 10,005 synthetic identifiers; pause, reopen, no refetch, legacy-page preservation and failed/rejected recovery). Full cross-platform results and Codex reviews must be checked against the exact current pull-request HEAD before merge advice.

The owner has authorised implementing proposed in-scope fixes and opening a pull request directly for approval, rather than requesting another permission merely to create it. **That is not merge authorisation.** Any substantive specification change still requires separate approval.

## Acceptance gates and next action

- AT-06: one real All Fields query accepted; diverse phrases and group unions remain partial.
- AT-07: complete live >10,000 identifier union still unverified.
- AT-09: live checkpoint/reopen/recovery still unverified.
- AT-19: no false-complete outcome is permitted; final source reconciliation remains outstanding.

After exact-HEAD tests and reviews, leave P1-04i unmerged for owner approval. After an approved merge, run the **existing** large identifier-validation workflow on the new `main` commit with existing secrets and safeguards, then inspect actual partitions, pages, source counts and recovery evidence. Do not equate the observed historical 19,483 count with an immutable current total. No extra diagnostic-only workflow is needed for this correction. Web of Science Starter P1-05 remains next after the PubMed evidence gate.
