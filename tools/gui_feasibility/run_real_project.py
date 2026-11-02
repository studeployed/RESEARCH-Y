"""Exercise the real project GUI on disposable projects with no live sources.

This is a separately reported feasibility experiment, not a product installer.
Browser transports receive only host-defined actions, never filesystem paths.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import UUID
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from tools.gui_feasibility.run_prototype import (environment, free_port, request, require,
                                                  wait_until, stop_owned_process, ExperimentFailure)
from research_y.projects import create_project, open_project
from research_y.application_inspection import read_application_snapshot, observe_export_request
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query

APP = ROOT / 'tools' / 'gui_feasibility' / 'real_project_app.py'


def fixture(parent):
    p = create_project(parent, '<img src=x onerror="window.__researchy_injected=true">')
    version = approve_strategy(p, theme='Synthetic biomedical terminology',
        approved_by='Fixture', approval_confirmed=True,
        groups=(StrategyGroup('group', '<b>Untrusted group label</b>',
             (ApprovedTerm('ECMO','researcher',True),)),))
    run = create_search_run(p, version.strategy_version_id)
    plan_source_query(p, run_id=run.run_id, group_id='group', source_name='pubmed',
                      exact_query='"ECMO"[All Fields]')
    snapshot = read_application_snapshot(p, selected_run_id=run.run_id).as_dict()
    require(snapshot['report']['status'] == 'incomplete' and
            snapshot['report']['queries'][0]['reported_matches'] is None and
            snapshot['report']['counts']['totals']['global_unique_publications'] is None,
            'fixture_not_incomplete')
    return p, run.run_id


# A prepare action can perform three independently supervised commands, each
# with a 35-second bound. The normal 3-second probing timeout is appropriate
# for health checks, but not for a complete approved export operation.
ACTION_RESPONSE_TIMEOUT = 115

# Native publication drives 11 sequential, 35-second-bounded worker calls,
# plus bootstrap, button readiness, and shutdown. Cap the complete scenario
# above that envelope; keep the shorter transport shutdown bound unchanged.
NATIVE_SCENARIO_TIMEOUT = 540


def request_action(port, headers):
    """Only this fixed localhost action may wait for a bounded full worker call."""
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=ACTION_RESPONSE_TIMEOUT)
    try:
        conn.request('POST', '/_probe/start', headers=headers)
        response = conn.getresponse()
        payload = response.read(1024 * 1024 + 1)
        require(len(payload) <= 1024 * 1024, 'action_response_too_large')
        return response.status, dict(response.getheaders()), payload
    finally:
        conn.close()


def transport_steps(port, token, scenario, run_id, export_id):
    origin = f'http://127.0.0.1:{port}'
    wait_until(lambda: reachable(port), timeout=40)
    require(request(port, '/')[0] == 403, 'unowned_page_access')
    require(request(port, '/_probe/start', method='POST', body=b'{"path":"C:/private"}',
                    headers={'Origin': origin})[0] == 403, 'browser_path_allowed')
    status, headers, _ = request(port, '/session', method='POST', headers={
        'Origin': origin, 'X-ResearchY-Bootstrap': token})
    require(status == 204, 'owner_session_failed')
    cookie = next(value for key, value in headers.items()
                  if key.lower() == 'set-cookie').split(';', 1)[0]
    auth = {'Origin': origin, 'Cookie': cookie}
    require(request(port, '/', headers=auth)[0] == 200, 'nicegui_page_missing')
    expected = (('open', 'select_run', 'prepare', 'prepare', 'resume', 'observe')
                if scenario == 'publish' else
                ('open', 'select_run', 'prepare', 'cancel', 'observe')
                if scenario == 'cancel' else
                ('open', 'select_run', 'select_export', 'observe'))
    observed = []
    for action in expected:
        status, _, payload = request_action(port, auth)
        require(status == 200, 'action_http_failed')
        state = json.loads(payload)
        code = state.get('error')
        require(code is None, 'actual_action_failed_' + action + '_' +
                (code if isinstance(code, str) and code.replace('_', '').isalnum()
                 and len(code) <= 64 else 'unknown'))
        require(state['actions'] and state['actions'][-1] == action, 'action_sequence_changed_' + action)
        observed.append(action)
        result = state['state']
        require(result['source_retrieval_verified'] is False, 'false_source_completeness')
        if action == 'open':
            require(result['selected_run_id'] is None, 'implicit_run_selected')
        if action == 'select_run':
            require(result['selected_run_id'] == run_id, 'wrong_run_selected')
            require(result['report']['queries'][0]['reported_matches'] is None, 'unknown_changed')
        if action == 'prepare':
            require(result['selected_export_id'] is not None, 'no_durable_request_id')
        if action == 'cancel':
            require(result['exports'][0]['recorded_state'] == 'cancelled'
                    and result['observation'] is None, 'cancellation_not_durable')
        if action == 'observe':
            cancelled = scenario in ('cancel', 'cancel_reopen')
            require(result['observation']['outcome'] ==
                    ('recorded_cancelled' if cancelled else 'published_verified')
                    and result['observation']['audited_success'] is (not cancelled),
                    'output_not_verified')
    require(request(port, '/_probe/stop', method='POST', headers=auth)[0] == 200,
            'stop_request_failed')
    return observed


def reachable(port):
    try:
        return request(port, '/bootstrap')[0] == 200
    except OSError:
        return False


def run_app(mode, scenario, project, parent, run_id, expected_export):
    import secrets
    token, port = secrets.token_hex(32), free_port()
    result = {'mode': mode, 'scenario': scenario, 'passed': False}
    with tempfile.TemporaryDirectory(prefix='researchy-real-gui-child-') as directory:
        root = Path(directory)
        app_dir = root / 'app'
        env = environment(root, port, token, mode == 'native')
        env.update(RESEARCHY_GUI_SELECTED_ROOT=str(project.root),
                   RESEARCHY_GUI_SELECTED_PARENT=str(parent),
                   RESEARCHY_GUI_EXPECTED_RUN_ID=run_id,
                   RESEARCHY_GUI_EXPECTED_EXPORT_ID=expected_export or '')
        with (root / 'private-process.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, str(APP), '--mode', mode,
                 '--scenario', scenario, '--port', str(port), '--directory', str(app_dir)],
                 cwd=root, env=env, stdout=log, stderr=log, start_new_session=os.name != 'nt')
            try:
                if mode == 'transport':
                    result['actions'] = transport_steps(port, token, scenario, run_id, expected_export)
                process.wait(timeout=NATIVE_SCENARIO_TIMEOUT if mode == 'native' else 120)
                require(process.returncode == 0, 'real_gui_child_failed')
                report_path = app_dir / 'app-result.json'
                require(report_path.is_file(), 'missing_real_gui_report')
                report = json.loads(report_path.read_text(encoding='utf-8'))
                # Keep only static status and action names in failure evidence. Never
                # publish child paths, project/source labels, secrets or raw reports.
                result['observed_status'] = report.get('status')
                result['observed_actions'] = [x for x in report.get('actions', [])
                    if x in ('open', 'select_run', 'select_export', 'prepare', 'resume', 'cancel', 'observe')]
                code = report.get('error')
                result['observed_error'] = (code if isinstance(code, str) and
                     code.replace('_', '').isalnum() and len(code) <= 64 else None)
                result['observed_worker_reaped'] = report.get('worker_reaped')
                result['observed_supervisor_stopped'] = report.get('supervisor_stopped')
                result['observed_outcome'] = report.get('observed_outcome')
                cancelled = scenario in ('cancel', 'cancel_reopen')
                require(report['status'] == 'finished' and report['real_services'] is True
                        and report['source_retrieval_verified'] is False
                        and report['selected_run_matches'] is True
                        and report['selected_export_matches'] is True
                        and report['observed_outcome'] ==
                            ('recorded_cancelled' if cancelled else 'published_verified')
                        and report['observation_audited'] is (not cancelled)
                        and report['session_revoked'] is True
                        and report['worker_reaped'] is True
                        and report['supervisor_stopped'] is True, 'real_gui_evidence_not_accepted')
                require(report['project_id'] == str(project.identifier), 'project_identity_changed')
                if expected_export:
                    require(report['export_id'] == expected_export, 'export_identity_changed')
                if mode == 'native':
                    require(report.get('native_rendering_verified') is True, 'native_rendering_not_verified')
                result.update(passed=True, export_id=report['export_id'],
                              project_identity_retained=True,
                              workbook_file_verified=not cancelled, native_rendering_verified=bool(
                                  report.get('native_rendering_verified', False)))
                with socket.socket() as sock:
                    require(sock.connect_ex(('127.0.0.1', port)) != 0, 'listener_not_closed')
            except Exception as exc:
                result['error'] = str(exc) if isinstance(exc, ExperimentFailure) else type(exc).__name__
            finally:
                stop_owned_process(process)
    require(token not in json.dumps(result), 'secret_in_evidence')
    return result


def run_scenario(mode):
    with tempfile.TemporaryDirectory(prefix='researchy-real-gui-project-') as root_text:
        root = Path(root_text)
        project, run_id = fixture(root)
        first = run_app(mode, 'publish', project, root, run_id, '')
        if not first['passed']:
            return [first]
        workbook = project.root / 'exports' / ('strategy-summary-' + run_id + '.xlsx')
        require(workbook.is_file(), 'real_workbook_missing')
        with ZipFile(workbook) as wb:
            require(wb.testzip() is None and 'xl/workbook.xml' in wb.namelist(), 'not_a_real_workbook')
        first['workbook_sha256_verified'] = sha256(workbook.read_bytes()).hexdigest() == (
            observe_export_request(project, first['export_id']).request.artifact_sha256)
        require(first['workbook_sha256_verified'], 'workbook_checksum_disagreement')
        with closing(sqlite3.connect(project.database_path)) as db:
            first_events = db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type LIKE 'workbook_export_v1:%'").fetchone()[0]
        moved = root / 'relocated'
        shutil.move(str(project.root), str(moved))
        reopened = open_project(moved)
        require(reopened.identifier == project.identifier, 'relocation_changed_identity')
        second = run_app(mode, 'reopen', reopened, root, run_id, first['export_id'])
        with closing(sqlite3.connect(reopened.database_path)) as db:
            second_events = db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type LIKE 'workbook_export_v1:%'").fetchone()[0]
        second['journal_unchanged_on_reopen'] = first_events == second_events
        require(second['journal_unchanged_on_reopen'], 'reopen_appended_export_receipt')

        # Independent, real disk-backed cancellation. The initial preparation
        # receipt and cancellation must survive a second app process; no Excel
        # artifact may be written, and observation must never claim verification.
        cancel_parent = root / 'cancel-case'
        cancel_parent.mkdir()
        cancel_project, cancel_run_id = fixture(cancel_parent)
        cancelled = run_app(mode, 'cancel', cancel_project, cancel_parent, cancel_run_id, '')
        if not cancelled['passed']:
            return [first, second, cancelled]
        cancel_workbook = (cancel_project.root / 'exports' /
                           ('strategy-summary-' + cancel_run_id + '.xlsx'))
        require(not cancel_workbook.exists(), 'cancelled_export_wrote_workbook')
        with closing(sqlite3.connect(cancel_project.database_path)) as db:
            original_events = db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type LIKE 'workbook_export_v1:%'"
            ).fetchone()[0]
        require(original_events == 2, 'cancelled_journal_not_precise')
        cancelled_reopen = run_app(mode, 'cancel_reopen', cancel_project,
                                    cancel_parent, cancel_run_id, cancelled['export_id'])
        with closing(sqlite3.connect(cancel_project.database_path)) as db:
            later_events = db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type LIKE 'workbook_export_v1:%'"
            ).fetchone()[0]
        cancelled_reopen['journal_unchanged_on_reopen'] = original_events == later_events
        require(cancelled_reopen['journal_unchanged_on_reopen'], 'cancel_reopen_appended_receipt')
        require(not cancel_workbook.exists(), 'cancel_reopen_wrote_workbook')
        return [first, second, cancelled, cancelled_reopen]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--native', action='store_true')
    args = parser.parse_args(argv)
    require(not args.native or sys.platform == 'win32', 'native_windows_required')
    modes = ['transport'] + (['native'] if args.native else [])
    results = [result for mode in modes for result in run_scenario(mode)]
    evidence = {'format': 'research-y-real-gui-feasibility-v1',
                'results': results, 'passed': bool(results) and all(r['passed'] for r in results),
                'real_project_services': True, 'synthetic_source_fixture': True,
                'source_retrieval_verified': False, 'gui_acceptance': False,
                'production_adoption_approved': False,
                'limitations': ['Host-selected fixture path, not a live native folder-selection dialog.',
                                'No literature retrieval; source counts and global publications remain unverified.',
                                'This proves a strategy workbook slice, not the full master-results export.',
                                'No packaged Windows installer or large-dataset performance acceptance.']}
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / 'real-project-evidence.json').write_text(
        json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(f"Real-project GUI experiment: {sum(r['passed'] for r in results)}/{len(results)} cases passed.")
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
