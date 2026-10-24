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

Private GitHub repository, `main` as the integration branch (branch-protection configuration pending). All substantive changes use feature branches and reviewed pull requests; **the project owner must explicitly approve every merge**. No existing application or project code is imported.

No authentication credentials, research datasets or live project folders may be committed. Source credentials will eventually be stored in the operating-system credential store, not in `.ryproj` manifests. See [`SECURITY.md`](SECURITY.md).

## Strategy/run persistence (P1-02b proposal, unmerged)

The feature branch also introduces a **storage-only** internal workflow:

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

## Offline source-specific strategy preview (P1-03a, proposed)

On the P1-03a feature branch, the `research_y.query_compiler` module compiles a **frozen, researcher-approved strategy snapshot** into transparent PubMed `[All Fields]` and Web of Science Starter `TS` OR queries, without executing them:

```python
from research_y.storage import get_strategy_snapshot
from research_y.query_compiler import compile_both

approved = get_strategy_snapshot(project, strategy.strategy_version_id)
pubmed_preview, wos_preview = compile_both(approved)
print(pubmed_preview.logical_union_query)
print(wos_preview.logical_union_query)
```

The returned source/group chunks retain atomic-term provenance and provider field limitations. Provider length limits are not guessed: a connector must provide an evidence-based `max_query_bytes` when known. No hit counts, source translation, source API acceptance, or completeness is asserted. See [query compilation documentation](docs/QUERY_COMPILER.md) and pending source checks.
