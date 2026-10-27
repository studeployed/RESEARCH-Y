"""No live network in normal CI; manual NCBI smoke stays secret-safe and opt-in."""

from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
LIVE_WORKFLOW = ROOT / ".github" / "workflows" / "pubmed-live-smoke.yml"


def test_live_provider_workflow_is_manual_only_and_read_only() -> None:
    text = LIVE_WORKFLOW.read_text(encoding="utf-8")
    assert "on:\n  workflow_dispatch:\n" in text
    assert "  pull_request:" not in text and "  push:" not in text
    assert "  schedule:" not in text and "  repository_dispatch:" not in text
    assert "permissions:\n  contents: read\n" in text
    assert "secrets.RESEARCHY_NCBI_CONTACT_EMAIL" in text
    assert "secrets.RESEARCHY_NCBI_API_KEY" in text
    assert "if [ -z \"$RESEARCHY_NCBI_CONTACT_EMAIL\" ]" in text
    assert "scripts/pubmed_source_smoke.py" in text
    assert '("ECMO"[All Fields])' in text
    assert "actions/upload-artifact" not in text
    assert "echo \"$RESEARCHY_NCBI_CONTACT_EMAIL\"" not in text
    assert "curl " not in text


def test_live_smoke_without_private_contact_does_not_attempt_network(monkeypatch, capsys) -> None:
    spec = importlib.util.spec_from_file_location(
        "_research_y_source_smoke_test", ROOT / "scripts" / "pubmed_source_smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("RESEARCHY_NCBI_CONTACT_EMAIL", raising=False)
    monkeypatch.delenv("RESEARCHY_NCBI_API_KEY", raising=False)
    assert module.main(["--query", '("ECMO"[All Fields])']) == 2
    captured = capsys.readouterr()
    assert "Not run: set RESEARCHY_NCBI_CONTACT_EMAIL privately" in captured.err
    assert captured.out == ""
