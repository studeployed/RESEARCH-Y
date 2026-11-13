from contextlib import closing
import sqlite3
import pytest
from openpyxl import load_workbook
from research_y.run_acceptance import read_acceptance,accept_run
from research_y.master_results import MasterResults,DEFAULT
from research_y.master_exports import export_results
from research_y.projects import open_project
from test_reviewed_master import populated,decide


def test_final_scope_requires_all_source_and_identity_evidence_and_revokes_after_change(tmp_path):
    project,run,queries,ids=populated(tmp_path)
    options=dict(actor="Reviewer",limitations="Starter Topic and accessible metadata only",confirmed=True)
    incomplete=read_acceptance(project,run)
    assert incomplete["status"]=="Incomplete" and not incomplete["eligible"]
    with pytest.raises(ValueError):
        accept_run(project,run,expected_revision=incomplete["revision"],**options)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    decide(project,ids["111"],ids["222"],"rejected_match")
    ready=read_acceptance(project,run)
    assert ready["eligible"] and ready["status"]=="Incomplete"
    saved=accept_run(project,run,expected_revision=ready["revision"],**options)
    assert saved["status"]=="Verified Complete" and saved["global_unique_publications"]==2
    reopened=open_project(project.root)
    assert read_acceptance(reopened,run)["receipt"]==saved["receipt"]
    with closing(MasterResults.capture(reopened,run)) as results:
        output=tmp_path/"Accepted.xlsx"
        export_results(reopened,results,output,DEFAULT,scope="entire")
    with closing(load_workbook(output,read_only=True)) as book:
        assert dict(list(book["Export Scope"].values)[1:])["status"]=="Verified Complete"
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",(queries["g-ecmo","pubmed"][0],))
    changed=read_acceptance(reopened,run)
    assert not changed["eligible"] and changed["status"]=="Incomplete" and changed["receipt"] is None
