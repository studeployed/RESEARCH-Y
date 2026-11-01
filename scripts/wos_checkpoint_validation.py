"""Manual fixed-query Starter acquisition/restart/identity-reconciliation gate.

Licensed records stay in the ephemeral local project, never in the artifact.
This is not an abstract-enrichment, multi-day-live or atomic-snapshot test.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import UUID

from research_y.projects import create_project, open_project, _validated_project_connection
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query
from research_y.wos_checkpoint_store import create_wos_checkpoint, inspect_wos_checkpoint, validate_wos_checkpoint
from research_y.wos_checkpoint_runner import run_wos_checkpoint
from research_y.wos_starter_client import WoSStarterClient

QUERY = 'TS=("ECMO")'
PROJECT = 'starter-validation'
EVIDENCE = 'wos-checkpoint-evidence.json'
STATE = 'wos-validation-state.json'
MAX_MATCHES = 30000
MAX_RESUME_REQUESTS = 1300


def _save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def _first_page(project, query_id):
    with _validated_project_connection(project) as db:
        row = db.execute('SELECT p.attempt_id,o.response_sha256 FROM wos_checkpoint_pages p '
                         'JOIN wos_checkpoint_observations o ON o.attempt_id=p.attempt_id '
                         'WHERE p.query_id=? AND p.page_number=1', (query_id,)).fetchone()
    return None if row is None else {'attempt_id':row[0], 'response_sha256':row[1]}


def evidence(project, query_id, stage):
    validate_wos_checkpoint(project, query_id)
    state = inspect_wos_checkpoint(project, query_id)
    result = asdict(state)
    result.update(source='Web of Science Starter', query=QUERY, database='WOS', stage_executed=stage,
                  licensed_record_content_exported=False, multi_day_live_tested=False,
                  checked_at_utc=datetime.now(timezone.utc).isoformat())
    result['commit_sha'] = os.environ.get('GITHUB_SHA') if re.fullmatch(r'[a-f0-9]{40}',os.environ.get('GITHUB_SHA','')) else None
    result['github_run_id'] = os.environ.get('GITHUB_RUN_ID') if re.fullmatch(r'\d{1,20}',os.environ.get('GITHUB_RUN_ID','')) else None
    with _validated_project_connection(project) as db:
        pages = db.execute('SELECT p.page_number,p.uid_sha256,o.response_sha256 FROM wos_checkpoint_pages p '
                           'JOIN wos_checkpoint_observations o ON o.attempt_id=p.attempt_id '
                           'WHERE p.query_id=? ORDER BY p.page_number', (query_id,)).fetchall()
        result['page_hashes'] = [{'page':p,'accessions_sha256':u,'response_sha256':r} for p,u,r in pages]
        digest = sha256()
        for (uid,) in db.execute('SELECT uid FROM wos_checkpoint_ids WHERE query_id=? ORDER BY uid', (query_id,)):
            digest.update((uid+'\n').encode('utf-8'))
        result['accession_union_sha256'] = digest.hexdigest()
        result['acquisition_first_page_requests'] = db.execute(
            "SELECT COUNT(*) FROM wos_checkpoint_attempts WHERE query_id=? AND purpose='acquire' AND page_number=1",
            (query_id,)).fetchone()[0]
        result['request_purposes'] = dict(db.execute(
            'SELECT purpose,COUNT(*) FROM wos_checkpoint_attempts WHERE query_id=? GROUP BY purpose', (query_id,)))
    return result


def start(workspace: Path, client: WoSStarterClient, *, now=lambda:datetime.now(timezone.utc)):
    workspace.mkdir(parents=True, mode=0o700, exist_ok=False)
    project = create_project(workspace, 'Controlled Starter validation', directory_name=PROJECT)
    version = approve_strategy(project, theme='Fixed public ECMO diagnostic',
        groups=(StrategyGroup('g1','ECMO',(ApprovedTerm('ECMO','researcher',True),)),),
        approved_by='Explicit manual workflow dispatch and local-retention confirmation', approval_confirmed=True)
    run = create_search_run(project, version.strategy_version_id)
    query = plan_source_query(project, run_id=run.run_id, group_id='g1', source_name='wos', exact_query=QUERY)
    create_wos_checkpoint(project, query.query_id, retention_authorized=True)
    run_wos_checkpoint(project, query.query_id, client, max_requests=1, now=now)
    result = evidence(project, query.query_id, 'start')
    good = (result['status']=='paused' and result['pages_committed']==1
            and result['reported_matches'] is not None and 50<result['reported_matches']<=MAX_MATCHES)
    result['stage_passed'] = good
    result['durable_recovery_tested'] = False
    if good:
        _save(workspace/STATE, {'query_id':query.query_id, 'project_id':str(project.identifier),
                               'first_page':_first_page(project, query.query_id)})
    _save(workspace/EVIDENCE, result)
    return result


def resume(workspace: Path, client: WoSStarterClient, *, now=lambda:datetime.now(timezone.utc), sleep=time.sleep):
    saved = json.loads((workspace/STATE).read_text(encoding='utf-8'))
    query_id = str(UUID(saved['query_id']))
    project = open_project(workspace/PROJECT)
    if str(project.identifier)!=saved['project_id'] or _first_page(project, query_id)!=saved['first_page']:
        raise ValueError('Diagnostic checkpoint identity changed')
    previous = inspect_wos_checkpoint(project, query_id)
    if previous.not_before_utc:
        delay = (datetime.fromisoformat(previous.not_before_utc)-now()).total_seconds()
        if 0<delay<=2:
            sleep(delay)  # Only the short pacing guard; never loop across a quota reset.
    run_wos_checkpoint(project, query_id, client, max_requests=MAX_RESUME_REQUESTS, now=now)
    result = evidence(project, query_id, 'resume')
    result['first_page_unchanged'] = _first_page(project, query_id)==saved['first_page']
    result['stage_passed'] = (result['enumeration_reconciled'] and result['first_page_unchanged']
                              and result['acquisition_first_page_requests']==1)
    result['durable_recovery_tested'] = result['stage_passed']
    _save(workspace/EVIDENCE, result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('start','resume'))
    parser.add_argument('--workspace',type=Path,required=True)
    args=parser.parse_args(argv)
    if os.environ.get('RESEARCHY_WOS_RETENTION_AUTHORIZED')!='true':
        print('Not run: confirm permitted local licensed-data retention.',file=sys.stderr)
        return 2
    key=os.environ.get('RESEARCHY_WOS_STARTER_API_KEY')
    if not key:
        print('Not run: configure the private Starter key.',file=sys.stderr)
        return 2
    try:
        client=WoSStarterClient(api_key=key,request_budget=1 if args.stage=='start' else MAX_RESUME_REQUESTS)
        result=(start if args.stage=='start' else resume)(args.workspace,client)
        print(json.dumps({k:result[k] for k in ('stage_executed','status','reason_code','reported_matches',
              'records_committed','pages_committed','verification_pages','requests_confirmed_attempted',
              'enumeration_reconciled','stage_passed','source_retrieval_verified','durable_recovery_tested')},sort_keys=True))
        return 0 if result['stage_passed'] else 3
    except Exception:
        print('Starter recovery validation incomplete; no source acceptance claimed.',file=sys.stderr)
        # Do not emit exception strings, licensed content, query bodies or secrets.
        return 3


if __name__=='__main__':
    raise SystemExit(main())
