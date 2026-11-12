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


def test_trusted_host_queue_selection_routes_only_current_run_pair(project_runs):
    project,run,historical=project_runs
    a=insert(project_runs,source="pubmed",number=1001,
             title="Same title",doi="10.9000/one")
    b=insert(project_runs,source="wos",number=1002,
             title="Same title",doi="10.9000/one")
    from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={"runs":[],"report":None,"exports":[]}
    flow._operation=lambda name,**kwargs: execute_command(
        ApplicationCommand.for_project(project,name,**kwargs))
    try:
        with pytest.raises(ProjectFlowError):
            flow.inspect_queue_candidate_pair(left=a,right=b,revision="a"*64)
        state=flow.inspect_candidate_queue()
        listing=state["candidate_queue"]
        assert listing["candidate_pair_total"]==1
        with pytest.raises(ProjectFlowError):
            flow.inspect_queue_candidate_pair(
                left=uid(),right=b,revision=listing["revision"])
        chosen=flow.inspect_queue_candidate_pair(
            left=a,right=b,revision=listing["revision"])
        offer=chosen["candidate_offer"]
        assert set(offer["retrieval_ids"])=={a,b}
        assert offer["automatic_match_allowed"] is False
        assert chosen["publication_page"] is not None
        with pytest.raises(ProjectFlowError):
            flow.confirm_candidate_decision(
                decision="confirmed_match",move_retrieval_id=a,
                actor="Researcher",evidence="Reviewed both metadata",
                acknowledged=False)
        resolved=flow.confirm_candidate_decision(
            decision="rejected_match",move_retrieval_id=None,
            actor="Researcher",evidence="Two distinct conference abstracts",
            acknowledged=True)
        assert resolved["candidate_last_outcome"]["action"]=="rejected_match"
        assert resolved["candidate_last_outcome"]["verified_audit_event_id"]>0
        assert resolved["candidate_queue"] is None
        assert read(project_runs)["rows"][0]["candidate_status"]=="rejected_match"
    finally:
        flow.close()


def test_trusted_host_refuses_cross_run_review_and_invalidates_page_on_change(project_runs):
    project,run,historical=project_runs
    a=insert(project_runs,number=1101,title="Across all runs",
             doi="10.9000/both")
    old=insert(project_runs,source="wos",number=1102,
               title="Across all runs",doi="10.9000/both",run=historical)
    from tools.gui_feasibility.real_project_flow import RealProjectFlow,ProjectFlowError
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={"runs":[],"report":None,"exports":[]}
    flow._operation=lambda name,**kwargs: execute_command(
        ApplicationCommand.for_project(project,name,**kwargs))
    try:
        first=flow.inspect_candidate_queue()["candidate_queue"]
        assert first["rows"][0]["both_in_selected_run"] is False
        with pytest.raises(ProjectFlowError):
            flow.inspect_queue_candidate_pair(
                left=a,right=old,revision=first["revision"])
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE search_runs SET status='failed' WHERE run_id=?",
                       (historical,))
        with pytest.raises(ProjectFlowError):
            flow.inspect_candidate_queue(
                cursor=tuple(first["rows"][0]["retrieval_ids"]),
                revision=first["revision"])
    finally:
        flow.close()


@pytest.mark.parametrize("decision", ["confirmed_match", "rejected_match"])
def test_explicit_cross_run_review_keeps_originals_and_only_moves_selected_source(project_runs, decision):
    from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
    from research_y.publication_review_gui import preview_candidate_reversal, confirm_candidate_reversal
    from research_y.publication_results import read_publication_page

    project, run_id, other_run = project_runs
    current = insert(project_runs, number=301, title="Fixture", doi="10.7777/same")
    other = insert(project_runs, source="wos", number=302, run=other_run, title="Fixture", doi="10.7777/same")
    with closing(sqlite3.connect(project.database_path)) as db:
        memberships = db.execute("SELECT * FROM query_retrievals ORDER BY query_id").fetchall()
        prior_links = dict(db.execute("SELECT retrieval_id,publication_id FROM publication_retrievals"))
    with closing(RealProjectFlow(selected_root=project.root, selected_parent=project.root.parent)) as flow:
        flow.project, flow.selected_run_id = project, run_id
        flow.snapshot = {"runs": [], "report": None, "exports": []}
        listing = flow.inspect_candidate_queue()["candidate_queue"]
        offer = flow.inspect_queue_candidate_pair(left=current, right=other, revision=listing["revision"],
                                                  cross_run=True)["candidate_offer"]
        assert offer["cross_run"] and {source["run_id"] for source in offer["sources"]} == {run_id, other_run}
        args = dict(decision=decision, actor="Fixture", evidence="Compared original locators", acknowledged=True,
                    move_retrieval_id=current if decision == "confirmed_match" else None)
        with pytest.raises(ProjectFlowError, match="publication_review_stale"):
            flow.confirm_candidate_decision(offer_revision="0"*64, **args)
        with pytest.raises(ProjectFlowError, match="publication_review_wrong_run"):
            flow.confirm_candidate_decision(**(args | {"decision": "confirmed_match", "move_retrieval_id": other}),
                                           offer_revision=offer["revision"])
        done = flow.confirm_candidate_decision(offer_revision=offer["revision"], **args)
        assert done["candidate_last_outcome"]["action"] == decision
    reopened = open_project(project.root)
    with closing(sqlite3.connect(reopened.database_path)) as db:
        assert db.execute("SELECT * FROM query_retrievals ORDER BY query_id").fetchall() == memberships
        links = dict(db.execute("SELECT retrieval_id,publication_id FROM publication_retrievals"))
    assert links[other] == prior_links[other]
    if decision == "confirmed_match":
        assert links[current] == links[other]
        revision = read_publication_page(reopened, run_id)["revision"]
        undo = preview_candidate_reversal(reopened, run_id, current, run_revision=revision)
        confirm_candidate_reversal(reopened, run_id, current, run_revision=revision,
                                   expected_revision=undo["revision"], actor="Fixture",
                                   evidence="Different publications", confirmed=True)
        with closing(sqlite3.connect(reopened.database_path)) as db:
            assert dict(db.execute("SELECT retrieval_id,publication_id FROM publication_retrievals")) == prior_links
    else:
        assert links == prior_links


