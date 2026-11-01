"""P1-06a disk-backed identity/provenance fixtures; no provider access."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from research_y.projects import create_project, open_project, ProjectFormatError
from research_y.publication_identity import (
    IDENTITY_EVENT, FIELD_EVENT, PublicationIntegrityError, StalePublicationError,
    materialise_retrieval, read_publication, associate_retrieval, reverse_association,
)
from research_y.publication_fields import select_source_field, clear_source_field


@pytest.fixture
def store(tmp_path):
    p = create_project(tmp_path, "Publication foundation")
    version, run, later = [str(uuid4()) for _ in range(3)]
    sources = ("pubmed", "wos", "pubmed")
    retrievals = [str(uuid4()) for _ in sources]
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)", (version, 1, p.created_at_utc, '{"synthetic":true}'))
        for index, group in enumerate(("g1", "g2")):
            db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)", (version, group, group, index))
        for rid in (run, later):
            db.execute("INSERT INTO search_runs(run_id,strategy_version_id,created_at_utc,status) "
                       "VALUES(?,?,?,'incomplete')", (rid, version, p.created_at_utc))
        for index, (retrieval, source) in enumerate(zip(retrievals, sources)):
            rid = later if index == 2 else run
            record = {"title": "Synthetic title" if source == "pubmed" else "Different source title",
                      "doi": "10.0000/synthetic-supplement", "abstract": None,
                      "format": "conference abstract", "abstract_number": str(index + 1),
                      "authors": [{"name": "Synthetic Researcher"}], "year": 2026}
            metadata = {"source": source, "record": record, "abstract_status": "not_returned_by_source",
                        "rights_status": "licence_review_required", "unknown_field": {"preserve": True}}
            db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                       (retrieval, rid, source, "synthetic-1", p.created_at_utc, json.dumps(metadata)))
            for group in ("g1", "g2"):
                query = str(uuid4())
                db.execute("INSERT INTO source_queries(query_id,run_id,strategy_version_id,group_id,"
                           "source_name,exact_query,reported_matches,status) VALUES(?,?,?,?,?,?,?,?)",
                           (query, rid, version, group, source, '"synthetic"', 7, "incomplete"))
                db.execute("INSERT INTO query_retrievals VALUES(?,?,?,?)", (query, retrieval, rid, source))
    return p, retrievals


def db_rows(p, table):
    with closing(sqlite3.connect(p.database_path)) as db:
        return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def protected_rows(p):
    return {name: db_rows(p, name) for name in (
        "source_retrievals", "query_retrievals", "source_queries", "search_runs", "strategy_versions", "strategy_groups")}


def pair(store):
    p, ids = store
    a, b = [materialise_retrieval(p, i, actor="Researcher") for i in ids[:2]]
    return p, ids, a, b


def link_args(a, b):
    return dict(expected_source_revision=a.revision, expected_target_revision=b.revision,
                actor="Researcher", evidence="Explicit synthetic bibliographic comparison", same_publication_confirmed=True)


def move(store):
    p, ids, a, b = pair(store)
    merged = associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))
    event_id = next(r["association_event_id"] for r in merged.retrievals if r["retrieval_id"] == ids[0])
    return p, ids, a, b, merged, event_id


def test_materialisation_is_idempotent_and_preserves_source_counts(store):
    p, ids = store
    before = protected_rows(p)
    first = materialise_retrieval(p, ids[0], actor="Researcher")
    audit = db_rows(p, "audit_events")
    again = materialise_retrieval(open_project(p.root), ids[0], actor="Researcher")
    assert first == again
    assert len(db_rows(p, "publications")) == 1
    assert db_rows(p, "audit_events") == audit
    assert protected_rows(p) == before
    assert len(first.retrievals[0]["memberships"]) == 2
    assert first.retrievals[0]["decision"]["status"] == "review_required"
    assert not first.deduplication_complete and not first.export_permissions_verified
    assert first.chosen_fields == {}


def test_shared_supplement_identifier_never_automatically_merges(store):
    p, ids = store
    result = [materialise_retrieval(p, i, actor="Researcher") for i in ids]
    assert len({v.publication_id for v in result}) == 3
    assert all(len(v.retrievals) == 1 for v in result)
    assert len(db_rows(p, "source_retrievals")) == 3


def test_full_paper_and_conference_abstract_are_not_automatically_collapsed(store):
    p, ids = store
    with closing(sqlite3.connect(p.database_path)) as db, db:
        raw = json.loads(db.execute("SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?", (ids[1],)).fetchone()[0])
        raw["record"]["format"] = "full journal article"
        db.execute("UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?", (json.dumps(raw), ids[1]))
    _, _, a, b = pair(store)
    assert a.publication_id != b.publication_id


def test_confirmed_association_keeps_originals_all_groups_and_retained_empty_identity(store):
    p, ids = store
    before = protected_rows(p)
    p, ids, a, b, result, event = move(store)
    assert len(result.retrievals) == 2
    assert len([m for r in result.retrievals for m in r["memberships"]]) == 4
    assert {r["source_name"] for r in result.retrievals} == {"pubmed", "wos"}
    assert len({r["original_metadata"]["record"]["title"] for r in result.retrievals}) == 2
    empty = read_publication(p, a.publication_id)
    assert not empty.active
    assert len(db_rows(p, "publications")) == 2
    assert protected_rows(p) == before
    current = next(r for r in result.retrievals if r["retrieval_id"] == ids[0])
    assert current["decision"]["status"] == "confirmed_match"
    assert current["decision"]["before"] == a.publication_id
    assert materialise_retrieval(p, ids[0], actor="Another researcher") == result


def test_repeated_association_is_noop_even_with_old_request_token(store):
    p, ids, a, b = pair(store)
    args = link_args(a, b)
    first = associate_retrieval(p, ids[0], b.publication_id, **args)
    audit = db_rows(p, "audit_events")
    assert associate_retrieval(p, ids[0], b.publication_id, **args) == first
    assert db_rows(p, "audit_events") == audit


def test_cross_run_association_preserves_distinct_run_and_query_provenance(store):
    p, ids, a, b, merged, _ = move(store)
    later = materialise_retrieval(p, ids[2], actor="Researcher")
    combined = associate_retrieval(p, ids[2], merged.publication_id, **link_args(later, merged))
    assert len(combined.retrievals) == 3
    assert len({r["run_id"] for r in combined.retrievals}) == 2
    assert len([m for r in combined.retrievals for m in r["memberships"]]) == 6
    assert all(m["reported_matches"] == 7 and m["status"] == "incomplete" for r in combined.retrievals for m in r["memberships"])


def test_reversal_is_append_only_idempotent_and_does_not_revive_old_revision(store):
    p, ids, a, b, merged, event = move(store)
    empty = read_publication(p, a.publication_id)
    args = dict(expected_current_revision=merged.revision, expected_restored_revision=empty.revision,
                actor="Researcher", evidence="Corrected mistaken publication association")
    restored = reverse_association(p, ids[0], event, **args)
    assert restored.publication_id == a.publication_id
    assert len(restored.retrievals) == len(read_publication(p, b.publication_id).retrievals) == 1
    assert restored.revision != a.revision
    assert restored.retrievals[0]["decision"]["status"] == "review_required"
    assert restored.retrievals[0]["decision"]["reverses_event_id"] == event
    audit = db_rows(p, "audit_events")
    assert reverse_association(p, ids[0], event, **args) == restored
    assert db_rows(p, "audit_events") == audit
    with pytest.raises(StalePublicationError):
        associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))


@pytest.mark.parametrize("which", ["source", "target"])
def test_stale_review_rejected_without_mutation(store, which):
    p, ids, a, b = pair(store)
    chosen = a if which == "source" else b
    select_source_field(p, chosen.publication_id, "title", retrieval_id=chosen.retrievals[0]["retrieval_id"],
                        path=("record", "title"), expected_revision=chosen.revision, actor="Researcher", reason="Source checked")
    before = db_rows(p, "publication_retrievals"), db_rows(p, "audit_events")
    with pytest.raises(StalePublicationError):
        associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))
    assert before == (db_rows(p, "publication_retrievals"), db_rows(p, "audit_events"))


@pytest.mark.parametrize("confirmed", [False, None, 1, "true"])
def test_explicit_confirmation_is_not_coerced(store, confirmed):
    p, ids, a, b = pair(store)
    args = link_args(a, b)
    args["same_publication_confirmed"] = confirmed
    with pytest.raises(ValueError, match="confirmation"):
        associate_retrieval(p, ids[0], b.publication_id, **args)
    assert read_publication(p, a.publication_id) == a


def test_reversal_rejects_later_decision(store):
    p, ids, a, b, merged, event = move(store)
    third = materialise_retrieval(p, ids[2], actor="Researcher")
    newest = associate_retrieval(p, ids[0], third.publication_id, **link_args(merged, third))
    with pytest.raises(StalePublicationError):
        reverse_association(p, ids[0], event, expected_current_revision=newest.revision,
                            expected_restored_revision=read_publication(p, a.publication_id).revision,
                            actor="Researcher", evidence="Stale decision")


def test_empty_identity_is_not_a_new_association_target(store):
    p, ids, a, b, merged, _ = move(store)
    empty = read_publication(p, a.publication_id)
    with pytest.raises(ValueError, match="active"):
        associate_retrieval(p, ids[1], empty.publication_id, **link_args(merged, empty))


def test_publication_can_be_reopened_after_relocation(store, tmp_path):
    p, ids, a, b, merged, _ = move(store)
    relocated = Path(shutil.move(str(p.root), str(tmp_path / "moved")))
    assert read_publication(open_project(relocated), merged.publication_id) == merged


def test_returned_metadata_is_detached_from_persistent_source(store):
    p, ids, a, b = pair(store)
    a.retrievals[0]["original_metadata"]["record"]["title"] = "Changed only in memory"
    assert read_publication(p, a.publication_id).retrievals[0]["original_metadata"]["record"]["title"] == "Synthetic title"


@pytest.mark.parametrize("mutation", ["source", "audit_pointer", "chosen_metadata"])
def test_inconsistent_stored_evidence_is_not_silently_repaired(store, mutation):
    p, ids, a, b = pair(store)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        if mutation == "source":
            db.execute("UPDATE source_retrievals SET original_metadata_json='{}' WHERE retrieval_id=?", (ids[0],))
        elif mutation == "audit_pointer":
            db.execute("UPDATE publication_retrievals SET decision_provenance_json=? WHERE retrieval_id=?",
                       ('{"version":1,"event_id":99999999}', ids[0]))
        else:
            db.execute("UPDATE publications SET chosen_metadata_json=? WHERE publication_id=?",
                       ('{"title":"legacy untraced value"}', a.publication_id))
    with pytest.raises(PublicationIntegrityError):
        read_publication(p, a.publication_id)


@pytest.mark.parametrize("raw", ["[]", "not-json", '{"a":1,"a":2}', '{"a":NaN}'],
                         ids=["array", "invalid", "duplicate-key", "nonfinite"])
def test_malformed_source_payload_fails_before_publication_creation(store, raw):
    p, ids = store
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?", (raw, ids[0]))
    before = db_rows(p, "audit_events")
    with pytest.raises(PublicationIntegrityError):
        materialise_retrieval(p, ids[0], actor="Researcher")
    assert not db_rows(p, "publications") and db_rows(p, "audit_events") == before


@pytest.mark.parametrize("operation", ["materialise", "associate", "reverse", "select", "clear"])
def test_failed_audit_rolls_back_whole_operation(store, operation):
    p, ids, a, b = pair(store)
    merged = None
    if operation == "reverse":
        merged = associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))
        event = next(r["association_event_id"] for r in merged.retrievals if r["retrieval_id"] == ids[0])
    if operation == "clear":
        a = select_source_field(p, a.publication_id, "title", retrieval_id=ids[0], path=("record", "title"),
                                expected_revision=a.revision, actor="Researcher", reason="Select original")
    with closing(sqlite3.connect(p.database_path)) as db:
        db.execute("CREATE TRIGGER reject_publication_audit BEFORE INSERT ON audit_events "
                   "WHEN NEW.event_type LIKE 'publication_%' BEGIN SELECT RAISE(ABORT,'audit unavailable'); END")
    before = {t: db_rows(p, t) for t in ("publications", "publication_retrievals", "audit_events")}
    sources = protected_rows(p)
    with pytest.raises(sqlite3.IntegrityError, match="audit unavailable"):
        if operation == "materialise":
            materialise_retrieval(p, ids[2], actor="Researcher")
        elif operation == "associate":
            associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))
        elif operation == "reverse":
            reverse_association(p, ids[0], event, expected_current_revision=merged.revision,
                                expected_restored_revision=read_publication(p, a.publication_id).revision,
                                actor="Researcher", evidence="Undo")
        elif operation == "select":
            select_source_field(p, a.publication_id, "title", retrieval_id=ids[0], path=("record", "title"),
                                expected_revision=a.revision, actor="Researcher", reason="Select original")
        else:
            clear_source_field(p, a.publication_id, "title", expected_revision=a.revision,
                               actor="Researcher", reason="Clear original")
    assert {t: db_rows(p, t) for t in before} == before
    assert protected_rows(p) == sources


def test_link_update_failure_does_not_leave_successful_audit(store):
    p, ids, a, b = pair(store)
    with closing(sqlite3.connect(p.database_path)) as db:
        db.execute("CREATE TRIGGER reject_link BEFORE UPDATE ON publication_retrievals "
                   "BEGIN SELECT RAISE(ABORT,'link unavailable'); END")
    audit = db_rows(p, "audit_events")
    with pytest.raises(sqlite3.IntegrityError, match="link unavailable"):
        associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))
    assert db_rows(p, "audit_events") == audit
    assert read_publication(p, a.publication_id) == a


def test_future_annotations_are_not_stranded_by_association(store):
    p, ids, a, b = pair(store)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("INSERT INTO classifications VALUES(?,?,?,?,?,?,?)",
                   (str(uuid4()), a.publication_id, "format", "abstract", "user_confirmed", '{}', p.created_at_utc))
    with pytest.raises(ValueError, match="annotations"):
        associate_retrieval(p, ids[0], b.publication_id, **link_args(a, b))
    assert len(db_rows(p, "classifications")) == 1


def test_other_project_handle_rejected_before_mutation(store, tmp_path):
    p, ids, a, b = pair(store)
    other = create_project(tmp_path, "Other project")
    wrong = replace(p, root=other.root)
    with pytest.raises(ProjectFormatError):
        materialise_retrieval(wrong, ids[0], actor="Researcher")
    assert not db_rows(other, "publications")


def test_unknown_source_and_publication_ids_are_not_fabricated(store):
    p, ids = store
    with pytest.raises(KeyError):
        materialise_retrieval(p, str(uuid4()), actor="Researcher")
    with pytest.raises(KeyError):
        read_publication(p, str(uuid4()))
    assert not db_rows(p, "publications")


@pytest.mark.parametrize("bad", ["", " ", "line\nbreak", "x" * 201], ids=["empty", "space", "control", "oversized"])
def test_actor_validation(store, bad):
    p, ids = store
    with pytest.raises(ValueError):
        materialise_retrieval(p, ids[0], actor=bad)
    assert not db_rows(p, "publications")


def test_sql_like_actor_is_preserved_as_data(store):
    p, ids = store
    actor = "'); DROP TABLE publications; --"
    result = materialise_retrieval(p, ids[0], actor=actor)
    assert result.retrievals[0]["decision"]["actor"] == actor
    assert len(db_rows(p, "publications")) == 1


def test_concurrent_materialisation_creates_one_identity(store):
    p, ids = store
    code = """import sys
