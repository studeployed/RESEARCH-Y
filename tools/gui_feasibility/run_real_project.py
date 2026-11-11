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
import signal
import threading
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import UUID, uuid4
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from tools.gui_feasibility.run_prototype import (environment, free_port, request, require,
                                                  wait_until, stop_owned_process, windows_process_table,
                                                  ExperimentFailure)
from research_y.projects import create_project, open_project
from research_y.application_inspection import read_application_snapshot, observe_export_request
from research_y import workbook_exports
from research_y.storage import ApprovedTerm, StrategyGroup, approve_strategy, create_search_run, plan_source_query

APP = ROOT / 'tools' / 'gui_feasibility' / 'real_project_app.py'


def _worker_parent_is_gui(child_pid, gui_pid):
    """Require direct, actual parentage before terminating an owned child."""
    if child_pid <= 0 or gui_pid <= 0 or child_pid == gui_pid:
        return False
    if os.name == 'nt':
        return windows_process_table().get(child_pid) == gui_pid
    # The feasibility Linux matrix uses procfs; fail closed elsewhere.
    if sys.platform.startswith('linux'):
        stat_text = (Path('/proc') / str(child_pid) / 'stat').read_text(
            encoding='ascii')
        return int(stat_text.rsplit(')', 1)[1].split()[1]) == gui_pid
    return False


def _gui_owner_matches_launcher(actual_gui_pid, launched_pid):
    """Verify the GUI owner PID against the process initially launched by us.

    On Windows a virtual-environment python.exe is a redirector: Popen may
    return its PID, while the actual GUI Python interpreter is its direct
    child. This does NOT relax worker parentage; that separate check must
    prove the worker is a direct child of the actual GUI interpreter.
    """
    if actual_gui_pid <= 0 or launched_pid <= 0:
        return False
    if actual_gui_pid == launched_pid:
        return True
    return (os.name == 'nt' and
            windows_process_table().get(actual_gui_pid) == launched_pid)


def terminate_marked_gui_worker(host, marker, owner_marker, stopping, result):
    """Terminate only a confirmed direct child of the real GUI host.

    This is a trusted parent-side test harness. It never searches for
    arbitrary user processes or accepts PID/path arguments over HTTP.
    """
    deadline = time.monotonic() + NATIVE_SCENARIO_TIMEOUT
    result['phase'] = 'await_marker'
    try:
        while not stopping.is_set() and time.monotonic() < deadline:
            if marker.is_file():
                result['phase'] = 'marker_detected'
                size = marker.stat().st_size
                if size == 0:
                    result['phase'] = 'marker_incomplete'
                    # O_EXCL creation can precede the worker's PID write.
                    # This is an incomplete marker, not a bad PID: retry
                    # without expanding the original bounded deadline.
                    time.sleep(.05)
                    continue
                if size > 24:
                    result['error'] = 'worker_marker_invalid'
                    return
                text = marker.read_text(encoding='ascii')
                if not text.isdecimal():
                    result['error'] = 'worker_marker_invalid'
                    return
                pid = int(text)
                result['phase'] = 'gui_owner_check'
                # Worker and owner markers are separate, private, exclusive
                # files: the GUI itself writes its actual PID before launching
                # the supervised worker. Browser data cannot spoof either.
                if not owner_marker.is_file() or owner_marker.stat().st_size == 0:
                    time.sleep(.05)
                    continue
                if owner_marker.stat().st_size > 24:
                    result['error'] = 'gui_owner_marker_invalid'
                    return
                owner_text = owner_marker.read_text(encoding='ascii')
                if not owner_text.isdecimal() or int(owner_text) <= 0:
                    result['error'] = 'gui_owner_marker_invalid'
                    return
                gui_pid = int(owner_text)
                if host.poll() is not None:
                    result['error'] = 'gui_exited_before_worker_stage'
                    return
                if not _gui_owner_matches_launcher(gui_pid, host.pid):
                    result['error'] = 'gui_owner_mismatch'
                    return
                result['gui_owner_relation'] = (
                    'direct' if gui_pid == host.pid else 'verified_launcher_child')
                result['phase'] = 'parentage_check'
                if not _worker_parent_is_gui(pid, gui_pid):
                    result['error'] = 'worker_parent_mismatch'
                    return
                result['phase'] = 'signal_delivery'
                os.kill(pid, signal.SIGTERM)
                result['terminated'] = True
                result['phase'] = 'signal_sent'
                return
            if host.poll() is not None:
                result['error'] = 'gui_exited_before_worker_stage'
                return
            time.sleep(.05)
        if not stopping.is_set():
            result['error'] = 'worker_stage_marker_timeout'
    except Exception:
        result['error'] = 'worker_termination_failed'


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


