"""Atomic, idempotent researcher-approved term/run admission acceptance.

No source HTTP, model, licence, archive, GUI or real biomedical data is used.
The test observes actual SQLite project state, exact compiler expressions,
unknown counts and rollback of every constituent audit/storage write.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
from uuid import uuid4

import pytest

from research_y.projects import create_project, open_project
from research_y.query_compiler import QueryCompilationError, compile_both
from research_y.storage import (
    ApprovedTerm, StrategyGroup, approve_strategy, get_strategy_snapshot,
    list_run_queries,
)
from research_y.strategy_admission import (
    StrategyAdmissionError, commit_approved_strategy,
)


def _groups():
    return (
        StrategyGroup("rv", "Right ventricle", (
            ApprovedTerm("right ventricle", "researcher", True),
            ApprovedTerm("right-ventricle", "deterministic", True,
                         "Spacing alternative"),
            ApprovedTerm("disabled provisional term", "researcher", True, enabled=False),
        )),
        StrategyGroup("ecls", "Extracorporeal support", (
            ApprovedTerm("ECMO", "researcher", True),
            ApprovedTerm("extracorporeal membrane oxygenation", "ai", True,
                         "Researcher accepted a proposal"),
        )),
    )


def _accept(p, *, request_id=None, groups=None, **changes):
    params = dict(request_id=request_id or str(uuid4()), theme="RV failure",
                  groups=groups if groups is not None else _groups(),
                  approved_by="Researcher", approval_confirmed=True)
    params.update(changes)
    return commit_approved_strategy(p, **params)


def _counts(p):
    with closing(sqlite3.connect(p.database_path)) as db:
        return tuple(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                     for table in ("strategy_versions", "strategy_groups",
                                   "search_runs", "source_queries", "audit_events"))


def test_approved_atomic_admission_has_exact_broad_or_queries_and_unknown_counts(tmp_path):
    p = create_project(tmp_path, "Broad real project")
    before = _counts(p)
    entry = _accept(p)
    assert entry.newly_created is True
    assert entry.version_number == 1 and entry.run_status == "pending"
    assert entry.query_count == 4
    assert _counts(p) == (before[0] + 1, before[1] + 2,
                          before[2] + 1, before[3] + 4, before[4] + 6)
    reopened = open_project(p.root)
    frozen = get_strategy_snapshot(reopened, entry.strategy_version_id)
    assert frozen["logic"] == "OR"
    assert frozen["theme"] == "RV failure"
    assert frozen["approved_by"] == "Researcher"
    assert frozen["groups"][0]["terms"][2]["enabled"] is False
    assert frozen["groups"][1]["terms"][1]["origin"] == "ai"
    compiled = compile_both(frozen)
    queries = list_run_queries(reopened, entry.run_id)
    assert len(queries) == entry.query_count
    by_source_group = {(q.source_name, q.group_id): q for q in queries}
    for source in compiled:
        assert source.executed is False
        assert source.reported_matches is None
        for group in source.groups:
            planned = by_source_group[(source.source_name, group.group_id)]
            assert planned.exact_query == group.exact_group_query
            assert planned.status == "pending"
            assert planned.reported_matches is None
            assert planned.parameters == {}
    assert '[All Fields]' in by_source_group['pubmed', 'rv'].exact_query
    assert ' OR ' in by_source_group['pubmed', 'rv'].exact_query
    assert 'TS=(' in by_source_group['wos', 'ecls'].exact_query
    assert "disabled provisional term" not in ''.join(q.exact_query for q in queries)
    assert all(' AND ' not in q.exact_query and ' NOT ' not in q.exact_query
               for q in queries)
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute(
            "SELECT status,completed_at_utc FROM search_runs WHERE run_id=?",
            (entry.run_id,)).fetchone() == ("pending", None)
        events = db.execute(
            "SELECT event_type,details_json FROM audit_events "
            "WHERE event_type IN ('strategy_approved','search_run_created',"
            "'source_query_planned') ORDER BY event_id"
        ).fetchall()
        assert len(events) == 6
        assert all(json.loads(payload).get("admission_request_id") == entry.request_id
                   for _, payload in events)


def test_lost_reply_replay_has_zero_new_writes_and_identical_ids(tmp_path):
    p = create_project(tmp_path, "Stable replay")
    request_id = str(uuid4())
    first = _accept(p, request_id=request_id)
    before = _counts(p)
    replay = _accept(p, request_id=request_id)
    assert not replay.newly_created
    assert replace(replay, newly_created=True) == first
    assert _counts(p) == before
    with closing(sqlite3.connect(p.database_path)) as db:
        assert len(db.execute("SELECT query_id FROM source_queries").fetchall()) == 4
    assert _accept(open_project(p.root), request_id=request_id) == replay


def test_conflicting_request_never_mints_a_second_strategy_or_run(tmp_path):
    p = create_project(tmp_path, "Refuse mutation")
    req = str(uuid4())
    original = _accept(p, request_id=req)
    old = _counts(p)
    changed = (StrategyGroup("g", "Different",
                            (ApprovedTerm("different", "researcher", True),)),)
    with pytest.raises(StrategyAdmissionError, match="^admission_conflict$"):
        _accept(p, request_id=req, groups=changed)
    with pytest.raises(StrategyAdmissionError, match="^admission_conflict$"):
        _accept(p, request_id=req, approved_by="Different person")
    assert _counts(p) == old
    assert _accept(p, request_id=req).run_id == original.run_id


def test_new_approval_is_a_new_frozen_version_not_an_edited_old_version(tmp_path):
    p = create_project(tmp_path, "Version history")
    old = approve_strategy(p, theme="Existing prior approval", groups=_groups(),
                           approved_by="Researcher", approval_confirmed=True)
    old_snapshot = get_strategy_snapshot(p, old.strategy_version_id)
    fresh = _accept(p)
    assert fresh.version_number == old.version_number + 1
    again = _accept(p, theme="Another approved strategy")
    assert again.version_number == fresh.version_number + 1
    assert len({old.strategy_version_id, fresh.strategy_version_id,
                again.strategy_version_id}) == 3
    assert get_strategy_snapshot(p, old.strategy_version_id) == old_snapshot


def test_disabled_or_empty_groups_remain_in_approval_but_are_not_planned(tmp_path):
    p = create_project(tmp_path, "Disabled group")
    groups = (
        StrategyGroup("disabled", "Disabled", (
            ApprovedTerm("unused term", "researcher", True, enabled=False),)),
        StrategyGroup("active", "Active", (
            ApprovedTerm("one literal", "researcher", True),)),
    )
    result = _accept(p, groups=groups)
    assert result.query_count == 2
    assert {q.group_id for q in list_run_queries(p, result.run_id)} == {"active"}
    snapshot = get_strategy_snapshot(p, result.strategy_version_id)
    assert len(snapshot['groups']) == 2


@pytest.mark.parametrize('change,expected_exception', [
    ({"approval_confirmed": False}, StrategyAdmissionError),
    ({"approval_confirmed": 1}, StrategyAdmissionError),
    ({"request_id": "not-a-uuid"}, StrategyAdmissionError),
    ({"request_id": 12}, StrategyAdmissionError),
    ({"theme": " "}, ValueError),
    ({"approved_by": " "}, ValueError),
    ({"groups": ()}, ValueError),
    ({"groups": (StrategyGroup("g", "G", (
        ApprovedTerm("unapproved", "researcher", False),)),)}, ValueError),
    ({"groups": (StrategyGroup("g", "G", (
        ApprovedTerm("ai with no reason", "ai", True),)),)}, ValueError),
    ({"groups": (StrategyGroup("g", "G", (
        ApprovedTerm("quoted \"unsafe\"", "researcher", True),)),)}, QueryCompilationError),
    ({"groups": (StrategyGroup("g", "G", (
        ApprovedTerm("unused", "researcher", True, enabled=False),)),)}, StrategyAdmissionError),
])
def test_invalid_strategy_does_not_write_audit_or_source_rows(tmp_path, change, expected_exception):
    p = create_project(tmp_path, "Invalid admission")
    baseline = _counts(p)
    with pytest.raises(expected_exception):
        _accept(p, **change)
    assert _counts(p) == baseline


def test_audit_failure_rolls_back_version_run_groups_and_every_query(tmp_path, monkeypatch):
    import research_y.strategy_admission as module
    p = create_project(tmp_path, "Atomic rollback")
    before = _counts(p)
    original = module._audit
    attempts = 0

    def fail_third_audit(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 4:
            raise OSError('injected audit writer failure')
        return original(*args, **kwargs)

    monkeypatch.setattr(module, '_audit', fail_third_audit)
    request_id = str(uuid4())
    with pytest.raises(OSError, match="injected audit"):
        _accept(p, request_id=request_id)
    assert attempts == 4
    assert _counts(p) == before
    monkeypatch.setattr(module, '_audit', original)
    recovered = _accept(p, request_id=request_id)
    assert recovered.newly_created
    assert recovered.version_number == 1
    assert recovered.query_count == 4


def test_inconsistent_existing_request_blocks_replay_without_mutating(tmp_path, monkeypatch):
    import research_y.strategy_admission as module
    p = create_project(tmp_path, "Evidence validation")
    req = str(uuid4())
    original = _accept(p, request_id=req)
    before = _counts(p)
    actual = module._plans

    def changed_plans(snapshot, request_id):
        planned = list(actual(snapshot, request_id))
        item = list(planned[0]); item[3] += ' OR "unexpected"[All Fields]'
        planned[0] = tuple(item)
        return tuple(planned)

    monkeypatch.setattr(module, '_plans', changed_plans)
    with pytest.raises(StrategyAdmissionError, match="^admission_evidence_invalid$"):
        _accept(p, request_id=req)
    assert _counts(p) == before
    monkeypatch.setattr(module, '_plans', actual)
    assert _accept(p, request_id=req).run_id == original.run_id


def test_parallel_requests_receive_distinct_versions_without_partial_rows(tmp_path):
    p = create_project(tmp_path, "Simultaneous approval")
    requests = [str(uuid4()) for _ in range(6)]

    def work(req):
        return _accept(p, request_id=req)

    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = list(pool.map(work, requests))
    assert sorted(x.version_number for x in entries) == list(range(1, 7))
    assert len({x.run_id for x in entries}) == 6
    assert len({x.strategy_version_id for x in entries}) == 6
    counts = _counts(p)
    assert counts[0] == 6 and counts[1] == 12
    assert counts[2] == 6 and counts[3] == 24


def test_parallel_same_request_id_creates_exactly_one_version(tmp_path):
    p = create_project(tmp_path, "Concurrent replay")
    req = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _accept(p, request_id=req), range(2)))
    assert results[0].run_id == results[1].run_id
    assert sorted(x.newly_created for x in results) == [False, True]
    assert _counts(p)[0:4] == (1, 2, 1, 4)
