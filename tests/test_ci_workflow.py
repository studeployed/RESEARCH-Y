"""Ensure the four required checks run on pull requests and merged main only."""

from pathlib import Path


def test_ci_event_triggers_avoid_redundant_feature_pushes() -> None:
    repo = Path(__file__).resolve().parents[1]
    workflow = (repo / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert (
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "  pull_request:\n"
        "    branches: [main]\n"
        "  workflow_dispatch:\n"
    ) in workflow
    assert "feat/**" not in workflow and "fix/**" not in workflow
    assert "permissions:\n  contents: read" in workflow


def test_four_required_platform_checks_remain_unchanged() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
    ).read_text(encoding="utf-8")
    assert 'runs-on: ${{ matrix.os }}' in workflow
    assert 'os: [ubuntu-latest, windows-latest]' in workflow
    assert 'python-version: ["3.12", "3.13"]' in workflow
    assert 'name: Test ${{ matrix.os }} / Python ${{ matrix.python-version }}' in workflow
    assert "run: python -m pytest --cov=research_y --cov-report=term-missing" in workflow