def test_cross_run_decision_rechecks_run_under_writer_lock(project_runs, monkeypatch):
    from research_y import publication_review_gui as review
    from research_y.publication_results import read_publication_page

    project, run_id, other_run = project_runs
    current = insert(project_runs, number=310, title="Fixture")
    other = insert(project_runs, source="wos", number=311, title="Fixture", run=other_run)
    revision = read_publication_page(project, run_id)["revision"]
    offer = review.preview_candidate_review(project, run_id, current, other, run_revision=revision, cross_run=True)
    original = candidates.decide_candidate

    def change_unrelated_query(*args, **kwargs):
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("UPDATE source_queries SET status='failed' WHERE run_id=? AND source_name='wos'", (run_id,))
        return original(*args, **kwargs)

    monkeypatch.setattr(candidates, "decide_candidate", change_unrelated_query)
    with pytest.raises(review.PublicationReviewError, match="publication_review_stale"):
        review.record_candidate_review(project, run_id, current, other, run_revision=revision,
                                       expected_revision=offer["revision"], decision="confirmed_match",
                                       move_retrieval_id=current, actor="Fixture", evidence="Compared sources",
                                       warnings_acknowledged=True, confirmed=True, cross_run=True)
    assert len(set(pair(project_runs, current, other).publication_ids)) == 2


def test_large_historical_only_key_bucket_never_enumerates_historical_pairs():
    """3,000 identical older titles must not lead to 4.5 million comparisons."""
    selected=uid()
    old=uid()
    bucket=[f"historical-{n:05d}" for n in range(3000)]
    sources={rid:{"run_id":old} for rid in bucket}
    assert list(queue._bucket_pairs(bucket,sources,selected))==[]


def test_bucket_emits_only_selected_selected_and_selected_historical():
    selected, old=uid(), uid()
    current=["a","b"]
    historical=[f"old-{n:05d}" for n in range(100)]
    data={rid:{"run_id":selected} for rid in current}
    data.update({rid:{"run_id":old} for rid in historical})
    candidates_found=set(queue._bucket_pairs(current+historical,data,selected))
    assert len(candidates_found)==201
    assert ("a","b") in candidates_found
    assert all(any(data[rid]["run_id"]==selected for rid in pair)
               for pair in candidates_found)


def test_cross_run_dense_bucket_fails_at_explicit_pair_cap(project_runs,monkeypatch):
    project,run,historical=project_runs
    insert(project_runs,number=1199,title="Same",doi="10.8888/same")
    for n in range(1200,1203):
        insert(project_runs,source="wos",number=n,run=historical,
               title="Same",doi="10.8888/same")
    monkeypatch.setattr(queue,"MAX_PAIR_CANDIDATES",2)
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs)
    assert exc.value.code=="candidate_queue_over_limit"


def build_ready_index(ctx):
    """Explicitly construct the original durable v5 index in bounded batches."""
    from research_y.candidate_index_build import (
        preview_candidate_index, start_candidate_index, advance_candidate_index)
    project=ctx[0]
    preview=preview_candidate_index(project)
    running=start_candidate_index(
        project, expected_revision=preview["revision"],
        actor="Synthetic researcher",confirmed=True)
    for _ in range(1000):
        if running["status"]=="ready":
            break
        running=advance_candidate_index(
            project, expected_revision=running["revision"],
            generation_id=running["generation_id"],
            actor="Synthetic researcher",confirmed=True)
    assert running["status"]=="ready"
    return running


def test_ready_cache_preserves_exact_original_candidate_evidence(project_runs):
    project,run,historical=project_runs
    a=insert(project_runs,source="pubmed",number=1501,
             title="Two matching conference reports",doi="10.3333/shared")
    b=insert(project_runs,source="wos",number=1502,
             title="Two matching conference reports",doi="10.3333/shared")
    old=insert(project_runs,source="wos",number=1503,
               title="Two matching conference reports",doi="10.3333/shared",
               run=historical)
    insert(project_runs,number=1504,title="No matches",doi="10.3333/nope")
    original=read(project_runs)
    assert original["index_backend"]=="original_source_projection"
    assert original["candidate_pair_total"]==3
    ready=build_ready_index(project_runs)
    cached=read(project_runs)
    assert ready["source_records"]==4
    assert cached["index_backend"]=="verified_derived_keys_v5"
    assert cached["index_status"]=="ready"
    assert cached["index_generation_id"]==ready["generation_id"]
    assert cached["candidate_pair_total"]==original["candidate_pair_total"]
    for current, previous in zip(cached["rows"],original["rows"]):
        assert current==previous
    assert cached["global_unique_publications"] is None
    assert cached["candidate_discovery_complete"] is False
    assert cached["exact_rule_coverage_complete"] is True
    assert "SECRET ABSTRACT" not in repr(cached)


def test_ready_cache_preserves_historical_rejection_and_resume_page(project_runs):
    project,run,historical=project_runs
    a=insert(project_runs,number=1601,title="Alpha",doi="10.7777/alpha")
    b=insert(project_runs,source="wos",number=1602,title="Beta",doi="10.7777/beta")
    offer=pair(project_runs,a,b)
    candidates.decide_candidate(
        project,a,b,expected_revision=offer.revision,
        decision="rejected_match",actor="Researcher",
        evidence="Separate abstracts",
        acknowledged_warnings=offer.warnings,decision_confirmed=True)
    for i in range(21):
        insert(project_runs,number=1700+i,title="Exact "+str(i),
               doi="10.7777/exact"+str(i))
        insert(project_runs,source="wos",number=1800+i,title="Exact "+str(i),
               doi="10.7777/exact"+str(i))
    original=read(project_runs)
    assert original["candidate_pair_total"]==22
    build_ready_index(project_runs)
    first=read(project_runs)
    assert first["candidate_pair_total"]==22
    assert len(first["rows"])==20 and first["next_after_pair"] is not None
    later=queue.read_candidate_queue(
        open_project(project.root),run,
        after_pair=tuple(first["next_after_pair"]),
        expected_revision=first["revision"])
    assert len(later["rows"])==2 and not later["has_more"]
    current=first["rows"]+later["rows"]
    original_pairs=original["rows"]
    assert len({tuple(x["retrieval_ids"]) for x in current})==22
    assert any(x["candidate_status"]=="rejected_match"
               and x["matched_exact_fields"]==[] for x in current)
    assert first["revision"]==later["revision"]
    assert first["index_backend"]==later["index_backend"]=="verified_derived_keys_v5"


def test_source_mutation_downgrades_cache_and_rejects_old_cursor(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=1901,title="One",doi="10.2222/same")
    b=insert(project_runs,source="wos",number=1902,
             title="Two",doi="10.2222/same")
    build_ready_index(project_runs)
    old=read(project_runs)
    assert old["index_status"]=="ready"
    insert(project_runs,number=1903,title="Three",doi="10.2222/same")
    current=read(project_runs)
    assert current["index_status"]=="stale"
    assert current["index_backend"]=="original_source_projection"
    assert current["candidate_pair_total"]==3
    assert "derived_source_key_cache_not_ready_original_scan_used" in current["warnings"]
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs,after_pair=tuple(old["rows"][0]["retrieval_ids"]),
             expected_revision=old["revision"])
    assert exc.value.code=="candidate_queue_stale"
    build_ready_index(project_runs)
    newer=read(project_runs)
    assert newer["index_status"]=="ready"
    assert newer["candidate_pair_total"]==3


