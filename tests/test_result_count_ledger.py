"""Identifier-stage gaps and corrupted local count evidence remain explicit."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from research_y import publication_identity as identity
from research_y import result_counts as counts
from research_y.result_count_ledger import CountIntegrityError
from research_y.projects import open_project
from test_result_counts import (fixture, add_record, uid, STAMP, row, source_row,
                                set_reported, fingerprint)


def pubmed_ledger(f, ids=('123','456'), root_count=None):
    qid=f.queries['g1','pubmed']
    count=len(ids) if root_count is None else root_count
    exact='"ECMO"[All Fields]'
    plan={'format_version':1,'root_query':exact,'root_count':count,'page_size':2,'partitions':[]}
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('UPDATE source_queries SET reported_matches=?,status="incomplete" WHERE query_id=?',(count,qid))
        db.execute('INSERT INTO pubmed_checkpoint_runs VALUES(?,?,?,?,?,?,?,?)',
                   (qid,exact,count,identity._json(plan),identity._hash(plan),'paused',STAMP,STAMP))
        if ids:
            page={'partition_index':-1,'retstart':0,'retmax':len(ids),'pmids':list(ids),
                  'reported_matches':count,'exact_query':exact,'accepted_translation':exact,
                  'warnings':[],'review_reasons':[],'response_sha256':'a'*64,'retrieved_at_utc':STAMP}
            db.execute('INSERT INTO pubmed_checkpoint_pages VALUES(?,?,?,?,?,?,?)',
                       (qid,-1,0,len(ids),identity._json(page),identity._hash(page),STAMP))
            for i in ids: db.execute('INSERT INTO pubmed_checkpoint_ids VALUES(?,?,?,?)',(qid,i,-1,0))
    return qid


def wos_ledger(f, ids=('WOS:123','WOS:456')):
    rids=[add_record(f,'wos',i) for i in ids]
    qid=f.queries['g1','wos']
    plan={'query_id':qid,'run_id':f.run,'strategy_version_id':f.strategy,'group_id':'g1',
          'source_name':'wos','exact_query':'TS=("ECMO")','parameters_json':'{}','database':'WOS',
          'page_size':50,'project_id':str(f.project.identifier),'sort_field':'LD+A',
          'retention_authorized':True,'strategy_sha256':identity._hash({})}
    quota={'daily_limit':5000,'daily_remaining':4999,'per_second_limit':5,'valid':True}
    attempt=uid()
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('UPDATE source_queries SET reported_matches=?,status="paused" WHERE query_id=?',(len(ids),qid))
        db.execute('INSERT INTO wos_checkpoint_jobs(query_id,plan_json,plan_sha256,baseline_count,next_page,created_at_utc,updated_at_utc) '
                   'VALUES(?,?,?,?,?,?,?)',(qid,identity._json(plan),identity._hash(plan),len(ids),2,STAMP,STAMP))
        db.execute('INSERT INTO wos_checkpoint_attempts(attempt_id,query_id,owner_token,purpose,page_number,page_size,'
                   'started_at_utc,finished_at_utc,outcome,http_status,sent,quota_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   (attempt,qid,uid(),'acquire',1,50,STAMP,STAMP,'success',200,1,identity._json(quota)))
        records=[identity._object(db.execute('SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?',(r,)).fetchone()[0])['record'] for r in rids]
        body={'metadata':{'total':len(ids),'page':1,'limit':50},'hits':records}
        descriptor={'exact_query':plan['exact_query'],'database':'WOS','requested_page':1,
                    'requested_limit':50,'retrieved_at_utc':STAMP,'quota':quota}
        db.execute('INSERT INTO wos_checkpoint_observations VALUES(?,?,?,?,?)',
                   (attempt,identity._json(body),identity._hash(body),identity._json(descriptor),identity._hash(descriptor)))
        db.execute('INSERT INTO wos_checkpoint_pages VALUES(?,?,?,?)',(qid,1,attempt,identity._hash(list(ids))))
        for n,(i,r,record) in enumerate(zip(ids,rids,records)):
            db.execute('INSERT INTO wos_checkpoint_ids VALUES(?,?,?,?,?,?)',(qid,i,1,n,r,identity._hash(record)))
    return qid,attempt,rids


def corrupt(db, table):
    # Corruption fixtures deliberately remove immutable protection, never production.
    for (name,) in db.execute('SELECT name FROM sqlite_master WHERE type="trigger" AND tbl_name=?',(table,)).fetchall():
        db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')


def test_pubmed_identifiers_reconciled_does_not_hide_missing_metadata(fixture):
    pubmed_ledger(fixture)
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert row(r)['reported_matches']==row(r)['retrieved_source_records']==2
    assert row(r)['metadata_source_records']==0
    assert row(r)['identifiers_without_metadata']==2
    assert row(r)['numeric_reconciliation']=='equal'
    assert r.totals['source_record_sum']==2
    assert r.totals['global_publication_identities']==0
    assert not r.source_retrieval_verified and not r.full_checkpoint_validation_performed
    assert 'identifiers_without_metadata' in r.warnings


def test_partial_metadata_and_cross_group_union(fixture):
    pubmed_ledger(fixture)
    add_record(fixture,groups=('g2',))
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert row(r)['identifiers_without_metadata']==2
    assert source_row(r)['source_unique_records']==2
    assert source_row(r)['metadata_source_records']==1
    assert source_row(r)['identifiers_without_metadata']==1


def test_pubmed_partial_identifier_shortfall(fixture):
    pubmed_ledger(fixture,ids=('123','456'),root_count=5)
    add_record(fixture)
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert row(r)['retrieved_minus_reported']==-3
    assert row(r)['identifiers_without_metadata']==1
    assert r.totals['unmaterialised_retrievals']==1


def test_pubmed_empty_result_is_explicit_zero_without_metadata(fixture):
    pubmed_ledger(fixture,ids=())
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert row(r)['retrieved_source_records']==0
    assert row(r)['reported_matches']==0
    assert row(r)['numeric_reconciliation']=='equal'
    assert not r.verified_complete


@pytest.mark.parametrize('damage', ['plan_checksum','plan_query','plan_count','page_checksum','page_offset','page_ids',
                                   'page_duplicate','index','metadata_outside','reported_count'], ids=str)
def test_pubmed_damage_never_returns_successful_numeric_count(fixture,damage):
    f=fixture
    qid=pubmed_ledger(f)
    if damage=='metadata_outside': add_record(f,identifier='789')
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        if damage=='plan_checksum': db.execute('UPDATE pubmed_checkpoint_runs SET plan_sha256=? WHERE query_id=?',('b'*64,qid))
        elif damage in ('plan_query','plan_count'):
            raw=db.execute('SELECT plan_json FROM pubmed_checkpoint_runs WHERE query_id=?',(qid,)).fetchone()[0]
            value=identity._object(raw)
            value['root_query' if damage=='plan_query' else 'root_count']='wrong' if damage=='plan_query' else 3
            db.execute('UPDATE pubmed_checkpoint_runs SET plan_json=?,plan_sha256=? WHERE query_id=?',(identity._json(value),identity._hash(value),qid))
        elif damage in ('page_checksum','page_offset','page_ids','page_duplicate'):
            corrupt(db,'pubmed_checkpoint_pages')
            raw=db.execute('SELECT page_json FROM pubmed_checkpoint_pages WHERE query_id=?',(qid,)).fetchone()[0]
            value=identity._object(raw)
            if damage=='page_offset': value['retstart']=1
            elif damage=='page_ids': value['pmids']=['invalid','456']
            elif damage=='page_duplicate': value['pmids']=['123','123']
            db.execute('UPDATE pubmed_checkpoint_pages SET page_json=?,page_sha256=? WHERE query_id=?',
                       (identity._json(value),'b'*64 if damage=='page_checksum' else identity._hash(value),qid))
        elif damage=='index':
            corrupt(db,'pubmed_checkpoint_ids')
            db.execute('UPDATE pubmed_checkpoint_ids SET pmid="789" WHERE query_id=? AND pmid="123"',(qid,))
        elif damage=='reported_count': db.execute('UPDATE source_queries SET reported_matches=7 WHERE query_id=?',(qid,))
    before=fingerprint(f.project)
    with pytest.raises(CountIntegrityError): counts.read_run_counts(f.project,f.run)
    assert fingerprint(f.project)==before


def test_starter_saved_metadata_and_page_index_count_agree(fixture):
    wos_ledger(fixture)
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert row(r,source='wos')['retrieved_source_records']==2
    assert row(r,source='wos')['metadata_source_records']==2
    q=next(q for q in r.queries if q['query_id']==fixture.queries['g1','wos'])
    assert q['checkpoint_check_scope']=='stored_hashes_and_identifier_links'
    assert not r.full_checkpoint_validation_performed


def test_starter_empty_acquisition_does_not_fabricate_abstracts(fixture):
    wos_ledger(fixture,ids=())
    r=counts.read_run_counts(fixture.project,fixture.run)
    assert row(r,source='wos')['numeric_reconciliation']=='equal'
    assert source_row(r,'wos')['source_unique_records']==0
    assert r.totals['extracted_individual_abstracts'] is None


@pytest.mark.parametrize('damage',['plan_checksum','plan_query','attempt','response_checksum','descriptor_checksum',
                                  'descriptor_page','uid_digest','body_count','body_ids','index_record','metadata',
                                  'extra_membership','reported_count'],ids=str)
def test_starter_damaged_evidence_fails_without_repair(fixture,damage):
    f=fixture
    qid,attempt,rids=wos_ledger(f)
    if damage=='extra_membership': add_record(f,'wos','WOS:789')
    with closing(sqlite3.connect(f.project.database_path)) as db,db:
        if damage in ('plan_checksum','plan_query'):
            corrupt(db,'wos_checkpoint_jobs')
            value=identity._object(db.execute('SELECT plan_json FROM wos_checkpoint_jobs WHERE query_id=?',(qid,)).fetchone()[0])
            if damage=='plan_query': value['exact_query']='different'
            db.execute('UPDATE wos_checkpoint_jobs SET plan_json=?,plan_sha256=? WHERE query_id=?',
                       (identity._json(value),'b'*64 if damage=='plan_checksum' else identity._hash(value),qid))
        elif damage=='attempt':
            corrupt(db,'wos_checkpoint_attempts')
            db.execute('UPDATE wos_checkpoint_attempts SET http_status=503 WHERE attempt_id=?',(attempt,))
        elif damage in ('response_checksum','descriptor_checksum','descriptor_page','body_count','body_ids'):
            corrupt(db,'wos_checkpoint_observations')
            body,desc=db.execute('SELECT response_json,descriptor_json FROM wos_checkpoint_observations WHERE attempt_id=?',(attempt,)).fetchone()
            body,desc=identity._object(body),identity._object(desc)
            if damage=='descriptor_page': desc['requested_page']=2
            if damage=='body_count': body['metadata']['total']=3
            if damage=='body_ids': body['hits'][0]['uid']='WOS:456'
            db.execute('UPDATE wos_checkpoint_observations SET response_json=?,response_sha256=?,descriptor_json=?,descriptor_sha256=? WHERE attempt_id=?',
                       (identity._json(body),'b'*64 if damage=='response_checksum' else identity._hash(body),
                        identity._json(desc),'b'*64 if damage=='descriptor_checksum' else identity._hash(desc),attempt))
        elif damage=='uid_digest':
            corrupt(db,'wos_checkpoint_pages')
            db.execute('UPDATE wos_checkpoint_pages SET uid_sha256=? WHERE query_id=?',('b'*64,qid))
        elif damage=='index_record':
            corrupt(db,'wos_checkpoint_ids')
            db.execute('UPDATE wos_checkpoint_ids SET record_sha256=? WHERE query_id=?',('b'*64,qid))
        elif damage=='metadata':
            value=identity._object(db.execute('SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?',(rids[0],)).fetchone()[0])
            value['record']['title']='Changed title'
            db.execute('UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?',(identity._json(value),rids[0]))
        elif damage=='reported_count': db.execute('UPDATE source_queries SET reported_matches=99 WHERE query_id=?',(qid,))
    before=fingerprint(f.project)
    with pytest.raises(CountIntegrityError): counts.read_run_counts(f.project,f.run)
    assert fingerprint(f.project)==before


def test_checkpoint_cannot_be_mislabelled_as_other_source(fixture):
    qid=pubmed_ledger(fixture)
    with closing(sqlite3.connect(fixture.project.database_path)) as db,db:
        db.execute('UPDATE source_queries SET source_name="manual" WHERE query_id=?',(qid,))
    with pytest.raises(CountIntegrityError): counts.read_run_counts(fixture.project,fixture.run)


def test_counts_refuse_hot_journal_until_explicit_project_recovery(fixture):
    f=fixture
    rid=add_record(f)
    original=counts.read_run_counts(f.project,f.run)
    child='''import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1])
c.execute('PRAGMA cache_size=10')
c.execute('BEGIN IMMEDIATE')
c.execute('UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?',('X'*2000000,sys.argv[2]))
os._exit(33)
'''
    result=subprocess.run([sys.executable,'-c',child,str(f.project.database_path),rid],capture_output=True,text=True,timeout=20)
    assert result.returncode==33,result.stderr
    journal=Path(str(f.project.database_path)+'-journal')
    assert journal.exists()
    before=fingerprint(f.project)
    with pytest.raises(CountIntegrityError): counts.read_run_counts(f.project,f.run)
    assert fingerprint(f.project)==before
    assert counts.read_run_counts(open_project(f.project.root),f.run)==original
    assert not journal.exists()
