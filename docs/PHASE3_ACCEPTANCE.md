# Phase 3 release acceptance

The release candidate combines the portable archive, master results, citation
import, publication exports, run comparisons, project documents and a Windows
installer with its own runtime. The three units are tracked in [issue #142](https://github.com/studeployed/RESEARCH-Y/issues/142).

| Gate | Observation and evidence |
|---|---|
| AT-01 | A project with reviewed publications, jobs, strategy, notes and source history reopens. A portable restore compares every database table. Native restart independently reopens the actual workbook. See `tests/test_project_archive.py`, `tests/test_run_comparison.py` and `tools/desktop_lifecycle.py`. |
| AT-02 | A permitted PDF attachment preserves its original filename, source, researcher, digest and project-relative link after transfer to another parent. Changed attachment bytes are rejected. See `tests/test_project_documents.py`. |
| AT-03 | An archive taken with an active WAL writer contains the committed database. A pre-publication interruption leaves the destination available for a clean retry. Existing projects are preserved. See `tests/test_project_archive.py`. |
| AT-04 | Only individually approved suggestions reach the frozen search. See the [Phase 2 record](PHASE2_ACCEPTANCE.md). |
| AT-05 | Test searches retain the OR union per group and across groups; two publications can have six separate source/group memberships. See `tests/test_query_compiler.py` and `tests/test_reviewed_master.py`. |
| AT-06 | The live clinical OR sample checked the provider's accepted PubMed translation for the exact tagged query. See the [dated sample](evidence/pubmed-metadata-43300410950-summary.json). |
| AT-07 | The live partitioned PubMed run recovered 19,483 distinct identifiers and reconciled the reported count. See the [aggregate evidence](evidence/pubmed-41235232458-summary.json). |
| AT-08 | A live Starter run reconciled 19,584 records across 392 acquisition and 392 independent verification pages. The checkpoint tests cover quota-aware pause, cooldown and resumption. Live quota depletion and a cross-date replenishment observation have separate evidence requirements in [#119](https://github.com/studeployed/RESEARCH-Y/issues/119). See the [dated run](evidence/wos-recovery-41306953908-summary.json) and `tests/test_wos_checkpoints.py`. |
| AT-09 | Durable checkpoint, partial-response and restart tests preserve original sources and membership counts. The recorded live samples cover provider-specific recovery. See `tests/test_pubmed_checkpoints.py`, `tests/test_wos_checkpoints.py` and the [Phase 1 record](PHASE1_ACCEPTANCE.md). |
| AT-10 | One reviewed publication may represent two original source records with all memberships retained. Confirmed and rejected comparisons carry separate receipts in the actual XLSX. See `tests/test_reviewed_master.py` and `tests/test_master_exports.py`. |
| AT-11–13 | Separate supplement abstracts, distinct printed/file page locators and official society-only guidance all survive reopen. See the [Phase 2 record](PHASE2_ACCEPTANCE.md). |
| AT-14–16 | Post-retrieval filters, classification overrides and targeted enrichment retain original source evidence and counts. See the [Phase 2 record](PHASE2_ACCEPTANCE.md) and `tests/test_master_results.py`. |
| AT-17 | Two retained run inventories distinguish new, retained, absent and changed records. An attributed note follows the same provider, database and record ID. Source and query tables remain unchanged. See `tests/test_run_comparison.py`. |
| AT-18 | Full, filtered and selected exports have separate denominators. An independent XLSX reader verifies publication and source rows, filters, frozen headers, specialist fields, comparison receipts, text-only cells, sheet splitting and reconstruction of long text. The separate strategy workbook remains available. See `tests/test_master_exports.py`, `tests/test_strategy_workbook.py` and `tests/test_reporting_checklist.py`. |
| AT-19 | Source or identity shortfalls prevent final acceptance. A researcher must record coverage limitations before a reconciled run can be marked Verified Complete. Changing a source to failed withdraws the current acceptance on reinspection. See `tests/test_run_acceptance.py`. |
| AT-20 | Basic search and the independently readable reviewed workbook operate with the optional model absent and cloud disabled. See `tests/test_phase2_acceptance.py`. |
| AT-21 | Archive directories, file inventories and checksums are validated before a destination becomes visible. The diagnostic export uses an allowlist of identifiers and states. Migration rollback, recovery and machine credential handling have separate tests. See `tests/test_project_archive.py`, `tests/test_release_evidence.py`, `tests/test_schema_migrations.py` and `tests/test_wos_migration.py`. |
| AT-22 | The Windows service benchmark captured 100,000 original publication identities in 14.285 s. Filtering, first/last page inspection and bulk selection of all 49,936 matches took 3.079 s. The host remained responsive with a longest measured sampling interval of 0.102 s. Source, membership and audit counts stayed unchanged. See the [measurement](evidence/phase3-master-windows-20261113.json), `tools/windows_master_benchmark.py` and the existing native 100k workflows. |

## Scope of the evidence

The Windows installer is a per-user x64 candidate. The clean-install workflow
uses its bundled Python and packages to create, save, reopen and relocate a
project. Windows WebView2 is a system prerequisite. Local model use is optional,
CPU-based and subject to researcher review. Paid cloud use and code signing
require separate authorisation. [Installation](WINDOWS_INSTALLER.md)

Source-specific live checks establish results for their recorded scopes and
dates. A release acceptance result does not certify a researcher's search.
Search outputs retain per-source limitations, including Starter coverage,
available metadata and unverified peer review. The Phase 3 benchmark measures
the frozen master service and interaction latency on synthetic originals.
Separate native workflows exercise the desktop window and earlier 100k source views.
