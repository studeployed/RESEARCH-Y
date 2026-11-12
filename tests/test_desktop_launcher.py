from contextlib import closing

import pytest

from research_y.desktop import settings
from research_y.desktop.flow import ProjectFlowError, RealProjectFlow
from research_y.desktop.session import DesktopGuard, server_proof
from test_gui_prototype import call, owner, ORIGIN, TOKEN


def test_desktop_starts_without_selected_paths_or_implicit_project(tmp_path):
    with closing(RealProjectFlow(recent_parent=tmp_path / "recent")) as flow:
        assert flow.state()["project"] is None and flow.state()["selected_run_id"] is None
        with pytest.raises(ProjectFlowError, match="trusted_selection_required"):
            flow.open_selected()
        with pytest.raises(ProjectFlowError, match="trusted_selection_required"):
            flow.create_selected("Pending")
        state = flow.create_native_parent(tmp_path, "Explicit choice")
        assert state["project"]["name"] == "Explicit choice"
        assert state["selected_run_id"] is None
    with closing(RealProjectFlow(recent_parent=tmp_path / "recent")) as reopened:
        assert reopened.state()["project"] is None
        assert len(reopened.state()["recent_projects"]) == 1


@pytest.mark.parametrize("path, method", [("/_probe/state", "GET"), ("/_probe/start", "POST"),
                                         ("/_probe/stop", "POST")])
def test_desktop_has_no_automation_routes_even_with_owner_session(path, method):
    session, cookie = owner()
    sent, reached = call(guard=DesktopGuard, session=session, path=path, method=method,
                         headers=[(b'origin', ORIGIN), (b'cookie', cookie)])
    assert not reached and sent[0]["status"] == 403


def test_native_bootstrap_proves_host_without_disclosing_launch_secret():
    sent, reached = call(guard=DesktopGuard, path="/bootstrap")
    headers = dict(sent[0]["headers"])
    assert not reached and headers[b'x-researchy-server'] == server_proof(TOKEN).encode()
    assert TOKEN.encode() not in sent[1]["body"] and TOKEN.encode() not in headers.values()


def test_source_settings_only_load_the_two_app_entries_and_redact_values(monkeypatch):
    calls = []
    def read(target):
        calls.append(target)
        return ("fixture@example.invalid", "fixture-private-key")
    monkeypatch.setattr(settings, "_read", read)
    pubmed, starter, warnings = settings.source_profiles()
    assert calls == [settings.PUBMED_TARGET, settings.STARTER_TARGET]
    assert not warnings and pubmed.api_key == starter.api_key == "fixture-private-key"
    assert "fixture" not in repr((pubmed, starter, warnings))


def test_invalid_source_profile_leaves_other_source_and_offline_work_available(monkeypatch):
    def read(target):
        if target == settings.PUBMED_TARGET:
            return ("bad address", "private")
        return None
    monkeypatch.setattr(settings, "_read", read)
    assert settings.source_profiles() == (None, None, ("PubMed settings could not be loaded.",))
