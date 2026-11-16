from contextlib import closing
from io import BytesIO
import sqlite3
from uuid import uuid4

from openpyxl import load_workbook
import pytest

from research_y.master_exports import export_results
from research_y.master_results import MasterResults,DEFAULT
from research_y.preflight_review import PRESS_ITEMS,read_preflight,record_preflight_review
from test_preflight_review import _project,_submission


def test_expansion_ancestry_and_run_update_method_in_both_workbooks(tmp_path):
    from research_y.desktop.strategy_setup import StrategyDraft
    from research_y.desktop.flow import RealProjectFlow
    from research_y.run_comparison import record_update_method
    from research_y.strategy_admission import commit_approved_strategy
    from research_y.strategy_report import capture_strategy_report
    from research_y.strategy_workbook import render_strategy_workbook
    project, earlier = _project(tmp_path)
    draft = StrategyDraft()
    group = draft.add_group("Support")
    seed = draft.add_term(group,"ECMO")
    draft.local_offers(group,seed,{"terms":["extracorporeal membrane oxygenation"],"model":"fixture"},12)
    draft.review_variant(next(iter(draft.suggestions)),"accept")
    second = draft.groups[0]["terms"][-1]["term_id"]
    draft.local_offers(group,second,{"terms":["ECLS"],"model":"fixture"},13)
    draft.review_variant(next(reversed(draft.suggestions)),"accept","extracorporeal life support")
    later = commit_approved_strategy(project,request_id=str(uuid4()),theme="Updated strategy",
        approved_by="Reviewer",groups=draft.approved_groups(),approval_confirmed=True).run_id
    method = "Repeated both database searches from inception with the revised approved terminology."
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(later)
        state = flow.save_update_method(later,earlier,method,"Reviewer",None)
        receipt = state["report"]["run"]["update_method"]
        assert receipt["earlier_run"] == earlier
        assert flow.save_update_method(later,earlier,method,"Reviewer",None)["report"]["run"]["update_method"] == receipt
    with pytest.raises(ValueError,match="changed"):
        record_update_method(project,later,earlier_run=earlier,method="Stale edit",actor="Reviewer",expected_event=None)
    report = capture_strategy_report(project,later)
    standalone = BytesIO(render_strategy_workbook(report))
    workbook = tmp_path/"Update.xlsx"
    with closing(MasterResults.capture(project,later)) as master:
        export_results(project,master,workbook,DEFAULT,scope="entire")
    for path in (standalone,workbook):
        with closing(load_workbook(path,read_only=True)) as book:
            assert method in str(list(book["Methods"].values))
            row = next(r for r in book["Search Terms"].values if "extracorporeal life support" in r)
            assert row[-3:] == ("ECMO","extracorporeal membrane oxygenation","extracorporeal life support")
    assert "update_method" not in capture_strategy_report(project,earlier).as_dict()["run"]


@pytest.mark.parametrize("plan", ["approved", "legacy_parameters", "title_only"])
def test_limits_and_connector_fields_are_reported_for_the_captured_plan(tmp_path, plan):
    project, run = _project(tmp_path)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        if plan == "legacy_parameters":
            db.execute("UPDATE source_queries SET parameters_json=? WHERE run_id=?", ('{"retmax":20}',run))
        if plan == "title_only":
            for source, query in (("pubmed", '"ECMO"[Title]'), ("wos", 'TI=("ECMO")')):
                db.execute("UPDATE source_queries SET exact_query=? WHERE run_id=? AND source_name=?",
                           (query,run,source))
    path = tmp_path / "Coverage.xlsx"
    with closing(MasterResults.capture(project,run)) as master:
        export_results(project,master,path,DEFAULT,scope="entire")
    with closing(load_workbook(path,read_only=True)) as book:
        rows = {r[1]:r[2:] for r in book["Reporting Checklist"].values if r[0]=="PRISMA-S"}
        for source in ("pubmed", "wos"):
            status, observation = rows["Connector fields / "+source]
            assert status == ("recorded" if plan=="approved" else "awaiting verification")
            assert ("All Fields" in observation) == (plan=="approved")
        assert rows["Search limits"][0] == ("recorded" if plan=="approved" else "awaiting verification")
        assert ("no language" in rows["Search limits"][1]) == (plan=="approved")
        if plan=="title_only":
            exact = {row[3] for row in list(book["Executed Queries"].values)[1:]}
            assert exact == {'"ECMO"[Title]', 'TI=("ECMO")'}
        assert dict(list(book["Methods"].values)[1:])["Research theme"]


def test_named_press_outcomes_in_real_workbook(tmp_path):
    project,run=_project(tmp_path)
    preflight=read_preflight(project,run)
    args=_submission(run,plan_sha=preflight["plan_sha256"],reviewer_role="independent_peer_reported",
                     press_items={k:("needs_revision" if k=="spelling" else "not_reviewed")
                                  for k in PRESS_ITEMS})
    record_preflight_review(project,**args)
    from uuid import uuid4
    record_preflight_review(project,**dict(args,review_id=str(uuid4()),reviewer_role="researcher_self_check"))
    path=tmp_path/"Methods.xlsx"
    with closing(MasterResults.capture(project,run)) as master:
        export_results(project,master,path,DEFAULT,scope="entire")
    with closing(load_workbook(path,read_only=True)) as book:
        rows={r[1]:r[2:] for r in list(book["Reporting Checklist"].values)[1:] if r[0]=="PRESS"}
        assert rows["Independent peer review"][0]=="reported by researcher"
        assert rows["spelling"][0]=="needs_revision" and args["reviewer_name"] in rows["spelling"][1]
        assert rows["search_fields"][0]=="not_reviewed"
