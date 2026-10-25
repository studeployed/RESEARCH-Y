"""Offline database/recovery fixtures; never contact PubMed or persist secrets."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3

import pytest

from research_y.projects import create_project, open_project
from research_y.pubmed_ids import PubMedIdentifierPage
from research_y.pubmed_partition import CountedPartition, DateWindow, PubMedPartitionResult
from research_y.pubmed_probe import PubMedCountProbe
from research_y.pubmed_checkpoint_store import (
    CheckpointIntegrityError, create_pubmed_checkpoint,
    commit_pubmed_checkpoint_page, inspect_pubmed_checkpoint,
    pause_pubmed_checkpoint,
)
from research_y.pubmed_checkpoint_resume import resume_pubmed_checkpoint
from research_y.storage import (
    ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query,
)

Q = '("ECMO"[All Fields])'
WINDOW = DateWindow(date(2025, 1, 1), date(2025, 1, 2))


def project_query(tmp_path: Path, name="Demo"):
    project = create_project(tmp_path, name)
    version = approve_strategy(
        project, theme="ECMO", approved_by="Reviewer", approval_confirmed=True,
        groups=(StrategyGroup("g1", "ECMO", (ApprovedTerm("ECMO", "researcher", True),)),),
    )
    run = create_search_run(project, version.strategy_version_id)
    query = plan_source_query(
        project, run_id=run.run_id, group_id="g1", source_name="pubmed", exact_query=Q,
    )
    return project, query.query_id


def plan(count: int = 4, *, parts=False):
    nodes = ()
    if parts:
        left, right = WINDOW.split()
        nodes = (
            CountedPartition(0, None, WINDOW, WINDOW.query_for(Q), count, 0, "split", "large query"),
            CountedPartition(1, 0, left, left.query_for(Q), count // 2, 1, "collect", "left"),
            CountedPartition(2, 0, right, right.query_for(Q), count-count//2, 1, "collect", "right"),
        )
    return PubMedPartitionResult(
        Q, WINDOW, count, "incomplete", (), nodes, (), (),
    )


def page(query=Q, ids=("1", "2"), *, retstart=0, count=4, retmax=None):
    return PubMedIdentifierPage(
        query, retstart, len(ids) if retmax is None else retmax, count,
        tuple(ids), query, (), (), "a" * 64, "2026-10-25T00:00:00+00:00",
    )


class FakeProvider:
    def __init__(self, ids_by_query):
        self.ids_by_query = ids_by_query
        self.counts = []
        self.pages = []
        self.bad_count = False
        self.bad_translation = False
        self.fail_at_offset = None

    def probe(self, query, *, allow_crdt_partition=False):
        self.counts.append((query, allow_crdt_partition))
        value = len(self.ids_by_query[query]) + (1 if self.bad_count else 0)
        accepted = query if not self.bad_translation else '"unexpected"[All Fields]'
        reasons = () if accepted == query else ("changed",)
        return PubMedCountProbe(query, accepted, value, "2026-10-25T00:00:00Z",
                                (), reasons, accepted == query)

    def fetch_esearch_page(self, query, *, retstart, retmax):
        self.pages.append((query, retstart, retmax))
        if retstart == self.fail_at_offset:
            raise RuntimeError("SECRET-CREDENTIAL-NEVER-LOG")
        ids = self.ids_by_query[query]
        return json.dumps({"esearchresult": {
            "count": str(len(ids)), "retmax": str(retmax), "retstart": str(retstart),
            "idlist": ids[retstart:retstart+retmax], "querytranslation": query,
            "warninglist": {"outputmessages": []},
            "errorlist": {"phrasesnotfound": []},
        }}).encode()


def test_checkpoint_plan_is_tied_to_approved_pubmed_query(tmp_path):
    project, query_id = project_query(tmp_path)
    result = create_pubmed_checkpoint(project, query_id, plan(), page_size=2)
    assert result.root_count == 4 and result.pages_expected == 2
    assert result.pages_committed == 0 and result.stored_status == "incomplete"
    with closing(sqlite3.connect(project.database_path)) as db, db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT reported_matches,status FROM source_queries WHERE query_id=?", (query_id,)).fetchone() == (4, "incomplete")
        assert db.execute("SELECT event_type FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()[0] == "pubmed_checkpoint_created"


def test_checkpoint_plan_idempotent_but_changed_counts_rejected(tmp_path):
    project, q = project_query(tmp_path)
    create_pubmed_checkpoint(project, q, plan(), page_size=2)
    create_pubmed_checkpoint(project, q, plan(), page_size=2)
    with pytest.raises(CheckpointIntegrityError, match="different immutable"):
        create_pubmed_checkpoint(project, q, plan(6), page_size=2)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='pubmed_checkpoint_created'").fetchone()[0] == 1


def test_validated_page_and_individual_ids_commit_atomically(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    result = commit_pubmed_checkpoint_page(p, q, page())
    assert result.pmids == ("1", "2") and result.next_offsets == ((-1, 2),)
    assert result.pages_committed == 1 and not result.identifiers_reconciled
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM pubmed_checkpoint_ids").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='pubmed_checkpoint_page_committed'").fetchone()[0] == 1


def test_identical_replay_does_not_add_duplicate_audit(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    commit_pubmed_checkpoint_page(p, q, page())
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM pubmed_checkpoint_pages").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='pubmed_checkpoint_page_committed'").fetchone()[0] == 1


def test_replay_with_conflicting_ids_refused_without_overwrite(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    with pytest.raises(CheckpointIntegrityError, match="immutable"):
        commit_pubmed_checkpoint_page(p, q, page(ids=("1", "99")))
    assert inspect_pubmed_checkpoint(p, q).pmids == ("1", "2")


def test_cannot_skip_offsets_or_commit_duplicate_pmid_on_later_page(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    with pytest.raises(CheckpointIntegrityError, match="skip"):
        commit_pubmed_checkpoint_page(p, q, page(ids=("3", "4"), retstart=2))
    commit_pubmed_checkpoint_page(p, q, page())
    with pytest.raises(CheckpointIntegrityError, match="overlap"):
        commit_pubmed_checkpoint_page(p, q, page(ids=("1", "4"), retstart=2))
    assert inspect_pubmed_checkpoint(p, q).pages_committed == 1


def test_reopen_and_relocate_retains_committed_pages(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    reopened = open_project(p.root)
    assert inspect_pubmed_checkpoint(reopened, q).pmids == ("1", "2")
    dest = tmp_path / "moved"
    p.root.rename(dest)
    relocated = open_project(dest)
    assert inspect_pubmed_checkpoint(relocated, q).next_offsets == ((-1, 2),)


def test_resume_fetches_missing_page_not_older_committed_page(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    remote = FakeProvider({Q: ["1", "2", "3", "4"]})
    out = resume_pubmed_checkpoint(open_project(p.root), q, remote)
    assert out.status == "identifiers_reconciled_metadata_pending"
    assert out.snapshot.pmids == ("1", "2", "3", "4")
    assert out.snapshot.identifiers_reconciled
    assert not out.source_retrieval_verified
    assert remote.pages == [(Q, 2, 2)]
    assert len(remote.counts) == 2
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute("SELECT status FROM source_queries WHERE query_id=?", (q,)).fetchone()[0] == "incomplete"


def test_crash_before_commit_refetches_and_does_not_claim_complete(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    remote = FakeProvider({Q: ["1", "2", "3", "4"]})
    remote.fail_at_offset = 2
    first = resume_pubmed_checkpoint(p, q, remote)
    assert first.status == "incomplete" and "SECRET-CREDENTIAL" not in repr(first)
    assert first.snapshot.pmids == ("1", "2")
    assert first.snapshot.pages_committed == 1
    second_provider = FakeProvider({Q: ["1", "2", "3", "4"]})
    second = resume_pubmed_checkpoint(open_project(p.root), q, second_provider)
    assert second.snapshot.identifiers_reconciled
    assert second_provider.pages == [(Q, 2, 2)]


def test_database_trigger_failure_rolls_back_page_ids_and_audit(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("""CREATE TRIGGER deny_checkpoint_audit BEFORE INSERT ON audit_events
            WHEN NEW.event_type='pubmed_checkpoint_page_committed'
            BEGIN SELECT RAISE(ABORT, 'simulated failing audit'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        commit_pubmed_checkpoint_page(p, q, page())
    snap = inspect_pubmed_checkpoint(p, q)
    assert snap.pmids == () and snap.pages_committed == 0
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM pubmed_checkpoint_ids").fetchone()[0] == 0
        db.execute("DROP TRIGGER deny_checkpoint_audit")
    resumed = resume_pubmed_checkpoint(p, q, FakeProvider({Q: ["1", "2", "3", "4"]}))
    assert resumed.snapshot.identifiers_reconciled


def test_existing_pages_are_sql_immutable(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    with closing(sqlite3.connect(p.database_path)) as db, db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE pubmed_checkpoint_pages SET page_json='{}'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM pubmed_checkpoint_ids")


def test_tampered_page_digest_detected_before_reuse(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("DROP TRIGGER immutable_pubmed_checkpoint_pages_update")
        db.execute("UPDATE pubmed_checkpoint_pages SET page_json='{}'")
    with pytest.raises(CheckpointIntegrityError, match="checksum"):
        inspect_pubmed_checkpoint(open_project(p.root), q)


def test_tampered_identifier_index_detected_even_with_intact_page(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("DROP TRIGGER immutable_pubmed_checkpoint_ids_update")
        db.execute("UPDATE pubmed_checkpoint_ids SET pmid='998' WHERE pmid='2'")
    with pytest.raises(CheckpointIntegrityError, match="identifier index"):
        inspect_pubmed_checkpoint(p, q)


def test_source_count_drift_leaves_pages_and_returns_incomplete(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    commit_pubmed_checkpoint_page(p, q, page())
    fake = FakeProvider({Q: ["1", "2", "3", "4"]})
    fake.bad_count = True
    result = resume_pubmed_checkpoint(p, q, fake)
    assert result.status == "incomplete"
    assert result.snapshot.pmids == ("1", "2")
    assert fake.pages == []


def test_review_required_query_does_not_fetch_missing_pages(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    fake = FakeProvider({Q: ["1", "2", "3", "4"]})
    fake.bad_translation = True
    assert resume_pubmed_checkpoint(p, q, fake).status == "incomplete"
    assert fake.pages == []


def test_paused_checkpoint_survives_reopening_and_does_not_mark_run_verified(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    paused = pause_pubmed_checkpoint(p, q)
    assert paused.stored_status == "paused"
    assert inspect_pubmed_checkpoint(open_project(p.root), q).stored_status == "paused"
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute("SELECT status FROM source_queries WHERE query_id=?", (q,)).fetchone()[0] == "paused"


def test_two_date_partitions_reconcile_global_unique_ids(tmp_path):
    p, q = project_query(tmp_path)
    result = plan(count=6, parts=True)
    create_pubmed_checkpoint(p, q, result, page_size=2)
    left, right = result.counted_partitions[1:]
    fake = FakeProvider({Q: list(map(str, range(1, 7))),
                         left.exact_subquery: ["1", "2", "3"],
                         right.exact_subquery: ["4", "5", "6"]})
    resumed = resume_pubmed_checkpoint(p, q, fake)
    assert resumed.snapshot.identifiers_reconciled
    assert resumed.snapshot.pages_expected == 4
    assert len(resumed.snapshot.pmids) == 6
    assert all('[crdt]' in query for query, _, _ in fake.pages)
    assert len(fake.counts) == 4  # baseline, each date interval, final baseline


def test_provider_date_count_mismatch_preserves_prior_completed_leaves(tmp_path):
    p, q = project_query(tmp_path)
    result = plan(count=6, parts=True)
    create_pubmed_checkpoint(p, q, result, page_size=2)
    left, right = result.counted_partitions[1:]
    commit_pubmed_checkpoint_page(p, q, page(left.exact_subquery, ids=("1", "2"), count=3, retmax=2))
    fake = FakeProvider({Q: list(map(str, range(1, 7))),
                         left.exact_subquery: ["1", "2", "3"],
                         right.exact_subquery: ["4", "5"]})
    out = resume_pubmed_checkpoint(p, q, fake)
    assert out.status == "incomplete"
    assert out.snapshot.pmids == ("1", "2")
    assert fake.pages == []


def test_partition_count_plan_overlap_or_gap_is_refused(tmp_path):
    p, q = project_query(tmp_path)
    root, left, right = plan(count=6, parts=True).counted_partitions
    invalid_right = CountedPartition(2, 0, left.interval, left.exact_subquery, 3, 1, "collect", "duplicate")
    corrupted = PubMedPartitionResult(Q, WINDOW, 6, "incomplete", (), (root, left, invalid_right), (), ())
    with pytest.raises(CheckpointIntegrityError, match="overlap|gaps"):
        create_pubmed_checkpoint(p, q, corrupted)


def test_wos_source_refused_before_creating_checkpoint(tmp_path):
    p = create_project(tmp_path, "WoS")
    version = approve_strategy(p, theme="Topic", approved_by="R", approval_confirmed=True,
                               groups=(StrategyGroup("g1", "Group", (ApprovedTerm("ECMO", "researcher", True),)),))
    run = create_search_run(p, version.strategy_version_id)
    q = plan_source_query(p, run_id=run.run_id, group_id="g1", source_name="wos", exact_query=Q)
    with pytest.raises(ValueError, match="Only PubMed"):
        create_pubmed_checkpoint(p, q.query_id, plan())


def test_zero_hits_need_no_pages_but_still_require_source_recheck(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(count=0), page_size=2)
    f = FakeProvider({Q: []})
    out = resume_pubmed_checkpoint(p, q, f)
    assert out.snapshot.identifiers_reconciled
    assert out.snapshot.pages_expected == 0 and not f.pages
    assert out.source_retrieval_verified is False


def test_checkpoint_requires_actual_planned_query_identical_to_root(tmp_path):
    p, q = project_query(tmp_path)
    wrong = PubMedPartitionResult('("Other"[All Fields])', WINDOW, 1, "incomplete", (), (), (), ())
    with pytest.raises(CheckpointIntegrityError, match="Approved query"):
        create_pubmed_checkpoint(p, q, wrong)


def test_no_checkpoint_state_is_never_a_fictional_hit_count(tmp_path):
    p, q = project_query(tmp_path)
    with pytest.raises(KeyError, match="No PubMed checkpoint"):
        inspect_pubmed_checkpoint(p, q)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        assert db.execute("SELECT reported_matches FROM source_queries WHERE query_id=?", (q,)).fetchone()[0] is None


def test_start_entrypoint_checkpoints_before_first_page_and_resumes_without_duplicate_fetch(tmp_path):
    from research_y.pubmed_checkpoint_resume import start_checkpointed_pubmed_retrieval

    project, query_id = project_query(tmp_path)
    remote = FakeProvider({Q: ["1", "2", "3", "4"]})
    remote.fail_at_offset = 2
    first = start_checkpointed_pubmed_retrieval(
        project, query_id, remote, date_window=WINDOW, page_size=2,
    )
    assert first.status == "incomplete"
    assert first.snapshot.pmids == ("1", "2")
    assert first.snapshot.pages_committed == 1
    resumed_provider = FakeProvider({Q: ["1", "2", "3", "4"]})
    second = start_checkpointed_pubmed_retrieval(
        open_project(project.root), query_id, resumed_provider,
        date_window=WINDOW, page_size=2,
    )
    assert second.status == "identifiers_reconciled_metadata_pending"
    assert second.snapshot.pmids == ("1", "2", "3", "4")
    assert resumed_provider.pages == [(Q, 2, 2)]
    assert not second.source_retrieval_verified


def test_start_entrypoint_rolls_back_failed_plan_audit_before_any_pages(tmp_path):
    from research_y.pubmed_checkpoint_resume import start_checkpointed_pubmed_retrieval

    project, query_id = project_query(tmp_path)
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("""CREATE TRIGGER deny_new_plan BEFORE INSERT ON audit_events
            WHEN NEW.event_type='pubmed_checkpoint_created'
            BEGIN SELECT RAISE(ABORT, 'local audit failure'); END""")
    fake = FakeProvider({Q: ["1", "2", "3", "4"]})
    result = start_checkpointed_pubmed_retrieval(
        project, query_id, fake, date_window=WINDOW, page_size=2,
    )
    assert result.status == "incomplete"
    assert fake.pages == []
    with closing(sqlite3.connect(project.database_path)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM pubmed_checkpoint_runs").fetchone()[0] == 0
        assert db.execute("SELECT reported_matches FROM source_queries WHERE query_id=?", (query_id,)).fetchone()[0] is None


def test_start_entrypoint_date_partition_result_is_persisted(tmp_path):
    from research_y.pubmed_checkpoint_resume import start_checkpointed_pubmed_retrieval

    project, query_id = project_query(tmp_path)
    left, right = WINDOW.split()
    all_ids = [str(n) for n in range(1, 9002)]
    fake = FakeProvider({
        Q: all_ids,
        WINDOW.query_for(Q): all_ids,
        left.query_for(Q): all_ids[:4500],
        right.query_for(Q): all_ids[4500:],
    })
    result = start_checkpointed_pubmed_retrieval(
        project, query_id, fake, date_window=WINDOW, page_size=1000,
    )
    assert result.status == "identifiers_reconciled_metadata_pending"
    assert result.snapshot.identifiers_reconciled
    assert result.snapshot.pages_expected == 10
    assert len(result.snapshot.pmids) == 9001
    assert not result.source_retrieval_verified
    assert inspect_pubmed_checkpoint(open_project(project.root), query_id).pmids == result.snapshot.pmids


def test_pause_during_inflight_request_commits_page_but_stops_next_request(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    fake = FakeProvider({Q: ["1", "2", "3", "4"]})
    orig = fake.fetch_esearch_page

    def pauses_after_request(query, *, retstart, retmax):
        if retstart == 0:
            pause_pubmed_checkpoint(p, q)
        return orig(query, retstart=retstart, retmax=retmax)

    fake.fetch_esearch_page = pauses_after_request
    paused = resume_pubmed_checkpoint(p, q, fake)
    assert paused.status == "paused"
    assert paused.snapshot.pmids == ("1", "2")
    assert paused.snapshot.stored_status == "paused"
    assert fake.pages == [(Q, 0, 2)]
    fresh = FakeProvider({Q: ["1", "2", "3", "4"]})
    resumed = resume_pubmed_checkpoint(open_project(p.root), q, fresh)
    assert resumed.status == "identifiers_reconciled_metadata_pending"
    assert fresh.pages == [(Q, 2, 2)]


def test_failed_final_status_audit_returns_incomplete_and_keeps_page_data(tmp_path):
    p, q = project_query(tmp_path)
    create_pubmed_checkpoint(p, q, plan(), page_size=2)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("""CREATE TRIGGER deny_final_checkpoint_status BEFORE INSERT ON audit_events
            WHEN NEW.event_type='pubmed_checkpoint_status'
            BEGIN SELECT RAISE(ABORT, 'SECRET-AUDIT-FAIL'); END""")
    fake = FakeProvider({Q: ["1", "2", "3", "4"]})
    result = resume_pubmed_checkpoint(p, q, fake)
    assert result.status == "incomplete"
    assert result.snapshot.pmids == ("1", "2", "3", "4")
    assert result.snapshot.pages_committed == 2
    assert result.snapshot.stored_status == "incomplete"
    assert "SECRET-AUDIT-FAIL" not in repr(result)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("DROP TRIGGER deny_final_checkpoint_status")
    second = resume_pubmed_checkpoint(open_project(p.root), q, FakeProvider({Q: ["1", "2", "3", "4"]}))
    assert second.status == "identifiers_reconciled_metadata_pending"
