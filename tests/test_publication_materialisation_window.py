"""Disk-backed, source-preserving two-batch consent and recovery regressions."""
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
from research_y.publication_materialisation_window import (
    MAX_SESSION_RECORDS, MaterialisationConflict,
    confirm_two_batch_materialisation, preview_two_batch_materialisation,
)


def _rid(index):
    return f"99999999-9999-4999-8999-{index + 1:012x}"


@pytest.fixture
def project_run(tmp_path):
    project = create_project(tmp_path, "Synthetic two-batch review")
    strategy, run = str(uuid4()), str(uuid4())
    stamp = project.created_at_utc
    qpub, qwos = str(uuid4()), str(uuid4())
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (strategy, 1, stamp, "{}"))
        db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                   (strategy, "all", "All original terms OR", 0))
        db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                   (run, strategy, stamp, "incomplete", None))
        for source, qid, query in (
            ("pubmed", qpub, '"one"[All Fields]'),
            ("wos", qwos, 'TS=("one")'),
        ):
            db.execute("INSERT INTO source_queries VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (qid, run, strategy, "all", source, query,
                        "{}", None, "incomplete", None))
        sources, memberships = [], []
        for i in range(132):
            pubmed = i % 2 == 0
            name = "pubmed" if pubmed else "wos"
            sid = str(10000000 + i) if pubmed else f"WOS:{10000000 + i}"
            record = {
                "title": "Identical abstract title" if i in (0, 1) else f"Distinct abstract {i}",
                "identifiers": {"doi": ["10.1000/shared"] if pubmed else "10.1000/shared"},
                "pmid" if pubmed else "uid": sid,
            }
            payload = ({"source": "NCBI PubMed EFetch XML", "record": record}
                       if pubmed else
                       {"provider": "wos_starter", "database": "WOS", "record": record})
            sources.append((_rid(i), run, name, sid, stamp, identity._json(payload)))
            memberships.append((qpub if pubmed else qwos, _rid(i), run, name))
        db.executemany("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)", sources)
        db.executemany("INSERT INTO query_retrievals VALUES(?,?,?,?)", memberships)
    return project, run, qpub