def test_unfinished_cache_never_suppresses_original_candidate_queue(project_runs):
    project,run,_=project_runs
    insert(project_runs,number=2001,title="Same title",doi="10.2222/same")
    insert(project_runs,source="wos",number=2002,
           title="Same title",doi="10.2222/same")
    from research_y.candidate_index_build import (
        preview_candidate_index,start_candidate_index,advance_candidate_index)
    first=preview_candidate_index(project)
    building=start_candidate_index(
        project,expected_revision=first["revision"],
        actor="Synthetic researcher",confirmed=True)
    assert read(project_runs)["index_status"]=="building"
    intermediate=advance_candidate_index(
        project,expected_revision=building["revision"],
        generation_id=building["generation_id"],
        actor="Synthetic researcher",confirmed=True,max_records=1)
    assert intermediate["status"]=="building"
    fallback=read(project_runs)
    assert fallback["candidate_pair_total"]==1
    assert fallback["index_backend"]=="original_source_projection"
    assert fallback["index_status"]=="building"


def test_cache_corruption_fails_closed_not_stale_fallback(project_runs):
    project,run,_=project_runs
    rid=insert(project_runs,number=2101)
    build_ready_index(project_runs)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("DELETE FROM candidate_index_keys WHERE retrieval_id=?",(rid,))
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs)
    assert exc.value.code=="candidate_queue_unavailable"


def test_cached_queue_source_keys_are_not_automatic_match_permissions(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=2201,title="Abstract one",
             doi="10.3333/conference")
    b=insert(project_runs,source="wos",number=2202,
             title="Abstract two",doi="10.3333/conference")
    build_ready_index(project_runs)
    response=read(project_runs)
    assert response["candidate_pair_total"]==1
    assert response["rows"][0]["matched_exact_fields"]==["doi"]
    assert response["rows"][0]["auto_merge_allowed"] is False
    assert response["rows"][0]["pair_already_associated"] is False
    assert {x["publication_id"] for x in response["rows"][0]["sources"]}.__len__()==2
    assert response["global_unique_publications"] is None


def test_trusted_host_index_consent_previews_and_reconciles_one_batch(project_runs):
    project,run,_=project_runs
    insert(project_runs,number=2301,title="Shared",doi="10.2323/one")
    insert(project_runs,source="wos",number=2302,title="Shared",doi="10.2323/one")
    from tools.gui_feasibility.real_project_flow import RealProjectFlow,ProjectFlowError
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={"runs":[],"report":None,"exports":[]}
    flow._operation=lambda name,**kwargs: execute_command(
        ApplicationCommand.for_project(project,name,**kwargs))
    try:
        with pytest.raises(ProjectFlowError,match="candidate_index_confirmation_required"):
            flow.confirm_candidate_index("Researcher")
        status=flow.inspect_candidate_index()
        assert status["candidate_index_state"]["status"]=="empty"
        assert status["candidate_index_offer"] is None
        offer=flow.offer_candidate_index("start")
        assert offer["candidate_index_offer"]["action"]=="start"
        begin=flow.confirm_candidate_index("Researcher")
        assert begin["candidate_index_offer"] is None
        assert begin["candidate_index_state"]["status"]=="building"
        assert begin["candidate_index_last_receipt"]["action"]=="start"
        offered=flow.offer_candidate_index("advance")
        assert offered["candidate_index_offer"]["processed_records"]==0
        completed=flow.confirm_candidate_index("Researcher")
        assert completed["candidate_index_state"]["status"]=="ready"
        assert completed["candidate_index_state"]["processed_records"]==2
        assert completed["candidate_index_last_receipt"]["action"]=="advance"
        refreshed=flow.inspect_candidate_queue()["candidate_queue"]
        assert refreshed["index_backend"]=="verified_derived_keys_v5"
        assert refreshed["candidate_pair_total"]==1
        with pytest.raises(ProjectFlowError,match="candidate_index_no_work"):
            flow.offer_candidate_index("advance")
        assert flow.state()["candidate_index_offer"] is None
    finally:
        flow.close()


def test_host_does_not_replay_lost_index_write_result(project_runs):
    project,run,_=project_runs
    insert(project_runs,number=2401)
    from tools.gui_feasibility.real_project_flow import RealProjectFlow,ProjectFlowError
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={"runs":[],"report":None,"exports":[]}
    call_count={"start":0}
    def intermittent(name,**kwargs):
        result=execute_command(ApplicationCommand.for_project(project,name,**kwargs))
        if name=="candidate_index_start":
            call_count["start"]+=1
            raise ProjectFlowError("worker_reply_lost_after_commit")
        return result
    flow._operation=intermittent
    try:
        flow.offer_candidate_index("start")
        with pytest.raises(ProjectFlowError,match="worker_reply_lost_after_commit"):
            flow.confirm_candidate_index("Researcher")
        assert call_count["start"]==1
        assert flow.state()["candidate_index_offer"] is None
        assert flow.state()["candidate_index_error"] is not None
        with pytest.raises(ProjectFlowError,match="candidate_index_confirmation_required"):
            flow.confirm_candidate_index("Researcher")
        state=flow.inspect_candidate_index()["candidate_index_state"]
        assert state["status"]=="building"
        assert state["generation_id"] is not None
        assert call_count["start"]==1
    finally:
        flow.close()


def test_index_command_allowlist_requires_single_use_revision_and_no_credentials(project_runs):
    project,run,_=project_runs
    insert(project_runs,number=2501)
    original=execute_command(ApplicationCommand.for_project(
        project,"candidate_index_preview"))
    for forged in (dict(run_id=run),
                   dict(candidate_index_confirmed=True),
                   dict(candidate_index_revision="a"*64),
                   dict(pilot_api_key="SECRET"),
                   dict(candidate_queue_cursor=(uid(),uid()))):
        with pytest.raises(ApplicationCommandError):
            ApplicationCommand.for_project(
                project,"candidate_index_preview",**forged)
    for forged in (dict(candidate_index_confirmed=False),
                   dict(candidate_index_generation=uid()),
                   dict(pilot_api_key="SECRET")):
        payload=dict(candidate_index_revision=original["revision"],
                     candidate_index_actor="Researcher",
                     candidate_index_confirmed=True)
        payload.update(forged)
        with pytest.raises(ApplicationCommandError):
            ApplicationCommand.for_project(
                project,"candidate_index_start",**payload)
    started=execute_command(ApplicationCommand.for_project(
        project,"candidate_index_start",
        candidate_index_revision=original["revision"],
        candidate_index_actor="Researcher",candidate_index_confirmed=True))
    with pytest.raises(ApplicationCommandError):
        execute_command(ApplicationCommand.for_project(
            project,"candidate_index_start",
            candidate_index_revision=original["revision"],
            candidate_index_actor="Researcher",candidate_index_confirmed=True))
    with pytest.raises(ApplicationCommandError):
        ApplicationCommand.for_project(
            project,"candidate_index_advance",
            candidate_index_revision=started["revision"],
            candidate_index_actor="Researcher",
            candidate_index_confirmed=True)
    assert "SECRET" not in repr(started)


