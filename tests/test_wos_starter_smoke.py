"""All smoke tests use local synthetic data, never a real Starter key/service."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import pytest
from research_y.wos_starter_client import WoSStarterClient,WoSHTTPResponse

ROOT=Path(__file__).resolve().parents[1]
spec=spec_from_file_location('_research_y_wos_smoke',ROOT/'scripts/wos_source_smoke.py')
smoke=module_from_spec(spec);spec.loader.exec_module(smoke)
KEY='SYNTHETIC-LICENSED-KEY'
HEADERS={'X-RateLimit-Limit-Day':'5000','X-RateLimit-Remaining-Day':'4997'}


def source(*,total=123,headers=HEADERS,duplicate=False,drift=False):
    calls=[]
    def respond(req,timeout):
        form=parse_qs(urlsplit(req.full_url).query)
        page,limit=int(form['page'][0]),int(form['limit'][0])
        calls.append((page,limit))
        count=total+int(drift and page==2)
        hits=[{'uid':f'WOS:{i+1:015d}','title':'LICENSED-SAMPLE-TITLE',
               'unrecognisedField':'RETAIN-LOCALLY-NOT-PUBLISH'}
              for i in range((page-1)*limit,min(page*limit,count))]
        if duplicate and page==2: hits[0]['uid']='WOS:000000000000001'
        return WoSHTTPResponse(200,headers,json.dumps({'metadata':{'total':count,'page':page,'limit':limit},'hits':hits}).encode())
    client=WoSStarterClient(api_key=KEY,transport=respond,sleep=lambda _:None,clock=lambda:100.0)
    return client,calls


def test_pilot_then_two_pages_with_licensed_content_excluded():
    c,calls=source();result=smoke.run_smoke(c)
    assert calls==[(1,1),(1,50),(2,50)]
    assert result['status']=='entitlement_and_two_page_sample_verified'
    assert result['reported_matches']==123
    assert result['validated_sample_records']==100
    assert result['access_probe_records_received']==1
    assert result['requests_made']==3
    assert result['accepted_translation'] is None
    assert not result['source_retrieval_verified']
    assert not result['durable_recovery_tested']
    encoded=json.dumps(result)
    for text in (KEY,'LICENSED-SAMPLE-TITLE','RETAIN-LOCALLY','WOS:000000000000001'):
        assert text not in encoded


@pytest.mark.parametrize('headers', [{},{'X-RateLimit-Limit-Day':'50'},
                                     {**HEADERS,'X-RateLimit-Remaining-Day':'0'}])
def test_missing_trial_or_exhausted_quota_does_not_bulk_fetch(headers):
    c,calls=source(headers=headers);result=smoke.run_smoke(c)
    assert result['status']=='incomplete' and len(calls)==1
    assert result['reported_matches']==123
    assert result['validated_sample_records']==0


@pytest.mark.parametrize(('kwargs','code'), [({'drift':True},'source_count_changed'),
                                           ({'duplicate':True},'cross_page_duplicate')])
def test_drift_or_repeated_page_not_accepted(kwargs,code):
    c,_=source(**kwargs);result=smoke.run_smoke(c)
    assert result['status']=='incomplete' and result['reason_code']==code
    assert result['validated_sample_records']==50


@pytest.mark.parametrize('total',[0,1,50])
def test_tiny_query_does_not_prove_two_page_acceptance(total):
    c,calls=source(total=total);result=smoke.run_smoke(c)
    assert result['reason_code']=='too_few_matches_for_two_page_smoke'
    assert len(calls)==1


def test_manual_workflow_secrets_scoped_and_no_private_payload_upload():
    text=(ROOT/'.github/workflows/wos-starter-live-smoke.yml').read_text()
    assert 'on:\n  workflow_dispatch:\n' in text
    assert all(x not in text for x in ('\n  push:','\n  pull_request:','\n  schedule:'))
    assert 'permissions:\n  contents: read' in text
    assert 'secrets.RESEARCHY_WOS_STARTER_API_KEY' in text
    assert text.count('RESEARCHY_WOS_STARTER_API_KEY:')==1
    assert 'if: always()' in text
    assert 'wos-starter-evidence.json' in text


def test_missing_key_no_network_or_false_evidence(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv('RESEARCHY_WOS_STARTER_API_KEY',raising=False)
    target=tmp_path/'nothing.json'
    assert smoke.main(['--output',str(target)])==2 and not target.exists()
    assert 'private' in capsys.readouterr().err


def test_fixed_smoke_query_matches_production_compiler():
    from research_y.query_compiler import _source_expression
    assert smoke.QUERY == _source_expression('wos',('ECMO',))


def test_final_page_missing_quota_cannot_keep_pilot_entitlement_pass():
    c,_=source()
    original=c._transport
    def changed(req,timeout):
        response=original(req,timeout)
        if 'page=2' in req.full_url:
            return WoSHTTPResponse(200,{},response.body)
        return response
    c._transport=changed
    result=smoke.run_smoke(c)
    assert result['status']=='incomplete'
    assert result['reason_code']=='quota_or_entitlement_changed'
    assert result['validated_sample_records']==50
