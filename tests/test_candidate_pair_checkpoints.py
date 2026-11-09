"""Disk-backed acceptance for bounded exact-key pair-hint checkpointing.

Every source, title, abstract and identifier is synthetic. This tests *review
hints only*, not automatic deduplication or the complete production queue.
"""
from __future__ import annotations

from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from research_y import candidate_pair_checkpoints as pairs
from research_y import publication_identity as identity
from research_y import publication_candidates as candidates
from research_y import candidate_index_build as keys
from research_y.projects import create_project, open_project


def uid():
    return str(uuid4())


@pytest.fixture
def study(tmp_path):
    p=create_project(tmp_path, "Synthetic checkpointed pairing")
    run, historical, version=uid(),uid(),uid()
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (version,1,p.created_at_utc,"{}"))
        db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                   (version,"g1","Biomedical",0))
        for run_id in (run,historical):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id,version,p.created_at_utc,"incomplete",None))
    return p,run,historical


def add(f, *, source_name="pubmed", number=1, title="Conference summary",
        doi=None, run=None, materialise=True,
        abstract="SECRET_LICENSED_ABSTRACT_DO_NOT_RETURN"):
    p, selected, _=f
    run_id=run or selected
    rid=uid()
    source_id=str(number) if source_name=="pubmed" else "WOS:"+str(number)
    doi=doi or "10.7777/synthetic"+str(number)
    if source_name=="pubmed":
        meta=dict(source="NCBI PubMed EFetch XML",
                  record=dict(pmid=source_id,title=title,
                              identifiers={"doi":[doi]},
                              publication_types=["Conference Abstract"],
                              abstract_sections=[{"text":abstract}]),
                  rights_review_required_for_abstract_redistribution=True)
    elif source_name=="wos":
        meta=dict(provider="wos_starter",database="WOS",
                  record=dict(uid=source_id,title=title,
                              identifiers={"doi":doi},types=["Conference Abstract"]),
                  rights_status="licence_review_required")
    else:
        meta=dict(source="manual",record={"title":title})
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (rid,run_id,source_name,source_id,
                    p.created_at_utc,identity._json(meta)))
    if materialise:
        identity.materialise_retrieval(p,rid,actor="Fixture researcher")
    return rid


def source_index(p):
    view=keys.preview_candidate_index(p)
    current=keys.start_candidate_index(
        p,expected_revision=view["revision"],
        actor="Researcher",confirmed=True)
    for _ in range(100):
        if current["status"]=="ready":
            break
        current=keys.advance_candidate_index(
            p,expected_revision=current["revision"],
            generation_id=current["generation_id"],
            actor="Researcher",confirmed=True)
    assert current["status"]=="ready"
    return current


def pair_start(f):
    p,run,_=f
    view=pairs.preview_pair_checkpoint(p,run)
    return pairs.start_pair_checkpoint(
        p,run,expected_revision=view["revision"],
        actor="Researcher",confirmed=True)


def pair_step(f, state):
    p,run,_=f
    return pairs.advance_pair_checkpoint(
        p,run,generation_id=state["generation_id"],
        expected_revision=state["revision"],
        actor="Researcher",confirmed=True)


def complete(f):
    current=pair_start(f)
    for _ in range(100):
        if current["status"]=="ready_keys_only":
            break
        current=pair_step(f,current)
    assert current["status"]=="ready_keys_only"
    return current


def table(p, sql, args=()):
    with closing(sqlite3.connect(p.database_path)) as db:
        return db.execute(sql,args).fetchall()


