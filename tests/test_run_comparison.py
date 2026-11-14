from contextlib import closing
import sqlite3
from uuid import uuid4

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
    row=next(r for r in view["rows"] if r["status"]=="retained")
    assert row["changed_fields"]==["abstract_number"] and row["notes"][0]["event_id"]==saved
    assert row["notes"][0]["original_retrieval_id"]==ids[0] and row["current_retrieval"]==ids[2]
    assert all(not r["notes"] for r in view["rows"] if r["status"]!="retained")
    subset=compare_runs(project,earlier,later,category="metadata_changed",page_size=1)
    assert subset["matching"]==1 and subset["rows"]==[row]
    assert [db_rows(project,t) for t in ("strategy_versions","source_retrievals","source_queries","query_retrievals")]==before
