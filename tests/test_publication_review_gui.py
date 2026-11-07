"""P1-06j3: bounded local candidate/undo review through original SQLite services.

All records and abstracts are synthetic. No provider calls or redistribution
of licensed source bodies; immutable source records and audit receipts matter.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import sqlite3
from uuid import uuid4

import pytest

from research_y import publication_identity as identity
from research_y.application_commands import (
    ApplicationCommand, ApplicationCommandError, execute_command)
from research_y.projects import create_project, open_project
from research_y.publication_review_gui import (
    PublicationReviewError, preview_candidate_review, record_candidate_review,
    preview_candidate_reversal, confirm_candidate_reversal,
    read_current_retrieval_link,
)


def uid():
    return str(uuid4())


@pytest.fixture
def study(tmp_path):
    project = create_project(tmp_path, "Researcher-reviewed literature")
    run, other, version = uid(), uid(), uid()
    q = {}
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (version, 1, project.created_at_utc, "{}"))
        for n, group in enumerate(("g1", "g2")):
            db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                       (version, group, "Group " + group, n))
        for run_id in (run, other):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id, version, project.created_at_utc, "incomplete", None))
            for group in ("g1", "g2"):
                for source in ("pubmed", "wos"):
                    query = uid()
                    db.execute(
                        "INSERT INTO source_queries(query_id,run_id,strategy_version_id,"
                        "group_id,source_name,exact_query) VALUES(?,?,?,?,?,?)",
                        (query, run_id, version, group, source,
                         '"ECMO"[All Fields]' if source=="pubmed" else 'TS=("ECMO")'))
                    q[run_id, group, source] = query
    return project, run, other, q


def add(study, *, source="pubmed", number=123, title="Same title",
        groups=("g1", "g2"), run=None, abstract="SECRET PRIVATE ABSTRACT"):
    project, primary, _, queries = study
    run_id = run or primary
    provider_id = str(number) if source == "pubmed" else "WOS:" + str(number)
    record = {"title": title, "identifiers": {
                  "doi": ["10.1234/synthetic-supplement"] if source == "pubmed"
                  else "10.1234/synthetic-supplement"}}
    if source == "pubmed":
        record.update(pmid=provider_id, abstract_sections=[{"text": abstract}],
                      abstract_status="present",
                      publication_types=["Conference Abstract"])
        payload = {"source": "NCBI PubMed EFetch XML", "record": record,
                   "rights_review_required_for_abstract_redistribution": True}
    else:
        record.update(uid=provider_id, types=["Conference Abstract"])
        payload = {"provider": "wos_starter", "database": "WOS", "record": record,
                   "rights_status": "licence_review_required"}
    rid = uid()
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (rid, run_id, source, provider_id, project.created_at_utc,
                    identity._json(payload)))
        for group in groups:
            db.execute("INSERT INTO query_retrievals VALUES(?,?,?,?)",
                       (queries[run_id,group,source],rid,run_id,source))
    identity.materialise_retrieval(project,rid,actor="Fixture")
    return rid


def page(study):
    from research_y.publication_results import read_publication_page
    return read_publication_page(study[0], study[1])


def db_rows(project, table):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def pair(study, a, b):
    return preview_candidate_review(study[0],study[1],a,b,
                                    run_revision=page(study)["revision"])


def do_decision(study, a, b, decision="confirmed_match", *,
                move=None, actor="Researcher", evidence="Compared original records"):
    offer = pair(study, a, b)
    return record_candidate_review(
        study[0],study[1],a,b,run_revision=offer["run_revision"],
        expected_revision=offer["revision"],decision=decision,
        move_retrieval_id=move,actor=actor,evidence=evidence,
        warnings_acknowledged=True,confirmed=True)


def test_preview_is_read_only_citation_only_and_never_merges_shared_doi(study):
    project, run, _, _ = study
    left=add(study,source="pubmed",number=1)
    right=add(study,source="wos",number=2)
    before=sha256(project.database_path.read_bytes()).hexdigest()
    p=pair(study,left,right)
    assert p["status"]=="review_required"
    assert p["automatic_match_allowed"] is False
    assert p["pair_already_associated"] is False
    assert p["global_unique_publications"] is None and not p["verified_complete"]
    assert p["abstract_text_displayed"] is False and p["no_network_requests"]
    assert any(row["field"] == "doi" and row["comparison"] == "equal"
               for row in p["comparison"])
    assert "SECRET PRIVATE ABSTRACT" not in str(p)
    assert len(db_rows(project,"publications")) == 2
    assert before == sha256(project.database_path.read_bytes()).hexdigest()


def test_confirmed_match_and_audited_reversal_preserve_every_source(study):
    project,run,_,_ = study
    a=add(study,source="pubmed",number=12)
    b=add(study,source="wos",number=13)
    source_before=db_rows(project,"source_retrievals")
    members_before=db_rows(project,"query_retrievals")
    p=pair(study,a,b)
    result=do_decision(study,a,b,move=a)
    assert result["decision"]=="confirmed_match" and result["requires_reinspection"]
    after=pair(study,a,b)
    assert after["status"]=="confirmed_match" and after["pair_already_associated"]
    assert after["recent_decisions"][-1]["status"] == "confirmed_match"
    assert result["resulting_candidate_revision"]==after["revision"]
    original = preview_candidate_reversal(
        project,run,a,run_revision=page(study)["revision"])
    assert original["association_event_id"]==after["recent_decisions"][-1]["association_event_id"]
    undone=confirm_candidate_reversal(
        project,run,a,run_revision=original["run_revision"],
        expected_revision=original["revision"],
        actor="Researcher",evidence="Distinct supplement abstracts",confirmed=True)
    assert undone["reversal_of_event_id"]==original["association_event_id"]
    receipt=read_current_retrieval_link(
        project,run,a,run_revision=page(study)["revision"])
    assert receipt["action"]=="reverse"
    assert receipt["reverses_event_id"]==original["association_event_id"]
    assert receipt["publication_id"]==original["restored_publication_id"]
    assert receipt["decision_status"]=="review_required"
    assert not pair(study,a,b)["pair_already_associated"]
    assert db_rows(project,"source_retrievals")==source_before
    assert db_rows(project,"query_retrievals")==members_before
    assert len(db_rows(project,"publications"))==2
    assert page(study)["global_unique_publications"] is None
    with pytest.raises(PublicationReviewError):
        confirm_candidate_reversal(project,run,a,
             run_revision=original["run_revision"],
             expected_revision=original["revision"],
             actor="Researcher",evidence="Cannot replay",confirmed=True)


def test_explicit_reject_and_reconsider_preserves_history_without_moving(study):
    project,run,_,_=study
    a=add(study,number=22,title="Abstract one")
    b=add(study,source="wos",number=23,title="Abstract two")
    before=db_rows(project,"publication_retrievals")
    rejected=do_decision(study,a,b,decision="rejected_match")
    assert rejected["decision"]=="rejected_match"
    assert db_rows(project,"publication_retrievals")==before
    current=pair(study,a,b)
    assert current["status"]=="rejected_match"
    assert current["prior_decision_count"]==1
    assert current["recent_decisions"][0]["evidence"]=="Compared original records"
    do_decision(study,a,b,decision="confirmed_match",move=a,
                evidence="Researcher explicitly reconsidered source evidence")
    newer=pair(study,a,b)
    assert newer["status"]=="confirmed_match"
    assert newer["prior_decision_count"]==2
    assert [x["status"] for x in newer["recent_decisions"]]==[
        "rejected_match","confirmed_match"]


def test_decision_requires_literal_confirmation_warnings_and_fresh_revision(study):
    project,run,_,queries=study
    a=add(study,number=44)
    b=add(study,source="wos",number=45)
    offer=pair(study,a,b)
    before=db_rows(project,"audit_events")
    for acknowledged,confirmed in ((False,True),(True,False),(1,True),(True,"yes")):
        with pytest.raises(PublicationReviewError):
            record_candidate_review(project,run,a,b,
                run_revision=offer["run_revision"],
                expected_revision=offer["revision"],
                decision="confirmed_match",move_retrieval_id=a,
                actor="Researcher",evidence="Explicit claim",
                warnings_acknowledged=acknowledged,confirmed=confirmed)
    with closing(sqlite3.connect(project.database_path)) as db,db:
        db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",
                   (queries[run,"g1","pubmed"],))
    with pytest.raises(PublicationReviewError) as exc:
        record_candidate_review(project,run,a,b,
            run_revision=offer["run_revision"],
            expected_revision=offer["revision"],
            decision="confirmed_match",move_retrieval_id=a,
            actor="Researcher",evidence="Stale source status",
            warnings_acknowledged=True,confirmed=True)
    assert exc.value.code=="publication_review_stale"
    assert db_rows(project,"audit_events")==before


def test_cross_run_source_and_invalid_reversal_fail_closed(study):
    project,run,other,_=study
    a=add(study,number=55)
    outside=add(study,number=56,run=other)
    rev=page(study)["revision"]
    with pytest.raises(PublicationReviewError) as exc:
        preview_candidate_review(project,run,a,outside,run_revision=rev)
    assert exc.value.code=="publication_review_wrong_run"
    with pytest.raises(PublicationReviewError) as exc:
        preview_candidate_reversal(project,run,a,run_revision=rev)
    assert exc.value.code=="publication_review_no_reversal"
    with pytest.raises(PublicationReviewError):
        read_current_retrieval_link(project,run,outside,run_revision=rev)


def test_worker_command_allowlist_and_no_forged_decisions(study):
    project,run,_,_=study
    a=add(study,number=67)
    b=add(study,source="wos",number=68)
    rev=page(study)["revision"]
    base=dict(run_id=run,candidate_left_id=a,candidate_right_id=b,
              candidate_run_revision=rev)
    for extras in (
        {"pilot_api_key":"SECRET"}, {"candidate_move_id":a},
        {"candidate_actor":"Forged"}, {"candidate_confirmed":True},
        {"publication_actor":"Forged"}, {"candidate_retrieval_id":a},
    ):
        with pytest.raises(ApplicationCommandError):
            ApplicationCommand.for_project(project,"candidate_review_preview",**base,**extras)
    read=execute_command(ApplicationCommand.for_project(
        project,"candidate_review_preview",**base))
    assert read["status"]=="review_required"
    for extras in (dict(candidate_confirmed=False),
                   dict(candidate_warnings_acknowledged=False)):
        common=dict(base,candidate_revision=read["revision"],
                    candidate_decision="confirmed_match",candidate_move_id=a,
                    candidate_actor="Researcher",candidate_evidence="Confirmed",
                    candidate_confirmed=True,candidate_warnings_acknowledged=True)
        common.update(extras)
        with pytest.raises(ApplicationCommandError):
            ApplicationCommand.for_project(project,"candidate_review_decide",**common)
    result=execute_command(ApplicationCommand.for_project(
        project,"candidate_review_decide",**base,
        candidate_revision=read["revision"],
        candidate_decision="confirmed_match",candidate_move_id=a,
        candidate_actor="Researcher",candidate_evidence="Confirmed source match",
        candidate_confirmed=True,candidate_warnings_acknowledged=True))
    assert result["decision"]=="confirmed_match"
    current=execute_command(ApplicationCommand.for_project(
        project,"candidate_link_status",run_id=run,
        candidate_retrieval_id=a,candidate_run_revision=page(study)["revision"]))
    assert current["action"]=="associate"
    with pytest.raises(ApplicationCommandError):
        ApplicationCommand.for_project(project,"candidate_reversal_confirm",
            run_id=run,candidate_retrieval_id=a,candidate_run_revision=rev,
            candidate_revision=read["revision"],candidate_actor="Researcher",
            candidate_evidence="No",candidate_confirmed=True,
            candidate_warnings_acknowledged=True)
    assert "SECRET" not in repr(result)


def test_host_requires_visible_selection_then_reconciles_match_and_reversal(study):
    project,run,_,_=study
    a=add(study,source="pubmed",number=90)
    b=add(study,source="wos",number=91)
    from tools.gui_feasibility.real_project_flow import RealProjectFlow,ProjectFlowError
    flow=RealProjectFlow(selected_root=project.root,selected_parent=project.root.parent)
    flow.project=project
    flow.selected_run_id=run
    flow.snapshot={"runs":[],"report":None,"exports":[]}

    def dispatch(name,**kwargs):
        return execute_command(ApplicationCommand.for_project(project,name,**kwargs))
    flow._operation=dispatch
    try:
        with pytest.raises(ProjectFlowError):
            flow.choose_candidate_source(a)
        current=flow.inspect_publications()
        p=current["publication_page"]
        with pytest.raises(ProjectFlowError):
            flow.confirm_candidate_decision(
                decision="confirmed_match",move_retrieval_id=a,
                actor="Researcher",evidence="Unreviewed",acknowledged=True)
        sources=[]
        for row in p["rows"]:
            detail=flow.inspect_publication_detail(
                publication_id=row["publication_id"],revision=p["revision"])
            sources.extend((row["publication_id"],s["retrieval_id"])
                           for s in detail["publication_detail"]["source_retrievals"])
        first=next(pid for pid,rid in sources if rid==a)
        second=next(pid for pid,rid in sources if rid==b)
        flow.inspect_publication_detail(publication_id=first,revision=p["revision"])
        selected=flow.choose_candidate_source(a)
        assert selected["candidate_first"]["retrieval_id"]==a
        flow.inspect_publication_detail(publication_id=second,revision=p["revision"])
        preview=flow.choose_candidate_source(b)
        assert preview["candidate_offer"]["automatic_match_allowed"] is False
        with pytest.raises(ProjectFlowError,match="publication_review_confirmation_required"):
            flow.confirm_candidate_decision(
                decision="confirmed_match",move_retrieval_id=a,
                actor="Researcher",evidence="Checked",acknowledged=False)
        result=flow.confirm_candidate_decision(
            decision="confirmed_match",move_retrieval_id=a,
            actor="Researcher",evidence="Compared source publication identities",
            acknowledged=True)
        assert result["candidate_last_outcome"]["action"]=="confirmed_match"
        assert result["candidate_offer"] is None
        assert result["publication_page"]["global_unique_publications"] is None
        current=flow.inspect_publications()
        p=current["publication_page"]
        pub=next(row["publication_id"] for row in p["rows"]
                 if row["original_source_records_in_run"]==2)
        flow.inspect_publication_detail(publication_id=pub,revision=p["revision"])
        pending=flow.offer_candidate_reversal(a)
        assert pending["reversal_offer"]["retrieval_id"]==a
        undone=flow.confirm_candidate_reversal(
            actor="Researcher",evidence="Two different meeting abstracts")
        assert undone["candidate_last_outcome"]["action"]=="reverse"
        assert undone["candidate_last_outcome"]["verified_audit_event_id"]>0
        assert undone["reversal_offer"] is None
    finally:
        flow.close()


def test_reopened_project_sees_committed_receipts_without_resending(study):
    project,run,_,_=study
    a=add(study,number=200)
    b=add(study,source="wos",number=201)
    offer=pair(study,a,b)
    do_decision(study,a,b,decision="rejected_match")
    reopened=open_project(project.root)
    current=preview_candidate_review(reopened,run,a,b,
                    run_revision=page(study)["revision"])
    assert current["status"]=="rejected_match"
    with pytest.raises(PublicationReviewError):
        record_candidate_review(reopened,run,a,b,
            run_revision=offer["run_revision"],
            expected_revision=offer["revision"],
            decision="confirmed_match",move_retrieval_id=a,
            actor="Researcher",evidence="Unsafe stale replay",
            warnings_acknowledged=True,confirmed=True)