def test_explicit_source_index_prerequisite_and_readonly_empty_state(study):
    p,run,_=study
    add(study)
    before=p.database_path.read_bytes()
    view=pairs.preview_pair_checkpoint(p,run)
    assert view["status"]=="not_started" and not view["index_ready"]
    assert view["global_unique_publications"] is None
    assert before==p.database_path.read_bytes()
    with pytest.raises(pairs.CandidatePairError) as exc:
        pairs.start_pair_checkpoint(
            p,run,expected_revision=view["revision"],
            actor="Researcher",confirmed=True)
    assert exc.value.code=="candidate_pair_index_not_ready"
    with pytest.raises(pairs.CandidatePairError) as exc:
        pairs.start_pair_checkpoint(
            p,run,expected_revision=view["revision"],
            actor="Researcher",confirmed=False)
    assert exc.value.code=="candidate_pair_confirmation_required"
    assert table(p,"SELECT COUNT(*) FROM candidate_pair_builds")==[(0,)]


def test_ready_exact_hints_keep_distinct_supplement_abstracts(study):
    p,run,_=study
    a=add(study,number=101,title="First abstract",
          doi="10.9999/shared-container")
    b=add(study,source_name="wos",number=102,title="Second abstract",
          doi="10.9999/shared-container")
    originals=table(p,"SELECT * FROM source_retrievals ORDER BY retrieval_id")
    source_index(p)
    done=complete(study)
    assert done["unique_pairs"]==1
    assert done["indexed_source_key_hints_complete"] is True
    assert done["historical_receipt_only_pairs_included"] is False
    assert done["candidate_discovery_complete"] is False
    assert done["deduplication_complete"] is False
    assert done["global_unique_publications"] is None
    page=pairs.read_pair_hint_page(p,run)
    assert page["pair_hint_total"]==1
    assert page["rows"]==[dict(
        retrieval_ids=sorted((a,b)),
        matched_exact_fields=["doi"],no_automatic_match=True)]
    assert "SECRET_LICENSED_ABSTRACT" not in repr(page)
    assert table(p,"SELECT * FROM source_retrievals ORDER BY retrieval_id")==originals
    assert table(p,"SELECT COUNT(*) FROM publications")==[(2,)]
    assert table(p,"SELECT COUNT(*) FROM candidate_pair_hints")==[(1,)]


def test_pair_builder_includes_selected_to_historical_not_historical_only(study):
    p,run,historical=study
    a=add(study,number=201,title="Relevant report",
          doi="10.1111/same")
    b=add(study,source_name="wos",number=202,
          title="Relevant report",doi="10.1111/same",run=historical)
    add(study,number=203,title="Old only",doi="10.1111/older",
        run=historical)
    add(study,source_name="wos",number=204,title="Old only",
        doi="10.1111/older",run=historical)
    source_index(p)
    done=complete(study)
    page=pairs.read_pair_hint_page(p,run)
    assert done["unique_pairs"]==1
    assert page["rows"][0]["retrieval_ids"]==sorted((a,b))
    assert page["rows"][0]["matched_exact_fields"]==["doi","title"]


def test_partial_dense_bucket_resumes_without_replays_or_pair_loss(study,monkeypatch):
    p,run,historical=study
    a=add(study,number=301,title="Many reports",doi="10.2222/dense")
    others=[
        add(study,source_name="wos",number=400+i,
            title="Many reports",doi="10.2222/dense",run=historical)
        for i in range(9)
    ]
    source_index(p)
    monkeypatch.setattr(pairs,"MAX_HINTS_PER_BATCH",2)
    monkeypatch.setattr(pairs,"MAX_KEYS_PER_BATCH",1)
    first=pair_step(study,pair_start(study))
    assert first["status"]=="building"
    assert first["emitted_hints"]==2
    assert first["cursor_other_id"] is not None
    reopened=open_project(p.root)
    assert pairs.preview_pair_checkpoint(reopened,run)["revision"]==first["revision"]
    latest=first
    for _ in range(30):
        if latest["status"]=="ready_keys_only":
            break
        latest=pair_step(study,latest)
    assert latest["status"]=="ready_keys_only"
    assert latest["unique_pairs"]==9
    assert latest["emitted_hints"]==18
    assert latest["processed_source_keys"]>=2
    assert len(table(p,"SELECT * FROM candidate_pair_hints"))==9
    assert set(tuple(r["retrieval_ids"]) for r in
               pairs.read_pair_hint_page(p,run)["rows"])=={
        tuple(sorted((a,b))) for b in others}
    with pytest.raises(pairs.CandidatePairError) as exc:
        pair_step(study,first)
    assert exc.value.code=="candidate_pair_stale"


