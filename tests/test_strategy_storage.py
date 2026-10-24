"""P1-02b storage acceptance fixtures: approval, frozen history and pending jobs.

No source networking, query compilation, or user interface is exercised here.
"""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from research_y.projects import create_project, open_project
from research_y.storage import (
    ApprovedTerm,
    StrategyGroup,
    approve_strategy,
    create_search_run,
    get_strategy_snapshot,
    list_run_queries,
    plan_source_query,
)


def _groups() -> tuple[StrategyGroup, ...]:
    return (
        StrategyGroup(
            "g-right", "Right ventricle",
            (
                ApprovedTerm("right ventricle", "researcher", True),
                ApprovedTerm("right-ventricle", "deterministic", True,
                             "Hyphenation variant"),
            ),
        ),
        StrategyGroup(
            "g-ecls", "Extracorporeal support",
            (
                ApprovedTerm("ECMO", "researcher", True),
                ApprovedTerm("extracorporeal membrane oxygenation",
                             "ai", True, "Terminology proposed for user approval"),
                ApprovedTerm("excluded variant", "researcher", True, enabled=False),
            ),
        ),
    )


def _approve(project, groups=None, **changes):
    kwargs = {
        "theme": "Right heart failure",
        "groups": _groups() if groups is None else groups,
        "approved_by": "Researcher",
        "approval_confirmed": True,
    }
    kwargs.update(changes)
    return approve_strategy(project, **kwargs)


def _db(project):
    return sqlite3.connect(project.database_path)


def _audit_count(project) -> int:
    with closing(_db(project)) as db:
        return db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]


def test_approve_and_reopen_persists_exact_or_union_and_provenance(tmp_path: Path) -> None:
    project = create_project(tmp_path, "My search")
    version = _approve(project)
    reopened = open_project(project.root)
    snapshot = get_strategy_snapshot(reopened, version.strategy_version_id)
    assert version.version_number == 1
    assert snapshot["logic"] == "OR"
    assert snapshot["theme"] == "Right heart failure"
    assert snapshot["approved_by"] == "Researcher"
    assert [g["group_id"] for g in snapshot["groups"]] == ["g-right", "g-ecls"]
    assert snapshot["groups"][0]["terms"][1]["text"] == "right-ventricle"
    assert snapshot["groups"][1]["terms"][1]["origin"] == "ai"
    assert snapshot["groups"][1]["terms"][1]["approved"] is True
    assert snapshot["groups"][1]["terms"][2]["enabled"] is False
    with closing(_db(project)) as db:
        assert db.execute("SELECT COUNT(*) FROM strategy_groups").fetchone()[0] == 2
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='strategy_approved'"
        ).fetchone()[0] == 1