def test_cached_index_skips_original_whole_project_field_reprojection(project_runs,monkeypatch):
    insert(project_runs,number=2601,title="Same cache field",doi="10.2626/shared")
    insert(project_runs,source="wos",number=2602,
           title="Same cache field",doi="10.2626/shared")
    build_ready_index(project_runs)
    def must_not_reproject_all_sources(*args,**kwargs):
        raise AssertionError("Whole-project original-field projection not used")
    monkeypatch.setattr(queue,"project_source",must_not_reproject_all_sources)
    answer=read(project_runs)
    assert answer["candidate_pair_total"]==1
    assert answer["index_backend"]=="verified_derived_keys_v5"


def test_cache_original_run_and_group_evidence_invalidates_navigation(project_runs):
    project,run,historical=project_runs
    insert(project_runs,number=2701,title="Same",doi="10.2727/shared")
    insert(project_runs,source="wos",number=2702,
           title="Same",doi="10.2727/shared")
    build_ready_index(project_runs)
    initial=read(project_runs)
    assert initial["index_backend"]=="verified_derived_keys_v5"
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE search_runs SET status='failed' WHERE run_id=?",
                   (historical,))
    updated=read(project_runs)
    assert updated["index_backend"]=="verified_derived_keys_v5"
    assert updated["index_generation_id"]==initial["index_generation_id"]
    assert updated["revision"]!=initial["revision"]
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs,after_pair=tuple(initial["rows"][0]["retrieval_ids"]),
             expected_revision=initial["revision"])
    assert exc.value.code=="candidate_queue_stale"


def test_forged_cached_pair_key_cannot_claim_false_exact_match(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=2801,title="Study one",doi="10.2828/first")
    b=insert(project_runs,source="wos",number=2802,
             title="Study two",doi="10.2828/second")
    build_ready_index(project_runs)
    assert read(project_runs)["candidate_pair_total"]==0
    with closing(sqlite3.connect(project.database_path)) as db,db:
        copied=db.execute(
            "SELECT value_sha256 FROM candidate_index_keys "
            "WHERE retrieval_id=? AND field='doi'",(a,)).fetchone()[0]
        db.execute("UPDATE candidate_index_keys SET value_sha256=? "
                   "WHERE retrieval_id=? AND field='doi'",(copied,b))
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs)
    assert exc.value.code=="candidate_queue_unavailable"


def test_host_resets_unsent_index_offer_when_selected_run_changes(project_runs):
    project,run,historical=project_runs
    from tools.gui_feasibility.real_project_flow import RealProjectFlow,ProjectFlowError
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={"runs":[{"run_id":run},{"run_id":historical}],
                   "report":None,"exports":[]}
    def dispatch(name,**kwargs):
        if name=="inspect":
            return {"snapshot":{"selected_run_id":kwargs.get("run_id"),
                                "runs":[{"run_id":run},{"run_id":historical}],
                                "report":{"status":"incomplete"},"exports":[]}}
        return execute_command(ApplicationCommand.for_project(project,name,**kwargs))
    flow._operation=dispatch
    try:
        flow.offer_candidate_index("start")
        assert flow.state()["candidate_index_offer"] is not None
        after=flow.select_run(historical)
        assert after["candidate_index_offer"] is None
        with pytest.raises(ProjectFlowError,match="candidate_index_confirmation_required"):
            flow.confirm_candidate_index("Researcher")
    finally:
        flow.close()


def build_ready_pairs(ctx):
    """Explicitly build the PR76 exact-key pair checkpoint to its safe boundary."""
    from research_y import candidate_pair_checkpoints as checkpoint
    project,run,_=ctx
    state=checkpoint.preview_pair_checkpoint(project,run)
    if not state["index_ready"]:
        build_ready_index(ctx)
        state=checkpoint.preview_pair_checkpoint(project,run)
    current=checkpoint.start_pair_checkpoint(
        project,run,expected_revision=state["revision"],
        actor="Fixture researcher",confirmed=True)
    for _ in range(1000):
        if current["status"]=="ready_keys_only":
            break
        current=checkpoint.advance_pair_checkpoint(
            project,run,generation_id=current["generation_id"],
            expected_revision=current["revision"],actor="Fixture researcher",
            confirmed=True)
    assert current["status"]=="ready_keys_only"
    return current


def reject_pair(ctx,a,b,*,evidence="Distinct abstract item, not a duplicate"):
    first=pair(ctx,a,b)
    result=candidates.decide_candidate(
        ctx[0],a,b,expected_revision=first.revision,
        decision="rejected_match",actor="Fixture researcher",evidence=evidence,
        acknowledged_warnings=first.warnings,decision_confirmed=True)
    assert result.status=="rejected_match"
    return result


def test_pair_checkpoint_queue_reconciles_receipt_only_and_key_pairs(project_runs):
    project,run,historical=project_runs
    same1=insert(project_runs,number=3101,title="Container alpha",
                 doi="10.3101/container")
    same2=insert(project_runs,source="wos",number=3102,
                 title="Container beta",doi="10.3101/container")
    distinct1=insert(project_runs,number=3103,title="Different abstract A",
                     doi="10.3103/first")
    distinct2=insert(project_runs,source="wos",number=3104,
                     title="Different abstract B",doi="10.3104/second")
    reject_pair(project_runs,distinct1,distinct2)
    # Neither matching metadata nor current publication identity can be
    # inferred from a prior explicit human decision.
    before=read(project_runs)
    assert before["candidate_pair_total"]==2
    expected={tuple(x["retrieval_ids"]):x for x in before["rows"]}
    assert expected[tuple(sorted((distinct1,distinct2)))]["matched_exact_fields"]==[]
    ready=build_ready_pairs(project_runs)
    assert ready["unique_pairs"]==1
    after=read(project_runs)
    assert after["index_backend"]=="verified_pair_checkpoint_v6"
    assert after["pair_index_status"]=="ready_keys_only"
    assert after["pair_index_generation_id"]==ready["generation_id"]
    assert after["receipt_only_pair_total"]==1
    assert after["prior_receipt_pairs"]==1
    assert after["candidate_pair_total"]==2
    assert {tuple(x["retrieval_ids"]):x for x in after["rows"]}==expected
    assert after["global_unique_publications"] is None
    assert after["candidate_discovery_complete"] is False
    assert after["deduplication_complete"] is False
    assert "SECRET ABSTRACT" not in repr(after)
    assert len({x["publication_id"] for x in after["rows"][0]["sources"]})==2


