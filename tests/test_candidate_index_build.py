"""P1-06k2a synthetic durability and recovery acceptance for derived keys.

This fixture never calls PubMed, Web of Science or external models. A complete
derived index is never interpreted as a completed search or deduplication.
"""
from __future__ import annotations

from contextlib import closing
import sqlite3

import pytest

from research_y import publication_identity as identity
from research_y.candidate_index_build import (
    CandidateIndexError, preview_candidate_index,
    start_candidate_index, advance_candidate_index,
)
from research_y.projects import create_project, open_project
from uuid import uuid4


def uid():
    return str(uuid4())


@pytest.fixture
def project_fixture(tmp_path):
    project = create_project(tmp_path, "Derived candidate-key index")
    run, historic, strategy = uid(), uid(), uid()
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (strategy, 1, project.created_at_utc, "{}"))
        db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                   (strategy, "g1", "Research", 0))
        for run_id in (run, historic):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id, strategy, project.created_at_utc, "incomplete", None))
    return project, run, historic


def source(fixture, *, source_name="pubmed", number=1, title="Shared abstract",
           doi="10.1000/supplement", run=None,
           abstract="PRIVATE_LICENSED_ABSTRACT_DO_NOT_EXPORT"):
    project, primary, _ = fixture
    run_id = run or primary
    rid = uid()
    record_id = str(number) if source_name=="pubmed" else (
        "WOS:"+str(number) if source_name=="wos" else str(number))
    if source_name=="pubmed":
        record = dict(
            pmid=record_id, title=title, identifiers={"doi":[doi]},
            publication_types=["Conference Abstract"],
            abstract_sections=[{"text":abstract}],
        )
        metadata = dict(source="NCBI PubMed EFetch XML",record=record,
                        rights_review_required_for_abstract_redistribution=True)
    elif source_name=="wos":
        record = dict(uid=record_id,title=title,
                      identifiers={"doi":doi},types=["Conference Abstract"])
        metadata = dict(provider="wos_starter",database="WOS",record=record,
                        rights_status="licence_review_required")
    else:
        metadata = dict(source="manual",record=dict(title=title,abstract=abstract))
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (rid,run_id,source_name,record_id,project.created_at_utc,
                    identity._json(metadata)))
    return rid


def begin(project, *, actor="Researcher"):
    proposal = preview_candidate_index(project)
    return start_candidate_index(project,expected_revision=proposal["revision"],
                                 actor=actor,confirmed=True)


def step(project, proposal, *, batch=128, actor="Researcher"):
    return advance_candidate_index(
        project,expected_revision=proposal["revision"],
        generation_id=proposal["generation_id"],actor=actor,
        confirmed=True,max_records=batch)


def table(project, query):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(query).fetchall()


def test_index_preview_empty_is_readonly_and_requires_explicit_authorisation(project_fixture):
    project,_,_=project_fixture
    source(project_fixture)
    before = project.database_path.read_bytes()
    preview=preview_candidate_index(project)
    assert preview["status"]=="empty"
    assert preview["source_records"]==1
    assert not preview["index_ready"]
    assert preview["global_unique_publications"] is None
    assert not preview["candidate_discovery_complete"]
    assert before == project.database_path.read_bytes()
    with pytest.raises(CandidateIndexError) as exc:
        start_candidate_index(project,expected_revision=preview["revision"],
                              actor="Researcher",confirmed=False)
    assert exc.value.code=="candidate_index_confirmation_required"
    assert table(project,"SELECT COUNT(*) FROM candidate_index_records")==[(0,)]