def test_exact_page_keyset_after_restart_20_plus_5(study):
    p,run,historical=study
    expected=set()
    for i in range(25):
        a=add(study,number=500+i,title="Unique topic "+str(i),
              doi="10.3333/unique"+str(i))
        b=add(study,source_name="wos",number=600+i,
              title="Unique topic "+str(i),
              doi="10.3333/unique"+str(i),run=historical)
        expected.add(tuple(sorted((a,b))))
    source_index(p)
    done=complete(study)
    assert done["unique_pairs"]==25
    first=pairs.read_pair_hint_page(p,run)
    assert len(first["rows"])==20
    assert first["next_after_pair"] is not None
    second=pairs.read_pair_hint_page(
        open_project(p.root),run,
        after_pair=tuple(first["next_after_pair"]),
        expected_revision=first["revision"])
    assert len(second["rows"])==5
    assert second["next_after_pair"] is None
    assert first["revision"]==second["revision"]
    assert {tuple(x["retrieval_ids"]) for x in
            first["rows"]+second["rows"]}==expected
    assert first["global_unique_publications"] is None
    assert first["historical_receipt_only_pairs_included"] is False


def test_source_change_invalidates_pair_checkpoint_even_after_ready(study):
    p,run,_=study
    add(study,number=701)
    source_index(p)
    done=complete(study)
    add(study,number=702)
    stale=pairs.preview_pair_checkpoint(p,run)
    assert stale["status"]=="stale"
    assert stale["index_ready"] is False
    with pytest.raises(pairs.CandidatePairError) as exc:
        pairs.read_pair_hint_page(p,run,expected_revision=done["revision"])
    assert exc.value.code=="candidate_pair_stale"
    source_index(p)
    new=pair_start(study)
    assert new["generation_id"]!=done["generation_id"]
    assert complete_if_needed(study,new)["status"]=="ready_keys_only"


def complete_if_needed(study, current):
    for _ in range(100):
        if current["status"]=="ready_keys_only":
            break
        current=pair_step(study,current)
    return current


def test_identity_link_and_explicit_rejection_invalidate_pair_generation(study):
    p,run,_=study
    a=add(study,number=801,title="Different one",doi="10.8888/one")
    b=add(study,source_name="wos",number=802,title="Different two",
          doi="10.8888/two")
    source_index(p)
    done=complete(study)
    assert done["unique_pairs"]==0
    candidate=candidates.read_candidate(p,a,b)
    decided=candidates.decide_candidate(
        p,a,b,expected_revision=candidate.revision,
        decision="rejected_match",actor="Researcher",
        evidence="Individual supplements are distinct",
        acknowledged_warnings=candidate.warnings,
        decision_confirmed=True)
    assert decided.status=="rejected_match"
    stale=pairs.preview_pair_checkpoint(p,run)
    assert stale["status"]=="stale"
    assert stale["index_ready"] is True
    assert stale["historical_receipt_only_pairs_included"] is False
    assert table(p,"SELECT COUNT(*) FROM audit_events WHERE "
                  "event_type='publication_candidate_decision_v1'")==[(1,)]


def test_link_insert_invalidates_during_partial_build(study):
    p,run,_=study
    a=add(study,number=901)
    pending=add(study,number=902,materialise=False)
    source_index(p)
    current=pair_start(study)
    identity.materialise_retrieval(p,pending,actor="Researcher")
    assert pairs.preview_pair_checkpoint(p,run)["status"]=="stale"
    with pytest.raises(pairs.CandidatePairError) as exc:
        pair_step(study,current)
    assert exc.value.code=="candidate_pair_stale"


