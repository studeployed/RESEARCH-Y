"""Disposable NiceGUI/pywebview experiment. Never open an existing project.

Run via run_prototype.py in the approved isolated dependency environment.
The actual ApplicationWorker runs a fixed synthetic service, NOT research work.
"""
from __future__ import annotations

import argparse
import asyncio
import http.client
import re
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from tools.gui_feasibility.prototype_guard import BOOTSTRAP_HTML, LaunchSession, PrototypeGuard

INJECTION = '<img src=x onerror="window.__researchy_injected=true"> & literal text'


from research_y.desktop.native import (
    create_guarded_window, install_native_navigation_veto, navigation_allowed,
    valid_initial_bootstrap, wait_for_native_http_ready,
)


def guarded_open_window(*args, **kwargs):
    """Spawn-target wrapper adding the Windows WebView2 veto and owner-death exit."""
    import multiprocessing as mp
    import webview
    allowed_origin = os.environ['RESEARCHY_PROTOTYPE_ALLOWED_ORIGIN']
    marker_dir = Path(os.environ['RESEARCHY_PROTOTYPE_MARKER_DIR'])
    # The HTTP layer must be ready, not merely the TCP listener. Validate
    # the route before WebView2's first (non-retrying) navigation.
    wait_for_native_http_ready(allowed_origin)
    (marker_dir / 'native-http-verified').write_text('1', encoding='ascii')
    real_create_window = webview.create_window

    def create_window(*window_args, **window_kwargs):
        return create_guarded_window(real_create_window, allowed_origin, marker_dir,
                                     *window_args, **window_kwargs)

    webview.create_window = create_window

    def parent_watch():
        parent = mp.parent_process()
        if parent is not None:
            parent.join()
            os._exit(75)

    threading.Thread(target=parent_watch, daemon=True, name='researchy-native-parent-watch').start()
    from nicegui.native import native_mode
    return native_mode._open_window(*args, **kwargs)


async def read_native_document(js, expression: str, *, seconds: float = 8.0):
    """Require a real document snapshot; tolerate only a transient unavailable window.

    The first Socket.IO client may connect before pywebview's native JS bridge
    returns a value. A None response is not evidence of a loaded document. Retry
    for a fixed finite window, then fail. Malformed/non-string responses fail
    immediately rather than being treated as readiness.
    """
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('native_document_not_ready')
        try:
            value = await asyncio.wait_for(js(expression), timeout=remaining)
        except asyncio.TimeoutError:
            raise TimeoutError('native_document_not_ready') from None
        if value is None:
            await asyncio.sleep(min(0.1, max(0, deadline - time.monotonic())))
            continue
        if type(value) is not str:
            raise RuntimeError('native_document_invalid_type')
        try:
            result = json.loads(value)
        except (ValueError, TypeError):
            raise RuntimeError('native_document_invalid_json') from None
        if (type(result) is not dict or set(result) != {'text', 'injected', 'url', 'fragment', 'cookie'}
                or type(result['text']) is not str or type(result['injected']) is not bool
                or not all(type(result[key]) is str for key in ('url', 'fragment', 'cookie'))):
            raise RuntimeError('native_document_invalid_shape')
        return result


def synthetic_work(command):
    """Trusted fixed service substituted only in this disposable prototype host."""
    from research_y.application_commands import ApplicationCommandError
    root = Path(command.project_root)
    (root / 'started').write_text(str(os.getpid()), encoding='ascii')
    if command.project_name == 'synthetic-failure':
        time.sleep(.5)
        raise ApplicationCommandError('project_busy')
    time.sleep(30 if command.project_name in ('synthetic-interrupt', 'synthetic-abrupt') else 3)
    return {'synthetic': True, 'search_complete': False, 'audited_export': False}


