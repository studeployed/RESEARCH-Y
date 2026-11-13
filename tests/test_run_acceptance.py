from contextlib import closing
import sqlite3
import pytest
from openpyxl import load_workbook
from research_y.run_acceptance import read_acceptance,accept_run
from research_y.master_results import MasterResults,DEFAULT
from research_y.master_exports import export_results
from research_y.projects import open_project
from test_reviewed_master import populated,decide
from test_run_execution_board import _project,_pubmed,_wos,Clock


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


def test_singleton_does_not_require_an_impossible_pair(tmp_path):
    from research_y.publication_identity import materialise_retrieval
    project,run,queries=_project(tmp_path)
    clock=Clock()
    for (_,source),(qid,query) in queries.items():
        if source=="pubmed":
            _pubmed(project,qid,query,pmids=())
        else:
            clock.sleep(60)
            _wos(project,qid,query,clock=clock,count=1)
    with closing(sqlite3.connect(project.database_path)) as db:
        rid,=db.execute("SELECT retrieval_id FROM source_retrievals").fetchone()
    materialise_retrieval(project,rid,actor="Reviewer")
    state=read_acceptance(project,run)
    assert state["eligible"] and state["global_unique_publications"]==1


def test_supplementary_identity_with_reviewed_pairs_and_cache_invalidation(tmp_path):
    from research_y.desktop.flow import RealProjectFlow
    project,run,_,ids=populated(tmp_path)
    decide(project,ids["111"],ids["WOS:000000001"],"confirmed_match")
    decide(project,ids["111"],ids["222"],"rejected_match")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        flow.select_run(run)
        ready=flow.run_acceptance()["run_acceptance"]
        decision=dict(expected_revision=ready["revision"],actor="Reviewer",limitations="Starter Topic only",confirmed=True)
        assert flow.run_acceptance(decision)["run_acceptance"]["receipt"]
        state=flow.import_bibliography(dict(label="Manual",manual={"title":"Additional publication"},indices=[0],revision=None,
                                            actor="Reviewer",confirmed=True))
        assert state["run_acceptance"] is None and not read_acceptance(project,run)["eligible"]
    with closing(sqlite3.connect(project.database_path)) as db:
        extra,=db.execute("SELECT retrieval_id FROM source_retrievals WHERE source_name='manual_bibliographic'").fetchone()
    for older in ids.values():
        decide(project,older,extra,"rejected_match")
    checked=read_acceptance(project,run)
    assert checked["eligible"] and checked["global_unique_publications"]==3
