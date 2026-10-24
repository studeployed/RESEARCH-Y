# RESEARCH-Y

Python-based, locally operated biomedical literature discovery application for Windows. **Development stage: Phase 1 durable storage and query compilation; not yet an installable or usable search application.**

## Scientific and technical baseline

The authoritative requirements are in [`RESEARCH-Y_SPEC.md`](RESEARCH-Y_SPEC.md), version `1.0.0-draft.1`, approved 23 October 2026. Search sensitivity and auditability take priority: term groups are combined using **OR**. No Medical Subject Headings (MeSH), automatic AND/NOT restrictions or silent retrieval truncation are authorised.

The development plan and tracked test coverage are in [`docs/ROADMAP.md`](docs/ROADMAP.md) and [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md). See [`HANDOVER.md`](HANDOVER.md) for current state and next action.

## Developer setup (not the future end-user installation process)

Python **3.12 or 3.13**:

```sh
python -m venv .venv
# Activate .venv using the relevant shell's command.
python -m pip install -r requirements-dev.txt -e .
python scripts/check_traceability.py
python -m pytest -q
```

Application runtime currently uses the Python standard library only. Development-test packages and the build backend are pinned. Database connectors, GUI, installation packaging and operational data-processing services remain future increments. The current schema is described in [`docs/SCHEMA.md`](docs/SCHEMA.md).

## Currently implemented developer API (P1-01 and merged P1-02a)

```python
from pathlib import Path
from research_y.projects import create_project, open_project, update_research_setup, read_research_setup

parent = Path("some-existing-parent-directory")
project = create_project(parent, "Right heart failure")
update_research_setup(project, theme="Right ventricular failure")
reopened = open_project(project.manifest_path)
assert read_research_setup(reopened).theme == "Right ventricular failure"
```

The parent directory must already exist. Opening a valid version-1 project now migrates its database to schema version 2 only after writing a consistent backup into `backups/`; migration failure preserves the previous data. This is an internal tested API, **not** an end-user command-line interface or the completed application.

## Source control

**Public** GitHub repository with an active ruleset protecting `main`. The ruleset requires pull requests, resolution of review conversations, and successful Windows/Linux checks on Python 3.12 and 3.13. Feature branches remain unrestricted. **The project owner must explicitly approve every merge.** No existing application or project code is imported.

No authentication credentials, research datasets or live project folders may be committed. Source credentials will eventually be stored in the operating-system credential store, not in `.ryproj` manifests. See [`SECURITY.md`](SECURITY.md).

## Strategy/run persistence (P1-02b merged in PR #13)

The merged storage layer provides this **storage-only** internal workflow:

```python
from research_y.storage import (
    ApprovedTerm, StrategyGroup, approve_strategy, create_search_run,
    plan_source_query, list_run_queries,
)

group = StrategyGroup("right-heart", "Right heart", (
    ApprovedTerm("right ventricle", "researcher", approved=True),
))
strategy = approve_strategy(
    project, theme="Right heart failure", groups=(group,),
    approved_by="Researcher", approval_confirmed=True,
)
run = create_search_run(project, strategy.strategy_version_id)
plan_source_query(
    project, run_id=run.run_id, group_id="right-heart",
    source_name="pubmed", exact_query='"right ventricle"[All Fields]',
)
assert list_run_queries(project, run.run_id)[0].reported_matches is None
```

This example does not actually retrieve records. Term approval must be a genuine researcher decision made before calling the API; the API records the confirmation, not a peer-review substitute. Provider query compilation, validation, execution and count reconciliation are separate increments.

## Offline source-specific strategy preview (P1-03a merged in PR #15)

The merged `research_y.query_compiler` module compiles a **frozen, researcher-approved strategy snapshot** into transparent PubMed `[All Fields]` and Web of Science Starter `TS` OR queries, without executing them:

```python
from research_y.storage import get_strategy_snapshot
from research_y.query_compiler import compile_both

approved = get_strategy_snapshot(project, strategy.strategy_version_id)
pubmed_preview, wos_preview = compile_both(approved)
print(pubmed_preview.logical_union_query)
print(wos_preview.logical_union_query)
```

The returned source/group chunks retain atomic-term provenance and provider field limitations. Provider length limits are not guessed: a connector must provide an evidence-based `max_query_bytes` when known. No hit counts, source translation, source API acceptance, or completeness is asserted. See [query compilation documentation](docs/QUERY_COMPILER.md) and pending source checks.

## PubMed count-only query acceptance (P1-03b proposal)

The P1-03b feature branch introduces a narrowly scoped ESearch count/translation
probe. It reports PubMed's actual `querytranslation`, any phrase/index warnings
and source-reported count, **without retrieving IDs or declaring a complete
search**. All checks in ordinary continuous integration use synthetic fixtures
and never call external source APIs.

Live verification is **opt-in**, requires your own contact details at runtime,
and has not been performed in this development environment:

```powershell
$env:RESEARCHY_NCBI_CONTACT_EMAIL = "your-contact@example.org"
python scripts/pubmed_smoke.py --query '("right ventricle"[All Fields])'
Remove-Item Env:RESEARCHY_NCBI_CONTACT_EMAIL
```

An optional `RESEARCHY_NCBI_API_KEY` environment variable can be supplied for
personal, permitted use. Neither variable belongs in the repository or logs.
Even a valid count/translation is **not** a completed PubMed retrieval.
See [source acceptance limits](docs/PUBMED_QUERY_ACCEPTANCE.md).

## PubMed identifier retrieval (P1-04a, proposed)

The new `research_y.pubmed_ids.retrieve_bounded_identifiers` helper uses the existing
count-only ESearch client to request real PubMed identifier pages, never inventing
identifiers, hit counts, source completion or missing metadata. It reconciles
source-reported counts with unique page identifiers for a bounded query and
retains prior validated pages on error.

- The default safe query limit is **9,000 records** (below NCBI's documented 10,000-identifier PubMed ESearch window). Larger queries return `partition_required` without fetching a misleading partial first window.
- Pages use `retstart` and `retmax` over the fixed HTTPS ESearch endpoint. Count drift, overlapping PMIDs, missing pages or changed query translation are surfaced as incomplete/review required.
- An optional `on_verified_page` callback can transactionally persist each checked page. The pagination helper itself **does not provide durable resumption**; that and non-overlapping >10,000-hit partitioning are subsequent Phase 1 increments.
- Even `identifiers_reconciled_metadata_pending` **does not mean `completed_verified`**: PubMed metadata/abstract acquisition and search-run reconciliation remain outstanding. No source record is fabricated.

See [bounded identifier retrieval](docs/PUBMED_IDENTIFIER_RETRIEVAL.md).

## PubMed large-result identifier partitioning (P1-04b proposal)

The feature branch `feat/p1-04b-crdt-date-partitioning` adds an internal
`retrieve_date_partitioned_identifiers` API for approved PubMed query text and
an **explicit caller-supplied** Create Date coverage window. A dated query
greater than the bounded 9,000-record ESearch window is recursively split at
whole calendar-day boundaries. Root and child counts, per-partition query text,
boundaries and unique PMID results remain inspectable.

The software does **not** silently choose a historical coverage window.
If the requested window does not account for all of PubMed's unfiltered hits,
or any single day remains oversized, the result is **incomplete**, not a
truncated success. Even a reconciled PMID set remains
`identifiers_reconciled_metadata_pending`, never a verified full-text/metadata
search. See [the partitioning protocol](docs/PUBMED_DATE_PARTITIONING.md).