def test_pair_checkpoint_queue_fences_receipt_only_keyset_20_plus_five(project_runs):
    project,run,_=project_runs
    receipt_pairs=[]
    for n in range(2):
        a=insert(project_runs,number=3200+n,title="Unique reviewer A "+str(n),
                 doi="10.3200/left"+str(n))
        b=insert(project_runs,source="wos",number=3300+n,
                 title="Unique reviewer B "+str(n),doi="10.3300/right"+str(n))
        reject_pair(project_runs,a,b,evidence="Two different meeting presentations")
        receipt_pairs.append(tuple(sorted((a,b))))
    for n in range(23):
        insert(project_runs,number=3400+n,title="Matching abstract "+str(n),
               doi="10.3400/shared"+str(n))
        insert(project_runs,source="wos",number=3500+n,
               title="Matching abstract "+str(n),doi="10.3400/shared"+str(n))
    first_old=read(project_runs)
    assert first_old["candidate_pair_total"]==25
    built=build_ready_pairs(project_runs)
    assert built["unique_pairs"]==23
    first=read(project_runs)
    assert first["candidate_pair_total"]==25
    assert first["receipt_only_pair_total"]==2
    assert len(first["rows"])==20 and first["has_more"] is True
    second=queue.read_candidate_queue(
        open_project(project.root),run,
        after_pair=tuple(first["next_after_pair"]),
        expected_revision=first["revision"])
    assert len(second["rows"])==5 and second["has_more"] is False
    assert second["revision"]==first["revision"]
    all_pairs=[tuple(x["retrieval_ids"]) for x in first["rows"]+second["rows"]]
    assert len(all_pairs)==len(set(all_pairs))==25
    assert set(receipt_pairs)<=set(all_pairs)
    assert all_pairs==sorted(all_pairs)
    assert first["global_unique_publications"] is None


def test_pair_checkpoint_queue_stale_after_reviewer_decision_falls_back(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=3601,title="Same exact",doi="10.3601/exact")
    b=insert(project_runs,source="wos",number=3602,
             title="Same exact",doi="10.3601/exact")
    build_ready_pairs(project_runs)
    before=read(project_runs)
    assert before["index_backend"]=="verified_pair_checkpoint_v6"
    reject_pair(project_runs,a,b)
    fallback=read(project_runs)
    assert fallback["index_backend"]=="verified_derived_keys_v5"
    assert fallback["candidate_pair_total"]==1
    assert fallback["rows"][0]["candidate_status"]=="rejected_match"
    with pytest.raises(queue.CandidateQueueError) as err:
        read(project_runs,after_pair=tuple(before["rows"][0]["retrieval_ids"]),
             expected_revision=before["revision"])
    assert err.value.code=="candidate_queue_stale"


def test_pair_checkpoint_queue_old_cursor_stale_after_historical_run_change(project_runs):
    project,run,historical=project_runs
    insert(project_runs,number=3701,title="Same",doi="10.3701/same")
    insert(project_runs,source="wos",number=3702,
           title="Same",doi="10.3701/same",run=historical)
    build_ready_pairs(project_runs)
    before=read(project_runs)
    assert before["index_backend"]=="verified_pair_checkpoint_v6"
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE search_runs SET status='failed' WHERE run_id=?",
                   (historical,))
    after=read(project_runs)
    assert after["index_backend"]=="verified_pair_checkpoint_v6"
    assert after["pair_index_generation_id"]==before["pair_index_generation_id"]
    assert after["revision"]!=before["revision"]
    with pytest.raises(queue.CandidateQueueError) as err:
        read(project_runs,after_pair=tuple(before["rows"][0]["retrieval_ids"]),
             expected_revision=before["revision"])
    assert err.value.code=="candidate_queue_stale"


def test_pair_checkpoint_queue_corrupt_exact_fields_fail_closed(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=3801,title="Alpha",doi="10.3801/shared")
    b=insert(project_runs,source="wos",number=3802,
             title="Beta",doi="10.3801/shared")
    build_ready_pairs(project_runs)
    original=read(project_runs)
    assert original["rows"][0]["matched_exact_fields"]==["doi"]
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE candidate_pair_hints SET fields_mask=fields_mask|8 "
                   "WHERE run_id=?",(run,))
    with pytest.raises(queue.CandidateQueueError) as err:
        read(project_runs)
    assert err.value.code=="candidate_queue_unavailable"


def test_pair_checkpoint_queue_never_reenumerates_source_key_buckets(project_runs,monkeypatch):
    project,run,_=project_runs
    insert(project_runs,number=3901,title="Same",doi="10.3901/same")
    insert(project_runs,source="wos",number=3902,
           title="Same",doi="10.3901/same")
    build_ready_pairs(project_runs)
    def no_old_index(*args,**kwargs):
        raise AssertionError("Old complete source-key enumeration forbidden")
    monkeypatch.setattr(queue,"_original_index",no_old_index)
    monkeypatch.setattr(queue,"_cached_index",no_old_index)
    monkeypatch.setattr(queue,"_bucket_pairs",no_old_index)
    result=read(project_runs)
    assert result["index_backend"]=="verified_pair_checkpoint_v6"
    assert result["candidate_pair_total"]==1


def test_trusted_gui_pair_backend_and_selection_still_enforces_original_decision(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=4001,title="Different abstract I",
             doi="10.4001/shared")
    b=insert(project_runs,source="wos",number=4002,
             title="Different abstract II",doi="10.4001/shared")
    build_ready_pairs(project_runs)
    from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={"runs":[],"report":None,"exports":[]}
    flow._operation=lambda name,**kwargs: execute_command(
        ApplicationCommand.for_project(project,name,**kwargs))
    try:
        current=flow.inspect_candidate_queue()["candidate_queue"]
        assert current["index_backend"]=="verified_pair_checkpoint_v6"
        assert current["rows"][0]["both_in_selected_run"]
        selected=flow.inspect_queue_candidate_pair(
            left=a,right=b,revision=current["revision"])
        assert selected["candidate_offer"]["automatic_match_allowed"] is False
        with pytest.raises(ProjectFlowError):
            flow.confirm_candidate_decision(
                decision="confirmed_match",move_retrieval_id=a,
                actor="Researcher",evidence="Not acknowledged",
                acknowledged=False)
        outcome=flow.confirm_candidate_decision(
            decision="rejected_match",move_retrieval_id=None,
            actor="Researcher",evidence="Separate individual abstract titles",
            acknowledged=True)
        assert outcome["candidate_last_outcome"]["action"]=="rejected_match"
        assert outcome["candidate_queue"] is None
        # A match or rejection makes the derived pair generation stale
        # immediately; never keep displaying it as an unchanged cache.
        assert read(project_runs)["index_backend"]!="verified_pair_checkpoint_v6"
    finally:
        flow.close()