from research_y.projects import open_project
from research_y.publication_identity import materialise_retrieval
print(materialise_retrieval(open_project(sys.argv[1]), sys.argv[2], actor='Concurrent fixture').publication_id)
"""
    children = []
    try:
        for _ in range(2):
            children.append(subprocess.Popen([sys.executable, "-c", code, str(p.root), ids[0]],
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        outputs = [child.communicate(timeout=20) for child in children]
        assert all(child.returncode == 0 for child in children), outputs
        assert outputs[0][0] == outputs[1][0]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()
    assert len(db_rows(p, "publications")) == 1
    assert len([r for r in db_rows(p, "audit_events") if r[2] == IDENTITY_EVENT]) == 1


def test_abrupt_process_exit_leaves_prior_committed_identities_intact(store):
    p, ids, a, b = pair(store)
    before = {t: db_rows(p, t) for t in ("publications", "publication_retrievals", "audit_events")}
    code = """import os, sys
from research_y.projects import open_project
import research_y.publication_identity as m
real = m._record_link
def crash(db, *args, **kwargs):
    result = real(db, *args, **kwargs)
    db.execute('PRAGMA cache_size=5')
    db.execute("INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES('fixture','crash',?)", ('X'*1000000,))
    os._exit(33)
m._record_link = crash
m.materialise_retrieval(open_project(sys.argv[1]),sys.argv[2],actor='Crash fixture')
"""
    child = subprocess.run([sys.executable, "-c", code, str(p.root), ids[2]],
                           capture_output=True, text=True, timeout=20)
    assert child.returncode == 33, child.stderr
    assert Path(str(p.database_path) + "-journal").exists()
    reopened = open_project(p.root)
    assert {t: db_rows(reopened, t) for t in before} == before
    assert materialise_retrieval(reopened, ids[2], actor="Recovery fixture").active


def test_identity_history_remains_inspectable_after_reversal(store):
    from research_y.publication_identity import read_retrieval_history
    p, ids, a, b, merged, event = move(store)
    assert read_retrieval_history(p, ids[2]) == ()
    original = read_retrieval_history(p, ids[0])
    reverse_association(p, ids[0], event, expected_current_revision=merged.revision,
                        expected_restored_revision=read_publication(p, a.publication_id).revision,
                        actor="Researcher", evidence="Undo decision")
    history = read_retrieval_history(p, ids[0])
    assert history[:-1] == original
    assert [e["action"] for e in history] == ["materialise", "associate", "reverse"]
    assert history[-1]["reverses_event_id"] == event
    with closing(sqlite3.connect(p.database_path)) as db, db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM audit_events WHERE event_id=?", (event,))


def test_history_chain_missing_predecessor_is_rejected(store):
    import research_y.publication_identity as module
    p, ids, a, b = pair(store)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        # Simulate inconsistent but append-only imported history, not a licence
        # to silently repair it. Normal operations cannot generate this chain.
        prior = a.retrievals[0]["decision"]
        bad = {**prior, "before": b.publication_id, "previous_event_id": 999999}
        eid = module._audit(db, IDENTITY_EVENT, bad)
        db.execute("UPDATE publication_retrievals SET decision_provenance_json=? WHERE retrieval_id=?",
                   (json.dumps({"version": 1, "event_id": eid}), ids[0]))
    with pytest.raises(PublicationIntegrityError):
        module.read_retrieval_history(p, ids[0])