def write_report(path, report):
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def error_record(exc):
    # No exception messages, source lines, tokens or absolute paths in evidence.
    return {'type': type(exc).__name__, 'frames': [
        {'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
        for frame in traceback.extract_tb(exc.__traceback__)[-8:]]}


def run(args):
    report = {'format': 'research-y-gui-lifecycle-v1', 'mode': args.mode,
              'scenario': args.scenario, 'python': sys.version.split()[0], 'platform': sys.platform,
              'synthetic_only': True, 'gui_acceptance': False, 'production_adoption_approved': False,
              'native_checks': {}, 'shutdown': {}, 'state': 'not_started'}
    report_path = args.directory / 'app-result.json'
    args.directory.mkdir(parents=True, exist_ok=False)
    pool = None
    try:
        expected = {'nicegui': '3.18.0', 'pywebview': '6.2.1'}
        if {key: version(key) for key in expected} != expected:
            raise RuntimeError('candidate_versions_changed')
        report['candidates'] = expected
        token = os.environ.pop('RESEARCHY_PROTOTYPE_LAUNCH')
        session = LaunchSession(args.port, token)
        expected_bootstrap = session.origin + '/bootstrap#' + token
        del token
        os.environ['RESEARCHY_PROTOTYPE_ALLOWED_ORIGIN'] = session.origin
        os.environ['RESEARCHY_PROTOTYPE_MARKER_DIR'] = str(args.directory)
        from nicegui import app, ui
        from research_y import application_worker as worker
        from research_y.application_commands import ApplicationCommand
        worker.execute_command = synthetic_work
        pool = worker.ApplicationWorker()
        with tempfile.TemporaryDirectory(prefix='researchy-synthetic-') as scratch:
            command = ApplicationCommand('inspect', scratch,
                '11111111-1111-4111-8111-111111111111', f'synthetic-{args.scenario}',
                '2026-11-02T00:00:00+00:00')
            stats = {'ticks': 0, 'operation_id': None, 'state': 'idle', 'error': None,
                     'result': None, 'started': False, 'submissions': 0, 'submitted_ids': []}
            labels, clients, tasks = {}, [], []
            closing = asyncio.Event()

            def refresh():
                if stats['operation_id']:
                    status = pool.poll(stats['operation_id'])
                    stats.update(state=status.state, error=status.error, result=status.result())
                stats['started'] = (Path(scratch) / 'started').is_file()
                return dict(stats)

            def submit():
                stats['submissions'] += 1
                stats['operation_id'] = pool.submit(command)
                stats['submitted_ids'].append(stats['operation_id'])
                return refresh()

            @ui.page('/')
            def page():
                clients.append(ui.context.client)
                ui.label('RESEARCH-Y — isolated synthetic prototype')
                ui.label('INCOMPLETE — no literature search or export is being performed.')
                labels['literal'] = ui.label(INJECTION).props('data-testid=literal')
                labels['ticks'] = ui.label('0').props('data-testid=ticks')
                labels['state'] = ui.label('idle').props('data-testid=state')
                ui.button('Run synthetic operation', on_click=submit).props('data-testid=start')

            @app.get('/_probe/state')
            async def state():
                return refresh()

            @app.post('/_probe/start')
            async def start():
                return submit()

            @app.post('/_probe/stop')
            async def stop():
                # Defer shutdown until the request response has been delivered.
                asyncio.get_running_loop().call_later(.1, app.shutdown)
                return {'stop_requested': True}

            async def ticker():
                while not closing.is_set():
                    stats['ticks'] += 1
                    refresh()
                    if labels:
                        labels['ticks'].set_text(str(stats['ticks']))
                        labels['state'].set_text(stats['state'])
                    await asyncio.sleep(.05)

            async def until(predicate, timeout=40):
                deadline = time.monotonic() + timeout
                while not predicate():
                    if time.monotonic() >= deadline:
                        raise TimeoutError('prototype_condition_timeout')
                    await asyncio.sleep(.05)

            async def js(expression):
                return await asyncio.wait_for(app.native.main_window.evaluate_js(expression), timeout=8)

            async def native_probe():
                try:
                    await until(lambda: session.redeemed and clients and clients[-1].has_socket_connection)
                    result = await read_native_document(
                        js, "JSON.stringify({text: document.querySelector('[data-testid=literal]').textContent, "
                            "injected: window.__researchy_injected === true, "
                            "url: location.pathname, fragment: location.hash, "
                            "cookie: document.cookie})")
                    if result['text'] != INJECTION or result['injected'] or result['url'] != '/' or result['fragment']:
                        raise RuntimeError('native_literal_or_bootstrap_failed')
                    if session.cookie_name in result['cookie']:
                        raise RuntimeError('native_cookie_not_httponly')
                    report['native_checks']['loaded_authenticated_page'] = True
                    report['native_checks']['literal_text_not_markup'] = True
                    report['native_checks']['launch_fragment_removed'] = True
                    report['native_checks']['cookie_httponly'] = True
                    # Prove the Windows-native WebView2 NavigationStarting veto cancels
                    # an attempted departure before the document leaves our origin.
                    await js("location.href='https://example.invalid/research-y-probe'; true")
                    await until(lambda: (args.directory / 'navigation-blocked').is_file(), timeout=8)
                    await asyncio.sleep(.2)
                    current_url = await asyncio.wait_for(app.native.main_window.get_current_url(), timeout=8)
                    if not current_url.startswith(session.origin + '/'):
                        raise RuntimeError('external_navigation_escape')
                    report['native_checks']['external_navigation_blocked'] = True
                    # Real browser clicks through NiceGUI's Socket.IO event route.
                    await js("document.querySelector('[data-testid=start]').click(); "
                             "document.querySelector('[data-testid=start]').click(); true")
                    await until(lambda: stats['submissions'] == 2 and stats['started'])
                    if len(set(stats['submitted_ids'])) != 1:
                        raise RuntimeError('duplicate_click_not_coalesced')
                    report['native_checks']['browser_clicks_received'] = True
                    report['native_checks']['active_clicks_coalesced'] = True
                    if args.scenario != 'failure':
                        if refresh()['state'] != 'running':
                            raise RuntimeError('synthetic_worker_not_running')
                        before = int(await js("document.querySelector('[data-testid=ticks]').textContent"))
                        await asyncio.sleep(.3)
                        after = int(await js("document.querySelector('[data-testid=ticks]').textContent"))
                        if after <= before or refresh()['state'] != 'running':
                            raise RuntimeError('native_responsiveness_not_observed')
                        report['native_checks']['rendered_heartbeat_during_worker'] = True
                        report['native_checks']['heartbeat_delta'] = after - before
                    if args.scenario not in ('interrupt', 'abrupt'):
                        await until(lambda: refresh()['state'] != 'running')
                        expected_state = 'failed' if args.scenario == 'failure' else 'returned'
                        if stats['state'] != expected_state:
                            raise RuntimeError('unexpected_worker_outcome')
                    if args.scenario == 'abrupt':
                        (args.directory / 'abrupt-ready').write_text('ready', encoding='ascii')
                        await asyncio.sleep(60)
                        raise RuntimeError('abrupt_host_death_not_initiated')
                    report['state'] = 'native_experiment_observed'
                except Exception as exc:
                    report['state'] = 'failed'
                    report['error'] = error_record(exc)
                finally:
                    # Fixed booleans expose *which* startup stage failed.
                    # Never record the launch URL, token, cookie, origin or
                    # native/private filesystem paths in public evidence.
                    report['native_startup_stages'] = {
                        **session.startup_stages(),
                        'native_http_verified': (args.directory / 'native-http-verified').is_file(),
                        'window_created': (args.directory / 'native-window-created').is_file(),
                        'before_show': (args.directory / 'native-before-show').is_file(),
                        'bootstrap_navigation': (args.directory / 'native-bootstrap-navigated').is_file(),
                        'home_navigation': (args.directory / 'native-home-navigated').is_file(),
                        'nicegui_page_created': bool(clients),
                        'nicegui_websocket_connected': any(
                            client.has_socket_connection for client in clients),
                    }
                    # Exercise genuine window closure, not merely server shutdown.
                    app.native.main_window.destroy()

            async def startup():
                tasks.append(asyncio.create_task(ticker()))
                if args.mode == 'native':
                    tasks.append(asyncio.create_task(native_probe()))

            async def shutdown():
                closing.set()
                tasks[0].cancel() if tasks else None
                if tasks:
                    await asyncio.gather(tasks[0], return_exceptions=True)
                await asyncio.to_thread(pool.close, grace_seconds=0, kill_seconds=2)
                final = refresh()
                session.revoke()
                report['shutdown'] = {
                    'worker_reaped': pool._process is None,
                    'supervisor_stopped': pool._thread is None or not pool._thread.is_alive(),
                    'session_revoked': not session.redeemed,
                    'operation_state': final['state'], 'operation_error': final['error'],
                    'result': final['result'],
                }
                if args.mode == 'transport':
                    report['state'] = 'transport_host_stopped'
                write_report(report_path, report)

            app.add_middleware(PrototypeGuard, session=session)
            app.on_startup(startup)
            app.on_shutdown(shutdown)
            if args.mode == 'native':
                # Replace NiceGUI's native child target only inside this disposable
                # process; production framework code and installed packages are untouched.
                from nicegui.native import native_mode
                native_mode._open_window = guarded_open_window
                # Fragment is never part of an HTTP request or evidence artifact.
                launch = os.environ.pop('RESEARCHY_PROTOTYPE_NATIVE_URL')
                if launch != expected_bootstrap:
                    raise ValueError('invalid_native_bootstrap')
                app.native.window_args.update(url=launch)
                app.native.start_args.update(gui='edgechromium', private_mode=True, debug=False)
            ui.run(host='127.0.0.1', port=args.port, native=args.mode == 'native',
                   reload=False, show=False, on_air=None, tailwind=False,
                   fastapi_docs=False, show_welcome_message=False, access_log=False,
                   proxy_headers=False, uvicorn_logging_level='error')
    except Exception as exc:
        report.update(state='failed', error=error_record(exc))
    finally:
        if pool is not None:
            try:
                pool.close(grace_seconds=0, kill_seconds=2)
            except Exception as exc:
                report.update(state='failed', error=error_record(exc))
        write_report(report_path, report)
    return 1 if report['state'] == 'failed' or not report['shutdown'] else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('transport', 'native'), required=True)
    parser.add_argument('--scenario', choices=('complete', 'interrupt', 'failure', 'abrupt'), required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