def _rows(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        def sql(query):
            return db.execute(query).fetchall()
        return {
            "sources": sql("SELECT * FROM source_retrievals ORDER BY retrieval_id"),
            "memberships": sql("SELECT * FROM query_retrievals ORDER BY retrieval_id"),
            "publications": sql("SELECT * FROM publications ORDER BY publication_id"),
            "links": sql("SELECT * FROM publication_retrievals ORDER BY retrieval_id"),
            "audit": sql("SELECT * FROM audit_events WHERE event_type='publication_identity_v1' ORDER BY event_id"),
        }


def _confirm(project, run, token):
    return confirm_two_batch_materialisation(
        project, run, expected_revision=token,
        actor="Synthetic Researcher", confirmed=True)


def test_two_batch_window_previews_and_commits_only_approved_ids(project_run):
    project, run, _ = project_run
    originals = _rows(project)
    checksum = sha256(project.database_path.read_bytes()).hexdigest()
    plan = preview_two_batch_materialisation(project, run)
    assert plan["batch_sizes"] == [64, 64]
    assert plan["batch_count"] == 2
    assert plan["maximum_batches"] == 2
    assert plan["maximum_source_records"] == MAX_SESSION_RECORDS == 128
    assert plan["proposed_source_records"] == 128
    assert plan["unmaterialised_retrievals"] == 132
    assert plan["existing_publication_hypotheses"] == 0
    assert plan["requires_explicit_confirmation"] is True
    assert plan["unattended_processing"] is False
    assert "Identical abstract title" not in str(plan)
    assert sha256(project.database_path.read_bytes()).hexdigest() == checksum

    reply = _confirm(project, run, plan["revision"])
    assert reply["committed_batches"] == 2
    assert reply["materialised_in_session"] == 128
    assert reply["unmaterialised_retrievals_remaining"] == 4
    assert reply["requires_new_preview_for_next_session"] is True
    assert reply["partial_commits_possible_if_interrupted"] is True
    assert reply["global_unique_publications"] is None
    assert reply["source_retrieval_verified"] is False
    assert reply["verified_complete"] is False
    assert reply["deduplication_complete"] is False

    reopened = open_project(project.root)
    after = _rows(reopened)
    assert after["sources"] == originals["sources"]
    assert after["memberships"] == originals["memberships"]
    assert len(after["publications"]) == 128
    assert len(after["links"]) == 128
    assert len(after["audit"]) == 128
    assert [row[0] for row in after["links"]] == [_rid(i) for i in range(128)]
    assert len({row[1] for row in after["links"]}) == 128
    assert all(identity.read_publication(reopened, row[1]).retrievals[0]["decision"]["status"]
               == "review_required" for row in after["links"][:3])
    assert preview_two_batch_materialisation(reopened, run)["batch_sizes"] == [4]
    with pytest.raises(MaterialisationConflict, match="stale"):
        _confirm(reopened, run, plan["revision"])
    assert _rows(reopened) == after


@pytest.mark.parametrize("modified", ["query", "source", "new_link"])
def test_approval_refuses_changes_before_first_commit(project_run, modified):
    project, run, qid = project_run
    first = preview_two_batch_materialisation(project, run)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        if modified == "query":
            db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?", (qid,))
        elif modified == "source":
            raw = db.execute("SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?",
                             (_rid(0),)).fetchone()[0]
            value = identity._object(raw)
            value["record"]["title"] = "Changed source title"
            db.execute("UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?",
                       (identity._json(value), _rid(0)))
        else:
            # Original single-source identity writer remains authoritative.
            pass
    if modified == "new_link":
        identity.materialise_retrieval(project, _rid(0), actor="External researcher")
    before = _rows(project)
    with pytest.raises(MaterialisationConflict, match="stale"):
        _confirm(project, run, first["revision"])
    assert _rows(project) == before


def test_second_batch_sqlite_failure_retains_first_and_refuses_replay(project_run):
    project, run, _ = project_run
    plan = preview_two_batch_materialisation(project, run)
    original = _rows(project)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute(
            "CREATE TRIGGER fail_second_batch BEFORE INSERT ON publication_retrievals "
            "WHEN NEW.retrieval_id='" + _rid(64) + "' "
            "BEGIN SELECT RAISE(ABORT,'injected second-batch failure'); END")
    with pytest.raises(sqlite3.DatabaseError):
        _confirm(project, run, plan["revision"])
    recovered = open_project(project.root)
    after = _rows(recovered)
    assert after["sources"] == original["sources"]
    assert after["memberships"] == original["memberships"]
    assert len(after["links"]) == 64
    assert len(after["publications"]) == 64
    assert len(after["audit"]) == 64
    assert [row[0] for row in after["links"]] == [_rid(i) for i in range(64)]
    with pytest.raises(MaterialisationConflict, match="stale"):
        _confirm(recovered, run, plan["revision"])
    assert _rows(recovered) == after
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("DROP TRIGGER fail_second_batch")
    again = preview_two_batch_materialisation(recovered, run)
    assert again["batch_sizes"] == [64, 4]
    assert _confirm(recovered, run, again["revision"])["materialised_in_session"] == 68
    assert len(_rows(recovered)["audit"]) == 132


def test_scope_change_between_batches_stops_without_unapproved_second_commit(
    project_run, monkeypatch,
):
    project, run, qid = project_run
    from research_y import publication_materialisation_window as window
    original = window.materialise_run_batch
    did_change = []
    def changed_after_first(*args, **kwargs):
        result = original(*args, **kwargs)
        if not did_change:
            did_change.append(True)
            with closing(sqlite3.connect(project.database_path)) as db, db:
                db.execute("UPDATE source_queries SET status='failed' WHERE query_id=?",
                           (qid,))
        return result
    plan = preview_two_batch_materialisation(project, run)
    with monkeypatch.context() as patched:
        patched.setattr(window, "materialise_run_batch", changed_after_first)
        with pytest.raises(MaterialisationConflict, match="scope"):
            _confirm(project, run, plan["revision"])
    assert len(_rows(project)["links"]) == 64
    with pytest.raises(MaterialisationConflict, match="stale"):
        _confirm(open_project(project.root), run, plan["revision"])


@pytest.mark.parametrize("at_batch,expected_commits", [(1, 0), (2, 64)])
def test_unrelated_new_strategy_between_preview_and_locked_write_is_refused(
    project_run, monkeypatch, at_batch, expected_commits,
):
    """Review finding: protect the original project-wide fence in BEGIN IMMEDIATE.

    The insertion does not alter the selected run's _plan revision. A
    read-only pre-check would therefore miss this TOCTOU race.
    """
    project, run, _ = project_run
    from research_y import publication_materialisation_window as window
    original_writer = window.materialise_run_batch
    called = []
    plan = preview_two_batch_materialisation(project, run)

    def external_write(*args, **kwargs):
        called.append(True)
        if len(called) == at_batch:
            with closing(sqlite3.connect(project.database_path)) as db, db:
                db.execute(
                    "INSERT INTO strategy_versions VALUES(?,?,?,?)",
                    (str(uuid4()), 2, project.created_at_utc, "{}"))
        return original_writer(*args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(window, "materialise_run_batch", external_write)
        with pytest.raises(MaterialisationConflict, match="Original scope"):
            _confirm(project, run, plan["revision"])
    reopened = open_project(project.root)
    after = _rows(reopened)
    assert len(after["links"]) == expected_commits
    assert len(after["publications"]) == expected_commits
    assert len(after["audit"]) == expected_commits
    with pytest.raises(MaterialisationConflict, match="stale"):
        _confirm(reopened, run, plan["revision"])
    assert _rows(reopened) == after


def test_trusted_host_allowlist_and_one_use_approval(project_run):
    project, run, _ = project_run
    preview = execute_command(ApplicationCommand.for_project(
        project, "publication_window_preview", run_id=run))
    assert preview["batch_sizes"] == [64, 64]
    confirm = ApplicationCommand.for_project(
        project, "publication_window_confirm", run_id=run,
        publication_view_revision=preview["revision"],
        publication_actor="Researcher", publication_confirmed=True)
    assert "source" not in repr(confirm)
    result = execute_command(confirm)
    assert result["committed_batches"] == 2
    with pytest.raises(ApplicationCommandError) as stale:
        execute_command(confirm)
    assert stale.value.code == "publication_materialisation_stale"
    with pytest.raises(ApplicationCommandError) as denied:
        ApplicationCommand.for_project(
            project, "publication_window_confirm", run_id=run,
            publication_view_revision=preview["revision"],
            publication_actor="Researcher", publication_confirmed=False)
    assert denied.value.code == "invalid_command"


@pytest.mark.parametrize("confirmed,revision", [
    (False, "a" * 64), (None, "a" * 64), (1, "a" * 64),
    (True, ""), (True, None), (True, "not-a-revision"),
])
def test_confirmation_requires_literal_consent_and_hash(project_run, confirmed, revision):
    project, run, _ = project_run
    with pytest.raises(ValueError):
        confirm_two_batch_materialisation(
            project, run, expected_revision=revision, actor="Researcher",
            confirmed=confirmed)
    assert not _rows(project)["links"]
