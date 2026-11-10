# P1-06k4c1 — 100,000 retained sources with 100,000 audited provisional identities

**Baseline:** owner-merged pull request (PR) #81, `main` `df6ab9a1268dd66f30e8fcf87b07a9b4aac34405`, 10 November 2026. The authoritative repository `RESEARCH-Y_SPEC.md` remains unchanged. This is a bounded performance and integrity stage toward **AT-22**, not final acceptance.

## Why this scenario?

PR79 measured 100,000-row indexed SQLite query kernels, PR80 measured a real 100,000-original-source project with only **128** audited provisional publication identities, and PR81 optimised its original-source scanning path without skipping validation. The next missing workload is the performance of the **canonical source-to-publication audit links** at high cardinality.

A real project can contain 100,000 original source retrievals that are all materialised into independent, unreviewed publication hypotheses. This is **not equivalent** to discovering 100,000 unique publications. Original metadata may later be shown to describe duplicates; no automatic matching or final publication count is authorised by materialisation alone.

## Reproducible benchmark fixture

The existing `scripts/benchmark_original_project.py` now supports `--materialise-all`. It creates the same actual project schema and synthetic PubMed/Web of Science source records, memberships, selected and historical runs as PR80. Defaults:

| Evidence category | Count |
|---|---:|
| Retained original source retrievals | 100,000 |
| Original query/group memberships | 100,000 |
| Selected-run original sources | 512 |
| Historical-run original sources | 99,488 |
| **Independent provisional publication identities** | **100,000** |
| Original source-to-publication audit/link receipts | **100,000** |
| Unmaterialised original sources | **0** |
| Known exact-key source-pair review hints touching the selected run | 64 |

The benchmark initially uses the **original public** `publication_identity.materialise_retrieval` service for its bounded 128-record baseline, then creates the remaining independent identities in SQLite transactions of at most **256 source rows**. This additional step is a **fixture-only preparation helper**, not a new user-facing operation and not a shortcut for production. It uses the same original `publication_identity._source_from_row` JSON and source SHA-256 decoder and the same production `publication_identity._record_link` writer, which appends a real immutable `explicit-publication-identity` audit event and writes the source-link pointer. Every created publication has its own canonical identifier; equal titles/DOIs are **not merged**.

The first extra transaction is deliberately committed, followed by a separate project reopen and keyset-cursor continuation through all remaining source rows. The small offline suite also injects a database failure partway through a transaction, confirms the entire uncommitted batch rolls back, reopens the project and resumes idempotently without duplicate links or receipts. This validates the fixture's checkpoint construction and the original schema's transaction/audit integrity; **it does not validate the researcher-confirmed GUI materialisation workflow for 100,000 records**.

Once fully materialised, the exact same production `read_run_counts`, `read_publication_page` and original-source `read_candidate_queue` methods run against the project. The selected run must have 512 provisional identities, no unmaterialised retrievals, 64 exact-key *candidate pairs*, and no final unique-publication count. The original candidate queue remains source backed and may be slow; every linked record must still pass original provenance and source-hash validation. A genuine spawned `ApplicationWorker` command is observed against the same 35-second host timeout. Worker timeouts, if any, are reported as **failures to establish the worker response gate** rather than silently relabelled as successful.

An independent reopen after reads/worker confirms exact source, membership, publication, link and append-only identity-audit event counts, SHA-256 fingerprints of first/last original metadata, SQLite `integrity_check` and `foreign_key_check`. The benchmark saves its own observed original DB size, wall times, parent-process peak resident set size (RSS), worker polling interval and request outcome. It makes no claim about total worker-plus-parent memory or actual browser painting.

## Running and evidence

```sh
python -m pip install -e .
python scripts/benchmark_original_project.py --records 100000 --selected 512 --matched 64 --materialise-all --worker-timeout-seconds 35 --json-output materialised-original-100k.json
```

The [materialised original 100k workflow](../.github/workflows/materialised-original-100k.yml) runs independently on Linux and Windows with Python 3.12; both produce auditable JSON artifacts. It must verify all original source/link/identity counts, full source-to-publication receipt counts, committed/reopened generation progress, same-run/historical source scope, and unchanged original data. The existing four-platform ordinary tests include a smaller **512-original-source fully materialised** scenario and a simulated transaction failure/reopen/idempotency test.

**Full 100,000-record native GUI acceptance remains outstanding**: the benchmark does not visit 100,000 unique publication rows in a rendered window, measure actual Windows graphical responsiveness, exercise the researcher-confirmed 64-row GUI materialisation batches at full scale, export 100,000 fully classified records, or validate provider retrieval completeness. The **entire** source catalogue is materialised in the benchmark, but the selected run still contains only 512 records; a single 100,000-record run requires a separate acceptance scenario.

## Methodological integrity

All data are synthetic and never access a source provider or clinical/real user records. The search queries/runs deliberately remain **incomplete**. The benchmark never promotes candidate hints into confirmed duplicates, ignores language/species restrictions, or fabricates abstracts, field choices, provenance or verified hit totals. The two abstracts sharing a container-like DOI remain two provisional publications unless a researcher makes an explicit audited decision.

The published evidence retains `all_100k_source_records_materialised=true` **only when exactly 100,000 originals each have one audited provisional identity**. It separately retains `researcher_confirmed_materialisation_workflow_tested=false`, `native_browser_rendering_measured=false`, `source_retrieval_verified=false`, `deduplication_complete=false`, `verified_complete=false`, `global_unique_publications=null`, and `full_AT_22_acceptance=false`. These distinctions are non-negotiable.

## Merge and next-step gates

Exact current HEAD, all four Python Windows/Linux 3.12/3.13 checks, both 100,000-identity platform artifacts, existing original-source/SQLite kernel regressions, definitively completed Codex **code review first** then exact-HEAD **security review**, all individual review findings and owner merge approval. No production or full AT-22 acceptance claim based on the fixture.

The next scope after observing this benchmark is to address actual bottlenecks **with validated provenance and finite resource budgets**, and separately test a 100,000-record selected-run workflow and native Windows GUI rendering before claiming full AT-22.
