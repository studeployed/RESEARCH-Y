"""Regression coverage for commit-specific review findings in P1-05b."""
from contextlib import closing
from datetime import datetime, timedelta
import json
import sqlite3
import pytest
from research_y.wos_starter_client import WoSHTTPResponse
from test_wos_checkpoints import KEY, setup, execute


@pytest.mark.parametrize('failed_purpose', ['verify', 'final'], ids=['later-verification-page', 'final-probe'])
def test_replayed_verification_prefix_cannot_reset_durable_failure_budget(tmp_path, failed_purpose):
    p,qs,c,s=setup(tmp_path)
    def backend(req,timeout):
        with closing(sqlite3.connect(p.database_path)) as db:
            purpose,page=db.execute(
                "SELECT purpose,page_number FROM wos_checkpoint_attempts WHERE outcome='started'"
            ).fetchone()
        response=s(req,timeout)
        if purpose==failed_purpose and (purpose=='final' or page==2):
            return WoSHTTPResponse(503,{**response.headers,'Retry-After':'120'},b'PRIVATE ERROR')
        return response
    for failure in range(1,4):
        result=execute(p,qs[0],c,backend)
        assert result.failures==failure
        assert result.records_committed==103
        assert result.verification_pages==(1 if failed_purpose=='verify' else 3)
        c.sleep(121)
    assert result.status=='incomplete' and result.reason_code=='retry_budget_exhausted'
    before=len(s.calls)
    execute(p,qs[0],c,backend,revalidate_quota=True)
    assert len(s.calls)==before


def test_verification_progress_beyond_prior_epoch_resets_failure_budget(tmp_path):
    p,qs,c,s=setup(tmp_path)
    failing_page=2
    def backend(req,timeout):
        with closing(sqlite3.connect(p.database_path)) as db:
            purpose,page=db.execute(
                "SELECT purpose,page_number FROM wos_checkpoint_attempts WHERE outcome='started'"
            ).fetchone()
        response=s(req,timeout)
        if purpose=='verify' and page==failing_page:
            return WoSHTTPResponse(503,{**response.headers,'Retry-After':'120'},b'PRIVATE ERROR')
        return response
    assert execute(p,qs[0],c,backend).failures==1
    c.sleep(121)
    assert execute(p,qs[0],c,backend).failures==2
    c.sleep(121)
    failing_page=3
    result=execute(p,qs[0],c,backend)
    assert result.failures==1 and result.verification_pages==2
    c.sleep(121)
    failing_page=None
    assert execute(p,qs[0],c,backend).enumeration_reconciled


@pytest.mark.parametrize('echo_key',[False,True],ids=['invalid-json','credential-echo'])
def test_validation_failure_retains_server_retry_after_across_new_clients(tmp_path,echo_key):
    p,qs,c,s=setup(tmp_path)
    def malformed(req,timeout):
        response=s(req,timeout)
        body=json.loads(response.body)
        body['hits'][0]['unexpectedField']={'secret':KEY}
        return WoSHTTPResponse(200,{**response.headers,'Retry-After':'300'},
                               json.dumps(body).encode() if echo_key else b'{')
    result=execute(p,qs[0],c,malformed)
    assert result.status=='incomplete' and result.records_committed==0
    assert datetime.fromisoformat(result.not_before_utc)>=c.now()+timedelta(seconds=300)
    before=len(s.calls)
    c.sleep(31)
    execute(p,qs[0],c,s,revalidate_quota=True)
    assert len(s.calls)==before
    c.sleep(270)
    assert execute(p,qs[0],c,s,revalidate_quota=True).enumeration_reconciled
    assert KEY.encode() not in p.database_path.read_bytes()
