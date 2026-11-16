import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Event
from unittest.mock import MagicMock

import pytest

from research_y.desktop import app
from research_y.desktop.flow import ProjectFlowError, RealProjectFlow
from test_reviewed_master import populated


@pytest.mark.parametrize(("action", "value"), [
    ("cloud_confirm", "revision"), ("local_suggest", {}), ("study_suggest", "source"),
    ("specialist", {"action": "enrichment_lookup", "data": {}}),
    ("master_results", {"operation": "lookup", "data": {}}),
    ("pubmed_pilot_confirm",None), ("wos_pilot_confirm",None), ("wos_acquisition_tick_confirm",None),
])
def test_navigation_during_slow_desktop_request(monkeypatch, action, value):
    ui, flow = MagicMock(), MagicMock()
    ui.page.side_effect = lambda path: lambda renderer: renderer()
    ui.refreshable.side_effect = lambda renderer: MagicMock(side_effect=renderer)
    callbacks, calls = [], []
    entered, finish = Event(), Event()

    def run(flow, operation, payload):
        calls.append(operation)
        if operation == action:
            entered.set()
            assert finish.wait(5)

    monkeypatch.setattr(app, "perform_action", run)
    monkeypatch.setattr(app, "render_project_panel",
                        lambda ui, flow, act, **kwargs: callbacks.append(act))
    app.build_page(MagicMock(), ui, flow)

    async def exercise():
        act, = callbacks
        task = asyncio.create_task(act(action, value))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            await act(action, value)
            await asyncio.wait_for(act("recent_refresh"), timeout=2)
            assert calls == [action, "recent_refresh"]
        finally:
            finish.set()
            await task

    asyncio.run(exercise())


def test_pending_pilot_allows_audit_navigation_and_rejects_premature_reconciliation(tmp_path,monkeypatch):
    from test_gui_pubmed_pilot import _flow, _inject_count_only_transport
    _,flow,_,query = _flow(tmp_path)
    entered,finish=Event(),Event()
    calls=_inject_count_only_transport(monkeypatch,flow)
    operation=flow._operation
    def hold(name,**kwargs):
        if name=="pubmed_pilot_count":
            entered.set()
            assert finish.wait(6)
        return operation(name,**kwargs)
    monkeypatch.setattr(flow,"_operation",hold)
    with closing(flow), ThreadPoolExecutor(2) as worker:
        flow.offer_pubmed_pilot(query["query_id"])
        pending=worker.submit(flow.confirm_pubmed_pilot)
        try:
            assert entered.wait(2)
            assert worker.submit(flow.read_project_audit).result(2)["project_audit"]
            with pytest.raises(ProjectFlowError,match="still_running"):
                worker.submit(flow.reconcile_pubmed_pilot).result(2)
        finally:
            finish.set()
        assert pending.result(5)["last_pubmed_pilot"]["reported_matches"] == 57 and len(calls)==1


def test_removed_term_rejects_slow_model_response(tmp_path):
    from test_optional_local_assistant import FixtureAssistant
    from research_y.projects import create_project
    entered,finish=Event(),Event()
    class Held(FixtureAssistant):
        def propose_terms(self, seed):
            entered.set()
            assert finish.wait(5)
            return super().propose_terms(seed)
    project=create_project(tmp_path,"Changing draft")
    with closing(RealProjectFlow(local_assistant=Held())) as flow, ThreadPoolExecutor(2) as worker:
        flow.open_native_folder(project.root)
        gid=flow.edit_setup("add_group",dict(label="Group"))["strategy_draft"]["groups"][0]["group_id"]
        tid=flow.edit_setup("add_term",dict(group_id=gid,text="Seed"))["strategy_draft"]["groups"][0]["terms"][0]["term_id"]
        pending=worker.submit(flow.propose_local_terms,gid,tid)
        try:
            assert entered.wait(2)
            worker.submit(flow.edit_setup,"remove_term",dict(group_id=gid,term_id=tid)).result(2)
        finally:
            finish.set()
        with pytest.raises(ProjectFlowError,match="seed_changed"):
            pending.result(2)
        assert not flow.state()["strategy_draft"]["suggestions"]


def test_pending_doi_lookup_preserves_newer_preview(tmp_path, monkeypatch):
    from research_y import crossref_client
    project, run, _, _ = populated(tmp_path)
    entered, finish = Event(), Event()

    def lookup(*args, **kwargs):
        entered.set()
        assert finish.wait(8)
        return {"status": "old lookup"}

    monkeypatch.setattr(crossref_client, "enrich_publication", lookup)
    with closing(RealProjectFlow()) as flow, ThreadPoolExecutor(2) as worker:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        page = flow.inspect_publications()["publication_page"]
        flow.inspect_publication_detail(publication_id=page["rows"][0]["publication_id"], revision=page["revision"])
        offer = flow.specialist_action("enrichment_offer", {})["specialist"]["enrichment"]
        data = dict(revision=offer["target"]["revision"], actor="Reviewer", refresh=False, contact="review@example.invalid")
        request = worker.submit(flow.specialist_action, "enrichment_lookup", data)
        try:
            assert entered.wait(3)
            with pytest.raises(ProjectFlowError):
                worker.submit(flow.specialist_action, "enrichment_lookup", data).result(2)
            # A newer preview of even the same record supersedes the earlier request.
            worker.submit(flow.specialist_action, "enrichment_offer", {}).result(2)
        finally:
            finish.set()
        result = request.result(3)["specialist"]
        assert result["enrichment"]["target"] == offer["target"] and "lookup_result" not in result
