"""Offline count projections: real disk-backed schema, identities and receipts."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

import pytest

from research_y.projects import Project, create_project, open_project
from research_y import publication_identity as identity
from research_y import publication_candidates as candidates
from research_y import result_counts as counts
from research_y.result_count_ledger import CountIntegrityError

STAMP = '2026-11-01T16:45:00+00:00'


def uid():
    return str(uuid4())


@dataclass
class Fixture:
    project: Project
    run: str
    strategy: str
    queries: dict


def new_run(p):
    run, strategy = uid(), uid()
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        version = db.execute('SELECT COUNT(*)+1 FROM strategy_versions').fetchone()[0]
        db.execute('INSERT INTO strategy_versions VALUES(?,?,?,?)', (strategy, version, STAMP, '{}'))
        for n, g in enumerate(('g1', 'g2')):
            db.execute('INSERT INTO strategy_groups VALUES(?,?,?,?)', (strategy, g, g, n))
        db.execute('INSERT INTO search_runs VALUES(?,?,?,?,?)', (run, strategy, STAMP, 'incomplete', None))
        queries = {}
        for g in ('g1', 'g2'):
            for source in ('pubmed', 'wos'):
                q = uid()
                exact = '"ECMO"[All Fields]' if source == 'pubmed' else 'TS=("ECMO")'
                db.execute('INSERT INTO source_queries(query_id,run_id,strategy_version_id,group_id,'
                           'source_name,exact_query) VALUES(?,?,?,?,?,?)', (q, run, strategy, g, source, exact))
                queries[g, source] = q
    return Fixture(p, run, strategy, queries)


@pytest.fixture
def fixture(tmp_path):
    return new_run(create_project(tmp_path, 'Count fixture'))


def add_record(f, source='pubmed', identifier='123', groups=('g1',), title='PRIVATE TITLE'):
    rid = uid()
    if source == 'pubmed':
        payload = {'source': 'NCBI PubMed EFetch XML', 'record': {
            'pmid': identifier, 'title': title, 'abstract_status': 'present',
            'abstract_sections': [{'text': 'PRIVATE ABSTRACT'}], 'identifiers': {'doi': ['10.1234/synthetic']}},
            'rights_review_required_for_abstract_redistribution': True}
    elif source == 'wos':
        payload = {'provider': 'wos_starter', 'database': 'WOS',
                   'record': {'uid': identifier, 'title': title, 'identifiers': {'doi': '10.1234/synthetic'}},
                   'abstract_status': 'not_returned_by_source', 'rights_status': 'licence_review_required'}
    else:
        payload = {'record': {'title': title}, 'rights_status': 'unknown'}
    with closing(sqlite3.connect(f.project.database_path)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)',
                   (rid, f.run, source, identifier, STAMP, identity._json(payload)))
        for g in groups:
            db.execute('INSERT INTO query_retrievals VALUES(?,?,?,?)', (f.queries[g, source], rid, f.run, source))
    return rid


def set_reported(f, group, source, reported, status='incomplete'):
    with closing(sqlite3.connect(f.project.database_path)) as db, db:
        db.execute('UPDATE source_queries SET reported_matches=?,status=? WHERE query_id=?',
                   (reported, status, f.queries[group, source]))


def row(result, group='g1', source='pubmed'):
    return next(s for g in result.groups if g['group_id'] == group for s in g['sources'] if s['source_name'] == source)


def source_row(result, source='pubmed'):
    return next(s for s in result.sources if s['source_name'] == source)


def decide(f, a, b, decision='confirmed_match'):
    for r in (a, b):
        identity.materialise_retrieval(f.project, r, actor='Fixture')
    view = candidates.read_candidate(f.project, a, b)
    return candidates.decide_candidate(f.project, a, b, expected_revision=view.revision,
        decision=decision, actor='Fixture', evidence='Synthetic explicit decision',
        acknowledged_warnings=view.warnings, decision_confirmed=True,
        move_retrieval_id=a if decision == 'confirmed_match' else None)


def fingerprint(p):
    return sha256(p.database_path.read_bytes()).hexdigest()


def test_two_sources_two_groups_one_identity_is_not_group_sum(fixture):
    f = fixture
    a = add_record(f, groups=('g1','g2'))
    b = add_record(f, 'wos', 'WOS:123', groups=('g1','g2'))
    for g in ('g1','g2'):
        for s in ('pubmed','wos'):
            set_reported(f, g, s, 1)
    decide(f, a, b)
    before = fingerprint(f.project)
    r = counts.read_run_counts(f.project, f.run)
    assert r.totals['global_publication_identities'] == 1
    assert r.totals['group_publication_identity_sum'] == 2
    assert [g['publication_identities'] for g in r.groups] == [1, 1]
    assert [s['source_unique_records'] for s in r.sources] == [1, 1]
    assert r.totals['source_record_sum'] == 2
    assert r.reviews['current_confirmed_matches'] == 1
    assert r.totals['global_unique_publications'] is None
    assert not r.verified_complete and not r.deduplication_complete
    assert fingerprint(f.project) == before


def test_unmaterialised_and_queryless_are_visible(fixture):
    f = fixture
    add_record(f)
    orphan = add_record(f, identifier='456', groups=())
    identity.materialise_retrieval(f.project, orphan, actor='Fixture')
    r = counts.read_run_counts(f.project, f.run)
    assert r.totals['unmaterialised_retrievals'] == 1
    assert r.totals['queryless_source_records'] == 1
    assert r.totals['global_publication_identities'] == 1
    assert r.totals['group_publication_identity_sum'] == 0
    assert source_row(r)['source_unique_records'] == 2
    assert row(r)['metadata_source_records'] == 1
    assert 'queryless_source_records' in r.warnings


@pytest.mark.parametrize('reported,expected', [(None,'unknown'),(0,'equal'),(10,'shortfall')], ids=['unknown','zero','shortfall'])
def test_unknown_zero_and_shortfall_are_not_conflated(fixture, reported, expected):
    set_reported(fixture, 'g1','pubmed',reported)
    r = counts.read_run_counts(fixture.project, fixture.run)
    assert row(r)['reported_matches'] is reported
    assert row(r)['numeric_reconciliation'] == expected
    assert not r.source_retrieval_verified


def test_excess_is_exposed_and_never_promoted(fixture):
    add_record(fixture)
    set_reported(fixture,'g1','pubmed',0,'completed_verified')
    r = counts.read_run_counts(fixture.project, fixture.run)
    assert row(r)['numeric_reconciliation'] == 'excess'
    assert row(r)['retrieved_minus_reported'] == 1
    assert 'identifier_count_excess' in r.warnings
    assert r.status == 'incomplete' and not r.verified_complete


@pytest.mark.parametrize('status', counts.RUN_STATUSES)
def test_stored_status_retained_but_does_not_certify_counts(fixture, status):
    with closing(sqlite3.connect(fixture.project.database_path)) as db, db:
        db.execute('UPDATE search_runs SET status=? WHERE run_id=?',(status,fixture.run))
        db.execute('UPDATE source_queries SET status=?,reported_matches=0 WHERE run_id=?',(status,fixture.run))
    before = fingerprint(fixture.project)
    r = counts.read_run_counts(fixture.project,fixture.run)
    assert r.stored_run_status == status
    assert all(q['stored_query_status'] == status for q in r.queries)
    assert not r.verified_complete and r.status == 'incomplete'
    assert fingerprint(fixture.project) == before


def test_two_query_chunks_use_unique_union_not_reported_sum(fixture):
    f = fixture
    rid = add_record(f)
    q2 = uid()
    set_reported(f,'g1','pubmed',1)
    with closing(sqlite3.connect(f.project.database_path)) as db, db:
        db.execute('INSERT INTO source_queries(query_id,run_id,strategy_version_id,group_id,source_name,'
                   'exact_query,reported_matches) VALUES(?,?,?,?,?,?,?)',
                   (q2,f.run,f.strategy,'g1','pubmed','"different"[All Fields]',1))
        db.execute('INSERT INTO query_retrievals VALUES(?,?,?,?)',(q2,rid,f.run,'pubmed'))
    r = counts.read_run_counts(f.project,f.run)
    assert row(r)['reported_matches'] is None
    assert row(r)['reported_count_status'] == 'union_not_established'
    assert row(r)['retrieved_source_records'] == 1
    assert source_row(r)['source_unique_records'] == 1
    assert len([q for q in r.queries if q['source_name']=='pubmed' and q['group_id']=='g1']) == 2


def test_unplanned_sources_and_groups_are_not_silent_zero_searches(fixture):
    f = fixture
    with closing(sqlite3.connect(f.project.database_path)) as db, db:
        db.execute('DELETE FROM source_queries WHERE run_id=?',(f.run,))
    r = counts.read_run_counts(f.project,f.run)
    assert r.queries == () and 'no_planned_queries' in r.warnings
    assert row(r)['reported_count_status'] == 'not_planned'
    assert row(r)['reported_matches'] is None
    assert len(r.groups) == 2


def test_repeated_runs_do_not_multiply_requested_run_counts(fixture):
    f = fixture
    a = add_record(f)
    second = new_run(f.project)
    b = add_record(second)
    decide(f,a,b)
    first = counts.read_run_counts(f.project,f.run)
    later = counts.read_run_counts(f.project,second.run)
    assert first.totals['source_record_sum'] == later.totals['source_record_sum'] == 1
    assert first.totals['global_publication_identities'] == later.totals['global_publication_identities'] == 1
    assert first.run_id != later.run_id
    assert not first.historical_snapshot


def test_reversal_excludes_retained_empty_identity_then_restores_it(fixture):
    f = fixture
    a,b = add_record(f),add_record(f,'wos','WOS:123')
    old = identity.materialise_retrieval(f.project,a,actor='Fixture')
    view = decide(f,a,b)
    after = counts.read_run_counts(f.project,f.run)
    event = identity.read_retrieval_history(f.project,a)[-1]['event_id']
    identity.reverse_association(f.project,a,event,
        expected_current_revision=identity.read_publication(f.project,view.publication_ids[0]).revision,
        expected_restored_revision=identity.read_publication(f.project,old.publication_id).revision,
        actor='Fixture',evidence='Reverse synthetic match')
    restored = counts.read_run_counts(f.project,f.run)
    assert after.totals['global_publication_identities'] == 1
    assert restored.totals['global_publication_identities'] == 2
    assert restored.reviews['stale_decisions'] == 1
    assert restored.reviews['decisions_conflicting_with_current_links'] == 1
    assert restored.revision != after.revision
    assert not restored.totals['inactive_identities_included']


def test_rejection_is_not_a_merge_and_replay_not_extra_count(fixture):
    a,b = add_record(fixture), add_record(fixture,'wos','WOS:123')
    decide(fixture,a,b,'rejected_match')
    first = counts.read_run_counts(fixture.project,fixture.run)
    second = counts.read_run_counts(fixture.project,fixture.run)
    assert first == second
    assert first.totals['global_publication_identities'] == 2
    assert first.reviews['current_rejected_matches'] == 1
    assert first.reviews['recorded_pair_decisions'] == 1


@pytest.mark.parametrize('change', ['run','query','membership'], ids=['run-status','query-count','new-membership'])
def test_changed_context_marks_previous_receipt_stale(fixture,change):
    f=fixture
    a,b=add_record(f),add_record(f,'wos','WOS:123')
    decide(f,a,b,'rejected_match')
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        if change=='run':
            db.execute('UPDATE search_runs SET status="failed" WHERE run_id=?',(f.run,))
        elif change=='query':
            db.execute('UPDATE source_queries SET reported_matches=7 WHERE query_id=?',(f.queries['g1','pubmed'],))
        else:
            db.execute('INSERT INTO query_retrievals VALUES(?,?,?,?)',(f.queries['g2','pubmed'],a,f.run,'pubmed'))
    r=counts.read_run_counts(f.project,f.run)
    assert r.reviews['stale_decisions']==1
    assert r.reviews['current_rejected_matches']==0
    assert 'recorded_decisions_need_review' in r.warnings


def test_previous_run_receipts_are_available_not_applied(fixture):
    f=fixture
    decide(f,add_record(f),add_record(f,'wos','WOS:123'),'rejected_match')
    other=new_run(f.project)
    a,b=add_record(other),add_record(other,'wos','WOS:123')
    for rid in (a,b): identity.materialise_retrieval(f.project,rid,actor='Fixture')
    result=counts.read_run_counts(f.project,other.run)
    assert result.reviews['prior_run_receipts_available']==1
    assert result.reviews['recorded_pair_decisions']==0
    assert result.totals['global_publication_identities']==2
    decide(other,a,b,'rejected_match')
    assert counts.read_run_counts(f.project,f.run).reviews['stale_decisions']==1


def test_rejected_pair_moved_by_explicit_identity_operation_is_flagged(fixture):
    f=fixture
    a,b=add_record(f),add_record(f,'wos','WOS:123')
    decide(f,a,b,'rejected_match')
    sa=identity.materialise_retrieval(f.project,a,actor='Fixture')
    sb=identity.materialise_retrieval(f.project,b,actor='Fixture')
    identity.associate_retrieval(f.project,a,sb.publication_id,
        expected_source_revision=sa.revision,expected_target_revision=sb.revision,
        actor='Fixture',evidence='Explicit override',same_publication_confirmed=True)
    r=counts.read_run_counts(f.project,f.run)
    assert r.reviews['decisions_conflicting_with_current_links']==1
    assert r.reviews['stale_decisions']==1


def test_no_licensed_text_or_permission_inferred(fixture):
    add_record(fixture)
    add_record(fixture,'wos','WOS:123')
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert 'PRIVATE' not in json.dumps(r.as_dict())
    assert not r.export_permissions_verified
    assert source_row(r)['abstract_status_counts']=={'present':1}
    assert source_row(r,'wos')['abstract_status_counts']=={'not_returned_by_source':1}
    assert r.totals['extracted_individual_abstracts'] is None
    assert r.totals['extracted_abstract_count_status']=='not_implemented'


def test_same_container_metadata_does_not_infer_extraction_or_merge(fixture):
    for n in ('123','456'):
        rid=add_record(fixture,identifier=n)
        with closing(sqlite3.connect(fixture.project.database_path)) as db,db:
            payload=identity._object(db.execute('SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?',(rid,)).fetchone()[0])
            payload['record']['publication_types']=['Conference Abstract']
            payload['record']['supplement']='Same supplement'
            db.execute('UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?',(identity._json(payload),rid))
        identity.materialise_retrieval(fixture.project,rid,actor='Fixture')
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert r.totals['global_publication_identities']==2
    assert r.totals['extracted_individual_abstracts'] is None


def test_extra_manual_source_not_hidden_or_assumed_reported(fixture):
    add_record(fixture,'manual','item-1',groups=())
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert source_row(r,'manual')['source_unique_records']==1
    assert row(r,source='manual')['reported_matches'] is None
    assert r.totals['queryless_source_records']==1


def test_reopen_relocate_and_repeated_read_are_stable(fixture,tmp_path):
    rid=add_record(fixture)
    identity.materialise_retrieval(fixture.project,rid,actor='Fixture')
    original=counts.read_run_counts(fixture.project,fixture.run)
    new_path=tmp_path/'Other # path%20'
    shutil.move(str(fixture.project.root),new_path)
    moved=open_project(new_path)
    assert counts.read_run_counts(moved,fixture.run)==original


@pytest.mark.parametrize('damage', ['metadata','association','field','receipt','foreign_key','identity','version','application'], ids=str)
def test_corrupt_or_legacy_evidence_fails_closed_without_mutation(fixture,damage):
    f=fixture
    rid=add_record(f)
    pub=identity.materialise_retrieval(f.project,rid,actor='Fixture')
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        if damage=='metadata': db.execute('UPDATE source_retrievals SET original_metadata_json="[]" WHERE retrieval_id=?',(rid,))
        elif damage=='association': db.execute('UPDATE publication_retrievals SET decision_provenance_json="{}" WHERE retrieval_id=?',(rid,))
        elif damage=='field': db.execute('UPDATE publications SET chosen_metadata_json=? WHERE publication_id=?',('{"title":"untraced"}',pub.publication_id))
        elif damage=='receipt': db.execute('INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES(?,?,?)',(STAMP,candidates.DECISION_EVENT,identity._json({'version':1,'at_utc':STAMP})))
        elif damage=='foreign_key': db.execute('UPDATE query_retrievals SET query_id=? WHERE retrieval_id=?',(uid(),rid))
        elif damage=='identity': db.execute('UPDATE project_metadata SET project_uuid=?',(uid(),))
        elif damage=='version': db.execute('PRAGMA user_version=1')
        elif damage=='application': db.execute('PRAGMA application_id=7')
    before=fingerprint(f.project)
    with pytest.raises(CountIntegrityError): counts.read_run_counts(f.project,f.run)
    assert fingerprint(f.project)==before
    assert list((f.project.root/'backups').iterdir())==[]


@pytest.mark.parametrize('bad', [-1,3.5,'not a count'])
def test_invalid_reported_counts_are_not_coerced(fixture,bad):
    with closing(sqlite3.connect(fixture.project.database_path)) as db,db:
        db.execute('PRAGMA ignore_check_constraints=ON')
        db.execute('UPDATE source_queries SET reported_matches=? WHERE query_id=?',(bad,fixture.queries['g1','pubmed']))
    with pytest.raises(CountIntegrityError): counts.read_run_counts(fixture.project,fixture.run)


def test_readonly_connection_rejects_writes(fixture,monkeypatch):
    before=fingerprint(fixture.project)
    def mutate(db,*args):
        db.execute('UPDATE search_runs SET status="completed_verified"')
    monkeypatch.setattr(counts,'_snapshot',mutate)
    with pytest.raises(CountIntegrityError): counts.read_run_counts(fixture.project,fixture.run)
    assert fingerprint(fixture.project)==before


def test_missing_database_is_not_created(fixture):
    fixture.project.database_path.unlink()
    with pytest.raises(CountIntegrityError): counts.read_run_counts(fixture.project,fixture.run)
    assert not fixture.project.database_path.exists()


def test_unknown_run_is_not_zero(fixture):
    with pytest.raises(CountIntegrityError,match='Unknown search run'):
        counts.read_run_counts(fixture.project,uid())


def test_no_filter_parameter_can_narrow_search_counts(fixture):
    with pytest.raises(TypeError): counts.read_run_counts(fixture.project,fixture.run,filters={'language':'en'})


def test_one_read_transaction_during_committed_identity_change(fixture,monkeypatch):
    f=fixture
    a,b=add_record(f),add_record(f,'wos','WOS:123')
    sa=identity.materialise_retrieval(f.project,a,actor='Fixture')
    sb=identity.materialise_retrieval(f.project,b,actor='Fixture')
    # Test-only journal mode allows a separate writer to commit during the read.
    with closing(sqlite3.connect(f.project.database_path)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
    original=counts._review_counts
    fired=[]
    def concurrent(db,sources):
        if not fired:
            fired.append(True)
            decide(f,a,b)
        return original(db,sources)
    with monkeypatch.context() as m:
        m.setattr(counts,'_review_counts',concurrent)
        old=counts.read_run_counts(f.project,f.run)
    new=counts.read_run_counts(f.project,f.run)
    assert old.totals['global_publication_identities']==2
    assert new.totals['global_publication_identities']==1
    assert old.revision!=new.revision
    assert old.reviews['recorded_pair_decisions']==0
    assert new.reviews['current_confirmed_matches']==1


def test_more_than_ten_thousand_records_have_no_candidate_batch_cap(fixture):
    f=fixture
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        for n in range(1,10002):
            rid=uid()
            payload={'source':'NCBI PubMed EFetch XML','record':{'pmid':str(n)}}
            db.execute('INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)',
                       (rid,f.run,'pubmed',str(n),STAMP,identity._json(payload)))
            db.execute('INSERT INTO query_retrievals VALUES(?,?,?,?)',(f.queries['g1','pubmed'],rid,f.run,'pubmed'))
    r=counts.read_run_counts(f.project,f.run)
    assert row(r)['retrieved_source_records']==10001
    assert r.totals['unmaterialised_retrievals']==10001
    assert not r.candidate_discovery_complete


@pytest.mark.parametrize('damage', ['manifest','unknown_status','source_id','abstract_state','parameters'])
def test_other_invalid_evidence_is_not_repaired(fixture,damage):
    f=fixture
    rid=add_record(f)
    if damage=='manifest':
        document=json.loads(f.project.manifest_path.read_text())
        document['name']='Different project'
        f.project.manifest_path.write_text(json.dumps(document))
    else:
        with closing(sqlite3.connect(f.project.database_path)) as db,db:
            if damage=='unknown_status':
                db.execute('PRAGMA ignore_check_constraints=ON')
                db.execute('UPDATE search_runs SET status="invented" WHERE run_id=?',(f.run,))
            elif damage=='parameters':
                db.execute('UPDATE source_queries SET parameters_json="[]" WHERE query_id=?',(f.queries['g1','pubmed'],))
            else:
                value=identity._object(db.execute('SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?',(rid,)).fetchone()[0])
                value['record']['pmid' if damage=='source_id' else 'abstract_status']='789' if damage=='source_id' else []
                db.execute('UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?',(identity._json(value),rid))
    before=fingerprint(f.project)
    with pytest.raises(CountIntegrityError): counts.read_run_counts(f.project,f.run)
    assert fingerprint(f.project)==before


def test_all_receipts_single_pass_keeps_existing_pair_lookup(fixture):
    f=fixture
    a,b=add_record(f),add_record(f,'wos','WOS:123')
    c,d=add_record(f,identifier='456'),add_record(f,'wos','WOS:456')
    decide(f,a,b,'rejected_match')
    decide(f,c,d,'rejected_match')
    with closing(sqlite3.connect(f.project.database_path)) as db:
        all_receipts=candidates._receipts(db,None)
        keys=all_receipts[0]['source_keys']
        assert candidates._receipts(db,keys)==[r for r in all_receipts if r['source_keys']==keys]
    assert counts.read_run_counts(f.project,f.run).reviews['recorded_pair_decisions']==2


@pytest.mark.parametrize('source,bad', [('pubmed','abc'),('pubmed','0'),('wos','not-an-accession')])
def test_malformed_primary_identifier_is_not_counted(fixture,source,bad):
    add_record(fixture,source,bad)
    with pytest.raises(CountIntegrityError): counts.read_run_counts(fixture.project,fixture.run)