def test_pair_checkpoint_queue_preserves_confirmed_match_without_equal_fields(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=4101,title="Independent source title A",
             doi="10.4101/one")
    b=insert(project_runs,source="wos",number=4102,
             title="Independent source title B",doi="10.4102/two")
    candidate=pair(project_runs,a,b)
    decided=candidates.decide_candidate(
        project,a,b,expected_revision=candidate.revision,
        decision="confirmed_match",actor="Researcher",
        evidence="Same individual publication confirmed from original files",
        acknowledged_warnings=candidate.warnings,
        decision_confirmed=True,move_retrieval_id=a)
    assert decided.status=="confirmed_match"
    before=read(project_runs)
    assert before["candidate_pair_total"]==1
    assert before["rows"][0]["candidate_status"]=="confirmed_match"
    assert before["rows"][0]["matched_exact_fields"]==[]
    state=build_ready_pairs(project_runs)
    assert state["unique_pairs"]==0
    after=queue.read_candidate_queue(open_project(project.root),run)
    assert after["index_backend"]=="verified_pair_checkpoint_v6"
    assert after["receipt_only_pair_total"]==1
    assert after["candidate_pair_total"]==1
    assert after["rows"]==before["rows"]
    assert after["rows"][0]["pair_already_associated"] is True
    assert after["rows"][0]["last_decision_event_id"] is not None
    assert after["global_unique_publications"] is None


