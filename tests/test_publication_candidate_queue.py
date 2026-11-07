"""Offline, disk-backed project-spanning exact-key candidate queue regressions."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import sqlite3
from uuid import uuid4

import pytest

from research_y import publication_identity as identity
from research_y import publication_candidates as candidates
from research_y import publication_candidate_queue as queue
from research_y.application_commands import (
    ApplicationCommand, ApplicationCommandError, execute_command,
)
from research_y.projects import create_project, open_project


def uid():
    return str(uuid4())


@pytest.fixture
def project_runs(tmp_path):
    project = create_project(tmp_path, "Synthetic candidate discovery")
    run, historical, version = uid(), uid(), uid()
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (version, 1, project.created_at_utc, "{}"))
        for idx, label in enumerate(("g1", "g2")):
            db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                       (version, label, label, idx))
        for run_id in (run, historical):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id, version, project.created_at_utc, "incomplete", None))
            for label in ("g1", "g2"):
                for source in ("pubmed", "wos"):
                    db.execute(
                        "INSERT INTO source_queries VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (uid(), run_id, version, label, source,
                         '"ECMO"[All Fields]' if source=="pubmed"
                         else 'TS=("ECMO")', "{}", None, "pending", None))
    return project, run, historical


def insert(ctx, *, source="pubmed", number=1, title="Abstract title",
           doi=None, run=None, materialise=True,
           abstract="SECRET ABSTRACT MUST NOT BE SHOWN"):
    project, active, _ = ctx
    run_id = active if run is None else run
    rid = uid()
    src_id = str(number) if source == "pubmed" else (
        "WOS:" + str(number) if source == "wos" else str(number))
    record = dict(title=title)
    if source == "pubmed":
        record.update(pmid=src_id, abstract_sections=[{"text":abstract}],
                      identifiers={"doi":[doi or "10.7777/"+str(number)]},
                      publication_types=["Conference Abstract"])
        payload={"source":"NCBI PubMed EFetch XML", "record":record,
                 "rights_review_required_for_abstract_redistribution":True}
    elif source == "wos":
        record.update(uid=src_id, identifiers={"doi":doi or "10.7777/"+str(number)},
                      types=["Conference Abstract"])
        payload={"provider":"wos_starter","database":"WOS","record":record,
                 "rights_status":"licence_review_required"}
    else:
        payload={"source":"manual_import","record":record,"rights_status":"unknown"}
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (rid,run_id,source,src_id,project.created_at_utc,identity._json(payload)))
        if source in ("pubmed","wos"):
            for group in ("g1","g2"):
                qid=db.execute("SELECT query_id FROM source_queries WHERE run_id=? "
                               "AND source_name=? AND group_id=?",
                               (run_id,source,group)).fetchone()[0]
                db.execute("INSERT INTO query_retrievals VALUES(?,?,?,?)",
                           (qid,rid,run_id,source))
    if materialise:
        identity.materialise_retrieval(project,rid,actor="Fixture")
    return rid


def read(ctx, **kwargs):
    return queue.read_candidate_queue(ctx[0],ctx[1],**kwargs)


def audit(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute("SELECT event_id,event_type,details_json FROM audit_events "
                          "ORDER BY event_id").fetchall()


def pair(ctx, a, b):
    return candidates.read_candidate(ctx[0],a,b)


def test_project_exact_key_index_is_readonly_and_doi_not_a_merge(project_runs):
    project, _, _ = project_runs
    a=insert(project_runs,source="pubmed",number=101,title="First abstract",
             doi="10.7777/shared-container")
    b=insert(project_runs,source="wos",number=102,title="Second abstract",
             doi="10.7777/shared-container")
    before=sha256(project.database_path.read_bytes()).hexdigest()
    page=read(project_runs)
    assert page["candidate_pair_total"]==1
    assert page["rows"][0]["retrieval_ids"]==list(sorted((a,b)))
    assert page["rows"][0]["matched_exact_fields"]==["doi"]
    assert page["rows"][0]["candidate_status"]=="review_required"
    assert page["rows"][0]["pair_already_associated"] is False
    assert page["rows"][0]["both_in_selected_run"] is True
    assert page["global_unique_publications"] is None
    assert page["candidate_discovery_complete"] is False
    assert not page["verified_complete"] and page["no_network_requests"]
    assert "SECRET ABSTRACT" not in repr(page)
    assert before==sha256(project.database_path.read_bytes()).hexdigest()


def test_20_row_keyset_paging_and_restart_without_silent_truncation(project_runs):
    for i in range(1,24):
        insert(project_runs,source="pubmed",number=100+i,title="Title "+str(i),
               doi="10.9000/unique"+str(i))
        insert(project_runs,source="wos",number=200+i,title="Title "+str(i),
               doi="10.9000/unique"+str(i))
    first=read(project_runs)
    assert first["candidate_pair_total"]==23
    assert len(first["rows"])==20 and first["has_more"]
    cursor=tuple(first["next_after_pair"])
    second=queue.read_candidate_queue(
        open_project(project_runs[0].root),project_runs[1],
        after_pair=cursor,expected_revision=first["revision"])
    assert len(second["rows"])==3 and not second["has_more"]
    all_pairs={tuple(r["retrieval_ids"]) for r in first["rows"]+second["rows"]}
    assert len(all_pairs)==23
    assert all(r["matched_exact_fields"]==["doi","title"]
               for r in first["rows"]+second["rows"])
    assert first["revision"]==second["revision"]


def test_historical_project_sources_are_visible_but_review_permission_scoped(project_runs):
    project,run,historical=project_runs
    selected=insert(project_runs,number=301,title="Same across runs",
                    doi="10.9000/cross")
    old=insert(project_runs,source="wos",number=302,title="Same across runs",
               doi="10.9000/cross",run=historical)
    insert(project_runs,number=303,title="Old-only",doi="10.9000/old",
           run=historical)
    insert(project_runs,source="wos",number=304,title="Old-only",
           doi="10.9000/old",run=historical)
    listing=read(project_runs)
    assert listing["candidate_pair_total"]==1
    entry=listing["rows"][0]
    assert set(entry["retrieval_ids"])=={selected,old}
    assert entry["both_in_selected_run"] is False
    assert {s["run_id"] for s in entry["sources"]}=={run,historical}
    assert listing["project_source_records"]==4
    assert "historical_cross_run_pairs_require_separate_review" in listing["warnings"]


def test_prior_rejected_pair_with_no_matching_fields_survives_queue_rebuild(project_runs):
    project,_,_=project_runs
    a=insert(project_runs,number=401,title="A",doi="10.9111/a")
    b=insert(project_runs,source="wos",number=402,title="B",doi="10.9111/b")
    assert read(project_runs)["candidate_pair_total"]==0
    candidate=pair(project_runs,a,b)
    decided=candidates.decide_candidate(
        project,a,b,expected_revision=candidate.revision,
        decision="rejected_match",actor="Researcher",
        evidence="Two different synthetic conference abstracts",
        acknowledged_warnings=candidate.warnings,
        decision_confirmed=True)
    assert decided.status=="rejected_match"
    page=read(project_runs)
    assert page["candidate_pair_total"]==1 and page["prior_receipt_pairs"]==1
    row=page["rows"][0]
    assert row["matched_exact_fields"]==[]
    assert row["candidate_status"]=="rejected_match"
    assert row["prior_decisions_recorded"]==1
    assert row["last_decision_event_id"] is not None
    assert "Two different synthetic" not in str(page)


def test_unmaterialised_and_unsupported_records_are_disclosed(project_runs):
    insert(project_runs,number=501,materialise=False)
    insert(project_runs,source="manual",number=502)
    result=read(project_runs)
    assert result["unmaterialised_project_records"]==1
    assert result["unsupported_project_records"]==1
    assert result["project_source_records"]==2
    assert result["candidate_pair_total"]==0
    assert result["exhaustive_duplicate_discovery"] is False


def test_stale_cursor_refuses_changed_selected_run_and_historical_evidence(project_runs):
    project,run,historical=project_runs
    a=insert(project_runs,number=601)
    b=insert(project_runs,source="wos",number=601)
    first=read(project_runs)
    old=first["revision"]
    cursor=tuple(first["rows"][0]["retrieval_ids"])
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE search_runs SET status='failed' WHERE run_id=?",
                   (historical,))
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs,after_pair=cursor,expected_revision=old)
    assert exc.value.code=="candidate_queue_stale"
    updated=read(project_runs)
    assert updated["revision"]!=old
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_queries SET status='failed' WHERE run_id=?",
                   (run,))
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs,after_pair=cursor,
             expected_revision=updated["revision"])
    assert exc.value.code=="candidate_queue_stale"


@pytest.mark.parametrize("cursor", [
    ("nonsense","different"), ("a"*36,"b"*36),
    ["00000000-0000-0000-0000-000000000001",
     "00000000-0000-0000-0000-000000000002"],
    ("00000000-0000-0000-0000-000000000002",
     "00000000-0000-0000-0000-000000000001"),
])
def test_invalid_cursor_and_missing_revision_fail_closed(project_runs,cursor):
    with pytest.raises(queue.CandidateQueueError):
        read(project_runs,after_pair=cursor)
    with pytest.raises(queue.CandidateQueueError):
        read(project_runs,after_pair=cursor,expected_revision="a"*64)


def test_refuses_over_limit_instead_of_partial_results(project_runs,monkeypatch):
    for n in range(701,704):
        insert(project_runs,source="pubmed",number=n,title="Every same",
               doi="10.7000/same")
    monkeypatch.setattr(queue,"MAX_PAIR_CANDIDATES",1)
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs)
    assert exc.value.code=="candidate_queue_over_limit"
    monkeypatch.setattr(queue,"MAX_PROJECT_RECORDS",2)
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs)
    assert exc.value.code=="candidate_queue_over_limit"


def test_corrupt_original_source_identity_is_not_silently_indexed(project_runs):
    project,_,_=project_runs
    r=insert(project_runs,number=801)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_retrievals SET original_metadata_json='{}' "
                   "WHERE retrieval_id=?", (r,))
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs)
    assert exc.value.code=="candidate_queue_unavailable"


def test_command_rejects_forged_query_fields_and_bad_cursor(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=901)
    b=insert(project_runs,source="wos",number=901)
    out=execute_command(ApplicationCommand.for_project(
        project,"candidate_queue_page",run_id=run))
    assert out["candidate_pair_total"]==1
    for extras in (
        {"pilot_api_key":"SECRET_KEY"},
        {"candidate_actor":"Forged"},
        {"publication_view_id":uid()},
        {"candidate_queue_cursor":(a,b)},
        {"candidate_queue_cursor":list(sorted((a,b))),
         "candidate_queue_revision":out["revision"]},
        {"candidate_queue_revision":"nonsense"},
    ):
        with pytest.raises(ApplicationCommandError):
            ApplicationCommand.for_project(
                project,"candidate_queue_page",run_id=run,**extras)
    valid=ApplicationCommand.for_project(
        project,"candidate_queue_page",run_id=run,
        candidate_queue_cursor=tuple(out["rows"][0]["retrieval_ids"]),
        candidate_queue_revision=out["revision"])
    nextpage=execute_command(valid)
    assert nextpage["rows"]==[] and not nextpage["has_more"]
    assert "SECRET" not in repr(out)
