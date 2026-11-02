"""Exercise actual loopback transport and optional Windows native window.

No browser driver dependency, research project, provider call or source credential.
Private temporary process logs are not uploaded; evidence excludes launch secrets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'tools' / 'gui_feasibility' / 'prototype_app.py'
SOCKET = '/_nicegui_ws/socket.io/?EIO=4&transport=websocket'


class ExperimentFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ExperimentFailure(code)


def environment(root, port, token, native):
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
               'HOME', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'PROGRAMFILES',
               'PROGRAMFILES(X86)', 'PROGRAMDATA', 'SYSTEMDRIVE', 'DISPLAY', 'LANG'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT), str(ROOT / 'src')]),
               PYTHONUNBUFFERED='1', RESEARCHY_PROTOTYPE_LAUNCH=token)
    # NiceGUI's general storage and the native private browser profile remain temporary.
    env['NICEGUI_STORAGE_PATH'] = str(root / 'nicegui-storage')
    if native:
        env['RESEARCHY_PROTOTYPE_NATIVE_URL'] = f'http://127.0.0.1:{port}/bootstrap#{token}'
    return env


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(port, path, *, method='GET', headers=None, body=None, upgrade=False):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    supplied = dict(headers or {})
    if upgrade:
        supplied.update({'Connection': 'Upgrade', 'Upgrade': 'websocket',
                         'Sec-WebSocket-Key': 'dGhlIHNhbXBsZSBub25jZQ==', 'Sec-WebSocket-Version': '13'})
    try:
        conn.request(method, path, body=body, headers=supplied)
        response = conn.getresponse()
        payload = b'' if response.status == 101 else response.read(1024 * 1024 + 1)
        require(len(payload) <= 1024 * 1024, 'response_too_large')
        return response.status, dict(response.getheaders()), payload
    finally:
        conn.close()


def wait_until(predicate, *, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise ExperimentFailure('condition_timeout')


def transport_checks(port, token, scenario):
    origin = f'http://127.0.0.1:{port}'
    def ready():
        try:
            return request(port, '/bootstrap')[0] == 200
        except OSError:
            return False
    wait_until(ready)
    checks = {}
    status, _, _ = request(port, '/')
    require(status == 403, 'unauthenticated_page_allowed')
    status, _, _ = request(port, '/session', method='POST',
                           headers={'Origin': origin, 'X-ResearchY-Bootstrap': '0' * 64})
    require(status == 403, 'bad_launch_token_allowed')
    status, headers, _ = request(port, '/session', method='POST',
                                 headers={'Origin': origin, 'X-ResearchY-Bootstrap': token})
    require(status == 204, 'launch_redemption_failed')
    cookie = next(value for key, value in headers.items() if key.lower() == 'set-cookie').split(';', 1)[0]
    auth = {'Cookie': cookie, 'Origin': origin}
    status, _, _ = request(port, '/session', method='POST',
                           headers={'Origin': origin, 'X-ResearchY-Bootstrap': token})
    require(status == 403, 'launch_token_replayed')
    checks['single_use_bootstrap'] = True
    cases = [
        ('wrong_host', '/', 'GET', {**auth, 'Host': 'untrusted.example'}, None),
        ('foreign_origin', '/', 'GET', {**auth, 'Origin': 'https://untrusted.example'}, None),
        ('same_site_wrong_port', '/', 'GET', {**auth, 'Sec-Fetch-Site': 'same-site'}, None),
        ('missing_cookie', '/_probe/state', 'GET', {'Origin': origin}, None),
        ('bad_cookie', '/_probe/state', 'GET', {**auth, 'Cookie': 'unknown=wrong'}, None),
        ('duplicate_cookie', '/', 'GET', {**auth, 'Cookie': cookie + '; ' + cookie}, None),
        ('missing_post_origin', '/_probe/start', 'POST', {'Cookie': cookie}, None),
        ('cross_origin_post', '/_probe/start', 'POST', {**auth, 'Origin': 'null'}, None),
        ('arbitrary_path_body', '/_probe/start', 'POST', auth, b'{"path":"C:/private"}'),
        ('encoded_traversal', '/_nicegui/3.18.0/static/%2e%2e/private', 'GET', auth, None),
        ('download_surface', '/_nicegui/3.18.0/download/file', 'GET', auth, None),
        ('upload_surface', '/_nicegui/3.18.0/upload/file', 'POST', auth, None),
        ('unknown_route', '/private', 'GET', auth, None),
    ]
    for name, path, method, request_headers, body in cases:
        require(request(port, path, method=method, headers=request_headers, body=body)[0] == 403,
                'rejection_failed_' + name)
        checks[name] = True
    for name, request_headers, expected in [
        ('missing_cookie', {'Origin': origin}, 403),
        ('foreign_origin', {**auth, 'Origin': 'https://untrusted.example'}, 403),
        ('missing_origin', {'Cookie': cookie}, 403),
        ('authorized', auth, 101),
    ]:
        require(request(port, SOCKET, headers=request_headers, upgrade=True)[0] == expected,
                'socket_boundary_failed_' + name)
        checks['websocket_' + name] = True
    def state():
        status, _, payload = request(port, '/_probe/state', headers=auth)
        require(status == 200, 'state_unavailable')
        return json.loads(payload)
    require(state()['submissions'] == 0, 'rejected_request_reached_service')
    status, headers, payload = request(port, '/', headers=auth)
    require(status == 200 and b'INCOMPLETE' in payload, 'actual_nicegui_page_missing')
    require(any(k.lower() == 'content-security-policy' for k in headers), 'security_headers_missing')
    require(not any(k.lower() == 'access-control-allow-origin' and v == '*' for k, v in headers.items()),
            'wildcard_origin_header')
    first = json.loads(request(port, '/_probe/start', method='POST', headers=auth)[2])
    second = json.loads(request(port, '/_probe/start', method='POST', headers=auth)[2])
    require(first['operation_id'] == second['operation_id'], 'double_submit_not_coalesced')
    checks['active_requests_coalesced'] = True
    wait_until(lambda: state()['started'])
    if scenario != 'failure':
        before = state()
        time.sleep(.3)
        after = state()
        require(before['state'] == after['state'] == 'running' and after['ticks'] > before['ticks'],
                'server_unresponsive_during_worker')
        checks['heartbeat_during_worker'] = True
    if scenario != 'interrupt':
        done = wait_until(lambda: (value if (value := state())['state'] != 'running' else None))
        expected = 'failed' if scenario == 'failure' else 'returned'
        require(done['state'] == expected, 'worker_outcome_incorrect')
    require(request(port, '/_probe/stop', method='POST', headers=auth)[0] == 200, 'stop_refused')
    return checks


def windows_process_table():
    """One native Toolhelp snapshot of process parent links.

    Avoid spawning PowerShell and querying CIM every 50 ms while checking
    abrupt-host cleanup. No extra runtime dependency, increased timeout,
    excluded process type or softened descendant-exit requirement.
    """
    if os.name != 'nt':
        return {}
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateToolhelp32Snapshot
    create.argtypes = (wintypes.DWORD, wintypes.DWORD)
    create.restype = wintypes.HANDLE
    first = kernel.Process32FirstW
    first.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    first.restype = wintypes.BOOL
    next_process = kernel.Process32NextW
    next_process.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    next_process.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL

    handle = create(0x00000002, 0)  # TH32CS_SNAPPROCESS, machine-local processes
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise OSError('process_snapshot_unavailable')
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        if not first(handle, ctypes.byref(entry)):
            raise OSError('process_snapshot_first_failed')
        result = {}
        while True:
            result[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not next_process(handle, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise OSError('process_snapshot_incomplete')
                break
        return result
    finally:
        if not close(handle):
            raise OSError('process_snapshot_close_failed')


def descendant_pids(root_pid):
    table = windows_process_table()
    found, frontier = set(), {int(root_pid)}
    while frontier:
        children = {pid for pid, parent in table.items() if parent in frontier and pid not in found}
        found.update(children)
        frontier = children
    return found


def stop_owned_process(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        else:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def run_abrupt_native_case():
    require(os.name == 'nt', 'abrupt_native_windows_required')
    token, port = secrets.token_hex(32), free_port()
    outcome = {'mode': 'native', 'scenario': 'abrupt', 'passed': False}
    with tempfile.TemporaryDirectory(prefix='researchy-gui-abrupt-') as directory:
        root = Path(directory)
        app_dir = root / 'app'
        marker = app_dir / 'abrupt-ready'
        navigation_marker = app_dir / 'navigation-blocked'
        with (root / 'private-process.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, str(APP), '--mode', 'native', '--scenario', 'abrupt',
                        '--port', str(port), '--directory', str(app_dir)], cwd=root,
                        env=environment(root, port, token, True), stdout=log, stderr=log)
            captured = set()
            stage = 'await_native_ready'
            try:
                wait_until(marker.is_file, timeout=60)
                require(navigation_marker.is_file(), 'native_navigation_veto_not_observed_before_abrupt')
                stage = 'inventory_owned_descendants'
                captured = descendant_pids(process.pid)
                require(len(captured) >= 2, 'owned_descendants_not_observed')
                outcome['descendants_before'] = len(captured)
                # Kill only the host process. Worker/native-window descendants must
                # terminate through their own parent-death ownership boundaries.
                stage = 'kill_host_pid_only'
                subprocess.run(['taskkill', '/PID', str(process.pid), '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=10, check=False)
                stage = 'verify_host_exit'
                process.wait(timeout=10)
                def remaining():
                    table = windows_process_table()
                    return sorted(pid for pid in captured if pid in table)
                stage = 'verify_owned_descendant_exit'
                wait_until(lambda: not remaining(), timeout=15)
                stage = 'verify_listener_exit'
                with socket.socket() as sock:
                    sock.settimeout(2)
                    require(sock.connect_ex(('127.0.0.1', port)) != 0, 'listener_survived_abrupt_host_death')
                outcome.update(navigation_blocked=True, descendants_remaining=0,
                               listener_closed=True, passed=True)
            except Exception as exc:
                outcome['error'] = str(exc) if isinstance(exc, ExperimentFailure) else type(exc).__name__
                outcome['failed_stage'] = stage
                if captured:
                    outcome['descendants_remaining'] = len([p for p in captured if p in windows_process_table()])
            finally:
                if process.poll() is None:
                    stop_owned_process(process)
                if captured:
                    leftovers = [pid for pid in captured if pid in windows_process_table()]
                    for pid in leftovers:
                        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=10, check=False)
    require(token not in json.dumps(outcome), 'launch_secret_in_evidence')
    return outcome


def validate_result(report, mode, scenario):
    expected = {'complete': 'returned', 'failure': 'failed', 'interrupt': 'interrupted'}[scenario]
    require(report.get('state') == ('native_experiment_observed' if mode == 'native' else 'transport_host_stopped'),
            'app_experiment_failed')
    require(report.get('synthetic_only') is True and report.get('gui_acceptance') is False,
            'invalid_evidence_scope')
    shutdown = report.get('shutdown', {})
    require(all(shutdown.get(key) is True for key in ('worker_reaped', 'supervisor_stopped', 'session_revoked')),
            'cleanup_unverified')
    require(shutdown.get('operation_state') == expected, 'shutdown_outcome_incorrect')
    if scenario == 'complete':
        require(shutdown.get('result') == {'synthetic': True, 'search_complete': False, 'audited_export': False},
                'synthetic_result_incorrect')
    if scenario == 'failure':
        require(shutdown.get('operation_error') == 'project_busy', 'failure_not_preserved')
    if mode == 'native':
        keys = ['loaded_authenticated_page', 'literal_text_not_markup', 'launch_fragment_removed',
                'cookie_httponly', 'external_navigation_blocked',
                'browser_clicks_received', 'active_clicks_coalesced']
        if scenario != 'failure':
            keys.append('rendered_heartbeat_during_worker')
        require(all(report.get('native_checks', {}).get(key) is True for key in keys), 'native_checks_missing')


def run_case(mode, scenario):
    token, port = secrets.token_hex(32), free_port()
    outcome = {'mode': mode, 'scenario': scenario, 'passed': False}
    with tempfile.TemporaryDirectory(prefix='researchy-gui-case-') as directory:
        root = Path(directory)
        report_path = root / 'app' / 'app-result.json'
        with (root / 'private-process.log').open('wb') as log:
            process = subprocess.Popen([sys.executable, str(APP), '--mode', mode, '--scenario', scenario,
                        '--port', str(port), '--directory', str(root / 'app')], cwd=root,
                        env=environment(root, port, token, mode == 'native'), stdout=log, stderr=log,
                        start_new_session=os.name != 'nt')
            try:
                if mode == 'transport':
                    outcome['transport_checks'] = transport_checks(port, token, scenario)
                process.wait(timeout=90)
                require(process.returncode == 0, 'prototype_process_failed')
                require(report_path.is_file(), 'prototype_report_missing')
                report = json.loads(report_path.read_text(encoding='utf-8'))
                outcome['observation'] = report
                validate_result(report, mode, scenario)
                # A terminated process is not enough: verify its listener is gone.
                with socket.socket() as sock:
                    sock.settimeout(2)
                    require(sock.connect_ex(('127.0.0.1', port)) != 0, 'listener_still_open')
                outcome.update(listener_closed=True, passed=True)
            except Exception as exc:
                outcome['error'] = str(exc) if isinstance(exc, ExperimentFailure) else type(exc).__name__
                if report_path.is_file():
                    outcome['observation'] = json.loads(report_path.read_text(encoding='utf-8'))
            finally:
                stop_owned_process(process)
    require(token not in json.dumps(outcome), 'launch_secret_in_evidence')
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--native', action='store_true')
    args = parser.parse_args(argv)
    require(not args.native or sys.platform == 'win32', 'native_windows_required')
    modes = ['transport'] + (['native'] if args.native else [])
    results = [run_case(mode, scenario) for mode in modes for scenario in ('complete', 'failure', 'interrupt')]
    if args.native:
        results.append(run_abrupt_native_case())
    evidence = {'format': 'research-y-gui-prototype-driver-v1', 'results': results,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'passed': all(item['passed'] for item in results), 'gui_acceptance': False,
        'production_adoption_approved': False,
        'limitations': ['Synthetic worker service, not a real project/export workflow.',
            'External navigation veto is Windows-native prototype evidence, not a cross-platform browser policy.',
            'Abrupt-host cleanup inventories only descendants observed immediately before termination; PID reuse is bounded by the short check window.',
            'No 100,000-record, installer, complete dependency security or licence acceptance.']}
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / 'prototype-evidence.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n',
                                                          encoding='utf-8')
    print(f"Graphical experiment: {sum(r['passed'] for r in results)}/{len(results)} scenarios passed.")
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
