"""P1-06j1 offline SQLite acceptance for revision-fenced run materialisation."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import sqlite3
from uuid import uuid4

import pytest

from research_y import publication_identity as identity, result_counts
from research_y.projects import create_project, open_project
from research_y.publication_run_materialisation import (
    MAX_BATCH, MaterialisationConflict, materialise_run_batch,
    preview_run_materialisation,
)


def uid():
    return str(uuid4())


@pytest.fixture
def case(tmp_path):
    project = create_project(tmp_path, "Materialise synthetic results")
    run, other, strategy = uid(), uid(), uid()
    queries = {}
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (strategy, 1, project.created_at_utc, "{}"))
        for index, group in enumerate(("g1", "g2")):
            db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                       (strategy, group, group, index))
        for run_id in (run, other):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id, strategy, project.created_at_utc, "incomplete", None))
            for group in ("g1", "g2"):
                for source in ("pubmed", "wos"):
                    query_id = uid()
                    db.execute(
                        "INSERT INTO source_queries(query_id,run_id,strategy_version_id,"
                        "group_id,source_name,exact_query) VALUES(?,?,?,?,?,?)",
                        (query_id, run_id, strategy, group, source,
                         '"ECMO"[All Fields]' if source == "pubmed" else 'TS=("ECMO")'),
                    )
                    queries[run_id, group, source] = query_id
    return project, run, other, queries


def add(case, *, source="pubmed", name="123", groups=("g1",), run=None):
    project, primary, _, queries = case
    run_id = primary if run is None else run
    record = dict(title="SAME SYNTHETIC TITLE",
                  identifiers={"doi": ["10.1234/same"]} if source == "pubmed"
                  else {"doi": "10.1234/same"},
                  **({"pmid": name} if source == "pubmed" else {"uid": name}))
    payload = (dict(source="NCBI PubMed EFetch XML", record=record,
                    rights_review_required_for_abstract_redistribution=True)
               if source == "pubmed" else
               dict(provider="wos_starter", database="WOS", record=record,
                    rights_status="licence_review_required"))
    rid = uid()
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (rid, run_id, source, name, project.created_at_utc, identity._json(payload)))
        for group in groups:
            db.execute("INSERT INTO query_retrievals VALUES(?,?,?,?)",
                       (queries[run_id, group, source], rid, run_id, source))
    return rid


def rows(project, table):
    with closing(sqlite3.connect(project.database_path)) as db:
        if table == "audit_events":
            # A newly created project already has its required project_created
            # audit receipt. These assertions count only publication-identity
            # events introduced by the operation under test.
            return db.execute(
                "SELECT * FROM audit_events WHERE event_type=? ORDER BY event_id",
                (identity.IDENTITY_EVENT,),
            ).fetchall()
        return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def do_batch(project, run, *, size=MAX_BATCH):
    preview = preview_run_materialisation(project, run, batch_size=size)
    return materialise_run_batch(
        project, run, expected_revision=preview["revision"], actor="Researcher",
        confirmed=True, batch_size=size,
    )


def test_preview_reads_without_writing_and_never_invents_final_counts(case):
    project, run, _, _ = case
    add(case)
    digest = sha256(project.database_path.read_bytes()).hexdigest()
    preview = preview_run_materialisation(project, run)
    assert preview["unmaterialised_retrievals"] == 1
    assert preview["source_records_retained"] == preview["batch_count"] == 1
    assert not preview["materialisation_complete"]
    assert preview["global_unique_publications"] is None
    assert not preview["verified_complete"] and not preview["deduplication_complete"]
    assert preview["no_network_requests"] is True
    assert sha256(project.database_path.read_bytes()).hexdigest() == digest


def test_bounded_batches_preserve_provider_records_and_never_automatically_merge(case):
    project, run, _, _ = case
    p1 = add(case, source="pubmed", name="123", groups=("g1", "g2"))
    p2 = add(case, source="pubmed", name="456", groups=("g2",))
    w1 = add(case, source="wos", name="WOS:123", groups=("g1", "g2"))
    before = {t: rows(project, t) for t in
              ("source_retrievals", "query_retrievals", "source_queries", "search_runs")}
    original = result_counts.read_run_counts(project, run)
    one = do_batch(project, run, size=2)
    assert one["materialised_in_batch"] == 2
    assert one["unmaterialised_retrievals_remaining"] == 1
    assert not one["materialisation_complete"] and not one["deduplication_complete"]
    reopened = open_project(project.root)
    two = do_batch(reopened, run, size=2)
    assert two["materialised_in_batch"] == 1
    assert two["materialisation_complete"] and two["global_unique_publications"] is None
    assert preview_run_materialisation(project, run)["batch_count"] == 0
    assert len(rows(project, "publications")) == 3
    assert len(rows(project, "publication_retrievals")) == 3
    assert len(rows(project, "audit_events")) == 3
    assert {t: rows(project, t) for t in before} == before
    assert all(identity.read_publication(project, pub_id).active
               for (pub_id, *_rest) in rows(project, "publications"))
    for retrieval in (p1, p2, w1):
        with closing(sqlite3.connect(project.database_path)) as db:
            pub_id = db.execute("SELECT publication_id FROM publication_retrievals WHERE retrieval_id=?",
                                (retrieval,)).fetchone()[0]
        snapshot = identity.read_publication(project, pub_id)
        assert snapshot.retrievals[0]["decision"]["status"] == "review_required"
        assert not snapshot.deduplication_complete
    after = result_counts.read_run_counts(project, run)
    assert after.totals["source_record_sum"] == original.totals["source_record_sum"] == 3
    assert after.totals["global_publication_identities"] == 3
    assert after.totals["global_unique_publications"] is None


@pytest.mark.parametrize("confirmed", [False, None, 1, "yes"])
def test_no_implicit_confirmation(case, confirmed):
    project, run, _, _ = case
    add(case)
    preview = preview_run_materialisation(project, run)
    with pytest.raises(ValueError, match="confirmation"):
        materialise_run_batch(project, run, expected_revision=preview["revision"],
                              actor="Researcher", confirmed=confirmed)
    assert rows(project, "publications") == []


@pytest.mark.parametrize("size", [0, -1, 65, True, 1.0, "64"])
def test_rejects_unbounded_and_noninteger_work(case, size):
    project, run, _, _ = case
    with pytest.raises(ValueError, match="batch size"):
        preview_run_materialisation(project, run, batch_size=size)
    assert rows(project, "audit_events") == []


def test_stale_revision_never_materialises_a_different_next_batch(case):
    project, run, _, _ = case
    a, b = add(case, name="123"), add(case, name="456")
    preview = preview_run_materialisation(project, run, batch_size=1)
    identity.materialise_retrieval(project, a, actor="Researcher")
    before = rows(project, "audit_events")
    with pytest.raises(MaterialisationConflict, match="stale"):
        materialise_run_batch(project, run, expected_revision=preview["revision"],
                              actor="Researcher", confirmed=True, batch_size=1)
    assert rows(project, "audit_events") == before
    assert len(rows(project, "publication_retrievals")) == 1
    assert b != a


def test_stale_query_status_requires_fresh_preview(case):
    project, run, _, queries = case
    add(case)
    preview = preview_run_materialisation(project, run)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",
                   (queries[run, "g1", "pubmed"],))
    with pytest.raises(MaterialisationConflict, match="stale"):
        materialise_run_batch(project, run, expected_revision=preview["revision"],
                              actor="Researcher", confirmed=True)
    assert rows(project, "publication_retrievals") == []


def test_other_run_and_queryless_records_are_not_lost(case):
    project, run, other, _ = case
    a = add(case, groups=())
    b = add(case, run=other)
    result = do_batch(project, run)
    assert result["materialised_in_batch"] == 1
    assert identity.read_retrieval_history(project, a)
    assert identity.read_retrieval_history(project, b) == ()
    assert preview_run_materialisation(project, other)["unmaterialised_retrievals"] == 1


def test_no_work_cannot_be_replayed_as_success(case):
    project, run, _, _ = case
    a = add(case)
    first = preview_run_materialisation(project, run)
    do_batch(project, run)
    second = preview_run_materialisation(project, run)
    assert second["materialisation_complete"]
    assert second["revision"] != first["revision"]
    with pytest.raises(MaterialisationConflict):
        materialise_run_batch(project, run, expected_revision=first["revision"],
                              actor="Researcher", confirmed=True)
    with pytest.raises(ValueError, match="No unmaterialised"):
        materialise_run_batch(project, run, expected_revision=second["revision"],
                              actor="Researcher", confirmed=True)
    assert len(rows(project, "audit_events")) == 1


def test_sqlite_audit_failure_rolls_back_every_identity_in_batch(case):
    project, run, _, _ = case
    add(case, name="123")
    add(case, name="456")
    preview = preview_run_materialisation(project, run)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("CREATE TRIGGER fixture_abort_audit BEFORE INSERT ON audit_events "
                   "BEGIN SELECT RAISE(ABORT, 'synthetic audit write failure'); END")
    with pytest.raises(sqlite3.DatabaseError):
        materialise_run_batch(project, run, expected_revision=preview["revision"],
                              actor="Researcher", confirmed=True)
    assert rows(project, "publications") == []
    assert rows(project, "publication_retrievals") == []
    assert rows(project, "audit_events") == []


def test_invalid_source_and_unknown_run_fail_without_write(case):
    project, run, _, _ = case
    retrieval = add(case)
    preview = preview_run_materialisation(project, run)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("UPDATE source_retrievals SET original_metadata_json='{}' "
                   "WHERE retrieval_id=?", (retrieval,))
    with pytest.raises((ValueError, RuntimeError)):
        materialise_run_batch(project, run, expected_revision=preview["revision"],
                              actor="Researcher", confirmed=True)
    with pytest.raises(ValueError):
        preview_run_materialisation(project, uid())
    assert rows(project, "publication_retrievals") == []


def test_batches_are_hard_capped_to_64_records(case):
    project, run, _, _ = case
    for n in range(1, 68):
        add(case, name=str(n))
    first = do_batch(project, run)
    assert first["materialised_in_batch"] == 64
    assert first["unmaterialised_retrievals_remaining"] == 3
    second = do_batch(open_project(project.root), run)
    assert second["materialised_in_batch"] == 3
    assert len(rows(project, "publication_retrievals")) == 67
