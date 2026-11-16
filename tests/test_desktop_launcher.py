from contextlib import closing
import asyncio
import sys
from types import SimpleNamespace

import pytest

from research_y.desktop import settings
from research_y.desktop.folders import NativeFolderError, select_project_index
from research_y.desktop.flow import ProjectFlowError, RealProjectFlow
from research_y.desktop.session import DesktopGuard, server_proof
from research_y.projects import create_project
from test_gui_prototype import call, owner, ORIGIN, TOKEN


def test_index_picker_reopens_relocated_project_and_preserves_selection_on_cancel(tmp_path, monkeypatch):
    project = create_project(tmp_path, "Relocated index")
    moved = project.root.rename(tmp_path / "New location")
    index = moved / project.manifest_path.name
    choices = iter([(str(index),), None, (str(moved / "Other.ryproj"),)])
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(FileDialog=SimpleNamespace(OPEN=1)))

    class Window:
        async def create_file_dialog(self, *, dialog_type, directory, allow_multiple, file_types):
            assert directory
            assert dialog_type == 1 and not allow_multiple and "*.ryproj" in file_types[0]
            return next(choices)

    with closing(RealProjectFlow(recent_parent=tmp_path / "recent")) as flow:
        selected = asyncio.run(select_project_index(Window()))
        state = flow.open_native_folder(selected.parent)
        assert state["project"]["project_id"] == str(project.identifier)
        assert flow.project.root == moved
        assert asyncio.run(select_project_index(Window())) is None
        with pytest.raises(NativeFolderError, match="native_selection_invalid"):
            asyncio.run(select_project_index(Window()))
        assert flow.state()["project"] == state["project"]


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


def test_launcher_connection_control_sends_one_fixed_count_without_disclosing_settings(monkeypatch):
    from urllib.parse import parse_qs
    from unittest.mock import MagicMock
    from test_pubmed_probe import response
    from research_y.pubmed_probe import ESEARCH_URL
    profile=settings.PubMedHostProfile("fixture@example.invalid","fixture-secret")
    calls=[]
    def send(req,timeout):
        calls.append(req)
        assert req.full_url==ESEARCH_URL and req.get_method()=="POST"
        fields=parse_qs(req.data.decode())
        assert fields["retmax"]==["0"] and fields["term"]==["1[uid]"]
        assert fields["email"]==[profile.contact_email] and fields["api_key"]==[profile.api_key]
        return response("1[uid]","1")
    with closing(RealProjectFlow(pubmed_profile=profile)) as flow:
        flow._pubmed_connection_test=settings.PubMedConnectionTest(profile,transport=send)
        ui=MagicMock()
        controls={}
        def button(label,on_click):
            controls[label]=on_click
            return MagicMock()
        ui.button.side_effect=button
        settings.render_settings(ui,flow)
        assert not calls and flow.project is None
        asyncio.run(controls["Test PubMed connection"]())
        assert len(calls)==1
        ui.label.return_value.set_text.assert_called_with("PubMed returned a valid count for the connection test.")
        assert "fixture-secret" not in str(ui.mock_calls) and profile.contact_email not in str(flow.state())


def test_connection_test_sanitizes_rejection_and_honours_persisted_project_pause(tmp_path):
    from urllib.error import HTTPError
    from contextlib import closing
    import sqlite3
    profile=settings.PubMedHostProfile("fixture@example.invalid","secret-value")
    project=create_project(tmp_path,"Source settings")
    calls=[]
    def denied(req,timeout):
        calls.append(req)
        raise HTTPError(req.full_url,403,"secret-value",{"Retry-After":"120"},None)
    first=settings.PubMedConnectionTest(profile,transport=denied)
    assert "Windows Credential Manager" in first.check(project)
    fresh=settings.PubMedConnectionTest(profile,transport=denied)
    assert "requested a pause" in fresh.check(project) and len(calls)==1
    with closing(sqlite3.connect(project.database_path)) as db:
        assert "secret-value" not in str(list(db.execute("SELECT details_json FROM audit_events")))
    assert "entitlement" in settings.source_error_help("authentication_or_entitlement_denied")
    assert "retry deadline" in settings.source_error_help("quota_or_rate_limited")


def test_pubmed_test_and_source_workers_cannot_overlap(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered,release=Event(),Event()
    def held(project):
        entered.set()
        assert release.wait(timeout=5)
        return "complete"
    profile=settings.PubMedHostProfile("user@example.invalid")
    with closing(RealProjectFlow(pubmed_profile=profile)) as flow, ThreadPoolExecutor(1) as worker:
        flow.create_native_parent(tmp_path,"Connection scheduling")
        flow._pubmed_connection_test=SimpleNamespace(check=held)
        for attr,value in (("_pending_pilot",{}),("_pubmed_source_pending",{}),("_pubmed_metadata_pending",{}),
                           ("_coord_pending",{"tasks":[{"source_name":"pubmed"}]})):
            setattr(flow,attr,value)
            assert "active PubMed session" in flow.test_pubmed_connection()
            setattr(flow,attr,None)
        future=worker.submit(flow.test_pubmed_connection)
        assert entered.wait(timeout=5)
        try:
            assert "already running" in flow.test_pubmed_connection()
            for start in (flow.confirm_pubmed_pilot,flow.confirm_pubmed_source,flow.confirm_pubmed_metadata):
                with pytest.raises(ProjectFlowError,match="connection test"):
                    start()
        finally:
            release.set()
        assert future.result(timeout=5)=="complete"
