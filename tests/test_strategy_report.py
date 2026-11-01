"""Repository integration: approved strategies, real counts, immutable XLSX input."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
import shutil
import sqlite3
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest

from research_y import publication_identity as identity
from research_y import result_counts
from research_y.projects import create_project, open_project
from research_y.storage import (ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query)
from research_y.strategy_report import capture_strategy_report, ReportIntegrityError, canonical, digest
from research_y.strategy_workbook import render_strategy_workbook

STAMP = '2026-11-01T20:00:00+00:00'


@pytest.fixture
def prepared(tmp_path):
    p = create_project(tmp_path, 'Synthetic export project')
    groups = tuple(StrategyGroup(g, g, (ApprovedTerm('ECMO', 'researcher', True),)) for g in ('g1','g2'))
    v = approve_strategy(p, theme='Synthetic strategy', groups=groups, approved_by='Fixture', approval_confirmed=True)
    r = create_search_run(p, v.strategy_version_id)
    queries = {}
    for group in ('g1','g2'):
        for source in ('pubmed','wos'):
            exact = '"ECMO"[All Fields]' if source == 'pubmed' else 'TS=("ECMO")'
            q = plan_source_query(p, run_id=r.run_id, group_id=group, source_name=source, exact_query=exact)
            queries[group,source] = q.query_id
    return SimpleNamespace(project=p, run=r.run_id, strategy=v.strategy_version_id, queries=queries)


def add(f, source, sid):
    rid = str(uuid4())
    if source == 'pubmed':
        metadata = {'source':'NCBI PubMed EFetch XML','record':{'pmid':sid,'title':'PRIVATE TITLE',
                    'abstract_sections':[{'text':'PRIVATE ABSTRACT'}],'abstract_status':'present'}}
    else:
        metadata = {'provider':'wos_starter','database':'WOS','record':{'uid':sid,'title':'PRIVATE TITLE'},
                    'abstract_status':'not_returned_by_source','rights_status':'licence_review_required'}
    with closing(sqlite3.connect(f.project.database_path)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)', (rid,f.run,source,sid,STAMP,canonical(metadata)))
        for g in ('g1','g2'):
            q = f.queries[g,source]
            db.execute('INSERT INTO query_retrievals VALUES(?,?,?,?)',(q,rid,f.run,source))
            db.execute('UPDATE source_queries SET reported_matches=1 WHERE query_id=?',(q,))
    return rid


def bytes_hash(p):
    return sha256(p.database_path.read_bytes()).hexdigest()


def test_complete_capture_uses_real_approved_strategy_and_keeps_originals(prepared):
    f = prepared
    before = bytes_hash(f.project)
    frozen = capture_strategy_report(f.project, f.run)
    data = frozen.as_dict()
    assert data['strategy']['snapshot']['theme'] == 'Synthetic strategy'
    assert data['strategy']['version_number'] == 1
    assert len(data['queries']) == 4
    assert data['queries'][0]['executed_at_utc'] is None
    assert data['counts']['status'] == 'incomplete'
    assert bytes_hash(f.project) == before
    assert list((f.project.root/'exports').iterdir()) == []
    assert render_strategy_workbook(frozen).startswith(b'PK')
    assert bytes_hash(f.project) == before


def test_two_sources_two_groups_preserve_denominators_and_omit_licensed_text(prepared):
    f = prepared
    a, b = add(f,'pubmed','123'), add(f,'wos','WOS:123')
    pa = identity.materialise_retrieval(f.project,a,actor='Fixture')
    pb = identity.materialise_retrieval(f.project,b,actor='Fixture')
    identity.associate_retrieval(f.project,a,pb.publication_id,
        expected_source_revision=pa.revision,expected_target_revision=pb.revision,
        actor='Fixture',evidence='Explicit synthetic match',same_publication_confirmed=True)
    before = bytes_hash(f.project)
    frozen = capture_strategy_report(f.project,f.run)
    counts = frozen.as_dict()['counts']
    assert counts['totals']['global_publication_identities'] == 1
    assert counts['totals']['group_publication_identity_sum'] == 2
    assert [s['source_unique_records'] for s in counts['sources']] == [1,1]
    assert counts['totals']['global_unique_publications'] is None
    content = render_strategy_workbook(frozen)
    with ZipFile(BytesIO(content)) as z:
        raw = b''.join(z.read(n) for n in z.namelist())
        assert b'PRIVATE ABSTRACT' not in raw and b'PRIVATE TITLE' not in raw
    assert 'Explicit synthetic match' not in frozen.payload_json
    assert bytes_hash(f.project) == before


@pytest.mark.parametrize('scope',['filtered','selected','latest',''],ids=['filtered','selected','latest','empty'])
def test_unsupported_scope_is_not_silently_ignored(prepared,scope):
    with pytest.raises(ValueError,match='Filtered export'):
        capture_strategy_report(prepared.project,prepared.run,scope=scope)


@pytest.mark.parametrize('key',['api_key','token','email','new_unreviewed_option'])
def test_unreviewed_parameter_keys_fail_closed(prepared,key):
    f = prepared
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        db.execute('UPDATE source_queries SET parameters_json=? WHERE query_id=?',
                   (canonical({key:'SYNTHETIC SECRET'}),f.queries['g1','pubmed']))
    before = bytes_hash(f.project)
    with pytest.raises(ReportIntegrityError) as error:
        capture_strategy_report(f.project,f.run)
    assert 'SYNTHETIC SECRET' not in str(error.value)
    assert bytes_hash(f.project) == before


def test_identifiers_without_metadata_stay_visible(prepared):
    # Reuse the separately tested immutable identifier-ledger fixture, not a mock count.
    from test_result_count_ledger import pubmed_ledger
    pubmed_ledger(prepared)
    data = capture_strategy_report(prepared.project,prepared.run).as_dict()
    query = next(q for q in data['counts']['queries'] if q['query_id']==prepared.queries['g1','pubmed'])
    assert query['reported_matches'] == query['retrieved_source_records'] == 2
    assert query['metadata_source_records'] == 0
    assert query['identifiers_without_metadata'] == 2
    assert data['status'] == 'incomplete'


def test_concurrent_commit_cannot_mix_counts_queries_and_status(prepared,monkeypatch):
    f = prepared
    with closing(sqlite3.connect(f.project.database_path)) as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
    original = result_counts._snapshot
    seen = []
    def intervening(db,p,run_id):
        counted = original(db,p,run_id)
        seen.append(id(db))
        with closing(sqlite3.connect(p.database_path)) as writer,writer:
            writer.execute("UPDATE search_runs SET status='failed' WHERE run_id=?",(run_id,))
            writer.execute("UPDATE source_queries SET status='failed' WHERE run_id=?",(run_id,))
        return counted
    monkeypatch.setattr(result_counts,'_snapshot',intervening)
    frozen = capture_strategy_report(f.project,f.run).as_dict()
    assert len(seen)==1
    assert frozen['run']['status']==frozen['counts']['stored_run_status']=='pending'
    assert all(q['status']=='pending' for q in frozen['queries'])
    assert all(q['stored_query_status']=='pending' for q in frozen['counts']['queries'])
    monkeypatch.undo()
    assert capture_strategy_report(f.project,f.run).as_dict()['run']['status']=='failed'


def test_snapshot_remains_frozen_after_reopen_relocation_and_new_status(prepared,tmp_path):
    f = prepared
    frozen = capture_strategy_report(f.project,f.run)
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        db.execute("UPDATE search_runs SET status='failed' WHERE run_id=?",(f.run,))
    target=tmp_path/'moved'
    shutil.move(str(f.project.root),target)
    moved=open_project(target)
    later=capture_strategy_report(moved,f.run)
    assert frozen.as_dict()['run']['status']=='pending'
    assert later.as_dict()['run']['status']=='failed'
    assert frozen.sha256!=later.sha256
    assert frozen.as_dict()['project']['project_id']==later.as_dict()['project']['project_id']
    assert str(target) not in later.payload_json
    assert render_strategy_workbook(frozen).startswith(b'PK')


def test_unsupported_legacy_snapshot_refused(prepared):
    f = prepared
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        db.execute('DROP TRIGGER immutable_strategy_versions_update')
        db.execute('UPDATE strategy_versions SET snapshot_json=? WHERE strategy_version_id=?',('{}',f.strategy))
    with pytest.raises(ReportIntegrityError): capture_strategy_report(f.project,f.run)


def test_unknown_run_refused_without_file_or_database_change(prepared):
    before=bytes_hash(prepared.project)
    with pytest.raises(ReportIntegrityError): capture_strategy_report(prepared.project,str(uuid4()))
    assert bytes_hash(prepared.project)==before


def test_failed_capture_leaves_no_partial_report(prepared,monkeypatch):
    def fail(*args): raise sqlite3.OperationalError('synthetic failure')
    monkeypatch.setattr(result_counts,'_snapshot',fail)
    before=bytes_hash(prepared.project)
    with pytest.raises(ReportIntegrityError): capture_strategy_report(prepared.project,prepared.run)
    assert bytes_hash(prepared.project)==before
    assert list((prepared.project.root/'exports').iterdir())==[]


def test_stored_partition_queries_retained_without_execution_claim(prepared):
    f=prepared
    q=f.queries['g1','pubmed']
    exact='"ECMO"[All Fields]'
    node=dict(index=0,parent_index=None,start='2020-01-01',end='2020-12-31',
              exact_subquery='("ECMO"[All Fields]) AND ("2020/01/01"[Create Date] : "2020/12/31"[Create Date])',
              reported_matches=0,decision='empty',depth=0,rationale='Synthetic counted date interval')
    plan=dict(format_version=1,root_query=exact,root_count=0,page_size=2,partitions=[node])
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        db.execute('UPDATE source_queries SET reported_matches=0,status="incomplete" WHERE query_id=?',(q,))
        db.execute('INSERT INTO pubmed_checkpoint_runs VALUES(?,?,?,?,?,?,?,?)',
                   (q,exact,0,canonical(plan),digest(canonical(plan)),'paused',STAMP,STAMP))
    frozen=capture_strategy_report(f.project,f.run)
    assert frozen.as_dict()['partitions'][0]['exact_subquery']==node['exact_subquery']
    assert frozen.as_dict()['partitions'][0]['evidence_scope']=='stored_count_plan_not_final_source_acceptance'
    content=render_strategy_workbook(frozen)
    with ZipFile(BytesIO(content)) as z:
        root=ET.fromstring(z.read('xl/worksheets/sheet7.xml'))
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        c=root.find('.//s:c[@r="G5"]',ns)
        assert ''.join(c.itertext())==node['exact_subquery']


def test_undeclared_strategy_fields_are_not_copied_into_export(prepared):
    f=prepared
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        raw=db.execute('SELECT snapshot_json FROM strategy_versions WHERE strategy_version_id=?',(f.strategy,)).fetchone()[0]
        doc=json.loads(raw)
        doc['api_key']='SYNTHETIC SECRET'
        db.execute('DROP TRIGGER immutable_strategy_versions_update')
        db.execute('UPDATE strategy_versions SET snapshot_json=? WHERE strategy_version_id=?',(canonical(doc),f.strategy))
    with pytest.raises(ReportIntegrityError): capture_strategy_report(f.project,f.run)


def test_render_failure_never_changes_research_state(prepared,monkeypatch):
    import openpyxl
    frozen=capture_strategy_report(prepared.project,prepared.run)
    before=bytes_hash(prepared.project)
    def fail(*a,**k): raise OSError('synthetic output failure')
    monkeypatch.setattr(openpyxl.Workbook,'save',fail)
    with pytest.raises(OSError): render_strategy_workbook(frozen)
    assert bytes_hash(prepared.project)==before
    assert list((prepared.project.root/'exports').iterdir())==[]