def test_frozen_strategy_versions_cannot_be_mutated_and_run_pins_version(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Two versions")
    first = _approve(project)
    old_snapshot = get_strategy_snapshot(project, first.strategy_version_id)
    run = create_search_run(project, first.strategy_version_id)
    second = _approve(
        project,
        (StrategyGroup("new", "Other", (ApprovedTerm("other", "researcher", True),)),),
        theme="New theme",
    )
    assert (first.version_number, second.version_number) == (1, 2)
    assert get_strategy_snapshot(project, first.strategy_version_id) == old_snapshot
    assert get_strategy_snapshot(project, second.strategy_version_id)["theme"] == "New theme"
    with closing(_db(project)) as db, db:
        assert db.execute(
            "SELECT strategy_version_id FROM search_runs WHERE run_id=?",
            (run.run_id,),
        ).fetchone()[0] == first.strategy_version_id
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE strategy_versions SET snapshot_json='{}' "
                "WHERE strategy_version_id=?", (first.strategy_version_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM strategy_groups WHERE strategy_version_id=?",
                (first.strategy_version_id,),
            )


@pytest.mark.parametrize(
    "bad",
    [
        {"approval_confirmed": False},
        {"approval_confirmed": 1},
        {"approved_by": " "},
        {"theme": ""},
        {"groups": ()},
        {"groups": (StrategyGroup("g", "Group", (ApprovedTerm("X", "ai", False, "Reason"),)),)},
        {"groups": (StrategyGroup("g", "Group", (ApprovedTerm("X", "ai", True),)),)},
        {"groups": (StrategyGroup("g", "Group", (ApprovedTerm("X", "unknown", True),)),)},
        {"groups": (StrategyGroup("g", "Group", (ApprovedTerm(" ", "researcher", True),)),)},
    ],
)
def test_invalid_or_unapproved_strategy_never_persists(tmp_path: Path, bad: dict) -> None:
    project = create_project(tmp_path, "Reject")
    before = _audit_count(project)
    with pytest.raises((ValueError, TypeError)):
        _approve(project, **bad)
    with closing(_db(project)) as db:
        assert db.execute("SELECT COUNT(*) FROM strategy_versions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM strategy_groups").fetchone()[0] == 0
    assert _audit_count(project) == before


@pytest.mark.parametrize(
    "groups",
    [
        (
            StrategyGroup("dup", "First", (ApprovedTerm("A", "researcher", True),)),
            StrategyGroup("dup", "Second", (ApprovedTerm("B", "researcher", True),)),
        ),
        (
            StrategyGroup("g", "First", (
                ApprovedTerm("A", "researcher", True),
                ApprovedTerm("A", "researcher", True),
            )),
        ),
    ],
)
def test_duplicate_groups_or_atomic_terms_cannot_appear_in_snapshot(
    tmp_path: Path, groups,
) -> None:
    project = create_project(tmp_path, "Duplicates")
    with pytest.raises(ValueError, match="Duplicate"):
        _approve(project, groups)
    assert _audit_count(project) == 1


def test_create_pending_run_and_unknown_strategy_failure(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Run")
    with pytest.raises(KeyError):
        create_search_run(project, "does-not-exist")
    assert _audit_count(project) == 1
    version = _approve(project)
    run = create_search_run(project, version.strategy_version_id)
    assert run.status == "pending"
    assert run.strategy_version_id == version.strategy_version_id
    with closing(_db(project)) as db:
        row = db.execute(
            "SELECT status, completed_at_utc FROM search_runs WHERE run_id=?",
            (run.run_id,),
        ).fetchone()
        assert row == ("pending", None)
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='search_run_created'"
        ).fetchone()[0] == 1


def test_plan_queries_are_persistent_unexecuted_and_have_unknown_counts(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Queries")
    version = _approve(project)
    run = create_search_run(project, version.strategy_version_id)
    q1 = plan_source_query(
        project, run_id=run.run_id, group_id="g-right", source_name="pubmed",
        exact_query='("right ventricle"[All Fields] OR "right-ventricle"[All Fields])',
        parameters={"limits": None, "format": "json"},
    )
    q2 = plan_source_query(
        project, run_id=run.run_id, group_id="g-ecls", source_name="wos",
        exact_query='TS=("extracorporeal membrane oxygenation" OR ECMO)',
    )
    moved = tmp_path / "moved"
    Path(shutil.move(str(project.root), str(moved)))
    reopened = open_project(moved)
    queries = list_run_queries(reopened, run.run_id)
    assert [q.query_id for q in queries] == [q1.query_id, q2.query_id]
    assert queries[0].exact_query == q1.exact_query
    assert queries[0].parameters == {"limits": None, "format": "json"}
    assert queries[0].reported_matches is None
    assert queries[1].reported_matches is None
    with closing(_db(reopened)) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM source_retrievals"
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='source_query_planned'"
        ).fetchone()[0] == 2


def test_wrong_group_and_unknown_run_are_rejected_atomically(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Wrong group")
    first = _approve(project)
    second = _approve(
        project, (StrategyGroup("other", "Only other", (
            ApprovedTerm("ABC", "researcher", True),)),),
    )
    run = create_search_run(project, first.strategy_version_id)
    before = _audit_count(project)
    for run_id, group in ((run.run_id, "other"), ("unknown", "g-right")):
        with pytest.raises((KeyError, ValueError)):
            plan_source_query(
                project, run_id=run_id, group_id=group, source_name="pubmed",
                exact_query="abc[All Fields]",
            )
    assert second.version_number == 2
    assert list_run_queries(project, run.run_id) == []
    assert _audit_count(project) == before


def test_non_pending_run_and_wrong_source_are_not_queued(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Statuses")
    version = _approve(project)
    run = create_search_run(project, version.strategy_version_id)
    with pytest.raises(ValueError, match="primary"):
        plan_source_query(
            project, run_id=run.run_id, group_id="g-right",
            source_name="unimplemented-provider", exact_query="X",
        )
    with closing(_db(project)) as db, db:
        db.execute("UPDATE search_runs SET status='incomplete' WHERE run_id=?", (run.run_id,))
    with pytest.raises(ValueError, match="pending"):
        plan_source_query(
            project, run_id=run.run_id, group_id="g-right",
            source_name="pubmed", exact_query="X",
        )
    assert list_run_queries(project, run.run_id) == []


def test_invalid_parameters_are_rejected_before_any_write(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Parameters")
    version = _approve(project)
    run = create_search_run(project, version.strategy_version_id)
    before = _audit_count(project)
    with pytest.raises(ValueError, match="strict JSON"):
        plan_source_query(
            project, run_id=run.run_id, group_id="g-right",
            source_name="pubmed", exact_query="X",
            parameters={"limit": float("nan")},
        )
    with pytest.raises(ValueError, match="keys"):
        plan_source_query(
            project, run_id=run.run_id, group_id="g-right",
            source_name="pubmed", exact_query="X",
            parameters={3: "invalid"},
        )
    assert _audit_count(project) == before
    assert list_run_queries(project, run.run_id) == []


def test_audit_failure_rolls_back_strategy_and_run_creation(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Atomic operations")
    with closing(_db(project)) as db, db:
        db.execute(
            "CREATE TRIGGER reject_approval BEFORE INSERT ON audit_events "
            "WHEN NEW.event_type='strategy_approved' "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        _approve(project)
    with closing(_db(project)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM strategy_versions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM strategy_groups").fetchone()[0] == 0
        db.execute("DROP TRIGGER reject_approval")
    version = _approve(project)
    assert version.version_number == 1
    with closing(_db(project)) as db, db:
        db.execute(
            "CREATE TRIGGER reject_run BEFORE INSERT ON audit_events "
            "WHEN NEW.event_type='search_run_created' "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        create_search_run(project, version.strategy_version_id)
    with closing(_db(project)) as db:
        assert db.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0] == 0


def test_audit_failure_rolls_back_source_query(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Query atomicity")
    version = _approve(project)
    run = create_search_run(project, version.strategy_version_id)
    with closing(_db(project)) as db, db:
        db.execute(
            "CREATE TRIGGER reject_query BEFORE INSERT ON audit_events "
            "WHEN NEW.event_type='source_query_planned' "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        plan_source_query(
            project, run_id=run.run_id, group_id="g-ecls",
            source_name="wos", exact_query='TS=("ECMO")',
        )
    assert list_run_queries(project, run.run_id) == []
    assert _audit_count(project) == 3  # created, approved, run; failed query absent


def test_unknown_snapshot_does_not_create_any_data(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Unknown")
    with pytest.raises(KeyError):
        get_strategy_snapshot(project, "not-here")
    assert _audit_count(project) == 1
