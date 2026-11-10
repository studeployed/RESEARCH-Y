"""Real original SQLite project source/identity/worker scale smoke tests.

Only the separate performance workflow runs the 100,000-source workload.
These smaller cases validate the semantics without raising CI time budgets.
"""
from __future__ import annotations

import pytest

from scripts.benchmark_original_project import (
    run, _seed, _rid, materialise_remaining_fixture, RUN,
)
from research_y.projects import create_project,open_project
from research_y import publication_identity as identity
from contextlib import closing
import json
import sqlite3


def test_original_project_retains_independent_provisional_identities():
    report=run(records=512,selected=128,matched=32,
               worker_timeout_seconds=35)
    assert report["synthetic_original_source_records"]==512
    assert report["selected_run_source_records"]==128
    assert report["historical_run_source_records"]==384
    assert report["original_provisional_identities"]==64
    assert report["unmaterialised_source_records"]==448
    assert report["matched_source_pairs"]==32
    assert report["restored_row_counts_match"] is True
    assert report["original_sqlite_integrity_check"]=="ok"
    assert report["original_foreign_key_check"]=="ok"
    assert report["worker"]["completed"] is True
    assert report["worker"]["candidate_count"]==32
    assert report["worker"]["response_rows"]==20
    assert report["worker"]["poll_count"]>=1
    assert report["worker"]["global_unique_publications"] is None
    assert report["worker"]["deduplication_complete"] is False
    assert report["no_network_requests"] is True
    assert report["global_unique_publications"] is None
    assert report["deduplication_complete"] is False
    assert report["source_retrieval_verified"] is False
    assert report["full_AT_22_acceptance"] is False
    assert report["all_100k_source_records_materialised"] is False
    assert report["native_browser_rendering_measured"] is False
    assert report["aggregate_original_database_size_bytes"]>0
    assert report["observed_parent_peak_rss_bytes"] is None or (
        report["observed_parent_peak_rss_bytes"]>0)


@pytest.mark.parametrize("arguments",[
    dict(records=10,selected=128,matched=32),
    dict(records=100001,selected=512,matched=64),
    dict(records=512,selected=1024,matched=32),
    dict(records=512,selected=127,matched=32),
    dict(records=512,selected=128,matched=65),
    dict(records=512,selected=510,matched=3),
    dict(records=512,selected=128,matched=0),
    dict(records=512,selected=128,matched=32,worker_timeout_seconds=0),
])
def test_original_source_benchmark_refuses_unbounded_input(arguments):
    with pytest.raises(ValueError):
        run(**arguments)


def test_one_matching_pair_has_no_invented_second_page():
    report=run(records=512,selected=128,matched=1,
               worker_timeout_seconds=35)
    assert report["matched_source_pairs"]==1
    assert report["original_provisional_identities"]==2
    assert report["unmaterialised_source_records"]==510
    assert report["timings_ms"]["second_source_backed_candidate_page_ms"] is None
    assert report["worker"]["candidate_count"]==1
    assert report["worker"]["response_rows"]==1
    assert report["worker"]["completed"] is True
    assert report["global_unique_publications"] is None
    assert report["full_AT_22_acceptance"] is False


def test_all_original_records_have_independent_audited_provisional_identities():
    report=run(records=512,selected=128,matched=2,
               worker_timeout_seconds=35,materialise_all=True)
    assert report["synthetic_original_source_records"]==512
    assert report["original_provisional_identities"]==512
    assert report["unmaterialised_source_records"]==0
    assert report["matched_source_pairs"]==2
    assert report["restored_row_counts_match"] is True
    assert report["original_sqlite_integrity_check"]=="ok"
    assert report["original_foreign_key_check"]=="ok"
    assert report["fixture_materialisation_resume"][
        "independently_reopened_before_resume"] is True
    assert report["fixture_materialisation_resume"][
        "all_original_audit_links_written"] is True
    assert report["fixture_materialisation_resume"][
        "production_gui_materialisation_path_exercised"] is False
    assert report["researcher_confirmed_materialisation_workflow_tested"] is False
    assert report["worker"]["completed"] is True
    assert report["worker"]["candidate_count"]==2
    assert report["worker"]["response_rows"]==2
    assert report["full_AT_22_acceptance"] is False
    assert report["all_100k_source_records_materialised"] is False
    assert report["global_unique_publications"] is None