# A subprocess exits after the final hard link becomes visible and after the
# uncommitted 'published' audit INSERT. Process exit rolls that transaction
# back, retaining only the earlier, durable 'publishing' receipt.
_CRASH_BEFORE_FINAL_RECEIPT = """
import os, sys
from research_y import workbook_exports as exports
from research_y.projects import open_project

project = open_project(sys.argv[1])
export_id = sys.argv[2]
append_original = exports._append

def crash_after_publication(db, candidate, previous, action, data):
    append_original(db, candidate, previous, action, data)
    if action == 'published' and candidate == export_id:
        os._exit(73)

exports._append = crash_after_publication
exports.resume_workbook_export(project, export_id)
raise SystemExit(72)
"""


def seed_unreceipted_workbook(project, run_id):
    """Real process death between a visible workbook and its final journal commit.

    The crash is confined to a disposable, subprocess-owned fixture; no
    production services are patched in the surviving GUI process.
    """
    export_id = str(uuid4())
    filename = 'strategy-summary-' + run_id + '.xlsx'
    workbook_exports.prepare_workbook_export(project, run_id, filename, export_id=export_id)
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
               'HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'PROGRAMDATA', 'SYSTEMDRIVE', 'LANG'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(ROOT / 'src')])
    attempt = subprocess.run(
        [sys.executable, '-c', _CRASH_BEFORE_FINAL_RECEIPT,
         str(project.root), export_id],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=45, check=False)
    require(attempt.returncode == 73, 'final_receipt_crash_fixture_failed')
    workbook = project.root / 'exports' / filename
    require(workbook.is_file(), 'unreceipted_workbook_not_visible')
    with ZipFile(workbook) as archive:
        require(archive.testzip() is None and 'xl/workbook.xml' in archive.namelist(),
                'unreceipted_workbook_not_valid_xlsx')
    observed = observe_export_request(project, export_id)
    require(observed.outcome == 'published_receipt_missing'
            and observed.request.recorded_state == 'publishing'
            and not observed.audited_success and not observed.source_retrieval_verified,
            'missing_receipt_falsely_verified')
    require(sha256(workbook.read_bytes()).hexdigest() ==
            observed.request.artifact_sha256, 'unreceipted_workbook_digest_mismatch')
    with closing(sqlite3.connect(project.database_path)) as db:
        count = db.execute('SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                           (f'{workbook_exports.EVENT}:{export_id}',)).fetchone()[0]
    require(count == 4, 'unexpected_crash_journal_count')
    return export_id, workbook


# The test harness injects errors ONLY in a disposable subprocess after a
# normally committed preparation. Neither GUI request handlers nor production
# worker code accept a fault selector, model or filesystem path from the browser.
_INJECT_EARLY_EXPORT_FAILURE = r'''
import errno
import sys
from research_y import workbook_exports as exports
from research_y.export_files import Directory
from research_y.projects import open_project

project = open_project(sys.argv[1])
export_id, kind = sys.argv[2:]
if kind == 'render':
    renderer_original = exports._renderer
    def permission_denied_renderer():
        method, _ = renderer_original()
        def denied(_):
            raise PermissionError(errno.EACCES, 'injected renderer access denied')
        return method, denied
    exports._renderer = permission_denied_renderer
elif kind == 'stage':
    write_original = Directory.write_new
    def disk_full_write(self, name, data):
        if name.startswith('retained-') and name.endswith('.xlsx'):
            write_original(self, name, b'PARTIAL-OWNED-STAGE')
            raise OSError(errno.ENOSPC, 'injected stage disk full')
        return write_original(self, name, data)
    Directory.write_new = disk_full_write
else:
    raise SystemExit(90)

try:
    exports.resume_workbook_export(project, export_id)
except exports.WorkbookExportError as exc:
    if exc.code == {'render': 'render_failed', 'stage': 'storage_failed'}[kind]:
        raise SystemExit(0)
raise SystemExit(91)
'''


def seed_failed_export(project, run_id, kind):
    """Create real durable failure evidence using an isolated faulted subprocess.

    Permission/disk-full are deterministic *injected* errors, not claims that
    the runner's host disk was actually exhausted or ACLs actually changed.
    """
    require(kind in ('render', 'stage'), 'unsupported_fault_fixture')
    export_id = str(uuid4())
    output_name = 'strategy-summary-' + run_id + '.xlsx'
    workbook_exports.prepare_workbook_export(project, run_id, output_name, export_id=export_id)
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
               'HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'PROGRAMDATA', 'SYSTEMDRIVE', 'LANG'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(ROOT / 'src')])
    attempt = subprocess.run(
        [sys.executable, '-c', _INJECT_EARLY_EXPORT_FAILURE,
         str(project.root), export_id, kind],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=45, check=False)
    require(attempt.returncode == 0, 'early_export_fault_fixture_not_triggered')
    expected_state = 'staging' if kind == 'stage' else 'prepared'
    expected_error = 'storage_failed' if kind == 'stage' else 'render_failed'
    expected_outcome = ('retained_artifact_changed' if kind == 'stage'
                        else 'not_yet_staged')
    snapshot = read_application_snapshot(project, selected_run_id=run_id).as_dict()
    observation = observe_export_request(project, export_id)
    require(len(snapshot['exports']) == 1
            and snapshot['exports'][0]['export_id'] == export_id
            and snapshot['exports'][0]['recorded_state'] == expected_state
            and snapshot['exports'][0]['last_error'] == expected_error
            and snapshot['report']['status'] == 'incomplete'
            and not snapshot['source_retrieval_verified']
            and observation.outcome == expected_outcome
            and not observation.audited_success,
            'early_export_failure_not_retained')
    partial = None
    if kind == 'stage':
        with workbook_exports._transaction(project, write=False) as db:
            state = workbook_exports._required(db, project, export_id)
        partial = (project.root / 'exports' / workbook_exports.STORE /
                   state['stage']['name'])
        require(partial.is_file() and partial.read_bytes() == b'PARTIAL-OWNED-STAGE',
                'failed_stage_not_preserved')
    require(not (project.root / 'exports' / output_name).exists(),
            'failed_export_has_final_workbook')
    return export_id, partial


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


def transport_window_steps(port, auth, scenario, run_id):
    """Run fixed, authorized real GUI actions; no browser-supplied identifiers."""
    lost = scenario == 'publication_window_lost_reply'
    expected = ('open', 'select_run', 'publication_window_offer',
                'publication_window_confirm', 'publication_window_inspect')
    observed = []
    for index, action in enumerate(expected):
        status, _, payload = request_action(port, auth)
        require(status == 200, 'window_action_http_failed')
        result = json.loads(payload)
        state = result['state']
        error = result.get('error')
        require(state['source_retrieval_verified'] is False,
                'window_falsely_verified_sources')
        if lost and action == 'publication_window_confirm':
            require(error == 'publication_window_reinspect_required',
                    'window_lost_reply_not_refused')
            require(state['publication_window_reinspect_required'] is True and
                    state['publication_window_last_outcome'] is None and
                    state['publication_window_offer'] is None,
                    'window_lost_reply_false_success')
            observed.append('publication_window_confirm_interrupted')
            continue
        require(error is None, 'window_action_failed')
        if action == 'open':
            require(state['selected_run_id'] is None, 'window_implicit_run')
        if action == 'select_run':
            require(state['selected_run_id'] == run_id, 'window_wrong_run')
        if action == 'publication_window_offer':
            offer = state['publication_window_offer']
            require(offer is not None and
                    offer['batch_sizes'] == [64, 64] and
                    offer['proposed_source_records'] == 128 and
                    offer['unmaterialised_retrievals'] == 132 and
                    offer['global_unique_publications'] is None,
                    'window_offer_not_bound_to_originals')
        if action == 'publication_window_confirm':
            receipt = state['publication_window_last_outcome']
            require(receipt is not None and
                    receipt['committed_batches'] == 2 and
                    receipt['materialised_in_session'] == 128 and
                    receipt['global_unique_publications'] is None and
                    state['publication_window_offer'] is None,
                    'window_confirm_not_audited')
        if action == 'publication_window_inspect':
            inspection = state['publication_window_last_inspection']
            require(inspection is not None and
                    inspection['unmaterialised_retrievals'] == 4 and
                    inspection['existing_publication_hypotheses'] == 128 and
                    'revision' not in inspection and
                    state['publication_window_offer'] is None and
                    state['publication_window_reinspect_required'] is False and
                    (state['publication_window_last_outcome'] is None) is lost,
                    'window_reinspection_not_durable')
        observed.append(action)
    require(request(port, '/_probe/stop', method='POST', headers=auth)[0] == 200,
            'window_stop_request_failed')
    return observed


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
    if scenario in ('publication_window', 'publication_window_lost_reply'):
        return transport_window_steps(port, auth, scenario, run_id)
    expected = (('open', 'select_run', 'prepare', 'prepare', 'resume', 'observe')
                if scenario == 'publish' else
                ('recent_open', 'select_run', 'select_export', 'observe')
                if scenario == 'recent_open' else
                ('open', 'select_run', 'prepare', 'cancel', 'observe')
                if scenario == 'cancel' else
                ('open', 'select_run', 'select_export', 'resume', 'observe')
                if scenario in ('receipt_recovered', 'render_recovered',
                                'stage_recovered', 'worker_recovered') else
                ('open', 'select_run', 'select_export', 'resume')
                if scenario == 'worker_killed' else
                ('open', 'select_run', 'select_export', 'observe'))
    observed = []
    for action in expected:
        status, _, payload = request_action(port, auth)
        require(status == 200, 'action_http_failed')
        state = json.loads(payload)
        code = state.get('error')
        if scenario == 'worker_killed' and action == 'resume':
            # A real child died during staging: failure is the required result.
            require(code == 'worker_interrupted',
                    'worker_death_returned_' + code
                    if code in ('worker_timeout', 'worker_interrupted',
                                'worker_unavailable', 'worker_start_failed',
                                'operation_failed', 'worker_protocol_failed',
                                'worker_busy')
                    else 'worker_death_not_reported')
            require(state['actions'] == ['open', 'select_run', 'select_export'],
                    'worker_failure_recorded_as_success')
            damaged = state['state']
            require(damaged['selected_export_id'] == export_id
                    and len(damaged['exports']) == 1
                    and damaged['exports'][0]['recorded_state'] == 'staging'
                    and damaged['observation'] is None
                    and damaged['source_retrieval_verified'] is False,
                    'worker_death_state_incorrect')
            observed.append('resume_interrupted')
            continue
        require(code is None, 'actual_action_failed_' + action + '_' +
                (code if isinstance(code, str) and code.replace('_', '').isalnum()
                 and len(code) <= 64 else 'unknown'))
        require(state['actions'] and state['actions'][-1] == action, 'action_sequence_changed_' + action)
        observed.append(action)
        result = state['state']
        require(result['source_retrieval_verified'] is False, 'false_source_completeness')
        if action in ('open', 'recent_open'):
            require(result['selected_run_id'] is None
                    and result['selected_export_id'] is None,
                    'implicit_run_or_export_selected')
        if action == 'recent_open':
            require(len(result['recent_projects']) == 1 and
                    result['recent_projects'][0]['project_id'] ==
                        result['project']['project_id'] and
                    result['recent_history_error'] is None,
                    'recent_identity_not_revalidated')
        if action == 'select_run':
            require(result['selected_run_id'] == run_id, 'wrong_run_selected')
            require(result['report']['queries'][0]['reported_matches'] is None, 'unknown_changed')
        if action == 'prepare':
            require(result['selected_export_id'] is not None, 'no_durable_request_id')
        if action == 'cancel':
            require(result['exports'][0]['recorded_state'] == 'cancelled'
                    and result['observation'] is None, 'cancellation_not_durable')
        if action == 'observe':
            expected_outcome = ('recorded_cancelled' if scenario in ('cancel', 'cancel_reopen')
                                else 'published_receipt_missing' if scenario == 'receipt_missing'
                                else 'not_yet_staged' if scenario == 'render_fault'
                                else 'retained_artifact_changed' if scenario == 'stage_fault'
                                else 'published_verified')
            require(result['observation']['outcome'] == expected_outcome
                    and result['observation']['audited_success'] is
                        (expected_outcome == 'published_verified'),
                    'output_status_incorrect')
            if scenario == 'receipt_missing':
                require(result['exports'][0]['recorded_state'] == 'publishing'
                        and result['selected_export_id'] == export_id,
                        'missing_receipt_request_replaced')
            if scenario in ('render_fault', 'stage_fault'):
                saved = result['exports'][0]
                expected_state = 'prepared' if scenario == 'render_fault' else 'staging'
                expected_error = 'render_failed' if scenario == 'render_fault' else 'storage_failed'
                require(saved['recorded_state'] == expected_state
                        and saved['last_error'] == expected_error
                        and result['selected_export_id'] == export_id
                        and len(result['exports']) == 1,
                        'fault_outcome_not_durable')
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
        env.update(RESEARCHY_GUI_SELECTED_ROOT=str(
                       parent / 'not-an-open-project' if scenario == 'recent_open' else project.root),
                   RESEARCHY_GUI_SELECTED_PARENT=str(parent),
                   RESEARCHY_GUI_RECENTS_PARENT=str(parent / '.private-launcher-state'),
                   RESEARCHY_GUI_EXPECTED_PROJECT_ID=str(project.identifier),
                   RESEARCHY_GUI_EXPECTED_RUN_ID=run_id,
                   RESEARCHY_GUI_EXPECTED_EXPORT_ID=expected_export or '')
        marker = root / 'private-worker-stage-pid'
        owner_marker = root / 'private-gui-owner-pid'
        if scenario == 'worker_killed':
            env['RESEARCHY_GUI_TEST_STAGE_MARKER'] = str(marker)
            env['RESEARCHY_GUI_TEST_OWNER_MARKER'] = str(owner_marker)
        stopping = threading.Event()
        termination = {'terminated': False, 'error': None}
        monitor = None
        with (root / 'private-process.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, str(APP), '--mode', mode,
                 '--scenario', scenario, '--port', str(port), '--directory', str(app_dir)],
                 cwd=root, env=env, stdout=log, stderr=log, start_new_session=os.name != 'nt')
            try:
                if scenario == 'worker_killed':
                    monitor = threading.Thread(
                        target=terminate_marked_gui_worker,
                        args=(process, marker, owner_marker, stopping, termination),
                        name='researchy-test-owned-worker-termination', daemon=True)
                    monitor.start()
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
                    if x in ('open', 'recent_open', 'select_run', 'select_export',
                             'prepare', 'resume', 'cancel', 'observe')]
                code = report.get('error')
                result['observed_error'] = (code if isinstance(code, str) and
                     code.replace('_', '').isalnum() and len(code) <= 64 else None)
                result['observed_worker_reaped'] = report.get('worker_reaped')
                result['observed_supervisor_stopped'] = report.get('supervisor_stopped')
                result['observed_outcome'] = report.get('observed_outcome')
                if scenario in ('publication_window', 'publication_window_lost_reply'):
                    lost = scenario == 'publication_window_lost_reply'
                    require(
                        report['status'] == 'finished' and
                        report['real_services'] is True and
                        report['source_retrieval_verified'] is False and
                        report['selected_run_matches'] is True and
                        report['window_remaining'] == 4 and
                        report['window_confirmed'] is (not lost) and
                        report['window_uncertain_error_observed'] is lost and
                        report['window_recovery_required'] is False and
                        report['error'] is None and
                        report['session_revoked'] is True and
                        report['worker_reaped'] is True and
                        report['supervisor_stopped'] is True and
                        report['project_id'] == str(project.identifier),
                        'window_original_gui_evidence_not_accepted')
                    if mode == 'native':
                        require(report.get('native_rendering_verified') is True,
                                'window_native_rendering_not_verified')
                        if lost:
                            require(report.get('window_recovery_notice_verified') is True,
                                    'window_native_recovery_notice_missing')
                    result.update(
                        passed=True, export_id=None,
                        project_identity_retained=True,
                        window_sources_reconciled=True,
                        native_rendering_verified=bool(
                            report.get('native_rendering_verified', False)))
                    with socket.socket() as sock:
                        require(sock.connect_ex(('127.0.0.1', port)) != 0,
                                'window_listener_not_closed')
                    return result
                expected_outcome = (None if scenario == 'worker_killed'
                                    else 'recorded_cancelled' if scenario in ('cancel', 'cancel_reopen')
                                    else 'published_receipt_missing' if scenario == 'receipt_missing'
                                    else 'not_yet_staged' if scenario == 'render_fault'
                                    else 'retained_artifact_changed' if scenario == 'stage_fault'
                                    else 'published_verified')
                expected_error = 'worker_interrupted' if scenario == 'worker_killed' else None
                require(report['status'] == 'finished' and report['real_services'] is True
                        and report['source_retrieval_verified'] is False
                        and report['selected_run_matches'] is True
                        and report['selected_export_matches'] is True
                        and report['observed_outcome'] == expected_outcome
                        and report['observation_audited'] is
                            (expected_outcome == 'published_verified')
                        and report['error'] == expected_error
                        and report['session_revoked'] is True
                        and report['worker_reaped'] is True
                        and report['supervisor_stopped'] is True, 'real_gui_evidence_not_accepted')
                require(report['project_id'] == str(project.identifier), 'project_identity_changed')
                if expected_export:
                    require(report['export_id'] == expected_export, 'export_identity_changed')
                if scenario == 'worker_killed':
                    require(termination['terminated'] is True and termination['error'] is None,
                            'gui_owned_worker_not_confirmed_terminated')
                    require(report['actions'] == ['open', 'select_run', 'select_export'],
                            'worker_interruption_accepted_as_success')
                if mode == 'native':
                    require(report.get('native_rendering_verified') is True, 'native_rendering_not_verified')
                result.update(passed=True, export_id=report['export_id'],
                              project_identity_retained=True,
                              workbook_file_verified=expected_outcome == 'published_verified',
                              native_rendering_verified=bool(
                                  report.get('native_rendering_verified', False)))
                with socket.socket() as sock:
                    require(sock.connect_ex(('127.0.0.1', port)) != 0, 'listener_not_closed')
            except Exception as exc:
                result['error'] = str(exc) if isinstance(exc, ExperimentFailure) else type(exc).__name__
            finally:
                stopping.set()
                stop_owned_process(process)
                if monitor is not None:
                    monitor.join(timeout=2)
                    # No PID, path, source content or OS exception is public.
                    # This bounded evidence distinguishes an absent marker,
                    # failed parentage check and a delivered termination.
                    result['worker_termination_phase'] = termination.get('phase')
                    result['worker_termination_error'] = termination.get('error')
                    result['worker_termination_confirmed'] = termination['terminated']
                    result['worker_stage_marker_seen'] = marker.is_file()
                    result['gui_owner_marker_seen'] = owner_marker.is_file()
                    result['gui_owner_relation'] = termination.get('gui_owner_relation')
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
        if not cancelled_reopen['passed']:
            return [first, second, cancelled, cancelled_reopen]

        # A real process dies after linking a valid XLSX but before its
        # 'published' receipt can commit. The first GUI visit must show
        # recovery-required, not success; the next GUI may reconcile the
        # exact original inode/digest and journal ID without a new export.
        receipt_parent = root / 'missing-receipt-case'
        receipt_parent.mkdir()
        receipt_project, receipt_run = fixture(receipt_parent)
        receipt_id, interrupted_file = seed_unreceipted_workbook(receipt_project, receipt_run)
        original_bytes_digest = sha256(interrupted_file.read_bytes()).hexdigest()
        original_identity = (interrupted_file.stat().st_dev, interrupted_file.stat().st_ino)
        before = read_application_snapshot(receipt_project, selected_run_id=receipt_run).as_dict()
        require(len(before['exports']) == 1
                and before['exports'][0]['export_id'] == receipt_id
                and before['exports'][0]['recorded_state'] == 'publishing'
                and before['report']['status'] == 'incomplete',
                'crash_inventory_inconsistent')
        missing = run_app(mode, 'receipt_missing', receipt_project, receipt_parent,
                          receipt_run, receipt_id)
        if not missing['passed']:
            return [first, second, cancelled, cancelled_reopen, missing]
        after = read_application_snapshot(receipt_project, selected_run_id=receipt_run).as_dict()
        require(len(after['exports']) == 1 and
                after['exports'][0]['recorded_state'] == 'publishing' and
                after['last_recorded_audit_event'] == before['last_recorded_audit_event'],
                'observation_changed_crash_evidence')
        require(sha256(interrupted_file.read_bytes()).hexdigest() == original_bytes_digest,
                'observation_modified_unreceipted_file')
        recovered = run_app(mode, 'receipt_recovered', receipt_project, receipt_parent,
                            receipt_run, receipt_id)
        if not recovered['passed']:
            return [first, second, cancelled, cancelled_reopen, missing, recovered]
        final = read_application_snapshot(receipt_project, selected_run_id=receipt_run).as_dict()
        current_file = receipt_project.root / 'exports' / interrupted_file.name
        require(len(final['exports']) == 1
                and final['exports'][0]['export_id'] == receipt_id
                and final['exports'][0]['recorded_state'] == 'published'
                and not final['source_retrieval_verified'],
                'crash_recovery_not_audited')
        require(sha256(current_file.read_bytes()).hexdigest() == original_bytes_digest
                and (current_file.stat().st_dev, current_file.stat().st_ino) == original_identity,
                'crash_recovery_overwrote_workbook')
        with closing(sqlite3.connect(receipt_project.database_path)) as db:
            event_count = db.execute('SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                                     (f'{workbook_exports.EVENT}:{receipt_id}',)).fetchone()[0]
        require(event_count == 5 and
                observe_export_request(receipt_project, receipt_id).audited_success,
                'crash_recovery_journal_mismatch')
        recovered['same_file_retained'] = True
        recovered['same_export_identity'] = True
        results = [first, second, cancelled, cancelled_reopen, missing, recovered]

        # Permission/render errors and partial stage writes are injected ONLY in
        # disposable subprocesses, never via a browser-controlled fault route.
        # The real GUI inspects the durable failure, then a separately started
        # instance retries exactly that export ID without overwriting evidence.
        for kind in ('render', 'stage'):
            fault_parent = root / (kind + '-fault-case')
            fault_parent.mkdir()
            fault_project, fault_run = fixture(fault_parent)
            fault_id, partial = seed_failed_export(fault_project, fault_run, kind)
            failure_snapshot = read_application_snapshot(
                fault_project, selected_run_id=fault_run).as_dict()
            partial_bytes = None if partial is None else partial.read_bytes()
            fault = run_app(mode, kind + '_fault', fault_project, fault_parent,
                            fault_run, fault_id)
            results.append(fault)
            if not fault['passed']:
                return results
            readback = read_application_snapshot(
                fault_project, selected_run_id=fault_run).as_dict()
            require(failure_snapshot['last_recorded_audit_event'] ==
                    readback['last_recorded_audit_event'],
                    'negative_observation_appended_audit')
            require(len(readback['exports']) == 1
                    and readback['exports'][0]['export_id'] == fault_id
                    and not (fault_project.root / 'exports' /
                             ('strategy-summary-' + fault_run + '.xlsx')).exists(),
                    'fault_observation_created_workbook')
            revived = run_app(mode, kind + '_recovered', fault_project, fault_parent,
                              fault_run, fault_id)
            results.append(revived)
            if not revived['passed']:
                return results
            after = read_application_snapshot(
                fault_project, selected_run_id=fault_run).as_dict()
            published_path = fault_project.root / 'exports' / (
                'strategy-summary-' + fault_run + '.xlsx')
            with ZipFile(published_path) as workbook:
                require(workbook.testzip() is None and
                        'xl/workbook.xml' in workbook.namelist(),
                        'recovered_workbook_invalid')
            observed = observe_export_request(fault_project, fault_id)
            require(len(after['exports']) == 1
                    and after['exports'][0]['export_id'] == fault_id
                    and after['exports'][0]['recorded_state'] == 'published'
                    and after['exports'][0]['last_error'] is None
                    and after['report']['status'] == 'incomplete'
                    and not after['source_retrieval_verified']
                    and observed.audited_success
                    and sha256(published_path.read_bytes()).hexdigest() ==
                        observed.request.artifact_sha256,
                    'failed_export_recovery_not_verified')
            if partial is not None:
                require(partial.is_file() and partial.read_bytes() == partial_bytes
                        and partial != published_path,
                        'partial_retained_stage_was_replaced')
            with closing(sqlite3.connect(fault_project.database_path)) as db:
                total_events = db.execute(
                    'SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                    (f'{workbook_exports.EVENT}:{fault_id}',)).fetchone()[0]
            require(total_events == (6 if kind == 'render' else 7),
                    'early_fault_recovery_event_count_changed')
            revived['original_request_retained'] = True
            revived['damaged_stage_retained'] = partial is not None

        # Unlike previous independent fault subprocess fixtures, this case
        # terminates the GUI's own supervised ApplicationWorker child while it
        # has already written a real but incomplete retained workbook stage.
        worker_parent = root / 'gui-worker-death-case'
        worker_parent.mkdir()
        worker_project, worker_run = fixture(worker_parent)
        worker_id = str(uuid4())
        output_name = 'strategy-summary-' + worker_run + '.xlsx'
        workbook_exports.prepare_workbook_export(
            worker_project, worker_run, output_name, export_id=worker_id)
        original_report = read_application_snapshot(
            worker_project, selected_run_id=worker_run).as_dict()
        killed = run_app(mode, 'worker_killed', worker_project,
                         worker_parent, worker_run, worker_id)
        results.append(killed)
        if not killed['passed']:
            return results
        interrupted = read_application_snapshot(
            worker_project, selected_run_id=worker_run).as_dict()
        require(len(interrupted['exports']) == 1 and
                interrupted['exports'][0]['export_id'] == worker_id and
                interrupted['exports'][0]['recorded_state'] == 'staging' and
                interrupted['exports'][0]['last_error'] is None and
                interrupted['report']['status'] == 'incomplete' and
                not interrupted['source_retrieval_verified'],
                'gui_worker_interruption_lost_checkpoint')
        with workbook_exports._transaction(worker_project, write=False) as db:
            journal = workbook_exports._required(db, worker_project, worker_id)
        partial = (worker_project.root / 'exports' / workbook_exports.STORE /
                   journal['stage']['name'])
        partial_bytes = partial.read_bytes()
        partial_identity = (partial.stat().st_dev, partial.stat().st_ino)
        require(0 < len(partial_bytes) < journal['stage']['size'] and
                sha256(partial_bytes).hexdigest() != journal['stage']['sha256'],
                'terminated_worker_did_not_leave_real_partial_file')
        negative = observe_export_request(worker_project, worker_id)
        require(negative.outcome == 'retained_artifact_changed'
                and not negative.audited_success
                and not negative.source_retrieval_verified,
                'interrupted_worker_falsely_verified')
        with closing(sqlite3.connect(worker_project.database_path)) as db:
            early_events = db.execute(
                'SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                (f'{workbook_exports.EVENT}:{worker_id}',)).fetchone()[0]
        require(early_events == 2 and
                interrupted['report']['queries'][0]['exact_query'] ==
                    original_report['report']['queries'][0]['exact_query']
                and interrupted['report']['queries'][0]['reported_matches'] is None
                and not (worker_project.root / 'exports' / output_name).exists(),
                'terminated_worker_changed_scientific_evidence')
        revived = run_app(mode, 'worker_recovered', worker_project,
                          worker_parent, worker_run, worker_id)
        results.append(revived)
        if not revived['passed']:
            return results
        recovered = read_application_snapshot(
            worker_project, selected_run_id=worker_run).as_dict()
        workbook = worker_project.root / 'exports' / output_name
        with ZipFile(workbook) as archive:
            require(archive.testzip() is None and
                    'xl/workbook.xml' in archive.namelist(),
                    'worker_recovery_workbook_corrupt')
        final_observation = observe_export_request(worker_project, worker_id)
        with closing(sqlite3.connect(worker_project.database_path)) as db:
            final_events = db.execute(
                'SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                (f'{workbook_exports.EVENT}:{worker_id}',)).fetchone()[0]
        require(len(recovered['exports']) == 1
                and recovered['exports'][0]['export_id'] == worker_id
                and recovered['exports'][0]['recorded_state'] == 'published'
                and recovered['report']['queries'][0]['exact_query'] ==
                    original_report['report']['queries'][0]['exact_query']
                and recovered['report']['queries'][0]['reported_matches'] is None
                and not recovered['source_retrieval_verified']
                and final_observation.outcome == 'published_verified'
                and final_observation.audited_success
                and sha256(workbook.read_bytes()).hexdigest() ==
                    final_observation.request.artifact_sha256
                and final_events == 6
                and partial.is_file() and partial.read_bytes() == partial_bytes
                and (partial.stat().st_dev, partial.stat().st_ino) == partial_identity,
                'worker_recovery_overwrote_or_falsified_evidence')
        revived['original_request_retained'] = True
        revived['damaged_stage_retained'] = True
        revived['gui_worker_termination_confirmed'] = True

        # The same private launcher history survives separate GUI processes.
        # A folder was relocated after publication; the trusted reopen has
        # updated its UUID entry to the *new* path. The new GUI's initial
        # launcher root is deliberately invalid; only an explicit recent-list
        # click can find, verify and reopen the original real project.
        recent = run_app(mode, 'recent_open', reopened, root, run_id, first['export_id'])
        results.append(recent)
        if not recent['passed']:
            return results
        with closing(sqlite3.connect(reopened.database_path)) as db:
            recent_events = db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type LIKE 'workbook_export_v1:%'"
            ).fetchone()[0]
        require(recent_events == second_events
                and observe_export_request(reopened, first['export_id']).audited_success,
                'recent_reopen_changed_export_audit')
        recent['same_uuid_after_relocation'] = True
        recent['no_implicit_run_selection'] = True
        recent['no_new_export_receipt'] = True
        return results


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
