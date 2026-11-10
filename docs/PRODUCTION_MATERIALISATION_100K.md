# P1-06k4d1 — First production-command materialisation steps against 100,000 sources

**Authority:** repository `RESEARCH-Y_SPEC.md` v1.0.0-draft.1, unchanged. **Baseline:** owner-merged pull request (PR) #83, `main` commit `893a369cf921f810907cf0dd64f48e3663564222`, 10 November 2026. This is **partial** evidence toward DATA-01/02/04, DUP-01–05, RUN-06, AUDIT-03, UI-05/07 and AT-01/09/10/19/22; it does not complete any of those mandatory product-level acceptance scenarios.

## Why this matters

PR82 and PR83 used the original project schema to prove **100,000 source records**, **100,000 source-to-provisional-publication links** and bounded read/worker performance, but **99,872** of those links in PR83's all-materialised benchmark were assembled using a *fixture-only* higher-throughput direct SQLite identity writer. The completed user-facing product is instead designed around explicit one-use consent and immutable previews: `preview_run_materialisation` and `materialise_run_batch` (up to 64 source records per transaction). The fixture writer cannot establish that the real preview/confirm process is usable at high cardinality. This increment exercises the actual existing trusted host and supervised child-process services.

The new test creates a real, disposable SQLite v6 project with 100,000 original synthetic PubMed/Web of Science source retrievals and 100,000 original group/query memberships, all in **one selected run**. As before, 64 cross-provider equal-title/DOI *review candidates* are initially materialised as **128 independent provisional publications** through the original single-source identity API. No automatic merge is performed. The **remaining 99,872 source records are initially unmaterialised**.

Two consecutive cycles exercise the original `ApplicationCommand` and `ApplicationWorker` operations:

1. Execute the read-only production `publication_materialisation_preview` command in a genuinely spawned supervised worker. Expect exactly 64 pending source records offered, all counts truthful, no provider requests, and no final publication number inferred.
2. Construct a **separate, explicitly confirmed** `publication_materialisation_confirm` command with that exact preview revision, actor and confirmation. Execute it in a spawned supervised worker, allowing only 64 new independent `review_required` publication links.
3. Close and independently reopen the project. Re-submit the *already consumed* confirmation as a simulated lost-reply retry. Require the canonical `publication_materialisation_stale` rejection and no change to any source, membership, identity or immutable identity-audit rows.
4. Reopen a **new** preview and repeat once with a fresh confirmation. The old review token never approves a second batch. Confirm that original data and existing identity links are not overwritten.

Each worker invocation is required to return **within the original 35-second host budget**; timeouts or failures are reported, never interpreted as committed success. A performance gate that fails is evidence of a genuine bottleneck, not a reason to increase the budget or bypass source/audit validation.

## Bounded evidence expected at the end

| Denominator | Original | After 1 confirmed batch | After 2 confirmed batches |
|---|---:|---:|---:|
| Original source retrievals | 100,000 | 100,000 | 100,000 |
| Original query/group memberships | 100,000 | 100,000 | 100,000 |
| Independent provisional publication identities | 128 | 192 | 256 |
| Original immutable identity-link audit events | 128 | 192 | 256 |
| Selected-run sources still unmaterialised | 99,872 | 99,808 | 99,744 |
| **Verified global unique publications** | **Unknown** | **Unknown** | **Unknown** |

For every stage the independent SQLite ledger validates the original source and membership SHA-256 fingerprints, publication/link/audit event counts, two-run-context consistency, `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. The first 256 synthetic retrievals must retain separate original publication IDs after the two stages. Rejected stale confirmations cannot add events, and the tests must prove this **after reopening** the project.

## Execute without any research/provider credentials

```sh
python -m pip install -e .
python scripts/benchmark_production_materialisation.py --records 100000 --matched 64 --worker-timeout-seconds 35 --json-output production-confirmed-100k.json
```

The [dedicated Windows/Linux workflow](../.github/workflows/production-materialisation-100k.yml) runs Python 3.12 on both platforms, saves JSON evidence and fails the job if a confirmed batch, source/audit integrity or the worker host bound fails. Small 512-record two-batch tests run in the existing four-platform Python test workflow.

## Restrictions, distinctions and next evaluation

- **This is synthetic simulated researcher consent**, not an observed person clicking the actual native graphical user interface (GUI), although the *production* trusted-host command validator and spawned worker are exercised. No browser rendering, actual mouse/keyboard responsiveness or Windows installer test is claimed.
- This does **not** process all 100,000 original sources through the 64-row production pathway: only **128 additional records** in two separate transactions are processed. A full-run production materialisation throughput estimate and all 100,000 production confirmation steps remain unvalidated. The earlier fixture-only bulk writer has not been replaced and is **not invoked** in this test.
- The source queries are intentionally `incomplete`. No provider retrieval verification, original abstract licensing validation or total unique publication count is claimed. `global_unique_publications=null`, `source_retrieval_verified=false`, `deduplication_complete=false`, `verified_complete=false`, and `full_AT_22_acceptance=false` remain explicit.
- Every recovery, count, original source hash and association receipt must be validated from **actual SQLite rows**, not inferred from a successful worker reply alone. The script must not transmit private source data to any network.
- This increment does not add an automatic batch loop or change the public GUI, schema, API credentials, operating modes or scientific search logic. It introduces no new runtime dependency.

The next stage should use the **measured** per-batch cost and any failures to decide whether a safe, resumable, explicit-consent throughput improvement is necessary. Do not build a silent unattended 100,000-row materialisation operation based on synthetic approvals. Full AT-22 also requires genuine native Windows GUI interaction and performance, complete provenance, and all-row output tests.

## Merge controls

The next PR must satisfy all four Python 3.12/3.13 Windows/Linux checks, both high-cardinality production-command benchmark jobs, and any applicable existing performance jobs. The code review and security review must each be **definitively completed for the exact current HEAD SHA**, all substantive findings resolved or dispositioned, and no outstanding required check or review thread overlooked. **No automatic merge; explicit owner authorisation is mandatory.**
