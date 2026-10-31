# RESEARCH-Y handover — 31 October 2026

## Authority and latest repository state

- Repository: https://github.com/studeployed/RESEARCH-Y; protected `main`. The approved version-controlled `RESEARCH-Y_SPEC.md` version `1.0.0-draft.1` remains authoritative and is unchanged.
- Independent Python-based development; no architecture, code or requirements imported from RESEARCH-X.
- Core PRs through **P1-04g (#24)** are merged. PR #23 added conservative outer-parenthesis translation recognition and passed 4/4 cross-platform post-merge tests.
- [PR #24](https://github.com/studeployed/RESEARCH-Y/pull/24) merged 31 October 2026, commit `d08402931d5e4cc23d662b71c0da65a30931afeb`. It introduced the manual-only, count-reconciled >10,000-ID PubMed validation and deliberate first-page pause/reopen. Its four Windows/Linux Python 3.12/3.13 post-merge test jobs passed.
- Deferred [Windows junction hardening issue #11](https://github.com/studeployed/RESEARCH-Y/issues/11) applies to future untrusted archive import work.

## Offline-tested foundations already merged

- Portable local projects; recoverable SQLite migrations; immutable approved broad OR-only query strategies; PubMed All Fields and Web of Science Starter Topic compilation.
- PubMed ESearch counts and accepted translations, recursive non-overlapping Create Date partitions, bounded ID pagination with unique-PMID reconciliation.
- Immutable, transactionally committed per-page SQLite checkpoint/PMID/audit ledger, explicit pause, reopen and no-repeat resumption, conservative source recount checks.
- PubMed EFetch XML bibliographic metadata and abstracts, source identity, missingness and rights flags, and recoverable metadata-batch storage.
- Credentialled GitHub Actions tests are **manually dispatched only**; normal PR and push CI is offline. NCBI contact/key values are private repository secrets, not committed.

## Real PubMed evidence and unresolved incident

1. [Live run #41073931474](https://github.com/studeployed/RESEARCH-Y/actions/runs/41073931474), 30 October 2026, **passed**: submitted `("ECMO"[All Fields])`; NCBI accepted `"ECMO"[All Fields]`; 19,479 matches; PMID 42958294 retrieved with matching EFetch bibliographic metadata and a three-section abstract. This verifies **one record only**, not the full source.
2. [Live large-identifier run #41207501975](https://github.com/studeployed/RESEARCH-Y/actions/runs/41207501975), 31 October 2026, **failed safely**: 19,483 source-reported matches, three count-only source requests, no committed PMID pages and no identifiers; the second process never executed. Recorded message: `A complete checkpoint plan could not be established`. Status remained `incomplete`, not `completed_verified`.
3. The exact first Create Date query's provider-accepted translation, warnings and count were not retained by that run. Thus the cause **cannot yet** be attributed to translated syntax, provider warnings, date coverage mismatch or transport errors. Do not revise or relax the conservative search logic on inference alone.

## Current authorised proposal — P1-04h

P1-04h introduces a separate **manual, count-only, maximum-two-request diagnostic**, described in `docs/PUBMED_PARTITION_DIAGNOSTIC.md`, to distinguish those possible causes using the actual live provider response. It reuses the same fixed public ECMO query, date interval, PubMed client and private GitHub Actions contact/key secrets. A second request checks the first whole-interval Create Date partition **without requesting any identifiers**. Its public-safe artifact records each provider count, accepted translation, warnings, review reasons, explicit count difference and controlled error category; it never claims full retrieval.

- The proposed workflow: `.github/workflows/pubmed-partition-count-diagnostic.yml`, dispatchable only **after a reviewed, owner-approved merge**.
- Tests: `tests/test_pubmed_partition_count_diagnostic.py` (offline source simulations, source rewriting, warnings, count drift, transport errors, secrets redaction and manual-only constraints).
- Any genuine source-side query rewrite or date mismatch requires further investigation **before** changing the production validator or large retrieval algorithm.
- Four cross-platform CI jobs, a verified Codex code review **and** security review on the exact PR HEAD, no unresolved material findings and **explicit owner merge authorisation** are required.

## Open acceptance gates and sequence

- AT-06: one generic real PubMed All Fields query accepted; diverse biomedical phrase/OR translations still unverified.
- AT-07: full >10,000-PMID disjoint counted union **not achieved** in live service.
- AT-09: real persisted pause/reopen/recovery **not reached** in last live run; fixture evidence partial.
- AT-19: incomplete status correctly retained; complete final-source reconciliation remains unverified.
- Full abstract/metadata reconciliation, Web of Science Starter P1-05 (#8), deduplication, reporting/export, GUI, archives, installer and other release gates remain pending.

**Next action:** review and test P1-04h; do not merge without owner approval. After merge, manually run the two-count diagnostic once, examine actual provider evidence, then determine the smallest scientifically justified correction before repeating the >10,000-ID workflow.
