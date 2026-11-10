# P1-06k4b1 — Original-project 100,000-source workload and worker-read evidence

**Baseline:** owner-merged pull request (PR) #79, `main` `d659e47083fa8efd487011f63140b1ed083ce77b`. The version-controlled `RESEARCH-Y_SPEC.md` remains authoritative and unchanged.

This is a bounded progression toward **AT-22** (representative 100,000-record processing and exploration), NOT the final performance, graphical-interface, source-completeness or deduplication acceptance test. The earlier [P1-06k4a query-kernel results](CANDIDATE_QUEUE_PERFORMANCE.md) remain the baseline for indexed SQL alone.

## Original evidence used in the scenario

`scripts/benchmark_original_project.py` opens a new, disposable **actual RESEARCH-Y schema-v6 project** through `create_project`, rather than a lookalike database. The generator performs bounded, atomic SQLite insertion of original, synthetic PubMed and Web of Science metadata and `query_retrievals` memberships, with the source-provider identity format and licence metadata expected by the original validation code. It deliberately leaves query/run status **incomplete**, reported hits **unknown**, and provider checkpoint/snapshot acceptance **unverified**.

The default original-project workload contains:

| Meaning | Count |
|---|---:|
| Retained original provider source retrievals | 100,000 |
| Original query-to-retrieval memberships | 100,000 |
| Sources in the selected run | 512 |
| Sources in an earlier run | 99,488 |
| Provisional publication identities, created using the **production audited materialisation service** | 128 |
| Original source records not yet materialised into publication identities | 99,872 |
| Selected-run pairs with matching synthetic original title and Digital Object Identifier (DOI), across providers and runs | 64 |

This intentionally models a **large project with partial identity preparation**. It is not a scenario with 100,000 fully materialised or deduplicated publications and must not be labelled as such. Each of the 64 synthetic pairs remains two separate, independent publication hypotheses: no automatic association or classification occurs.

The script calls the **real** `read_run_counts`, `read_publication_page` and `read_candidate_queue` functions. Without a prepared source-key cache, the candidate queue takes the original full-project source projection path; this exposes its current large-data fallback behaviour and 100,000-record workload limit rather than benchmarking only the PR79 in-memory fixture. A first and second revision-fenced candidate page must have correct original source totals, exact pair count, no overlapping canonical pairs and unknown final unique-publication count.

Next the script submits **the same original candidate-queue command** through the genuine `ApplicationWorker` spawned-process boundary used by the graphical application. While it executes, the host thread repeatedly polls; the report records worker state, elapsed time, number of polls and longest observed poll interval. The existing graphical host uses a **35-second** worker timeout, which is therefore the default bound. If the benchmark worker cannot return within that bound, it is stopped and reported as `timeout`, **not falsely claimed successful**.

Afterward, the project is independently reopened using `open_project`. The script requires the original source and query membership counts, publication/association counts, append-only audit row count and **first/last source metadata SHA-256 fingerprints** to be identical; it checks `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. A failure is a test failure, not an incomplete result disguised as success.

## Reproducible run

```sh
python -m pip install -e .
python scripts/benchmark_original_project.py --records 100000 --selected 512 --matched 64 --worker-timeout-seconds 35 --json-output original-project-100k.json
```

The [original-project 100k workflow](../.github/workflows/original-project-100k.yml) runs the script on GitHub-hosted **Linux and Windows Python 3.12** runners and uploads a JSON evidence artifact for each platform. The existing four-platform Python test matrix runs a smaller **512-original-source** project using the same original services and validates the reported scope/unknown publication count.

The report records separate source insertion and audited identity materialisation time, count projection, original publication page, first/second source-backed candidate pages, spawned worker read, observed parent-process peak resident set size (RSS), project file size and total elapsed time. The worker is a **real subprocess**, but the main-thread polling metric is **not a browser-rendering or native-window frame-rate test**. Resident memory is observed for the parent process only; combined worker/parent memory, Windows GUI paint latency and external-data responsiveness are not yet established.

## Methodological and acceptance boundaries

This workload avoids externally queried information entirely: all titles, accession numbers and DOIs are synthetic. It does **not** fetch PubMed or WoS, verify ESearch partitions or WoS quotas, interpret society guidance, extract individual conference abstracts, automate deduplication, run a local large language model, assess study design or export a final workbook. No source user credential, real clinical document or licensed abstract is included.

The full, representative **100,000-publication end-to-end test** remains outstanding because only 128 of the 100,000 retained sources receive audited provisional identities. The test also does not exercise the ready-v6 pair checkpoint on all 100,000 records or render the native Windows graphical user interface under load. No absolute latency or memory threshold has been approved; measured results must not be extrapolated into `AT-22=passed`.

Every output explicitly sets `full_AT_22_acceptance=false`, `all_100k_source_records_materialised=false`, `original_sources_complete=false`, `source_retrieval_verified=false`, `deduplication_complete=false`, `verified_complete=false` and `global_unique_publications=null`. A clean SQLite integrity check **does not** establish search completeness or publication identity correctness.

## Acceptance of this incremental PR

The merge gate requires original database fixture integrity, correct selected/historical denominators, accurate 64-pair original candidate discovery (no false auto-merges), unchanged post-worker source/audit evidence, observed Windows/Linux benchmark output and honest timeout disclosure, and the existing complete four-platform regression suite. Definitive exact-HEAD Codex **code review** must complete before verifying/requesting **security review** for that same commit, with every finding dispositioned. No owner-unapproved merge.

**Next bounded follow-up:** interpret measured original-count and candidate-source projection latencies and optimize any pathological 100,000-original-record read paths without weakening source identity/audit validation. A subsequent, more expensive 100,000-**materialised**-record build and native Windows interface responsiveness test is still needed for full AT-22.