def _pair_gui(ctx, *, inspect_override=None):
    """Host fixture uses actual worker command validation and original SQLite."""
    from tools.gui_feasibility.real_project_flow import RealProjectFlow,ProjectFlowError
    project,run,historical=ctx
    flow=RealProjectFlow(selected_root=project.root,
                         selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={
        "runs":[{"run_id":run},{"run_id":historical}],
        "report":{"status":"incomplete"},"exports":[]}
    def dispatch(name,**kwargs):
        if name=="inspect" and inspect_override is not None:
            return inspect_override(kwargs)
        try:
            return execute_command(
                ApplicationCommand.for_project(project,name,**kwargs))
        except ApplicationCommandError as exc:
            raise ProjectFlowError(exc.code) from None
    flow._operation=dispatch
    return flow


def test_gui_pair_index_uses_separate_preview_and_confirmation(project_runs):
    project,run,_=project_runs
    a=insert(project_runs,number=5101,title="Separate supplement abstract A",
             doi="10.5101/container")
    b=insert(project_runs,source="wos",number=5102,
             title="Separate supplement abstract B",doi="10.5101/container")
    build_ready_index(project_runs)
    before=read(project_runs)
    assert before["index_backend"]=="verified_derived_keys_v5"
    source_events=audit(project)
    flow=_pair_gui(project_runs)
    try:
        state=flow.inspect_candidate_pairs()
        assert state["candidate_pair_state"]["status"]=="not_started"
        assert state["candidate_pair_state"]["index_ready"] is True
        assert audit(project)==source_events
        with pytest.raises(Exception,match="candidate_pair_confirmation_required"):
            flow.confirm_candidate_pairs("Researcher")
        offered=flow.offer_candidate_pairs("start")
        assert offered["candidate_pair_offer"]["run_id"]==run
        assert offered["candidate_pair_offer"]["action"]=="start"
        assert audit(project)==source_events
        started=flow.confirm_candidate_pairs("Researcher")
        assert started["candidate_pair_offer"] is None
        assert started["candidate_pair_state"]["status"]=="building"
        assert started["candidate_pair_state"]["processed_source_keys"]==0
        assert started["candidate_pair_last_receipt"]["action"]=="start"
        assert started["candidate_pair_error"] is None
        offered=flow.offer_candidate_pairs("advance")
        assert offered["candidate_pair_offer"]["action"]=="advance"
        advanced=flow.confirm_candidate_pairs("Researcher")
        assert advanced["candidate_pair_state"]["status"]=="ready_keys_only"
        assert advanced["candidate_pair_state"]["unique_pairs"]==1
        assert advanced["candidate_pair_state"]["historical_receipt_only_pairs_included"] is False
        assert advanced["candidate_pair_last_receipt"]["action"]=="advance"
        assert advanced["candidate_pair_last_receipt"]["status"]=="ready_keys_only"
        assert advanced["candidate_pair_offer"] is None
        assert advanced["candidate_queue"] is None
        current=flow.inspect_candidate_queue()["candidate_queue"]
        assert current["index_backend"]=="verified_pair_checkpoint_v6"
        assert current["rows"][0]["auto_merge_allowed"] is False
        assert current["candidate_pair_total"]==1
        assert current["global_unique_publications"] is None
        assert len({s["publication_id"] for s in current["rows"][0]["sources"]})==2
        with pytest.raises(Exception,match="candidate_pair_no_work"):
            flow.offer_candidate_pairs("advance")
    finally:
        flow.close()


def test_gui_pair_index_rejects_missing_source_key_cache(project_runs):
    project,run,_=project_runs
    insert(project_runs,number=5201)
    flow=_pair_gui(project_runs)
    events=audit(project)
    try:
        first=flow.inspect_candidate_pairs()["candidate_pair_state"]
        assert first["status"]=="not_started"
        assert first["index_ready"] is False
        with pytest.raises(Exception,match="candidate_pair_index_not_ready"):
            flow.offer_candidate_pairs("start")
        assert flow.state()["candidate_pair_offer"] is None
        assert audit(project)==events
        assert read(project_runs)["candidate_pair_total"]==0
    finally:
        flow.close()


def test_gui_pair_index_worker_reply_lost_requires_original_reinspect(project_runs):
    project,run,_=project_runs
    insert(project_runs,number=5301,title="Common",doi="10.5301/shared")
    insert(project_runs,source="wos",number=5302,
           title="Common",doi="10.5301/shared")
    build_ready_index(project_runs)
    flow=_pair_gui(project_runs)
    from tools.gui_feasibility.real_project_flow import ProjectFlowError
    try:
        flow.offer_candidate_pairs("start")
        flow.confirm_candidate_pairs("Researcher")
        flow.offer_candidate_pairs("advance")
        actual=flow._operation
        dispatched={"advance":0}
        def lost_reply(name,**kwargs):
            result=actual(name,**kwargs)
            if name=="candidate_pair_advance":
                dispatched["advance"]+=1
                raise ProjectFlowError("worker_reply_lost_after_commit")
            return result
        flow._operation=lost_reply
        with pytest.raises(ProjectFlowError,match="worker_reply_lost_after_commit"):
            flow.confirm_candidate_pairs("Researcher")
        after=flow.state()
        assert after["candidate_pair_offer"] is None
        assert after["candidate_pair_state"] is None
        assert after["candidate_pair_error"]=="candidate_pair_reinspect_required"
        with pytest.raises(ProjectFlowError,match="candidate_pair_confirmation_required"):
            flow.confirm_candidate_pairs("Researcher")
        restored=flow.inspect_candidate_pairs()["candidate_pair_state"]
        assert restored["status"]=="ready_keys_only"
        assert restored["unique_pairs"]==1
        assert dispatched["advance"]==1
        assert len([e for e in audit(project)
                    if e[1]=="candidate_pair_batch_committed_v1"])==1
    finally:
        flow.close()


def test_gui_pair_index_refuses_stale_evidence_after_offered_step(project_runs):
    project,run,_=project_runs
    insert(project_runs,number=5401)
    build_ready_index(project_runs)
    flow=_pair_gui(project_runs)
    from tools.gui_feasibility.real_project_flow import ProjectFlowError
    try:
        flow.offer_candidate_pairs("start")
        flow.confirm_candidate_pairs("Researcher")
        flow.offer_candidate_pairs("advance")
        insert(project_runs,number=5402)
        with pytest.raises(ProjectFlowError,match="candidate_pair_stale"):
            flow.confirm_candidate_pairs("Researcher")
        assert flow.state()["candidate_pair_offer"] is None
        assert flow.state()["candidate_pair_state"] is None
        assert flow.state()["candidate_pair_error"] is not None
        saved=flow.inspect_candidate_pairs()["candidate_pair_state"]
        assert saved["status"]=="stale"
        assert saved["index_ready"] is False
    finally:
        flow.close()


def test_gui_pair_index_run_switch_discards_unsubmitted_consent(project_runs):
    project,run,historical=project_runs
    insert(project_runs,number=5501)
    build_ready_index(project_runs)
    def inspect(kwargs):
        return {"snapshot":{
            "selected_run_id":kwargs["run_id"],
            "runs":[{"run_id":run},{"run_id":historical}],
            "report":{"status":"incomplete"},"exports":[]}}
    flow=_pair_gui(project_runs,inspect_override=inspect)
    from tools.gui_feasibility.real_project_flow import ProjectFlowError
    try:
        flow.offer_candidate_pairs("start")
        assert flow.state()["candidate_pair_offer"]["run_id"]==run
        switched=flow.select_run(historical)
        assert switched["selected_run_id"]==historical
        assert switched["candidate_pair_state"] is None
        assert switched["candidate_pair_offer"] is None
        assert switched["candidate_pair_last_receipt"] is None
        with pytest.raises(ProjectFlowError,match="candidate_pair_confirmation_required"):
            flow.confirm_candidate_pairs("Researcher")
        assert flow.inspect_candidate_pairs()["candidate_pair_state"]["status"]=="not_started"
    finally:
        flow.close()


def test_pair_checkpoint_command_fields_are_strictly_allowlisted(project_runs):
    project,run,_=project_runs
    initial=execute_command(ApplicationCommand.for_project(
        project,"candidate_pair_preview",run_id=run))
    assert initial["method"]=="candidate-pair-hint-checkpoints/1"
    assert initial["global_unique_publications"] is None
    assert initial["candidate_discovery_complete"] is False
    for fields in (
        {"run_id":None},
        {"run_id":run,"pilot_api_key":"SECRET"},
        {"run_id":run,"candidate_pair_generation":uid()},
        {"run_id":run,"candidate_pair_revision":"a"*64},
        {"run_id":run,"candidate_index_revision":"a"*64},
        {"run_id":run,"candidate_queue_revision":"a"*64},
        {"run_id":run,"publication_view_id":uid()},
        {"run_id":run,"export_id":uid()},
    ):
        with pytest.raises(ApplicationCommandError,match="invalid_command"):
            ApplicationCommand.for_project(project,"candidate_pair_preview",**fields)
    valid=dict(run_id=run,candidate_pair_revision=initial["revision"],
               candidate_pair_actor="Researcher",candidate_pair_confirmed=True)
    for fields in (
        {"candidate_pair_confirmed":False},
        {"candidate_pair_revision":"not-a-digest"},
        {"candidate_pair_generation":uid()},
        {"pilot_api_key":"SECRET"},
        {"directory":"/tmp/forged"},
    ):
        with pytest.raises(ApplicationCommandError,match="invalid_command"):
            ApplicationCommand.for_project(
                project,"candidate_pair_start",**(valid|fields))
    for generation in (None,"forged",[]):
        with pytest.raises(ApplicationCommandError,match="invalid_command"):
            ApplicationCommand.for_project(
                project,"candidate_pair_advance",
                **(valid|{"candidate_pair_generation":generation}))
    with pytest.raises(ApplicationCommandError,match="candidate_pair_index_not_ready"):
        execute_command(ApplicationCommand.for_project(
            project,"candidate_pair_start",**valid))


def test_large_review_history_is_validated_once_not_for_each_visible_pair(
    project_runs, monkeypatch,
):
    """A 20-pair page cannot repeat the full audit scan twenty times."""
    project,run,_=project_runs
    for n in range(21):
        insert(project_runs,number=7100+n,
               title="Individual report "+str(n),
               doi="10.7100/individual"+str(n))
        insert(project_runs,source="wos",number=7200+n,
               title="Individual report "+str(n),
               doi="10.7100/individual"+str(n))
    for n in range(6):
        a=insert(project_runs,number=7300+n,
                 title="Distinct source A "+str(n),
                 doi="10.7300/left"+str(n))
        b=insert(project_runs,source="wos",number=7400+n,
                 title="Distinct source B "+str(n),
                 doi="10.7400/right"+str(n))
        reject_pair(project_runs,a,b)
    build_ready_pairs(project_runs)
    original=candidates._receipts
    calls=[]
    def instrumented(db,keys):
        calls.append(keys)
        return original(db,keys)
    monkeypatch.setattr(candidates,"_receipts",instrumented)
    page=read(project_runs)
    assert page["index_backend"]=="verified_pair_checkpoint_v6"
    assert len(page["rows"])==20
    assert page["candidate_pair_total"]==27
    assert page["receipt_only_pair_total"]==6
    assert all(value is None for value in calls)
    # Once for the canonical count projection and once for the candidate
    # overlay. Individual rows reuse those validated original receipts.
    assert len(calls)==2
    assert all(row["auto_merge_allowed"] is False for row in page["rows"])
    assert page["global_unique_publications"] is None


def test_prevalidated_receipt_index_matches_original_pair_review(project_runs):
    """Reused history must preserve stale/other-run warnings and exact revision."""
    project,run,historical=project_runs
    a=insert(project_runs,number=7501,title="Report one",doi="10.7500/one")
    b=insert(project_runs,source="wos",number=7502,
             title="Report two",doi="10.7500/two")
    reject_pair(project_runs,a,b)
    with closing(sqlite3.connect(project.database_path)) as db:
        validated=candidates._receipts(db,None)
        lookup=candidates._index_validated_receipts(validated)
        original,original_state=candidates._view(db,tuple(sorted((a,b))))
        indexed,indexed_state=candidates._view(
            db,tuple(sorted((a,b))),validated_receipts_by_keys=lookup)
    assert original==indexed
    assert original_state==indexed_state
    assert indexed.status=="rejected_match"
    assert len(indexed.prior_decisions)==1
    assert indexed.automatic_match_allowed is False


def test_cached_decisions_never_bypass_full_journal_integrity(project_runs,monkeypatch):
    """A corrupt audited decision remains a hard failure, not a cache miss."""
    project,run,_=project_runs
    insert(project_runs,number=7601,title="Same report",doi="10.7600/d")
    insert(project_runs,source="wos",number=7602,
           title="Same report",doi="10.7600/d")
    build_ready_pairs(project_runs)
    def invalid_audit(*_args,**_kwargs):
        raise identity.PublicationIntegrityError("Corrupted canonical receipt")
    monkeypatch.setattr(candidates,"_receipts",invalid_audit)
    with pytest.raises(queue.CandidateQueueError) as exc:
        read(project_runs)
    assert exc.value.code=="candidate_queue_unavailable"


def test_fallback_queue_also_validates_one_journal_per_projection(project_runs,monkeypatch):
    """Original-v5 fallback remains conservative without per-pair revalidation."""
    project,run,_=project_runs
    for n in range(6):
        insert(project_runs,number=7700+n,title="Match "+str(n),
               doi="10.7700/key"+str(n))
        insert(project_runs,source="wos",number=7800+n,
               title="Match "+str(n),doi="10.7700/key"+str(n))
    build_ready_index(project_runs)
    original=candidates._receipts
    calls=[]
    def instrumented(db,keys):
        calls.append(keys)
        return original(db,keys)
    monkeypatch.setattr(candidates,"_receipts",instrumented)
    page=read(project_runs)
    assert page["index_backend"]=="verified_derived_keys_v5"
    assert len(page["rows"])==6
    assert len(calls)==2 and all(x is None for x in calls)


def test_bulk_original_source_decoder_matches_individual_authoritative_read(
    project_runs,
):
    """Streaming shares the *exact* raw source/run/hash evidence contract."""
    project,run,historical=project_runs
    linked=insert(project_runs,source="pubmed",number=8801,
                  title="Current independent source",doi="10.8801/one")
    historical_link=insert(project_runs,source="wos",number=8802,
                           title="Historical independent source",
                           doi="10.8801/two",run=historical)
    unknown=insert(project_runs,source="pubmed",number=8803,
                   title="Retained but unmaterialised",
                   materialise=False,run=historical)
    unsupported=insert(project_runs,source="manual",number=8804,
                       title="Non-provider original source",
                       materialise=False,run=historical)
    from research_y.application_inspection import _read
    with _read(project) as db:
        observed=[]
        for row in db.execute(queue._ORIGINAL_SOURCE_STREAM_SQL):
            six,status,linked_rid=row[:6],row[6],row[7]
            rid=six[0]
            canonical=identity._source(db,rid)
            streamed=identity._source_from_row(six,status)
            assert streamed==canonical
            assert status==canonical["run_status"]
            assert streamed["source_sha256"]==identity._hash(six)
            streamed_link=(identity._link_from_evidence(
                streamed,row[8],row[9],row[10:])
                if linked_rid is not None else None)
            assert streamed_link==identity._link(db,rid)
            observed.append(rid)
    assert set(observed)=={linked,historical_link,unknown,unsupported}
    assert read(project_runs)["candidate_pair_total"]==0


def test_original_queue_rejects_inconsistent_link_receipt_without_silent_loss(
    project_runs,
):
    project,_,_=project_runs
    rid=insert(project_runs,number=8855)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute(
            'UPDATE publication_retrievals SET decision_provenance_json=? '
            'WHERE retrieval_id=?',
            ('{"version":1,"event_id":999999999}',rid))
    before=audit(project)
    with pytest.raises(queue.CandidateQueueError) as err:
        read(project_runs)
    assert err.value.code=="candidate_queue_unavailable"
    assert audit(project)==before


def test_large_unlinked_history_is_not_queried_again_per_record(
    project_runs,monkeypatch,
):
    """One original scan; no historical source/run/link point lookup per row."""
    project,run,historical=project_runs
    a=insert(project_runs,source="pubmed",number=8901,
             title="Chosen conference abstract A",
             doi="10.8901/same")
    b=insert(project_runs,source="wos",number=8902,
             title="Chosen conference abstract B",
             doi="10.8901/same")
    rows=[]
    for n in range(420):
        source_id=str(900000+n)
        rid=uid()
        payload={
            "source":"NCBI PubMed EFetch XML",
            "record":{"pmid":source_id,
                      "title":"Unlinked historical abstract "+str(n),
                      "identifiers":{"doi":["10.9999/history"+str(n)]}},
        }
        rows.append((
            rid,historical,"pubmed",source_id,project.created_at_utc,
            identity._json(payload),
        ))
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executemany("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",rows)
    historical_ids={row[0] for row in rows}
    original_source=identity._source
    calls=[]
    def checked_source(db,rid):
        if rid in historical_ids:
            calls.append(rid)
        return original_source(db,rid)
    monkeypatch.setattr(identity,"_source",checked_source)
    page=read(project_runs)
    assert page["index_backend"]=="original_source_projection"
    assert page["project_source_records"]==422
    assert page["unmaterialised_project_records"]==420
    assert page["candidate_pair_total"]==1
    assert page["rows"][0]["retrieval_ids"]==sorted((a,b))
    assert page["rows"][0]["matched_exact_fields"]==["doi"]
    assert calls==[]  # all 420 originals still parsed and SHA-checked in stream
    assert page["global_unique_publications"] is None


def test_corrupt_unmaterialised_historical_source_still_fails_closed(
    project_runs,
):
    project,run,historical=project_runs
    rid=insert(project_runs,number=8951,
               run=historical,materialise=False)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_retrievals SET original_metadata_json=? "
                   "WHERE retrieval_id=?",('{"record":{"pmid":"BAD"}}',rid))
    with pytest.raises(queue.CandidateQueueError) as err:
        read(project_runs)
    assert err.value.code=="candidate_queue_unavailable"


def test_stream_original_query_uses_one_ordered_source_scan(project_runs):
    """SQLite should seek joined run/association rows by primary key."""
    project,_,_=project_runs
    with closing(sqlite3.connect(project.database_path)) as db:
        plan=[row[3] for row in db.execute(
            "EXPLAIN QUERY PLAN "+queue._ORIGINAL_SOURCE_STREAM_SQL)]
    assert any("SCAN r" in step for step in plan),plan
    assert any("SEARCH s" in step for step in plan),plan
    assert any("SEARCH l" in step for step in plan),plan
    assert not any("USE TEMP B-TREE" in step for step in plan),plan
