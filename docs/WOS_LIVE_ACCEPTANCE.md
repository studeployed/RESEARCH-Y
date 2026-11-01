# P1-05c — Observed Starter enumeration and recovery acceptance

**Evidence date:** 1 November 2026. **Scope:** one fixed-query live enumeration and controlled two-process restart, not complete connector/product acceptance. The approved specification is unchanged.

## Provenance and expected outcome

[Workflow run 41306953908](https://github.com/studeployed/RESEARCH-Y/actions/runs/41306953908) completed successfully at 12:46:29 Coordinated Universal Time (UTC), on merged commit `a4bb2b308aa96fe4076cde31efef668c23199173` from pull request #28. The manual workflow used its explicit local-retention confirmation and the existing private Clarivate credential. Post-merge test run 41306431736 passed all four Windows/Linux Python 3.12/3.13 configurations.

The test was expected to commit one 50-record acquisition page, stop, reopen the project in a separate Python process, acquire only missing pages, compare all ordered accession pages in one verification session, and recheck the final source count. The fixed query was `TS=("ECMO")`, collection `WOS`; no new scientific restriction was introduced. Counts below are historical observations, not constants that future provider responses must match.

## Observed result

| Measure | Expected invariant | Observed |
|---|---|---|
| Reported / committed count | Equal, without silently accepting truncation | 19,584 / 19,584 |
| Acquisition pages | Complete contiguous coverage at 50 records/page | 392 / 392 |
| Identity-verification pages | Every acquired page verified separately | 392 |
| Request purposes | Acquisition + verification + resume/final probes | 392 + 392 + 1 + 1 = 786 |
| First process | One committed page, explicit pause | 50 records; `session_budget_reached` |
| Separate-process resume | First acquisition page unchanged and not reacquired | Both recorded true; one first-page acquisition request |
| Failure / unknown-outcome counts | Explicit, never inferred from success colour | 0 / 0 |
| Observed daily allowance | Provider-reported rather than assumed | 5,000; 4,214 remaining |
| Final scoped outcome | Reconciled enumeration, not frozen snapshot | `completed_with_warnings` |

The retained record reports `enumeration_reconciled=true`, `durable_recovery_tested=true` and `stage_passed=true`. It explicitly retains `source_retrieval_verified=false`, `provider_snapshot_guaranteed=false`, `abstract_enrichment_complete=false` and `multi_day_live_tested=false`. The parent multi-source run is not promoted to verified complete.

## Retained evidence and independent-check boundary

`docs/evidence/wos-recovery-41306953908-summary.json` is the **unchanged aggregate audit report**, not the original workflow artifact. It preserves all top-level recorded results, the 16 aggregate check outcomes, run/commit identities, checksums and limitations. No accessions, licensed titles, abstracts or database are committed.

- Original GitHub artifact: `wos-recovery-evidence-41306953908`, identifier `13083623977`; the service reports expiry on 15 November 2026.
- Artifact ZIP SHA-256: `f41d86bc97a3a682b72dd1e83eaaccc74883a9a8ec43adec17d181da5c38549a`.
- Original `wos-checkpoint-evidence.json` SHA-256: `cf113adbd7e60074400f69f4c6b871996d3c67c95761f1601792fb9e43be6aed`.
- Retained aggregate audit SHA-256: `90ba97684c5bebe447697f3bc01d09aafee40adc1f560fcc7f32d4546c4b900f`.

SHA-256 means Secure Hash Algorithm, 256-bit. These hashes identify the reviewed files; they do not recreate missing records or establish source authenticity independently.

The original aggregate artifact and downloaded audit were rechecked when preparing this update: ZIP contents matched the evidence file byte-for-byte, and the recorded count/page/request arithmetic and explicit limitations matched. The original evidence listed 392 contiguous acquisition-page hashes. The audit found 16/16 aggregate checks consistent. Raw accessions, licensed payloads and the database were absent, so the audit **cannot independently recompute** individual-record metadata, page membership or the accession-union digest. It relies on the executed checkpoint validator for those assertions. The complete original artifact remains separately downloadable while retained by GitHub; this committed summary does not preserve its per-page hash list.

`tests/test_wos_live_evidence.py` checks the retained report's identity, fixed historical accounting and explicit limitations offline. These are evidence-regression checks, not a rerun of the live service or an independent record-level audit.

## Requirement disposition

| Requirement / scenario | Evidence now available | Still open |
|---|---|---|
| SRC-05, SRC-06; AT-08 | Institutional allowance, full 50-record pagination and observed count reconciliation for this query | Real quota-exhaustion/reset and multi-day recovery; broader provider-limit behaviour |
| RUN-04, RUN-06; AT-09 | Controlled pause, separate-process reopen, unchanged committed first acquisition page | Live multi-day interruption/failure scenarios; product-wide recovery |
| SRC-08, RUN-05; AT-19 | Explicit warning status and no snapshot/full-source claim | Other partial/failing source paths and end-to-end presentation |
| DATA-03–06; SRC-07 | Supplied source metadata retained by the tested implementation | Independent field-level completeness, full abstracts and permitted enrichment |
| AT-21 | Offline safeguards and aggregate-only evidence | Full security/release acceptance, including deferred issue #11 |

The traceability matrix deliberately keeps these broad requirements **partial**. Parent issue #8 stays open. Offline quota/failure fixtures remain useful but are not relabelled live evidence.

## Next ready work

P1-06 under issue #9 follows: publication identity, reversible conservative deduplication, reconciled master counts, initial Excel output and a minimal application flow. Initiate a narrow P1-06a publication-identity/provenance increment first, with explicit anti-false-merge fixtures; do not combine all of P1-06 into one unreviewable change. Preparing that increment does not depend on pretending that the remaining source-acceptance gaps are closed. No new source call or repeat smoke test is needed to record the completed scenario.
