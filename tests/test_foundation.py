"""Foundation constraints requiring no source credentials or network access."""

from pathlib import Path

import research_y


def test_package_has_development_version() -> None:
    assert research_y.__version__ == "0.1.0.dev0"


def test_spec_has_approved_baseline_and_revision_entry() -> None:
    specification = (Path(__file__).resolve().parents[1] / "RESEARCH-Y_SPEC.md").read_text(
        encoding="utf-8"
    )
    assert "Version | **1.0.0-draft.1**" in specification
    assert "**Approved initial implementation baseline — 23 October 2026**" in specification
    assert "**Approved as initial implementation baseline; development authorised.**" in specification