def test_nonindexed_source_and_unmaterialised_sources_are_not_false_pairs(study):
    p,run,_=study
    add(study,number=1001,materialise=False,title="Same")
    add(study,number=1002,title="Same",doi="10.5678/same")
    source_index(p)
    out=complete(study)
    assert out["unique_pairs"]==0
    assert out["candidate_discovery_complete"] is False


def test_empty_project_finishes_without_fake_negative_search_result(study):
    p,run,_=study
    source_index(p)
    out=complete(study)
    assert out["unique_pairs"]==0
    assert out["processed_source_keys"]==0
    assert out["status"]=="ready_keys_only"
    assert not out["candidate_discovery_complete"]
    assert not out["source_retrieval_verified"]
    assert not out["verified_complete"]


def test_batch_abort_rolls_back_all_pair_rows_counters_and_audit(study):
    p,run,_=study
    add(study,number=1101,doi="10.7777/same")
    add(study,source_name="wos",number=1102,doi="10.7777/same")
    source_index(p)
    started=pair_start(study)
    before=table(p,"SELECT * FROM audit_events ORDER BY event_id")
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("CREATE TRIGGER fail_pair_insert "
                   "BEFORE INSERT ON candidate_pair_hints "
                   "BEGIN SELECT RAISE(ABORT,'simulated write failure'); END")
    with pytest.raises(pairs.CandidatePairError):
        pair_step(study,started)
    assert table(p,"SELECT * FROM audit_events ORDER BY event_id")==before
    assert table(p,"SELECT COUNT(*) FROM candidate_pair_hints")==[(0,)]
    assert pairs.preview_pair_checkpoint(p,run)["revision"]==started["revision"]
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("DROP TRIGGER fail_pair_insert")
    assert complete_if_needed(study,started)["unique_pairs"]==1


def test_over_limit_fails_entire_transaction_no_truncation(study,monkeypatch):
    p,run,historical=study
    add(study,number=1201,title="Many reports",doi="10.2222/dense")
    for n in range(3):
        add(study,source_name="wos",number=1210+n,
            title="Many reports",doi="10.2222/dense",run=historical)
    source_index(p)
    started=pair_start(study)
    monkeypatch.setattr(pairs,"MAX_UNIQUE_PAIRS",1)
    before=table(p,"SELECT * FROM audit_events ORDER BY event_id")
    with pytest.raises(pairs.CandidatePairError) as exc:
        pair_step(study,started)
    assert exc.value.code=="candidate_pair_over_limit"
    assert table(p,"SELECT * FROM audit_events ORDER BY event_id")==before
    assert table(p,"SELECT COUNT(*) FROM candidate_pair_hints")==[(0,)]
    assert pairs.preview_pair_checkpoint(p,run)["status"]=="building"


def test_bad_cursor_and_old_revision_fail_closed(study):
    p,run,_=study
    a=add(study,number=1301)
    b=add(study,source_name="wos",number=1302)
    source_index(p)
    ready=complete(study)
    for cursor in ((b,a),("bad",uid()),[a,b]):
        with pytest.raises(pairs.CandidatePairError):
            pairs.read_pair_hint_page(
                p,run,after_pair=cursor,expected_revision=ready["revision"])
    with pytest.raises(pairs.CandidatePairError) as exc:
        pairs.read_pair_hint_page(
            p,run,after_pair=tuple(sorted((a,b))),
            expected_revision="a"*64)
    assert exc.value.code=="candidate_pair_stale"


def test_range_seek_queries_are_index_backed(study):
    p,run,_=study
    with closing(sqlite3.connect(p.database_path)) as db:
        targets=(
            (pairs.NEXT_KEY_SQL,(run,"","","")),
            (pairs.PEERS_SQL,("doi","b"*64,"",uid(),run,uid(),129)),
        )
        for sql,args in targets:
            plan=[v[3].upper() for v in
                  db.execute("EXPLAIN QUERY PLAN "+sql,args)]
            assert any("INDEX" in x or "PRIMARY KEY" in x for x in plan),plan
            assert not any("SCAN SOURCE_RETRIEVALS" in x for x in plan),plan
