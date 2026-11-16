from contextlib import closing
import sqlite3
from uuid import uuid4
import pytest

from research_y import publication_identity as identity
from research_y.projects import open_project
from research_y.run_comparison import append_note,compare_runs
from test_publication_identity import store,db_rows


def test_repeat_search_preserves_original_versions_and_carries_scoped_notes(store):
    project,ids=store
    with closing(sqlite3.connect(project.database_path)) as db,db:
        earlier,first=db.execute("SELECT run_id,source_record_id FROM source_retrievals WHERE retrieval_id=?",(ids[0],)).fetchone()
        later=db.execute("SELECT run_id FROM source_retrievals WHERE retrieval_id=?",(ids[2],)).fetchone()[0]
        # Represent a new search finding this same source ID with corrected metadata.
        db.execute("UPDATE source_retrievals SET source_record_id=? WHERE retrieval_id=?",(first,ids[2]))
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",(str(uuid4()),later,"pubmed","only-later",
                   project.created_at_utc,identity._json({"record":{"title":"New publication"}})))
    for rid in ids:
        identity.materialise_retrieval(project,rid,actor="Fixture reviewer")
    before=[db_rows(project,t) for t in ("strategy_versions","source_retrievals","source_queries","query_retrievals")]
    saved=append_note(project,ids[0],actor="Reviewer",text="Check the source's abstract number")
    view=compare_runs(open_project(project.root),earlier,later)
    assert view["source_counts"]=={"new":1,"retained":1,"absent":1,"metadata_changed":1}
    assert view["publication_correspondence"]==dict(earlier_only=1,later_only=0,shared_publication_id=0,
            distinct_ids_with_recurring_source=1,earlier_unresolved=0,later_unresolved=0)
    row=next(r for r in view["rows"] if r["status"]=="retained")
    assert row["changed_fields"]==["abstract_number"] and row["notes"][0]["event_id"]==saved
    assert row["notes"][0]["original_retrieval_id"]==ids[0] and row["current_retrieval"]==ids[2]
    assert all(not r["notes"] for r in view["rows"] if r["status"]!="retained")
    subset=compare_runs(project,earlier,later,category="metadata_changed",page_size=1)
    assert subset["matching"]==1 and subset["rows"]==[row]
    assert [db_rows(project,t) for t in ("strategy_versions","source_retrievals","source_queries","query_retrievals")]==before


def test_split_or_missing_publication_links_are_reported_as_unresolved():
    from research_y.run_comparison import _publication_correspondence
    def records(**pairs):
        return {source:{"publication_id":pid} for source,pid in pairs.items()}
    before=records(a="old",b="old",c="same",d="unresolved",e="absent")
    after=records(a="left",b="right",c="same",d=None,f="new")
    assert _publication_correspondence(before,after)==dict(earlier_only=1,later_only=1,shared_publication_id=1,
            distinct_ids_with_recurring_source=0,earlier_unresolved=2,later_unresolved=2)


def test_researcher_carries_a_classification_to_a_rediscovered_publication(tmp_path):
    from research_y import study_classification as classification
    from research_y.desktop.flow import RealProjectFlow
    from research_y.storage import create_search_run
    from test_reviewed_master import populated

    project,earlier,_,ids=populated(tmp_path)
    original=ids["111"]
    with closing(sqlite3.connect(project.database_path)) as db:
        strategy,=db.execute("SELECT strategy_version_id FROM search_runs WHERE run_id=?",(earlier,)).fetchone()
        old,=db.execute("SELECT publication_id FROM publication_retrievals WHERE retrieval_id=?",(original,)).fetchone()
    later=create_search_run(project,strategy).run_id
    new_rid=str(uuid4())
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("INSERT INTO source_retrievals SELECT ?,?,source_name,source_record_id,retrieved_at_utc,"
                   "json_set(original_metadata_json,'$.record.title','Updated title') FROM source_retrievals WHERE retrieval_id=?",
                   (new_rid,later,original))
    new=identity.materialise_retrieval(project,new_rid,actor="Researcher").publication_id
    def decide(pid,label):
        return classification.review_classification(project,pid,dimension="language",labels=[label],actor="First reviewer",
                rationale="Checked the original",expected_revision=classification.read_classification(project,pid)["revision"],
                confirmed=True)["decisions"]["language"]
    earlier_review=decide(old,"multilingual")
    with closing(RealProjectFlow()) as flow:
        flow.open_native_folder(project.root)
        def compare():
            page=flow.compare_run_history(earlier,later)["run_comparison"]
            return next(row for row in page["rows"] if row["current_retrieval"]==new_rid)
        row=compare()
        assert row["previous_publication"]==old and row["current_publication"]==new
        history=row["classifications"]
        assert history["previous_decisions"]["language"]==earlier_review and not history["current_decisions"]
        assert "title" in row["changed_fields"]
        args=dict(current_retrieval=new_rid,dimension="language",event_id=earlier_review["event_id"],
                  revision=history["current_revision"],actor="Update reviewer",rationale="Checked the new evidence")
        corrected=decide(old,"English")
        with pytest.raises(identity.StalePublicationError):
            flow.carry_classification(**args)
        assert not classification.read_classification(project,new)["decisions"]
        row=compare()
        args["event_id"]=corrected["event_id"]
        flow.select_run(later)
        queue=flow.inspect_study_queue(False,False,False)["study_queue"]
        candidate,=queue["rows"]
        flow.open_queued_study(new,candidate["revision"])
        compare()
        refreshed=flow.carry_classification(**args)
        assert refreshed["queued_study"]["current"]["language"]==["English"]
        assert refreshed["queued_study"]["revision"]!=candidate["revision"]
        assert refreshed["study_queue"]["rows"][0]["revision"]==refreshed["queued_study"]["revision"]
        stored=classification.read_classification(open_project(project.root),new)["decisions"]["language"]
        assert stored["labels"]==["English"] and stored["actor"]=="Update reviewer"
        assert stored["earlier_decision"]["event_id"]==corrected["event_id"]
        assert classification.read_classification(project,old)["decisions"]["language"]==corrected
