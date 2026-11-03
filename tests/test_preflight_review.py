"""Pre-run integrity/PRESS review evidence: real SQLite, no provider/network calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import uuid4
import sqlite3

import pytest

from research_y.projects import create_project, open_project
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy
from research_y.preflight_review import (
    EVENT, PRESS_ITEMS, PreflightError, read_preflight,
    record_preflight_review,
)
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError


def _project(tmp_path):
    project = create_project(tmp_path, "Pre-run scientific integrity")
    approved = commit_approved_strategy(
        project, request_id=str(uuid4()),
        theme="RV function on extracorporeal support",
        groups=(
            StrategyGroup("cardiac", "Right ventricle", (
                ApprovedTerm("right ventricle", "researcher", True),
                ApprovedTerm("right-ventricle", "deterministic", True,
                             "Hyphenation alternative"),
            )),
            StrategyGroup("support", "Extracorporeal", (
                ApprovedTerm("ECMO", "researcher", True),
                ApprovedTerm("inactive term", "researcher", True, enabled=False),
            )),
        ), approved_by="Researcher", approval_confirmed=True,
    )
    return project, approved.run_id


def _reviews(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                          (EVENT,)).fetchone()[0]


def _submission(run_id, *, plan_sha, review_id=None, **changes):
    args=dict(run_id=run_id, review_id=review_id or str(uuid4()),
        expected_plan_sha256=plan_sha,
        reviewer_name="Researcher", reviewer_role="researcher_self_check",
        press_items={key:"reviewed" for key in PRESS_ITEMS},
        review_note="No untested exclusion applied.",
        known_relevant=("PMID 100", "DOI 10.1/example"))
    args.update(changes)
    return args


def test_offline_preflight_checks_complete_original_or_plan_without_writes(tmp_path):
    project, run_id = _project(tmp_path)
    before = _reviews(project)
    report = read_preflight(project, run_id)
    assert report["run_id"] == run_id and report["logic"] == "OR"
    assert report["group_count"] == 2 and report["active_group_count"] == 2
    assert report["active_term_count"] == 3
    assert report["programmatic_checks"]["stored_query_coverage"] == "verified"
    assert report["programmatic_checks"]["exact_compiler_match"] == "verified"
    assert report["programmatic_checks"]["press_peer_review"] == "not_verified"
    assert report["provider_counts"] is None and report["estimated_workload"] is None
    assert report["workload_status"] == "unknown_until_pilot_counts"
    assert report["source_retrieval_verified"] is False
    assert report["execution_authorized"] is False
    assert report["last_review"] is None
    assert len(report["sources"]) == 2
    assert {source["source_name"] for source in report["sources"]} == {"pubmed", "wos"}
    assert len(report["sources"][0]["queries"]) == 2
    assert len(report["sources"][1]["queries"]) == 2
    assert all(q["reported_matches"] is None and q["status"] == "pending"
               for source in report["sources"] for q in source["queries"])
    assert "[All Fields]" in report["sources"][0]["overall_union_preview"]
    assert "TS=(" in report["sources"][1]["overall_union_preview"]
    assert "inactive term" not in str([s["queries"] for s in report["sources"]])
    assert " AND " not in str([s["queries"] for s in report["sources"]])
    assert "full text" in report["sources"][1]["source_coverage"]
    assert _reviews(project) == before
    reopened = open_project(project.root)
    assert read_preflight(reopened, run_id)["plan_sha256"] == report["plan_sha256"]


def test_press_review_is_append_only_named_and_not_actual_peer_verification(tmp_path):
    project, run_id = _project(tmp_path)
    report = read_preflight(project, run_id)
    params = _submission(run_id, plan_sha=report["plan_sha256"],
                         reviewer_role="independent_peer_reported",
                         reviewer_name="Another clinician",
                         press_items={k:("needs_revision" if k=="spelling" else
                                         "not_reviewed" if k=="search_fields" else
                                         "reviewed") for k in PRESS_ITEMS})
    result = record_preflight_review(project, **params)
    assert result["newly_recorded"] is True
    assert result["peer_review_verified"] is False
    assert result["execution_authorized"] is False
    assert result["source_retrieval_verified"] is False
    assert _reviews(project) == 1
    next_read = read_preflight(open_project(project.root), run_id)
    record = next_read["last_review"]
    assert record["review_id"] == params["review_id"]
    assert record["reviewer_role"] == "independent_peer_reported"
    assert record["peer_review_verified"] is False
    assert record["press_items"]["spelling"] == "needs_revision"
    assert record["press_items"]["search_fields"] == "not_reviewed"
    assert record["known_relevant"] == ["PMID 100", "DOI 10.1/example"]
    assert record["known_relevant_status"] == "not_tested_against_provider"
    assert not next_read["execution_authorized"] and next_read["provider_counts"] is None
    with closing(sqlite3.connect(project.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM source_queries WHERE run_id=?",
                          (run_id,)).fetchone()[0] == 4
        assert db.execute(
            "SELECT COUNT(*) FROM source_queries WHERE run_id=? AND "
            "(reported_matches IS NOT NULL OR status!='pending')",
            (run_id,)).fetchone()[0] == 0


def test_lost_review_response_replays_same_receipt_without_second_write(tmp_path):
    project, run_id = _project(tmp_path)
    args = _submission(run_id, plan_sha=read_preflight(project, run_id)["plan_sha256"])
    first = record_preflight_review(project, **args)
    second = record_preflight_review(open_project(project.root), **args)
    assert first["newly_recorded"] is True and second["newly_recorded"] is False
    assert first["review_id"] == second["review_id"]
    assert _reviews(project) == 1
    with pytest.raises(PreflightError, match="^review_conflict$"):
        record_preflight_review(project, **dict(args, review_note="Changed later"))
    assert _reviews(project) == 1
    other = record_preflight_review(project, **dict(args, review_id=str(uuid4()),
                                                review_note="New separate review"))
    assert other["newly_recorded"] is True and _reviews(project) == 2
    assert read_preflight(project, run_id)["last_review"]["review_id"] == other["review_id"]


def test_stale_hash_cannot_attach_review_to_different_plan(tmp_path):
    project, run_id = _project(tmp_path)
    report = read_preflight(project, run_id)
    before = _reviews(project)
    with pytest.raises(PreflightError, match="^stale_preflight$"):
        record_preflight_review(project, **_submission(
            run_id, plan_sha="f"*64))
    assert _reviews(project) == before
    with pytest.raises(PreflightError, match="^invalid_identifier$"):
        read_preflight(project, "../not-run")
    with pytest.raises(PreflightError, match="^unknown_run$"):
        read_preflight(project, str(uuid4()))
    assert read_preflight(project, run_id)["plan_sha256"] == report["plan_sha256"]


@pytest.mark.parametrize("mutation", [
    "different_query", "missing_query", "invented_language_limit",
    "already_executed", "provider_hit_count", "nonpending_run",
])
def test_changed_incomplete_or_executed_plan_fails_closed(tmp_path, mutation):
    project, run_id = _project(tmp_path)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        query_id = db.execute(
            "SELECT query_id FROM source_queries WHERE run_id=? LIMIT 1",
            (run_id,)).fetchone()[0]
        if mutation=="different_query":
            db.execute("UPDATE source_queries SET exact_query=? WHERE query_id=?",
                       ('TS=("changed" AND "term")', query_id))
        elif mutation=="missing_query":
            db.execute("DELETE FROM source_queries WHERE query_id=?", (query_id,))
        elif mutation=="invented_language_limit":
            db.execute('UPDATE source_queries SET parameters_json=? WHERE query_id=?',
                       ('{"language":"en"}',query_id))
        elif mutation=="already_executed":
            db.execute("UPDATE source_queries SET status='running' WHERE query_id=?",
                       (query_id,))
        elif mutation=="provider_hit_count":
            db.execute("UPDATE source_queries SET reported_matches=40 WHERE query_id=?",
                       (query_id,))
        else:
            db.execute("UPDATE search_runs SET status='running' WHERE run_id=?",
                       (run_id,))
    expected = ("run_not_pending" if mutation=="nonpending_run" else
                "plan_unverified")
    with pytest.raises(PreflightError, match="^"+expected+"$"):
        read_preflight(project, run_id)
    assert _reviews(project)==0


@pytest.mark.parametrize("change", [
    {"reviewer_name":""},
    {"reviewer_name":" private"},
    {"reviewer_role":"certified_by_software"},
    {"press_items":{}},
    {"press_items":{k:"passed" for k in PRESS_ITEMS}},
    {"known_relevant":("duplicate","duplicate")},
    {"known_relevant":("record secret",)},
    {"known_relevant":["not a tuple"]},
    {"review_note":" private path"},
    {"review_id":"not uuid"},
])
def test_invalid_review_input_never_creates_a_receipt(tmp_path, change):
    project, run_id = _project(tmp_path)
    args = _submission(run_id, plan_sha=read_preflight(project, run_id)["plan_sha256"])
    args.update(change)
    with pytest.raises(PreflightError):
        record_preflight_review(project, **args)
    assert _reviews(project) == 0


def test_audit_insert_failure_rolls_back_and_retry_succeeds(tmp_path, monkeypatch):
    import research_y.preflight_review as module
    project, run_id = _project(tmp_path)
    args=_submission(run_id, plan_sha=read_preflight(project, run_id)["plan_sha256"])
    original=module._audit

    def interrupted(*unused, **kwargs):
        raise sqlite3.OperationalError("injected disk busy")

    monkeypatch.setattr(module, "_audit", interrupted)
    with pytest.raises(PreflightError, match="^review_evidence_invalid$"):
        record_preflight_review(project, **args)
    assert _reviews(project)==0
    monkeypatch.setattr(module, "_audit", original)
    assert record_preflight_review(project, **args)["newly_recorded"]
    assert _reviews(project)==1


def test_simultaneous_same_review_id_creates_one_receipt(tmp_path):
    project,run_id=_project(tmp_path)
    args=_submission(run_id, plan_sha=read_preflight(project,run_id)["plan_sha256"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _: record_preflight_review(project, **args),
                              range(2)))
    assert sorted(r["newly_recorded"] for r in results)==[False,True]
    assert _reviews(project)==1


def test_real_supervised_worker_review_retry_and_restart(tmp_path, monkeypatch):
    project,run_id=_project(tmp_path)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        flow.open_selected()
        flow.select_run(run_id)
        before = flow.inspect_preflight()
        assert before["preflight_report"]["plan_sha256"]
        assert before["preflight_report"]["source_retrieval_verified"] is False
        with pytest.raises(ProjectFlowError, match="^preflight_confirmation_required$"):
            flow.record_preflight_review()
        flow.offer_preflight_review(reviewer_name="Researcher",
            reviewer_role="researcher_self_check",
            press_items={k:"reviewed" for k in PRESS_ITEMS},
            review_note="Manual research review, no provider retrieval.",
            known_relevant=("PMID 100",))
        assert flow.state()["preflight_candidate"]["reviewer_name"]=="Researcher"
        assert _reviews(project)==0
        original=flow._operation
        attempted=[]
        lost=True
        def lost_after_write(name,**kw):
            nonlocal lost
            result=original(name,**kw)
            if name=="preflight_record":
                attempted.append(kw["review_id"])
                if lost:
                    lost=False
                    raise ProjectFlowError("worker_interrupted")
            return result
        monkeypatch.setattr(flow,"_operation",lost_after_write)
        with pytest.raises(ProjectFlowError, match="^worker_interrupted$"):
            flow.record_preflight_review()
        assert _reviews(project)==1
        assert flow.state()["preflight_review_reconciliation_required"] is True
        with pytest.raises(ProjectFlowError, match="^preflight_reconciliation_required$"):
            flow.select_run(run_id)
        accepted=flow.record_preflight_review()
        assert attempted[0]==attempted[1]
        assert _reviews(project)==1
        assert accepted["preflight_review_reconciliation_required"] is False
        assert accepted["preflight_report"]["last_review"]["review_id"]==attempted[0]
        assert accepted["selected_run_id"]==run_id
        assert accepted["source_retrieval_verified"] is False
    finally:
        flow.close()
    reopened=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        reopened.open_selected(); reopened.select_run(run_id)
        assert reopened.state()["preflight_report"] is None
        after=reopened.inspect_preflight()
        assert after["preflight_report"]["last_review"]["review_id"]==attempted[0]
    finally:
        reopened.close()


def test_unconfirmed_review_can_be_revised_without_database_mutation(tmp_path):
    project,run_id=_project(tmp_path)
    flow=RealProjectFlow(selected_root=project.root,selected_parent=tmp_path)
    try:
        flow.open_selected();flow.select_run(run_id);flow.inspect_preflight()
        flow.offer_preflight_review(reviewer_name="Reviewer",
            reviewer_role="researcher_self_check",
            press_items={k:"not_reviewed" for k in PRESS_ITEMS})
        assert flow.state()["preflight_candidate"] is not None
        before=_reviews(project)
        after=flow.revise_preflight_review()
        assert after["preflight_candidate"] is None
        assert _reviews(project)==before
        with pytest.raises(ProjectFlowError, match="^preflight_confirmation_required$"):
            flow.record_preflight_review()
    finally:
        flow.close()


def test_gui_exposes_real_review_actions_but_not_browser_file_or_source_trigger():
    import inspect
    from tools.gui_feasibility.real_project_app import run
    source=inspect.getsource(run)
    assert "name == 'preflight_inspect'" in source
    assert "name == 'preflight_offer'" in source
    assert "name == 'preflight_record'" in source
    assert "flow.record_preflight_review()" in source
    assert "data-testid=preflight-coverage" in source
    assert "data-testid=preflight-query" in source
    assert "data-testid=preflight-unknown" in source
    assert "data-testid=preflight-retry" in source
    assert "peer review" in source or "peer-review" in source
    assert "/_probe/terms" not in source
    assert "ui.html(" not in source
