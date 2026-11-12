from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from research_y.projects import open_project
from research_y.provisional_manifest_intent import list_manifest_intents, prepare_manifest_intent, preview_manifest_intent
from research_y.storage import create_search_run
from tools.gui_feasibility.real_project_flow import ProjectFlowError, RealProjectFlow
from tools.gui_feasibility.run_real_project import fixture


def opened(project, run_id):
    flow = RealProjectFlow(selected_root=project.root, selected_parent=project.root.parent)
    flow.open_selected()
    flow.select_run(run_id)
    return flow


def test_preview_cancel_switch_stale_and_duplicate_confirmation(tmp_path):
    project, run_id = fixture(tmp_path)
    with closing(sqlite3.connect(project.database_path)) as db:
        version = db.execute("SELECT strategy_version_id FROM search_runs").fetchone()[0]
    second = create_search_run(project, version)
    with closing(opened(project, run_id)) as flow:
        before = project.database_path.read_bytes()
        offer = flow.preview_manifest("one.xlsx", "Researcher")["manifest_offer"]
        assert offer["global_unique_publications"] is None
        assert flow.dismiss_manifest(offer["offer_token"])["manifest_offer"] is None
        assert project.database_path.read_bytes() == before
        changed = flow.preview_manifest("two.xlsx", "Researcher")["manifest_offer"]
        with pytest.raises(ProjectFlowError, match="manifest_offer_changed"):
            flow.confirm_manifest(offer["offer_token"])
        flow.select_run(second.run_id)
        with pytest.raises(ProjectFlowError, match="manifest_offer_changed"):
            flow.confirm_manifest(changed["offer_token"])
        flow.select_run(run_id)
        offer = flow.preview_manifest("three.xlsx", "Researcher")["manifest_offer"]
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE source_queries SET status='failed' WHERE run_id=?", (run_id,))
        with pytest.raises(ProjectFlowError, match="stale_original_revision"):
            flow.confirm_manifest(offer["offer_token"])
        assert flow.state()["manifest_offer"] is None
        offer = flow.preview_manifest("three.xlsx", "Researcher")["manifest_offer"]
        receipt = flow.confirm_manifest(offer["offer_token"])["manifest_receipt"]
        assert receipt["state"] == "consent_current"
        with pytest.raises(ProjectFlowError, match="manifest_offer_changed"):
            flow.confirm_manifest(offer["offer_token"])
        with pytest.raises(ProjectFlowError, match="invalid_manifest_request"):
            flow.preview_manifest("../outside.xlsx", "Researcher")
    assert len(list_manifest_intents(project, run_id)["entries"]) == 1
    assert not list((project.root / "exports").iterdir())


@pytest.mark.parametrize("committed", [False, True])
def test_lost_reply_reinspection_and_fresh_host_history(tmp_path, monkeypatch, committed):
    project, run_id = fixture(tmp_path)
    with closing(opened(project, run_id)) as flow:
        offer = flow.preview_manifest("saved.xlsx", "Researcher")["manifest_offer"]
        original = flow._operation

        def lose_reply(name, **kwargs):
            if name == "prepare_manifest_intent":
                if committed:
                    original(name, **kwargs)
                raise ProjectFlowError("worker_interrupted")
            return original(name, **kwargs)

        monkeypatch.setattr(flow, "_operation", lose_reply)
        with pytest.raises(ProjectFlowError, match="worker_interrupted"):
            flow.confirm_manifest(offer["offer_token"])
        with pytest.raises(ProjectFlowError, match="manifest_reconciliation_required"):
            flow.confirm_manifest(offer["offer_token"])
        monkeypatch.setattr(flow, "_operation", original)
        checked = flow.reconcile_manifest()
        assert not checked["manifest_pending"]
        if not committed:
            assert checked["manifest_offer"]["export_id"] == offer["export_id"]
            checked = flow.confirm_manifest(offer["offer_token"])
        assert checked["manifest_receipt"]["export_id"] == offer["export_id"]
    with closing(opened(open_project(project.root), run_id)) as fresh:
        with pytest.raises(ProjectFlowError, match="unknown_export"):
            fresh.inspect_saved_manifest(offer["export_id"])
        replay = fresh.preview_manifest("saved.xlsx", "Researcher")["manifest_offer"]
        assert replay["export_id"] == offer["export_id"] and replay["offer_token"] != offer["offer_token"]
        with pytest.raises(ProjectFlowError, match="manifest_offer_changed"):
            fresh.confirm_manifest(offer["offer_token"])
        assert fresh.confirm_manifest(replay["offer_token"])["manifest_receipt"] == checked["manifest_receipt"]
        entry, = fresh.manifest_history()["manifest_history"]["entries"]
        assert entry["event_id"] == checked["manifest_receipt"]["audit_event_id"]
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE source_queries SET status='failed' WHERE run_id=?", (run_id,))
        read = fresh.inspect_saved_manifest(entry["export_id"])["manifest_receipt"]
        assert read["state"] == "stale_reapproval_required"
        assert read["audit_event_id"] == entry["event_id"]
    assert not list((project.root / "exports").iterdir())


def test_saved_consent_history_cursor_is_exclusive_and_run_scoped(tmp_path):
    project, run_id = fixture(tmp_path)
    revision = preview_manifest_intent(project, run_id)["original_revision"]
    for number in range(21):
        prepare_manifest_intent(project, run_id, f"consent-{number}.xlsx", export_id=str(uuid4()),
                                expected_revision=revision, actor="Synthetic researcher", confirmed=True)
    with closing(sqlite3.connect(project.database_path)) as db:
        version = db.execute("SELECT strategy_version_id FROM search_runs").fetchone()[0]
    other = create_search_run(project, version)
    with closing(opened(project, run_id)) as flow:
        first = flow.manifest_history()["manifest_history"]
        assert [entry["output_name"] for entry in first["entries"]] == [
            f"consent-{number}.xlsx" for number in range(20, 0, -1)]
        last = flow.manifest_history(older=True)["manifest_history"]
        assert [entry["output_name"] for entry in last["entries"]] == ["consent-0.xlsx"]
        assert last["next_before_event_id"] is None
        flow.select_run(other.run_id)
        assert flow.manifest_history()["manifest_history"]["entries"] == []
        with pytest.raises(ProjectFlowError, match="unknown_export"):
            flow.inspect_saved_manifest(last["entries"][0]["export_id"])