def test_two_source_same_supplement_hashes_are_hints_not_merges(project_fixture):
    project,run,_=project_fixture
    a=source(project_fixture,number=1)
    b=source(project_fixture,source_name="wos",number=2)
    started=begin(project)
    finished=step(project,started)
    assert finished["committed_records"]==2
    assert finished["generation_completed"] and finished["index_ready"]
    assert finished["processed_records"]==2
    assert finished["unsupported_records"]==0
    assert finished["indexed_keys"]>=4
    assert finished["source_query_executed"] is False
    assert finished["global_unique_publications"] is None
    assert finished["deduplication_complete"] is False
    with closing(sqlite3.connect(project.database_path)) as db:
        rows=db.execute("SELECT field,value_sha256 FROM candidate_index_keys "
                        "WHERE retrieval_id=? ORDER BY field",(a,)).fetchall()
        other=db.execute("SELECT field,value_sha256 FROM candidate_index_keys "
                         "WHERE retrieval_id=? ORDER BY field",(b,)).fetchall()
        contents=str(db.execute("SELECT * FROM candidate_index_state").fetchall()) + (
                 str(db.execute("SELECT * FROM candidate_index_records").fetchall()) +
                 str(db.execute("SELECT * FROM candidate_index_keys").fetchall()))
        assert any(field=="doi" for field,_ in rows)
        assert dict(rows)["doi"]==dict(other)["doi"]
        assert dict(rows)["title"]==dict(other)["title"]
        assert len(rows[0][1])==64
        assert "Shared abstract" not in contents
        assert "PRIVATE_LICENSED_ABSTRACT" not in contents
        assert db.execute("SELECT COUNT(*) FROM publications").fetchone()[0]==0
    assert preview_candidate_index(project)["revision"]==finished["revision"]


def test_incremental_128_plus_three_preserves_resume_and_restart(project_fixture):
    project,run,historic=project_fixture
    for idx in range(131):
        source(project_fixture,source_name="wos",number=idx+1,
               run=historic if idx%2 else run)
    started=begin(project)
    partial=step(project,started)
    assert partial["committed_records"]==128
    assert not partial["index_ready"]
    assert partial["remaining_records"]==3
    assert partial["processed_records"]==128
    reopened=open_project(project.root)
    resumed=preview_candidate_index(reopened)
    assert resumed["revision"]==partial["revision"]
    assert resumed["running_sha256"]==partial["running_sha256"]
    finished=step(reopened,resumed)
    assert finished["committed_records"]==3
    assert finished["status"]=="ready"
    assert finished["remaining_records"]==0
    assert finished["processed_records"]==131
    with pytest.raises(CandidateIndexError) as exc:
        step(reopened,started)
    assert exc.value.code=="candidate_index_stale"
    with pytest.raises(CandidateIndexError) as exc:
        step(reopened,finished)
    assert exc.value.code=="candidate_index_no_work"
    assert table(project,"SELECT COUNT(*) FROM candidate_index_records")==[(131,)]


def test_failed_transaction_does_not_commit_partial_index_or_audit(project_fixture):
    project,_,_=project_fixture
    source(project_fixture,number=1)
    source(project_fixture,source_name="wos",number=2)
    started=begin(project)
    before=table(project,"SELECT * FROM audit_events")
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("CREATE TRIGGER synthetic_abort_candidate_key "
                   "BEFORE INSERT ON candidate_index_keys "
                   "BEGIN SELECT RAISE(ABORT,'simulated index failure'); END")
    with pytest.raises(CandidateIndexError):
        step(project,started)
    assert table(project,"SELECT COUNT(*) FROM candidate_index_records")==[(0,)]
    assert table(project,"SELECT COUNT(*) FROM candidate_index_keys")==[(0,)]
    assert table(project,"SELECT * FROM audit_events")==before
    assert preview_candidate_index(project)["revision"]==started["revision"]
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("DROP TRIGGER synthetic_abort_candidate_key")
    assert step(project,started)["status"]=="ready"


def test_new_source_invalidates_finished_index_atomically(project_fixture):
    project,_,_=project_fixture
    rid=source(project_fixture)
    completed=step(project,begin(project))
    old_epoch=completed["source_epoch"]
    source(project_fixture,number=99)
    stale=preview_candidate_index(project)
    assert stale["status"]=="stale"
    assert stale["source_epoch"]==old_epoch+1
    assert stale["index_ready"] is False
    assert stale["remaining_records"] is None
    with pytest.raises(CandidateIndexError) as exc:
        step(project,completed)
    assert exc.value.code=="candidate_index_stale"
    rebuilt=begin(project)
    assert rebuilt["status"]=="building" and rebuilt["processed_records"]==0
    assert rebuilt["generation_id"]!=completed["generation_id"]
    assert step(project,rebuilt)["source_records"]==2


