from contextlib import closing
import sqlite3

from openpyxl import load_workbook
import pytest

from research_y.master_exports import export_results
from research_y.master_results import MasterResults,DEFAULT
from research_y.preflight_review import PRESS_ITEMS,read_preflight,record_preflight_review
from test_preflight_review import _project,_submission


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
