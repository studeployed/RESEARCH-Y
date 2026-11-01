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


def test_ci_timeouts_are_bounded_and_platform_specific() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
    ).read_text(encoding="utf-8")
    assert "    timeout-minutes: ${{ matrix.timeout-minutes }}\n" in workflow
    assert (
        "        include:\n"
        "          - os: ubuntu-latest\n"
        "            timeout-minutes: 15\n"
        "          - os: windows-latest\n"
        "            timeout-minutes: 30\n"
    ) in workflow
    assert "      fail-fast: false\n" in workflow


def test_ci_reports_progress_without_filtering_or_ignoring_tests() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
    ).read_text(encoding="utf-8")
    commands = [line.strip() for line in workflow.splitlines()
                if line.strip().startswith("run: python -m pytest")]
    # Preserve full discovery and coverage; only reporting flags are added.
    assert commands == [
        "run: python -m pytest --cov=research_y --cov-report=term-missing "
        "--tb=short -v --durations=20"
    ]
    assert "continue-on-error:" not in workflow
    assert "secrets." not in workflow