def test_source_change_during_build_requires_explicit_new_generation(project_fixture):
    project,_,_=project_fixture
    for n in (1,2):
        source(project_fixture,number=n)
    partial=step(project,begin(project),batch=1)
    source(project_fixture,number=3)
    stale=preview_candidate_index(project)
    assert stale["status"]=="stale" and stale["processed_records"]==1
    with pytest.raises(CandidateIndexError) as exc:
        step(project,partial,batch=1)
    assert exc.value.code=="candidate_index_stale"
    assert table(project,"SELECT COUNT(*) FROM candidate_index_records")==[(1,)]
    restarted=begin(project)
    assert restarted["status"]=="building"
    final=step(project,restarted)
    assert final["processed_records"]==3 and final["index_ready"]


def test_source_metadata_update_triggers_stale_without_audit_deletion(project_fixture):
    project,_,_=project_fixture
    rid=source(project_fixture)
    completed=step(project,begin(project))
    before=table(project,"SELECT COUNT(*) FROM audit_events")[0][0]
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_retrievals SET retrieved_at_utc=? "
                   "WHERE retrieval_id=?",(project.created_at_utc,rid))
    state=preview_candidate_index(project)
    assert state["status"]=="stale"
    assert state["source_epoch"]==completed["source_epoch"]+1
    assert table(project,"SELECT COUNT(*) FROM audit_events")[0][0]==before


def test_zero_source_index_has_defensible_complete_cache_not_complete_search(project_fixture):
    project,_,_=project_fixture
    started=begin(project)
    completed=step(project,started)
    assert completed["committed_records"]==0
    assert completed["index_ready"] is True
    assert completed["candidate_discovery_complete"] is False
    assert completed["global_unique_publications"] is None
    assert completed["verified_complete"] is False
    assert table(project,"SELECT COUNT(*) FROM candidate_index_records")==[(0,)]


def test_invalid_batch_parameters_and_wrong_generation_never_write(project_fixture):
    project,_,_=project_fixture
    source(project_fixture)
    started=begin(project)
    before=table(project,"SELECT * FROM audit_events")
    for bound in (0,129,-1,True,"100"):
        with pytest.raises(CandidateIndexError):
            step(project,started,batch=bound)
    with pytest.raises(CandidateIndexError) as exc:
        advance_candidate_index(project,expected_revision=started["revision"],
                                generation_id=uid(),actor="Researcher",
                                confirmed=True)
    assert exc.value.code=="candidate_index_stale"
    with pytest.raises(CandidateIndexError):
        advance_candidate_index(project,expected_revision=started["revision"],
                                generation_id=started["generation_id"],
                                actor="Researcher",confirmed=False)
    assert table(project,"SELECT * FROM audit_events")==before


def test_malformed_original_provider_source_rolls_back_entire_batch(project_fixture):
    project,_,_=project_fixture
    rid=source(project_fixture,number=3)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_retrievals SET original_metadata_json='{}' "
                   "WHERE retrieval_id=?",(rid,))
    started=begin(project)
    with pytest.raises(CandidateIndexError):
        step(project,started)
    assert preview_candidate_index(project)["status"]=="building"
    assert table(project,"SELECT COUNT(*) FROM candidate_index_records")==[(0,)]


def test_unsupported_source_remains_counted_without_fake_missing_candidates(project_fixture):
    project,_,_=project_fixture
    source(project_fixture,source_name="manual",number=1)
    finished=step(project,begin(project))
    assert finished["unsupported_records"]==1
    assert finished["processed_records"]==1
    assert finished["indexed_keys"]==0
    assert finished["candidate_discovery_complete"] is False


def test_cache_integrity_failure_is_visible_not_assumed_complete(project_fixture):
    project,_,_=project_fixture
    source(project_fixture)
    finished=step(project,begin(project))
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("DELETE FROM candidate_index_keys")
    with pytest.raises(CandidateIndexError) as exc:
        preview_candidate_index(project)
    assert exc.value.code=="candidate_index_unavailable"