@pytest.mark.parametrize("materialise_all", [False, True])
def test_single_run_original_sources_preserve_in_run_candidate_pairs(materialise_all):
    report=run(records=512,selected=512,matched=2,
               worker_timeout_seconds=35,materialise_all=materialise_all)
    assert report["synthetic_original_source_records"]==512
    assert report["selected_run_source_records"]==512
    assert report["historical_run_source_records"]==0
    assert report["original_provisional_identities"]==(
        512 if materialise_all else 4)
    assert report["selected_run_provisional_identities"]==(
        512 if materialise_all else 4)
    assert report["unmaterialised_source_records"]==(
        0 if materialise_all else 508)
    assert report["matched_source_pairs"]==2
    assert report["restored_row_counts_match"] is True
    assert report["original_sqlite_integrity_check"]=="ok"
    assert report["original_foreign_key_check"]=="ok"
    assert report["worker"]["completed"] is True
    assert report["worker"]["candidate_count"]==2
    assert report["worker"]["response_rows"]==2
    assert report["global_unique_publications"] is None
    assert report["source_retrieval_verified"] is False
    assert report["deduplication_complete"] is False
    assert report["full_AT_22_acceptance"] is False
    assert report["all_100k_sources_in_selected_run"] is False


def test_single_run_matching_keys_are_two_original_cross_provider_records(tmp_path):
    project=create_project(tmp_path,"Same-run cross-source source fixture")
    assert _seed(project,512,512,2)==4
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM source_retrievals WHERE run_id<>?",
            (RUN,)
        ).fetchone()==(0,)
        assert db.execute(
            "SELECT COUNT(*) FROM publications"
        ).fetchone()==(4,)
        for i in range(2):
            originals=db.execute(
                "SELECT r.source_name,r.original_metadata_json,p.publication_id "
                "FROM source_retrievals r "
                "JOIN publication_retrievals p ON p.retrieval_id=r.retrieval_id "
                "WHERE r.retrieval_id IN (?,?) ORDER BY r.retrieval_id",
                (_rid(i),_rid(i+2))
            ).fetchall()
            assert len(originals)==2
            assert {row[0] for row in originals}=={"pubmed","wos"}
            assert len({row[2] for row in originals})==2
            dois=set()
            for source,raw,_ in originals:
                record=json.loads(raw)["record"]
                value=record["identifiers"]["doi"]
                dois.add(value[0] if source=="pubmed" else value)
            assert len(dois)==1


def test_fixture_link_batch_failure_rolls_back_and_reopens_without_duplicates(tmp_path):
    project=create_project(tmp_path,"Materialisation rollback fixture")
    assert _seed(project,512,128,1)==2
    failing_id=_rid(5)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute(
            "CREATE TRIGGER synthetic_fail_identity "
            "BEFORE INSERT ON publication_retrievals "
            "WHEN NEW.retrieval_id='"+failing_id+"' "
            "BEGIN SELECT RAISE(ABORT,'injected fixture failure'); END"
        )
    with pytest.raises(sqlite3.DatabaseError):
        materialise_remaining_fixture(
            project,batch_size=32,max_batches=1
        )
    with closing(sqlite3.connect(project.database_path)) as db:
        before=db.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
        linked=db.execute("SELECT COUNT(*) FROM publication_retrievals").fetchone()[0]
        audited=db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
            (identity.IDENTITY_EVENT,)
        ).fetchone()[0]
        assert (before,linked,audited)==(2,2,2)
        assert db.execute("PRAGMA integrity_check").fetchone()==("ok",)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("DROP TRIGGER synthetic_fail_identity")
    recovered=open_project(project.root)
    first=materialise_remaining_fixture(
        recovered,batch_size=32,max_batches=1
    )
    assert first["newly_materialised"]==31
    assert first["bounded_transactions"]==1
    assert first["exhausted_sources"] is False
    rest=materialise_remaining_fixture(
        recovered,batch_size=32,
        after_id=first["last_committed_retrieval_id"],
    )
    assert rest["exhausted_sources"] is True
    assert 2+first["newly_materialised"]+rest["newly_materialised"]==512
    after=open_project(project.root)
    with closing(sqlite3.connect(after.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM publications").fetchone()==(512,)
        assert db.execute("SELECT COUNT(*) FROM publication_retrievals").fetchone()==(512,)
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                          (identity.IDENTITY_EVENT,)).fetchone()==(512,)
    no_replay=materialise_remaining_fixture(after,batch_size=256)
    assert no_replay["newly_materialised"]==0
    assert no_replay["exhausted_sources"] is True
    with closing(sqlite3.connect(after.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                          (identity.IDENTITY_EVENT,)).fetchone()==(512,)


def test_materialise_fixture_refuses_unsafe_cursor_and_batch_limits(tmp_path):
    project=create_project(tmp_path,"Bounded materialisation guard")
    for kwargs in (
        dict(batch_size=0),dict(batch_size=513),dict(batch_size=True),
        dict(max_batches=0),dict(max_batches=1001),
        dict(after_id="not-a-valid-uuid"),dict(after_id=12),
    ):
        with pytest.raises(ValueError):
            materialise_remaining_fixture(project,**kwargs)
