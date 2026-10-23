# RESEARCH-Y

Python-based, locally operated biomedical literature discovery application for Windows. **Development stage: foundation / first Phase 1 increment; not yet an installable or usable search application.**

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

Application runtime currently uses the Python standard library only. Development-test packages and the build backend are pinned. Database connectors, GUI, installation packaging and the complete project data model will be added only as their increments are developed and verified.

## Currently implemented developer API (P1-01 only)

```python
from pathlib import Path
from research_y.projects import create_project, open_project, update_research_setup, read_research_setup

parent = Path("some-existing-parent-directory")
project = create_project(parent, "Right heart failure")
update_research_setup(project, theme="Right ventricular failure")
reopened = open_project(project.manifest_path)
assert read_research_setup(reopened).theme == "Right ventricular failure"
```

The parent directory must already exist. This is an internal tested API, **not** an end-user command-line interface or the completed application.

## Source control

Private GitHub repository, `main` as the protected integration branch once configured. All substantive changes use feature branches and reviewed pull requests; **the project owner must explicitly approve every merge**. No existing application or project code is imported.

No authentication credentials, research datasets or live project folders may be committed. Source credentials will eventually be stored in the operating-system credential store, not in `.ryproj` manifests. See [`SECURITY.md`](SECURITY.md).
