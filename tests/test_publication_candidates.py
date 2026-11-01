"""Disk-backed candidate/decision contracts; synthetic data and no network."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from research_y.projects import create_project, open_project
from research_y import publication_candidates as candidate_module
from research_y.publication_candidates import (
    DECISION_EVENT, decide_candidate, find_candidates, read_candidate,
)
from research_y.publication_fields import select_source_field, clear_source_field
from research_y.publication_identity import (
    PublicationIntegrityError, StalePublicationError, materialise_retrieval,
    read_publication, reverse_association, read_retrieval_history,
)

STAMP = "2026-11-01T12:00:00+00:00"


def metadata(kind, *, doi="10.1234/example", title="Synthetic publication"):
    if kind == "pubmed":
        return {"source": "NCBI PubMed EFetch XML", "record": {
            "pmid": "100", "title": title, "identifiers": {"doi": [doi], "pmid": ["100"]},
            "authors": [{"last_name": "Test", "fore_name": "Ada"}],
            "publication_dates": [{"kind": "journal_pub_date", "year": "2026"}],
            "journal": {"title": "Synthetic Journal", "pages": "11-19"},
            "publication_types": ["Journal Article"], "abstract_status": "present",
            "abstract_sections": [{"text": "PRIVATE-SYNTHETIC-ABSTRACT"}]},
            "rights_review_required_for_abstract_redistribution": True}
    return {"provider": "wos_starter", "database": "WOS", "record": {
        "uid": "WOS:000000000000001", "title": title, "identifiers": {"doi": doi, "pmid": "100"},
        "source": {"sourceTitle": "Synthetic Journal", "publishYear": 2026, "pages": {"range": "11-19"}},
        "names": {"authors": [{"displayName": "Test, Ada"}]}, "types": ["Article"]},
        "abstract_status": "not_returned_by_source", "rights_status": "licence_review_required"}


def seed(project, payload, kind, *, run_id=None, memberships=True):
    retrieval_id, version = str(uuid4()), str(uuid4())
    run_id = run_id or str(uuid4())
    source_id = payload["record"].get("pmid") if kind == "pubmed" else payload["record"].get("uid")
    source_id = source_id or "SYNTHETIC:unknown"
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        number = db.execute("SELECT COUNT(*)+1 FROM strategy_versions").fetchone()[0]
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)", (version, number, STAMP, '{}'))
        for i in range(2):
            db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)", (version, f'g{i}', f'Group {i}', i))
        db.execute("INSERT INTO search_runs(run_id,strategy_version_id,created_at_utc,status) VALUES(?,?,?,'incomplete')",
                   (run_id, version, STAMP))
        db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                   (retrieval_id, run_id, kind, source_id, STAMP, json.dumps(payload)))
        if memberships:
            for i in range(2):
                query_id = str(uuid4())
                db.execute("INSERT INTO source_queries(query_id,run_id,strategy_version_id,group_id,source_name,exact_query,reported_matches,status) "
                           "VALUES(?,?,?,?,?,?,1,'incomplete')", (query_id, run_id, version, f'g{i}', kind, 'Synthetic approved query'))
                db.execute("INSERT INTO query_retrievals VALUES(?,?,?,?)", (query_id, retrieval_id, run_id, kind))
    materialise_retrieval(project, retrieval_id, actor="Fixture")
    return retrieval_id


def setup(tmp_path, left=None, right=None, *, memberships=True):
    project = create_project(tmp_path, "Candidate fixture")
    a = seed(project, metadata("pubmed") if left is None else left, "pubmed", memberships=memberships)
    b = seed(project, metadata("wos") if right is None else right, "wos", memberships=memberships)
    return project, a, b


def dump(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return '\n'.join(db.iterdump())


def source_state(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        return {table: db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in (
            'source_retrievals', 'source_queries', 'query_retrievals', 'search_runs', 'strategy_versions', 'strategy_groups')}


def args(snapshot, *, decision="rejected_match", moving=None):
    return dict(expected_revision=snapshot.revision, decision=decision, actor="Researcher",
                evidence="Explicit synthetic evidence", acknowledged_warnings=snapshot.warnings,
                decision_confirmed=True, move_retrieval_id=moving)


def decide(project, a, b, **options):
    return decide_candidate(project, a, b, **options)


def test_comparison_is_symmetric_read_only_and_not_automatic(tmp_path):
    p, a, b = setup(tmp_path)
    before = dump(p)
    result = read_candidate(p, a, b)
    assert read_candidate(p, b, a) == result
    assert dump(p) == before
    assert result.status == 'review_required'
    assert not result.automatic_match_allowed and not result.deduplication_complete
    for field in ('title', 'doi', 'pmid', 'authors', 'year', 'journal', 'pages'):
        assert result.comparison['comparisons'][field] == 'equal'
    assert 'doi_scope_and_registration_unverified' in result.warnings
    assert len(result.sources) == 2 and all(len(s['memberships']) == 2 for s in result.sources)
    assert all(s['run_status'] == 'incomplete' for s in result.sources)


@pytest.mark.parametrize('doi', ['10.1234/EXAMPLE', 'https://doi.org/10.1234/example',
    'http://dx.doi.org/10.1234/example', 'doi:10.1234/example', ' 10.1234/example '],
    ids=['case', 'https-prefix', 'dx-prefix', 'doi-prefix', 'outer-space'])
def test_only_conservative_identifier_variants_agree(tmp_path, doi):
    p, a, b = setup(tmp_path, right=metadata('wos', doi=doi))
    result = read_candidate(p, a, b)
    assert result.comparison['comparisons']['doi'] == 'equal'
    assert result.status == 'review_required'


@pytest.mark.parametrize('value', [None, '', [], 123, True, {}, ['10.1234/example', '10.1234/other'],
                                  ['10.1234/example', None], 'bad', '10.1234/a b'],
                         ids=['null','empty','list','number','boolean','object','multiple','mixed','invalid','space'])
def test_missing_malformed_multiple_identifiers_never_agree(tmp_path, value):
    right = metadata('wos'); right['record']['identifiers']['doi'] = value
    p, a, b = setup(tmp_path, right=right)
    assert read_candidate(p, a, b).comparison['comparisons']['doi'] == 'not_comparable'


@pytest.mark.parametrize('value', ['10.1234/example.', '10.1234/ex%61mple', '10.1234/(example)'])
def test_punctuation_and_encoding_are_not_silently_stripped(tmp_path, value):
    p, a, b = setup(tmp_path, right=metadata('wos', doi=value))
    assert read_candidate(p, a, b).comparison['comparisons']['doi'] == 'different'


@pytest.mark.parametrize('parent', ['10.1234/example', ['10.1234/example'], True])
def test_malformed_parent_cannot_impersonate_identifier_field(tmp_path, parent):
    right = metadata('wos'); right['record']['identifiers'] = parent
    p, a, b = setup(tmp_path, right=right)
    assert read_candidate(p, a, b).comparison['comparisons']['doi'] == 'not_comparable'


def test_identical_missing_titles_are_not_agreement(tmp_path):
    left = metadata('pubmed', title=None); right = metadata('wos', title=None)
    p, a, b = setup(tmp_path, left, right)
    assert read_candidate(p, a, b).comparison['comparisons']['title'] == 'not_comparable'


def test_same_doi_does_not_hide_conflicting_title_year_and_pmid(tmp_path):
    right = metadata('wos', title='Different synthetic publication')
    right['record']['source']['publishYear'] = 2024
    right['record']['identifiers']['pmid'] = '999'
    p, a, b = setup(tmp_path, right=right)
    c = read_candidate(p, a, b)
    assert c.comparison['candidate_hint'] and c.status == 'review_required'
    assert {'title_different', 'year_different', 'pmid_different'} <= set(c.warnings)


@pytest.mark.parametrize('types', [['Meeting Abstract'], ['Proceedings Paper'], ['Conference Abstract']])
def test_shared_container_or_abstract_is_never_automatic(tmp_path, types):
    right = metadata('wos'); right['record']['types'] = types
    right['record']['container'] = {'doi': '10.1234/example'}
    p, a, b = setup(tmp_path, right=right)
    c = read_candidate(p, a, b)
    assert 'abstract_or_container_scope_requires_review' in c.warnings
    assert 'container_or_abstract_metadata_present' in c.warnings
    assert len(set(c.publication_ids)) == 2 and not c.automatic_match_allowed


@pytest.mark.parametrize('dates', [[{'kind':'pubmed_history_received','year':'2026'}],
    [{'kind':'journal_pub_date','year':'2026'}, {'kind':'article_Electronic','year':'2025'}],
    [{'kind':'journal_pub_date','year':'2026'}, 'malformed']], ids=['history','ambiguous','malformed'])
def test_dates_are_not_invented_from_history_or_ambiguity(tmp_path, dates):
    left=metadata('pubmed'); left['record']['publication_dates']=dates
    p,a,b=setup(tmp_path,left=left)
    assert read_candidate(p,a,b).comparison['comparisons']['year']=='not_comparable'


def test_rejection_persists_and_exact_retry_is_noop(tmp_path):
    p,a,b=setup(tmp_path); current=read_candidate(p,a,b); request=args(current)
    before=source_state(p)
    rejected=decide(p,a,b,**request)
    assert rejected.status=='rejected_match'
    assert rejected.prior_decisions[-1]['status']=='rejected_match'
    after=dump(p)
    assert decide(open_project(p.root),b,a,**request)==rejected
    assert dump(p)==after and source_state(p)==before
    assert len(set(rejected.publication_ids))==2


def test_confirmation_retains_every_membership_and_original(tmp_path):
    p,a,b=setup(tmp_path); current=read_candidate(p,a,b); before=source_state(p)
    request=args(current,decision='confirmed_match',moving=a)
    matched=decide(p,a,b,**request)
    assert matched.status=='confirmed_match' and len(set(matched.publication_ids))==1
    publication=read_publication(p,matched.publication_ids[0])
    assert len(publication.retrievals)==2 and sum(len(r['memberships']) for r in publication.retrievals)==4
    assert source_state(p)==before
    after=dump(p); assert decide(p,a,b,**request)==matched and dump(p)==after
    receipt=matched.prior_decisions[-1]
    assert receipt['association_event_id'] and receipt['reviewed_context']['sources']
    assert 'PRIVATE-SYNTHETIC-ABSTRACT' not in json.dumps(receipt)
    assert 'Synthetic publication' not in json.dumps(receipt)
    assert receipt['comparison']['comparisons']['doi']=='equal'


def test_explicit_reconsideration_retains_rejection_and_undo_invalidates_receipt(tmp_path):
    p,a,b=setup(tmp_path); original=read_candidate(p,a,b)
    rejected=decide(p,a,b,**args(original))
    matched=decide(p,a,b,**args(rejected,decision='confirmed_match',moving=a))
    assert [d['status'] for d in matched.prior_decisions]==['rejected_match','confirmed_match']
    with pytest.raises(ValueError,match='Reverse'):
        decide(p,a,b,**args(matched))
    old_id=original.publication_ids[original.retrieval_ids.index(a)]
    current=read_publication(p,matched.publication_ids[0]); restored=read_publication(p,old_id)
    reverse_association(p,a,matched.prior_decisions[-1]['association_event_id'],
        expected_current_revision=current.revision,expected_restored_revision=restored.revision,
        actor='Researcher',evidence='Undo synthetic decision')
    fresh=read_candidate(p,a,b)
    assert fresh.status=='review_required' and 'prior_decision_needs_review' in fresh.warnings
    assert len(set(fresh.publication_ids))==2
    with pytest.raises(StalePublicationError):
        decide(p,a,b,**args(rejected,decision='confirmed_match',moving=a))
    assert decide(p,a,b,**args(fresh)).status=='rejected_match'


@pytest.mark.parametrize('change', ['source-run','target-run','query','field'])
def test_changed_review_context_rejects_stale_decision(tmp_path,change):
    p,a,b=setup(tmp_path); old=read_candidate(p,a,b)
    if change=='field':
        s=read_publication(p,old.publication_ids[0])
        select_source_field(p,s.publication_id,'title',retrieval_id=old.retrieval_ids[0],
            path=('record','title'),expected_revision=s.revision,actor='Editor',reason='Choice')
    else:
        source=next(s for s in old.sources if s['retrieval_id']==(a if change=='source-run' else b))
        with closing(sqlite3.connect(p.database_path)) as db,db:
            if change=='query': db.execute("UPDATE source_queries SET status='failed'")
            else: db.execute("UPDATE search_runs SET status='failed' WHERE run_id=?",(source['run_id'],))
    before=dump(p)
    with pytest.raises(StalePublicationError): decide(p,a,b,**args(old))
    assert dump(p)==before and read_candidate(p,a,b).revision!=old.revision


def test_exact_retry_after_run_change_is_not_accepted(tmp_path):
    p,a,b=setup(tmp_path); request=args(read_candidate(p,a,b));decide(p,a,b,**request)
    with closing(sqlite3.connect(p.database_path)) as db,db: db.execute("UPDATE search_runs SET status='failed'")
    before=dump(p)
    with pytest.raises(StalePublicationError):decide(p,a,b,**request)
    assert dump(p)==before


@pytest.mark.parametrize('option,value', [('decision_confirmed',False),('decision_confirmed',1),
    ('actor',''),('evidence',''),('expected_revision','invalid'),('decision','automatic_high_confidence'),
    ('acknowledged_warnings',()),('move_retrieval_id',str(uuid4()))],
    ids=['unconfirmed','truthy','actor','evidence','token','automatic','unacknowledged','wrong-move'])
def test_invalid_decisions_make_no_changes(tmp_path,option,value):
    p,a,b=setup(tmp_path); request=args(read_candidate(p,a,b));request[option]=value;before=dump(p)
    with pytest.raises(ValueError):decide(p,a,b,**request)
    assert dump(p)==before


@pytest.mark.parametrize('guard',['field','annotation'])
def test_existing_identity_guards_are_not_bypassed(tmp_path,guard):
    p,a,b=setup(tmp_path);c=read_candidate(p,a,b);pid=c.publication_ids[c.retrieval_ids.index(a)]
    if guard=='field':
        s=read_publication(p,pid)
        select_source_field(p,pid,'title',retrieval_id=a,path=('record','title'),expected_revision=s.revision,
                            actor='Researcher',reason='Keep field')
    else:
        with closing(sqlite3.connect(p.database_path)) as db,db:
            db.execute("INSERT INTO classifications VALUES(?,?,?,?,?,?,?)",(str(uuid4()),pid,'design','unknown','review_required','{}',STAMP))
    c=read_candidate(p,a,b);before=dump(p)
    with pytest.raises(ValueError):decide(p,a,b,**args(c,decision='confirmed_match',moving=a))
    assert dump(p)==before


@pytest.mark.parametrize('failure',['receipt','identity','link'])
def test_decision_and_association_roll_back_together(tmp_path,failure):
    p,a,b=setup(tmp_path);c=read_candidate(p,a,b)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        if failure=='link':
            db.execute("CREATE TRIGGER reject_link BEFORE UPDATE ON publication_retrievals BEGIN SELECT RAISE(ABORT,'fail'); END")
        else:
            event=DECISION_EVENT if failure=='receipt' else 'publication_identity_v1'
            db.execute(f"CREATE TRIGGER reject_decision BEFORE INSERT ON audit_events WHEN NEW.event_type='{event}' BEGIN SELECT RAISE(ABORT,'fail'); END")
    before=dump(p)
    with pytest.raises(sqlite3.IntegrityError):decide(p,a,b,**args(c,decision='confirmed_match',moving=a))
    assert dump(p)==before


def test_previous_run_receipts_visible_not_automatically_applied(tmp_path):
    p,a,b=setup(tmp_path);old=read_candidate(p,a,b);request=args(old);decide(p,a,b,**request)
    a2=seed(p,metadata('pubmed'),'pubmed');b2=seed(p,metadata('wos',title='Changed title'),'wos')
    fresh=read_candidate(p,a2,b2)
    assert fresh.status=='review_required' and len(set(fresh.publication_ids))==2
    assert 'prior_run_decision_available' in fresh.warnings and 'title_different' in fresh.warnings
    assert fresh.prior_decisions[-1]['status']=='rejected_match'
    decide(p,a2,b2,**args(fresh))
    with pytest.raises(StalePublicationError):decide(p,a,b,**request)


def test_other_source_namespace_does_not_inherit_receipt(tmp_path):
    p,a,b=setup(tmp_path);decide(p,a,b,**args(read_candidate(p,a,b)))
    a2=seed(p,metadata('pubmed'),'pubmed');raw=metadata('wos');raw['database']='MEDLINE'
    b2=seed(p,raw,'wos');c=read_candidate(p,a2,b2)
    assert not c.prior_decisions


def test_reopen_and_relocation_preserve_receipts(tmp_path):
    p,a,b=setup(tmp_path);result=decide(p,a,b,**args(read_candidate(p,a,b)))
    destination=tmp_path/'relocated';shutil.move(str(p.root),destination)
    assert read_candidate(open_project(destination),a,b)==result


def test_bounded_candidate_batch_is_read_only_and_does_not_truncate(tmp_path):
    p,a,b=setup(tmp_path);before=dump(p)
    assert len(find_candidates(p,(b,a)))==1 and dump(p)==before
    for ids in ((a,), (a,a), tuple(str(uuid4()) for _ in range(33))):
        with pytest.raises(ValueError):find_candidates(p,ids)
    assert dump(p)==before


def test_unrelated_audit_does_not_invalidate_candidate(tmp_path):
    p,a,b=setup(tmp_path);c=read_candidate(p,a,b)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES(?,?,?)",(STAMP,'unrelated','{}'))
    assert read_candidate(p,a,b)==c


def test_unknown_source_does_not_fabricate_metadata(tmp_path):
    p,a,b=setup(tmp_path,right={'record':{'uid':'WOS:unknown'},'provider':'other'})
    c=read_candidate(p,a,b)
    assert 'unsupported_source_layout' in c.warnings
    assert all(v=='not_comparable' for v in c.comparison['comparisons'].values())


def test_source_corruption_fails_closed(tmp_path):
    p,a,b=setup(tmp_path)
    with closing(sqlite3.connect(p.database_path)) as db,db:
        db.execute("UPDATE source_retrievals SET original_metadata_json='{}' WHERE retrieval_id=?",(a,))
    with pytest.raises(PublicationIntegrityError):read_candidate(p,a,b)


def test_receipts_are_append_only_and_corrupt_receipts_fail_closed(tmp_path):
    p,a,b=setup(tmp_path);r=decide(p,a,b,**args(read_candidate(p,a,b)))
    with closing(sqlite3.connect(p.database_path)) as db,db:
        for sql in ("UPDATE audit_events SET details_json='{}'", "DELETE FROM audit_events"):
            with pytest.raises(sqlite3.IntegrityError):db.execute(sql)
        db.execute("INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES(?,?,?)",
                   (STAMP,DECISION_EVENT,json.dumps({'version':1,'at_utc':STAMP})))
    with pytest.raises(PublicationIntegrityError):read_candidate(p,a,b)


def test_queryless_parent_run_still_invalidates_review(tmp_path):
    p,a,b=setup(tmp_path,memberships=False);c=read_candidate(p,a,b)
    with closing(sqlite3.connect(p.database_path)) as db,db:db.execute("UPDATE search_runs SET status='cancelled'")
    with pytest.raises(StalePublicationError):decide(p,a,b,**args(c))


def test_rule_change_requires_fresh_review(tmp_path,monkeypatch):
    p,a,b=setup(tmp_path);request=args(read_candidate(p,a,b));decide(p,a,b,**request)
    monkeypatch.setattr(candidate_module,'RULE_VERSION','source-pair-comparison/2')
    assert read_candidate(p,a,b).status=='review_required'
    with pytest.raises(StalePublicationError):decide(p,a,b,**request)


def test_concurrent_exact_decisions_produce_one_receipt(tmp_path):
    p,a,b=setup(tmp_path);request=args(read_candidate(p,a,b),decision='confirmed_match',moving=a)
    script='''import json,sys
from research_y.projects import open_project
from research_y.publication_candidates import decide_candidate
p=open_project(sys.argv[1]);r=decide_candidate(p,sys.argv[2],sys.argv[3],**json.loads(sys.argv[4]))
assert r.status=="confirmed_match"
'''
    command=[sys.executable,'-c',script,str(p.root),a,b,json.dumps(request)]
    procs=[subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    try:
        for proc in procs:
            stdout,stderr=proc.communicate(timeout=30)
            assert proc.returncode==0,stderr
    finally:
        for proc in procs:
            if proc.poll() is None:proc.kill();proc.communicate()
    with closing(sqlite3.connect(p.database_path)) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type=?",(DECISION_EVENT,)).fetchone()[0]==1
    assert len(read_retrieval_history(p,a))==2


def test_abrupt_exit_between_identity_and_receipt_recovers(tmp_path):
    p,a,b=setup(tmp_path);before=dump(p);request=args(read_candidate(p,a,b),decision='confirmed_match',moving=a)
    script='''import json,os,sys
from research_y.projects import open_project
from research_y import publication_identity as identity
from research_y.publication_candidates import decide_candidate,DECISION_EVENT
real=identity._audit
def crash(db,kind,details):
    if kind==DECISION_EVENT:
        db.execute("PRAGMA cache_size=10")
        db.execute("UPDATE project_metadata SET theme=?",("X"*10000000,))
        os._exit(37)
    return real(db,kind,details)
identity._audit=crash
p=open_project(sys.argv[1]);decide_candidate(p,sys.argv[2],sys.argv[3],**json.loads(sys.argv[4]))
'''
    process=subprocess.run([sys.executable,'-c',script,str(p.root),a,b,json.dumps(request)],
                           capture_output=True,text=True,timeout=30,check=False)
    assert process.returncode==37,process.stderr
    journal=Path(str(p.database_path)+'-journal');assert journal.exists()
    reopened=open_project(p.root);assert dump(reopened)==before and not journal.exists()
    assert decide(reopened,a,b,**request).status=='confirmed_match'


@pytest.mark.parametrize('kind', ['source-id','redundant-pmid','authors','types','year'])
def test_malformed_optional_values_are_visible_not_agreement(tmp_path, kind):
    left=metadata('pubmed');right=metadata('wos')
    if kind=='source-id':
        left['record']['pmid']=['100']
    elif kind=='redundant-pmid':left['record']['identifiers']['pmid']=['999']
    elif kind=='authors':right['record']['names']['authors']=[{'displayName':None}]
    elif kind=='types':right['record']['types']=['Article',None]
    elif kind=='year':right['record']['source']['publishYear']=True
    if kind=='source-id':
        # The stored provider identifier is canonical, while the metadata is not.
        p,a,b=setup(tmp_path)
        # Mutate BEFORE materialisation via a separate fixture record.
        left['record']['pmid']='100'
        a=seed(p,left,'pubmed')
        # Test this invariant using a direct projection; existing rows reject corruption.
        from research_y.publication_match_evidence import project_source
        from research_y.publication_identity import _source
        with closing(sqlite3.connect(p.database_path)) as db:
            source=_source(db,a)
        source['original_metadata']['record']['pmid']=['999']
        assert 'source_identifier_unverified' in project_source(source)['warnings']
        return
    p,a,b=setup(tmp_path,left,right);c=read_candidate(p,a,b)
    if kind=='redundant-pmid':assert 'conflicting_source_identifiers' in c.warnings
    else:assert c.comparison['comparisons'][{'types':'document_types'}.get(kind,kind)]=='not_comparable'


def test_nested_starter_supplement_and_container_only_doi_not_publication_id(tmp_path):
    right=metadata('wos');right['record']['source']['supplement']='Supplement 1'
    right['record']['identifiers'].pop('doi');right['record']['container']={'doi':'10.1234/example'}
    p,a,b=setup(tmp_path,right=right);c=read_candidate(p,a,b)
    assert c.comparison['comparisons']['doi']=='not_comparable'
    assert 'container_or_abstract_metadata_present' in c.warnings


def test_source_fields_not_caller_modified_snapshot_are_authoritative(tmp_path):
    p,a,b=setup(tmp_path);c=read_candidate(p,a,b)
    c.comparison['comparisons']['title']='forged'
    result=decide(p,a,b,**args(c))
    assert result.prior_decisions[-1]['comparison']['comparisons']['title']=='equal'


def test_collective_author_and_no_author_cases_are_not_invented(tmp_path):
    left=metadata('pubmed');left['record']['authors']=[{'collective_name':'Synthetic Group'}]
    right=metadata('wos');right['record']['names']['authors']=[{'displayName':'Synthetic Group'}]
    p,a,b=setup(tmp_path,left,right)
    assert read_candidate(p,a,b).comparison['comparisons']['authors']=='equal'
    left['record']['authors']=[42];a2=seed(p,left,'pubmed')
    assert read_candidate(p,a2,b).comparison['comparisons']['authors']=='not_comparable'


def test_new_decision_can_reconfirm_already_associated_pair(tmp_path):
    p,a,b=setup(tmp_path);c=read_candidate(p,a,b)
    matched=decide(p,a,b,**args(c,decision='confirmed_match',moving=a))
    links_before=read_retrieval_history(p,a)
    request=args(matched,decision='confirmed_match',moving=a);request['evidence']='Fresh explicit confirmation'
    again=decide(p,a,b,**request)
    assert len(again.prior_decisions)==2 and again.prior_decisions[-1]['association_event_id'] is None
    assert read_retrieval_history(p,a)==links_before


def test_empty_no_support_batch_returns_none_without_claiming_no_duplicates(tmp_path):
    right=metadata('wos',title='Another title',doi='10.1234/other');right['record']['identifiers']['pmid']='999'
    p,a,b=setup(tmp_path,right=right);c=read_candidate(p,a,b)
    assert not c.comparison['candidate_hint'] and not c.deduplication_complete
    assert find_candidates(p,(a,b))==()
    decide(p,a,b,**args(c));assert len(find_candidates(p,(a,b)))==1


@pytest.mark.parametrize('warnings', [None, ['duplicated','duplicated'], [False]])
def test_invalid_warning_acknowledgement_rejected(tmp_path,warnings):
    p,a,b=setup(tmp_path);request=args(read_candidate(p,a,b));request['acknowledged_warnings']=warnings
    before=dump(p)
    with pytest.raises(ValueError):decide(p,a,b,**request)
    assert dump(p)==before


def test_identical_or_unmaterialised_ids_and_bad_namespace_rejected(tmp_path):
    p,a,b=setup(tmp_path)
    with pytest.raises(ValueError):read_candidate(p,a,a)
    with pytest.raises(ValueError):read_candidate(p,a,str(uuid4()))
    raw=metadata('wos');raw['database']=42;b2=seed(p,raw,'wos')
    with pytest.raises(PublicationIntegrityError):read_candidate(p,a,b2)


def test_shared_association_helper_requires_existing_transaction(tmp_path):
    from research_y.publication_identity import _associate_in_transaction
    p,a,b=setup(tmp_path);c=read_candidate(p,a,b)
    with closing(sqlite3.connect(p.database_path)) as db:
        with pytest.raises(ValueError,match='transaction'):
            _associate_in_transaction(db,a,c.publication_ids[c.retrieval_ids.index(b)],
                expected_source_revision=c.publication_revisions[c.retrieval_ids.index(a)],
                expected_target_revision=c.publication_revisions[c.retrieval_ids.index(b)],
                actor='Researcher',evidence='Not allowed',same_publication_confirmed=True)


def test_original_public_association_api_still_works_and_invalidates_candidate(tmp_path):
    from research_y.publication_identity import associate_retrieval
    p,a,b=setup(tmp_path);c=decide(p,a,b,**args(read_candidate(p,a,b)))
    origin=c.publication_ids[c.retrieval_ids.index(a)];target=c.publication_ids[c.retrieval_ids.index(b)]
    options=dict(expected_source_revision=read_publication(p,origin).revision,
        expected_target_revision=read_publication(p,target).revision,actor='Direct reviewer',
        evidence='Explicit direct review',same_publication_confirmed=True)
    result=associate_retrieval(p,a,target,**options);after=dump(p)
    assert associate_retrieval(p,a,target,**options)==result and dump(p)==after
    assert read_candidate(p,a,b).status=='review_required'


def test_source_document_type_warning_is_not_hidden_by_normalised_type(tmp_path):
    raw=metadata('wos');raw['record']['sourceTypes']=['Meeting Abstract']
    p,a,b=setup(tmp_path,right=raw)
    assert 'abstract_or_container_scope_requires_review' in read_candidate(p,a,b).warnings


def test_different_abstracts_with_shared_supplement_remain_distinct(tmp_path):
    left=metadata('pubmed',title='Synthetic abstract A');left['record']['publication_types']=['Meeting Abstract']
    right=metadata('wos',title='Synthetic abstract B');right['record']['types']=['Meeting Abstract']
    right['record']['source']['supplement']='Shared supplement';right['record']['identifiers']['pmid']='200'
    p,a,b=setup(tmp_path,left,right);before=dump(p)
    result=find_candidates(p,(a,b))
    assert len(result)==1 and 'title_different' in result[0].warnings
    assert len(set(result[0].publication_ids))==2 and dump(p)==before
    assert decide(p,a,b,**args(result[0])).status=='rejected_match'
