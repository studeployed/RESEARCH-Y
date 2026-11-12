"""Trusted graphical two-batch consent and recovery against real SQLite.

The experimental host is tested using its actual allowlisted application
commands. Only its unrelated project-inventory inspection is stubbed; every
preview, write, source/audit check and stale-token rejection uses original
SQLite services. No provider calls, licensed text or network credentials.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import sqlite3
from uuid import uuid4

import pytest

from research_y import publication_identity as identity
from research_y.application_commands import (
    ApplicationCommand, ApplicationCommandError, execute_command,
)
from research_y.projects import create_project, open_project
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError


def _rid(index: int) -> str:
    return f"99999999-9999-4999-8999-{index + 1:012x}"


@pytest.fixture
def project_run(tmp_path):
    project = create_project(tmp_path, "Original source GUI consent fixture")
    run, other, strategy = str(uuid4()), str(uuid4()), str(uuid4())
    stamp = project.created_at_utc
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (strategy, 1, stamp, "{}"))
        db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                   (strategy, "all", "All terms OR", 0))
        queries = {}
        for run_id in (run, other):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id, strategy, stamp, "incomplete", None))
            for source in ("pubmed", "wos"):
                qid = str(uuid4())
                db.execute("INSERT INTO source_queries VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (qid, run_id, strategy, "all", source,
                            '"ventricle"[All Fields]' if source == "pubmed"
                            else 'TS=("ventricle")', "{}", None, "incomplete", None))
                queries[run_id, source] = qid
        sources, members = [], []
        for i in range(132):
            pubmed = i % 2 == 0
            source = "pubmed" if pubmed else "wos"
            sid = str(20000001 + i) if pubmed else f"WOS:{20000001 + i}"
            title = "Same reference title" if i < 2 else f"Distinct source {i}"
            record = {
                "pmid" if pubmed else "uid": sid, "title": title,
                "identifiers": {"doi": ["10.1000/same"] if pubmed
                                else "10.1000/same"},
            }
            payload = (
                {"source": "NCBI PubMed EFetch XML", "record": record}
                if pubmed else
                {"provider": "wos_starter", "database": "WOS",
                 "record": record, "rights_status": "licence_review_required"}
            )
            sources.append((_rid(i), run, source, sid, stamp, identity._json(payload)))
            members.append((queries[run, source], _rid(i), run, source))
        db.executemany("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)", sources)
        db.executemany("INSERT INTO query_retrievals VALUES(?,?,?,?)", members)
    return project, run, other


def _counts(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return tuple(db.execute(sql).fetchone()[0] for sql in (
            "SELECT COUNT(*) FROM publications",
            "SELECT COUNT(*) FROM publication_retrievals",
            "SELECT COUNT(*) FROM audit_events WHERE event_type='publication_identity_v1'",
            "SELECT COUNT(*) FROM source_retrievals",
            "SELECT COUNT(*) FROM query_retrievals",
        ))


def _flow(project, run, other):
    flow = RealProjectFlow(
        selected_root=project.root, selected_parent=project.root.parent)
    flow.project = project
    flow.selected_run_id = run
    run_rows = [{"run_id": run}, {"run_id": other}]
    flow.snapshot = {"runs": run_rows, "report": {"status": "incomplete"},
                     "exports": []}

    def original_operation(name, **kw):
        if name == "inspect":
            return {"snapshot": {"runs": run_rows, "exports": [],
                                 "selected_run_id": kw.get("run_id"),
                                 "report": {"status": "incomplete"}}}
        try:
            return execute_command(ApplicationCommand.for_project(
                project, name, **kw))
        except ApplicationCommandError as exc:
            # The genuine ApplicationWorker reports this static code in a
            # failed OperationStatus. RealProjectFlow._operation_for_project
            # translates that status into ProjectFlowError, never leaking
            # a raw service exception to the user-facing recovery flow.
            raise ProjectFlowError(exc.code) from None
    flow._operation = original_operation
    flow._publish()
    return flow


def test_preview_and_confirmation_are_one_use_and_independently_reconciled(project_run):
    project, run, other = project_run
    flow = _flow(project, run, other)
    try:
        before_hash = sha256(project.database_path.read_bytes()).hexdigest()
        offered = flow.offer_publication_window()
        plan = offered["publication_window_offer"]
        assert plan["batch_sizes"] == [64, 64]
        assert plan["proposed_source_records"] == 128
        assert plan["unmaterialised_retrievals"] == 132
        assert offered["publication_materialisation_offer"] is None
        assert offered["publication_window_last_outcome"] is None
        assert sha256(project.database_path.read_bytes()).hexdigest() == before_hash
        with pytest.raises(ProjectFlowError, match="confirmation_required"):
            flow.confirm_publication_window(" ")
        assert flow.state()["publication_window_offer"] == plan
        completed = flow.confirm_publication_window("Researcher")
        receipt = completed["publication_window_last_outcome"]
        assert receipt["materialised_in_session"] == 128
        assert receipt["committed_batches"] == 2
        assert receipt["unmaterialised_retrievals_remaining"] == 4
        assert completed["publication_window_offer"] is None
        assert completed["publication_window_reinspect_required"] is False
        assert completed["publication_page"] is None
        assert completed["candidate_queue"] is None
        assert completed["report"]["status"] == "incomplete"
        assert _counts(open_project(project.root)) == (128, 128, 128, 132, 132)
        with closing(sqlite3.connect(project.database_path)) as db:
            links = db.execute(
                "SELECT retrieval_id,publication_id FROM publication_retrievals "
                "ORDER BY retrieval_id").fetchall()
        assert [row[0] for row in links] == [_rid(i) for i in range(128)]
        assert len({row[1] for row in links}) == 128
        assert receipt["global_unique_publications"] is None
        with pytest.raises(ProjectFlowError, match="confirmation_required"):
            flow.confirm_publication_window("Researcher")
        assert _counts(project) == (128, 128, 128, 132, 132)
        next_offer = flow.offer_publication_window()["publication_window_offer"]
        assert next_offer["batch_sizes"] == [4]
        assert next_offer["proposed_source_records"] == 4
        flow.dismiss_publication_window()
        assert flow.state()["publication_window_offer"] is None
        assert _counts(project) == (128, 128, 128, 132, 132)
    finally:
        flow.close()


def test_recovery_after_second_transaction_failure_requires_read_only_reinspection(
    project_run,
):
    project, run, other = project_run
    flow = _flow(project, run, other)
    try:
        offer = flow.offer_publication_window()["publication_window_offer"]
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute(
                "CREATE TRIGGER fail_second_gui_window BEFORE INSERT "
                "ON publication_retrievals WHEN NEW.retrieval_id='" +
                _rid(64) + "' "
                "BEGIN SELECT RAISE(ABORT, 'synthetic second-batch fault'); END")
        with pytest.raises(ProjectFlowError, match="publication_window_reinspect_required"):
            flow.confirm_publication_window("Researcher")
        assert flow.state()["publication_window_offer"] is None
        assert flow.state()["publication_window_last_outcome"] is None
        assert flow.state()["publication_window_reinspect_required"] is True
        assert _counts(open_project(project.root)) == (64, 64, 64, 132, 132)
        with pytest.raises(ProjectFlowError, match="reinspect_required"):
            flow.offer_publication_window()
        before = _counts(project)
        inspection = flow.inspect_publication_window()
        assert inspection["publication_window_reinspect_required"] is False
        assert inspection["publication_window_offer"] is None
        assert inspection["publication_window_last_inspection"][
            "unmaterialised_retrievals"] == 68
        assert inspection["publication_window_last_inspection"][
            "existing_publication_hypotheses"] == 64
        assert "revision" not in inspection["publication_window_last_inspection"]
        assert _counts(project) == before
        with closing(sqlite3.connect(project.database_path)) as db, db:
            db.execute("DROP TRIGGER fail_second_gui_window")
        offer2 = flow.offer_publication_window()["publication_window_offer"]
        assert offer2["revision"] != offer["revision"]
        assert offer2["batch_sizes"] == [64, 4]
        assert flow.confirm_publication_window("Researcher")[
            "publication_window_last_outcome"]["materialised_in_session"] == 68
        assert _counts(open_project(project.root)) == (132, 132, 132, 132, 132)
    finally:
        flow.close()


def test_lost_returned_reply_must_not_fabricate_success_or_auto_retry(project_run):
    project, run, other = project_run
    flow = _flow(project, run, other)
    original = flow._operation
    try:
        offer = flow.offer_publication_window()["publication_window_offer"]
        executed = []
        def reply_lost(name, **kwargs):
            if name == "publication_window_confirm":
                executed.append(original(name, **kwargs))
                raise ProjectFlowError("worker_interrupted")
            return original(name, **kwargs)
        flow._operation = reply_lost
        with pytest.raises(ProjectFlowError, match="publication_window_reinspect_required"):
            flow.confirm_publication_window("Researcher")
        assert len(executed) == 1
        assert flow.state()["publication_window_last_outcome"] is None
        assert flow.state()["publication_window_reinspect_required"] is True
        assert _counts(project)[:3] == (128, 128, 128)
        with pytest.raises(ProjectFlowError, match="reinspect_required"):
            flow.offer_publication_window()
        flow._operation = original
        state = flow.inspect_publication_window()
        assert state["publication_window_last_inspection"]["unmaterialised_retrievals"] == 4
        assert state["publication_window_last_outcome"] is None
        assert state["publication_window_offer"] is None
        assert "revision" not in str(state["publication_window_last_inspection"])
        assert _counts(project)[:3] == (128, 128, 128)
        assert offer["proposed_source_records"] == 128
    finally:
        flow.close()


def test_run_switch_discards_window_consent_and_recovery(project_run):
    project, run, other = project_run
    flow = _flow(project, run, other)
    try:
        flow.offer_publication_window()
        assert flow.state()["publication_window_offer"] is not None
        state = flow.select_run(other)
        assert state["selected_run_id"] == other
        assert state["publication_window_offer"] is None
        assert state["publication_window_last_outcome"] is None
        assert state["publication_window_last_inspection"] is None
        assert state["publication_window_reinspect_required"] is False
        with pytest.raises(ProjectFlowError, match="confirmation_required"):
            flow.confirm_publication_window("Researcher")
        assert _counts(project) == (0, 0, 0, 132, 132)
    finally:
        flow.close()


def test_both_preparation_modes_cannot_have_simultaneous_offers(project_run):
    project, run, other = project_run
    flow = _flow(project, run, other)
    try:
        flow.offer_publication_materialisation()
        assert flow.state()["publication_materialisation_offer"] is not None
        flow.offer_publication_window()
        assert flow.state()["publication_materialisation_offer"] is None
        assert flow.state()["publication_window_offer"] is not None
        flow.offer_publication_materialisation()
        assert flow.state()["publication_window_offer"] is None
        assert flow.state()["publication_materialisation_offer"] is not None
    finally:
        flow.close()


def test_experimental_gui_action_and_source_free_labels_are_allowlisted():
    from pathlib import Path
    root = Path(__file__).parents[1]
    from desktop_source import project_ui_source
    content = project_ui_source()
    for action in ("publication_window_inspect", "publication_window_offer",
                   "publication_window_confirm", "publication_window_dismiss"):
        assert action in content
    for key in ("publication-window-heading", "publication-window-preview",
                "publication-window-confirm", "publication-window-reinspect",
                "publication-window-recovery", "publication-window-inspection"):
        assert "data-testid=" + key in content
    assert "if value is not None:" in content
    assert "flow.confirm_publication_window(value)" in content
