"""Offline driver tests; no licensed data, private keys or external access."""
from importlib.util import module_from_spec,spec_from_file_location
import json
from pathlib import Path
import pytest
from research_y.wos_starter_client import WoSStarterClient
from test_wos_checkpoints import Clock,Provider,KEY

ROOT=Path(__file__).resolve().parents[1]
spec=spec_from_file_location('_wos_checkpoint_driver',ROOT/'scripts/wos_checkpoint_validation.py')
driver=module_from_spec(spec);spec.loader.exec_module(driver)


def client(clock,provider):
    return WoSStarterClient(api_key=KEY,transport=provider,request_budget=1300,
                            clock=clock.monotonic,sleep=clock.sleep,utc_now=clock.now)


def test_manual_driver_pause_reopen_reconciliation_and_public_artifact(tmp_path):
    clock=Clock();source=Provider(clock)
    workspace=tmp_path/'validation'
    first=driver.start(workspace,client(clock,source),now=clock.now)
    assert first['stage_passed'] and first['pages_committed']==1
    clock.sleep(2)
    second=driver.resume(workspace,client(clock,source),now=clock.now,sleep=clock.sleep)
    assert second['stage_passed'] and second['durable_recovery_tested']
    assert second['enumeration_reconciled'] and second['first_page_unchanged']
    assert second['records_committed']==second['reported_matches']==103
    assert second['request_purposes']=={'acquire':3,'probe':1,'verify':3,'final':1}
    assert not second['source_retrieval_verified'] and not second['multi_day_live_tested']
    encoded=(workspace/driver.EVIDENCE).read_text()
    assert all(secret not in encoded for secret in (KEY,'Synthetic title','unexpectedField','WOS:000000000000001'))
    assert json.loads(encoded)['acquisition_first_page_requests']==1


@pytest.mark.parametrize('total',[0,50,30001],ids=['zero','one-page','over-budget'])
def test_driver_bounds_stop_after_one_page(tmp_path,total):
    clock=Clock();source=Provider(clock,total)
    result=driver.start(tmp_path/'bounded',client(clock,source),now=clock.now)
    assert not result['stage_passed'] and len(source.calls)==1
    assert not (tmp_path/'bounded'/driver.STATE).exists()


def test_no_authorisation_or_key_never_starts(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv('RESEARCHY_WOS_RETENTION_AUTHORIZED',raising=False)
    monkeypatch.delenv('RESEARCHY_WOS_STARTER_API_KEY',raising=False)
    args=['start','--workspace',str(tmp_path/'not-created')]
    assert driver.main(args)==2
    monkeypatch.setenv('RESEARCHY_WOS_RETENTION_AUTHORIZED','true')
    assert driver.main(args)==2 and not (tmp_path/'not-created').exists()
    assert capsys.readouterr().out==''


def test_workflow_is_manual_consent_bounded_and_never_uploads_database():
    text=(ROOT/'.github/workflows/wos-starter-live-recovery.yml').read_text()
    assert 'on:\n  workflow_dispatch:\n' in text
    assert all(s not in text for s in ('\n  push:','\n  pull_request:','\n  schedule:'))
    assert 'default: false' in text and 'if: ${{ inputs.confirm_local_retention }}' in text
    assert 'research-y-wos-starter-live' in text
    assert text.count('RESEARCHY_WOS_STARTER_API_KEY:')==2
    assert text.count('python scripts/wos_checkpoint_validation.py ')==2
    assert 'wos-checkpoint-evidence.json' in text
    assert all(s not in text for s in ('researchy.sqlite3','data/raw','**/*','--verbose'))
    assert driver.MAX_RESUME_REQUESTS==1300 and driver.MAX_MATCHES==30000
