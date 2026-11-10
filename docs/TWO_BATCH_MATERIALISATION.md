# P1-06k4d2 — Explicit, finite two-batch provisional materialisation

**Authority:** RESEARCH-Y repository `RESEARCH-Y_SPEC.md` (unchanged). **Baseline:** owner-merged PR #84, `main` commit `14023f856bed07b4390fa0eac11d9d8ddc0180f9`, 10 November 2026.

## Rationale and scope

PR #84 verified two separate, genuine 64-record production confirmations in a 100,000-original-source project. A single preview or confirm took approximately **5.7–6.2 seconds** on the observed Windows/Linux runs. A full 100,000-original-source project would otherwise require roughly **1,563 separate researcher confirmations** in the worst case (100,000 / 64, rounded up), making the existing single-batch flow impractical for high-cardinality searches. The final initial product must offer straightforward supervised processing while retaining reproducibility and auditable source integrity.

This increment adds an **internal trusted-host operation** to let a researcher explicitly approve *one finite window containing at most two 64-record batches*, never an unspecified whole run. The operation is strictly opt-in. It does not add a browser control, background daemon, source request, database migration, model interaction or new scientific deduction. Only new, independent provisional publication identities are created; two identical titles, digital object identifiers (DOIs) or supplement references remain two records until independently reviewed.

## Operations

- `publication_window_preview` calls the original count-based, source-validated preview, then freezes up to **128 precisely ordered pending source IDs** and their approved project source/query/group/run scope into a SHA-256 revision. It displays counts and proposed batch sizes, **never licensed source metadata or the original identifiers themselves**.
- `publication_window_confirm` requires a matching one-use token, nonempty researcher actor and literal `True` confirmation. The only writer is the existing `materialise_run_batch`; every call retains its original `BEGIN IMMEDIATE` transaction, strict **64-record maximum**, independent source validation and immutable link audit receipt.
- For every approved 64-record transaction, the original writer acquires SQLite's `BEGIN IMMEDIATE` lock and **rechecks the full original source/strategy/query/run/membership SHA-256 and exact consented source IDs under that same write lock**, before it inserts any publication or audit receipt. This closes a time-of-check/time-of-use race: a concurrent writer cannot alter unrelated project evidence after a preliminary read and before the materialisation commit. Between the first and second batches, the operation also independently checks the next planned IDs and the pending count. A changed original project scope, a competing association, a different next page or a stale batch revision **stops the session**, leaving only previously committed batches.
- A failed second batch rolls back only that batch. The first remains durable and is recovered from the original SQLite file. The old *window* approval no longer matches the changed identity count and **cannot be replayed**. The researcher must reopen the project and explicitly approve a fresh window, not assume that a missing or lost worker response means no commit.
- The operation returns a strictly bounded, source-free receipt with number of committed batches, newly provisional source records, remaining original sources and **truthful non-complete flags**. The spawned worker protocol remains bounded and its actual host responsiveness is validated separately.

The scope fingerprint includes `strategy_versions`, `strategy_groups`, `search_runs`, `source_queries`, `source_retrievals` and `query_retrievals`. It excludes deliberately changing publications, original identity-link audit receipts and mutable derived indexes. Each original writer still validates the current full-run revision immediately before its own commit. Neither the fingerprint nor a successful commit certifies underlying provider completeness or search accuracy. The component has no credential or network access.

## Required evidence and tests

The small disk-backed regressions in `tests/test_publication_materialisation_window.py` check an original 132-source project, two 64-row independent transactions, source and membership preservation, no automatic same-DOI merge, a four-record remainder and stale consent rejection. Fault-injection creates a SQLite trigger which aborts **the second batch only**; the first batch survives unchanged across reopen, and an attempted approval replay fails. Changes to the original query/source or a competing identity before approval are refused; an original scope mutation introduced *between* the two commits also stops before the second. Forged host commands and nonboolean confirmation are rejected.

The [dedicated 100,000-original-source workflow](../.github/workflows/two-batch-materialisation-100k.yml) runs the genuine spawned `ApplicationWorker` **window preview and two-batch confirm** on Windows and Linux Python 3.12, with a hard **35-second per-command bound** and saved JSON. It verifies 100,000 original sources/memberships, 128 initially audited identity links, **128 further links over two approved transactions** (256 total) and **99,744 unmaterialised** originals, independent reopen, source/membership digests, SQLite integrity/foreign-key results and consumption of the original token.

```sh
python -m pip install -e .
python -m scripts.benchmark_materialisation_window --records 100000 --matched 64 --worker-timeout-seconds 35 --json-output two-batch-evidence.json
```

A slow or failed worker is a **failed** performance gate, never permission to increase timeout or bypass original audit checks. Actual observed times must be cited by workflow run and HEAD commit before any success claim.

## Methodological and product boundaries

This is **not** an unattended 100,000-record materialisation pathway, continuous background job, or automatically approved next window. A session can commit **at most 128 provisional identities**, not final distinct publications. A researcher must explicitly confirm every new window. A fully operational GUI to obtain that consent and display recovery is a **separate unfinished step**. Repeatedly invoking this internal host command on an entire project without actual owner review is not authorised.

The test does not validate native Windows browser painting, large-table interaction, whole-project confirmed duplicate review, export of 100,000 fully classified records, live PubMed or Web of Science completeness, total parent-plus-worker peak memory, or the final AT-22 acceptance gate. It preserves `global_unique_publications=null`, `deduplication_complete=false`, `source_retrieval_verified=false`, `verified_complete=false` and `full_AT_22_acceptance=false` in all test reports. The user has not signed off any change to broad OR-search logic or the authoritative specification.

## Review and merge gate

Verify exact PR HEAD, all four Python 3.12/3.13 Windows/Linux tests, both 100,000-original-source window benchmarks and any impacted prior workflows; require definitive matching-commit Codex **code review first**, then **security review**, with individual receipts, findings and threads verified. Do not call it complete based on an automated reaction, successful-looking comment or older-commit review. No merge without explicit project-owner authorisation.

The following increment should integrate a researcher-visible preview/approval/recovery flow and validate native graphical responsiveness before calling the user-facing feature complete.