def test_cache_state_is_hash_bound_to_consent_and_cannot_be_replayed(project_fixture):
    project,_,_=project_fixture
    source(project_fixture)
    first=preview_candidate_index(project)
    gen=begin(project)
    with pytest.raises(CandidateIndexError) as exc:
        start_candidate_index(project,expected_revision=first["revision"],
                              actor="Researcher",confirmed=True)
    assert exc.value.code=="candidate_index_stale"
    done=step(project,gen)
    assert done["generation_id"]==gen["generation_id"]
    assert done["revision"]!=gen["revision"]


def test_derived_index_never_prevents_original_source_deletion(project_fixture):
    """Source changes remain authoritative; cache is disposable, not a blocker."""
    project,_,_=project_fixture
    rid=source(project_fixture,number=1011)
    ready=step(project,begin(project))
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("DELETE FROM source_retrievals WHERE retrieval_id=?",(rid,))
    stale=preview_candidate_index(project)
    assert stale["status"]=="stale"
    assert stale["source_epoch"]==ready["source_epoch"]+1
    assert stale["index_ready"] is False
    assert stale["source_records"]==0
    assert table(project,"SELECT COUNT(*) FROM candidate_index_records")==[(0,)]
    assert table(project,"SELECT COUNT(*) FROM candidate_index_keys")==[(0,)]
    restarted=begin(project)
    assert step(project,restarted)["status"]=="ready"


def test_failed_source_write_does_not_invalidate_completed_cache(project_fixture):
    """The source trigger epoch belongs to the original source transaction."""
    project,_,_=project_fixture
    rid=source(project_fixture,number=1)
    ready=step(project,begin(project))
    with pytest.raises(sqlite3.IntegrityError):
        with closing(sqlite3.connect(project.database_path)) as db,db:
            db.execute("PRAGMA foreign_keys=ON")
            # Reject a duplicate original provider identity, not an index write.
            db.execute("INSERT INTO source_retrievals "
                       "SELECT ?,run_id,source_name,source_record_id,"
                       "retrieved_at_utc,original_metadata_json "
                       "FROM source_retrievals WHERE retrieval_id=?",(uid(),rid))
    now=preview_candidate_index(project)
    assert now["revision"]==ready["revision"]
    assert now["status"]=="ready"


def test_resumed_batch_and_more_probe_seek_by_primary_key(project_fixture):
    """Do not regress to nullable-cursor OR that rescans historical records."""
    from research_y import candidate_index_build as index
    project,_,_=project_fixture
    with closing(sqlite3.connect(project.database_path)) as db:
        for sql, args in ((index._RESUME_SQL, (uid(),128)),
                          (index._MORE_SQL,(uid(),))):
            plans=[row[3].upper() for row in db.execute(
                "EXPLAIN QUERY PLAN "+sql,args)]
            assert any("SEARCH" in detail for detail in plans), plans
            assert not any("SCAN SOURCE_RETRIEVALS" in detail for detail in plans), plans


def test_batch_progress_validation_does_not_rescan_all_cached_supported_rows(project_fixture):
    from research_y import candidate_index_build as index
    project,_,_=project_fixture
    for n in range(1301,1304):
        source(project_fixture,number=n)
    ready=step(project,begin(project))
    observed=[]
    with closing(sqlite3.connect(project.database_path)) as db:
        db.set_trace_callback(observed.append)
        raw=index._state(db)
        assert raw["processed_records"]==3
        assert not any("WHERE supported=0" in sql for sql in observed)
        assert not any("generation_id<>" in sql for sql in observed)
        assert any("WHERE retrieval_id=" in sql for sql in observed)
        observed.clear()
        fully_checked=index._state(db,full_cache_check=True)
        assert fully_checked["running_sha256"]==ready["running_sha256"]
        assert any("WHERE supported=0" in sql for sql in observed)
    assert preview_candidate_index(project)["index_ready"]


def test_full_status_check_detects_tampered_cached_support_count(project_fixture):
    project,_,_=project_fixture
    rid=source(project_fixture,number=1401)
    ready=step(project,begin(project))
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE candidate_index_records SET supported=0 "
                   "WHERE retrieval_id=?",(rid,))
    with pytest.raises(CandidateIndexError) as exc:
        preview_candidate_index(project)
    assert exc.value.code=="candidate_index_unavailable"
