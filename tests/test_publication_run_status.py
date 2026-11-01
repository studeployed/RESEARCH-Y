"""Parent-run status is evidence, not a synonym for per-query status."""
from contextlib import closing
import sqlite3

import pytest

from research_y.publication_identity import (
    StalePublicationError, materialise_retrieval, read_publication,
    associate_retrieval, reverse_association,
)
from research_y.publication_fields import select_source_field, clear_source_field
from test_publication_identity import store, db_rows, pair, move, link_args


def set_run_status(p, snapshot, status):
    run_id = snapshot.retrievals[0]["run_id"]
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("UPDATE search_runs SET status=? WHERE run_id=?", (status, run_id))


def identity_state(p):
    return {t: db_rows(p, t) for t in ("publications", "publication_retrievals", "audit_events")}


def test_parent_status_is_distinct_evidence_without_changing_query_status(store):
    p, ids, a, b = pair(store)
    queries = db_rows(p, "source_queries")
    set_run_status(p, a, "failed")
    fresh = read_publication(p, a.publication_id)
    assert fresh.revision != a.revision
    assert fresh.retrievals[0]["run_status"] == "failed"
    assert all(m["run_status"] == "failed" and m["status"] == "incomplete"
               for m in fresh.retrievals[0]["memberships"])
    assert db_rows(p, "source_queries") == queries


@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize("status", ["failed", "cancelled", "completed_with_warnings"])
def test_changed_parent_status_rejects_stale_source_or_target_review(store, side, status):
    p, ids = store
    # Different runs ensure the unchanged side's token remains valid.
    a = materialise_retrieval(p, ids[0], actor="Researcher")
    b = materialise_retrieval(p, ids[2], actor="Researcher")
    set_run_status(p, a if side == "source" else b, status)
    before = identity_state(p)
    with pytest.raises(StalePublicationError):
        associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))
    assert identity_state(p) == before
    fresh_a, fresh_b = [read_publication(p, v.publication_id) for v in (a, b)]
    unchanged, original = (fresh_b, b) if side == "source" else (fresh_a, a)
    assert unchanged.revision == original.revision
    result = associate_retrieval(p, ids[0], b.publication_id, **link_args(fresh_a, fresh_b))
    assert {r["run_status"] for r in result.retrievals} == {"incomplete", status}
    assert not result.deduplication_complete


@pytest.mark.parametrize("operation", ["select", "clear"])
def test_changed_parent_status_rejects_stale_field_decision(store, operation):
    p, ids, a, b = pair(store)
    if operation == "clear":
        a = select_source_field(p, a.publication_id, "title", retrieval_id=ids[0],
                                path=("record", "title"), expected_revision=a.revision,
                                actor="Researcher", reason="Original choice")
    set_run_status(p, a, "failed")
    before = identity_state(p)
    with pytest.raises(StalePublicationError):
        if operation == "select":
            select_source_field(p, a.publication_id, "title", retrieval_id=ids[0],
                                path=("record", "title"), expected_revision=a.revision,
                                actor="Researcher", reason="Stale choice")
        else:
            clear_source_field(p, a.publication_id, "title", expected_revision=a.revision,
                               actor="Researcher", reason="Stale clear")
    assert identity_state(p) == before


def test_parent_run_evidence_exists_without_query_memberships(store):
    p, ids = store
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("DELETE FROM query_retrievals WHERE retrieval_id=?", (ids[0],))
    a = materialise_retrieval(p, ids[0], actor="Researcher")
    assert not a.retrievals[0]["memberships"]
    set_run_status(p, a, "failed")
    fresh = read_publication(p, a.publication_id)
    assert fresh.retrievals[0]["run_status"] == "failed"
    assert fresh.revision != a.revision
    # Dynamic run status must not be part of the immutable source-row checksum.
    assert fresh.retrievals[0]["source_sha256"] == a.retrievals[0]["source_sha256"]


def test_changed_parent_status_rejects_stale_reversal(store):
    p, ids, a, b, merged, event = move(store)
    empty = read_publication(p, a.publication_id)
    set_run_status(p, merged, "failed")
    before = identity_state(p)
    with pytest.raises(StalePublicationError):
        reverse_association(p, ids[0], event, expected_current_revision=merged.revision,
                            expected_restored_revision=empty.revision,
                            actor="Researcher", evidence="Stale undo")
    assert identity_state(p) == before
