from contextlib import closing
import sqlite3

from openpyxl import load_workbook
import pytest

from research_y.master_exports import export_results
from research_y.master_results import MasterResults,DEFAULT
from research_y.preflight_review import PRESS_ITEMS,read_preflight,record_preflight_review
from test_preflight_review import _project,_submission


@pytest.mark.parametrize("legacy_parameters", [False, True])
def test_limits_and_connector_fields_are_reported_for_the_captured_plan(tmp_path, legacy_parameters):
    project, run = _project(tmp_path)
    if legacy_parameters:
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE source_queries SET parameters_json=? WHERE run_id=?", ('{"retmax":20}',run))
    path = tmp_path / "Coverage.xlsx"
    with closing(MasterResults.capture(project,run)) as master:
        export_results(project,master,path,DEFAULT,scope="entire")
    with closing(load_workbook(path,read_only=True)) as book:
        rows = {r[1]:r[2:] for r in book["Reporting Checklist"].values if r[0]=="PRISMA-S"}
        assert "Not web-interface All Fields" in rows["Connector fields / wos"][1]
        assert "not article full text" in rows["Connector fields / pubmed"][1]
        assert rows["Search limits"][0] == ("awaiting verification" if legacy_parameters else "recorded")
        assert ("no language" in rows["Search limits"][1]) == (not legacy_parameters)
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
