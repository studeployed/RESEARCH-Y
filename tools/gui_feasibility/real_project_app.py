"""Isolated real-project NiceGUI adapter; selects paths only in the trusted host.

Uses real RESEARCH-Y project/inspection/worker/workbook services on disposable
projects. Not a product launcher, installer, production GUI or source search.
"""
from __future__ import annotations

import argparse
import asyncio
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

from tools.gui_feasibility.prototype_guard import LaunchSession, PrototypeGuard
from tools.gui_feasibility.prototype_app import guarded_open_window
from tools.gui_feasibility.real_project_flow import ProjectFlowError, RealProjectFlow

LITERAL_NAME = '<img src=x onerror="window.__researchy_injected=true">'


def write_report(path, report):
    path.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def run(args):
    report = {'format': 'research-y-gui-real-project-v1', 'mode': args.mode,
              'scenario': args.scenario, 'status': 'starting', 'real_services': True,
              'synthetic_source_fixture': True, 'source_retrieval_verified': False,
              'gui_acceptance': False, 'production_adoption_approved': False}
    args.directory.mkdir(parents=True, exist_ok=False)
    destination = args.directory / 'app-result.json'
    flow = None
    try:
        if {k: version(k) for k in ('nicegui', 'pywebview')} != {'nicegui': '3.18.0', 'pywebview': '6.2.1'}:
            raise RuntimeError('unapproved_graphical_versions')
        from nicegui import ui, app
        root = Path(os.environ.pop('RESEARCHY_GUI_SELECTED_ROOT'))
        parent = Path(os.environ.pop('RESEARCHY_GUI_SELECTED_PARENT'))
        launch = os.environ.pop('RESEARCHY_PROTOTYPE_LAUNCH')
        session = LaunchSession(args.port, launch)
        expected_bootstrap = session.origin + '/bootstrap#' + launch
        del launch
        flow = RealProjectFlow(selected_root=root, selected_parent=parent)
        os.environ['RESEARCHY_PROTOTYPE_ALLOWED_ORIGIN'] = session.origin
        os.environ['RESEARCHY_PROTOTYPE_MARKER_DIR'] = str(args.directory)
        events, clients, tasks = [], [], []
        last_error = {'code': None}
        finished = asyncio.Event()
        sequence = (('open', 'select_run', 'prepare', 'prepare', 'resume', 'observe')
                    if args.scenario == 'publish' else
                    ('open', 'select_run', 'select_export', 'observe'))
        action_lock = asyncio.Lock()
        select_id = os.environ.pop('RESEARCHY_GUI_EXPECTED_RUN_ID')
        expected_export = os.environ.pop('RESEARCHY_GUI_EXPECTED_EXPORT_ID', '')

        async def act(name, value=None):
            async with action_lock:
                try:
                    def perform():
                        if name == 'open':
                            return flow.open_selected()
                        if name == 'create':
                            return flow.create_selected(value)
                        if name == 'select_run':
                            return flow.select_run(value)
                        if name == 'select_export':
                            return flow.select_export(value)
                        if name == 'prepare':
                            return flow.prepare()
                        if name == 'resume':
                            return flow.resume()
                        if name == 'observe':
                            return flow.observe()
                        raise ProjectFlowError('unsupported_action')
                    await asyncio.to_thread(perform)
                    last_error['code'] = None
                    events.append(name)
                except ProjectFlowError as exc:
                    last_error['code'] = str(exc)
                except Exception:
                    last_error['code'] = 'unhandled_action_failure'
                if clients:
                    panel.refresh()
                return view()

        def view():
            return {'state': flow.state(), 'actions': list(events),
                    'error': last_error['code'], 'pending': action_lock.locked()}

        @ui.refreshable
        def panel():
            state = flow.state()
            project = state['project']
            ui.label('INCOMPLETE — no source retrieval is verified.').props('data-testid=incomplete')
            if project is None:
                ui.label('No project open. A host-selected location is required.')
            else:
                ui.label('Project: ' + project['name']).props('data-testid=project-name')
                ui.label('Location: ' + project['location']).props('data-testid=project-location')
                for item in state['runs']:
                    rid = item['run_id']
                    ui.button(f"Select run/version {item['version_number']} ({rid})",
                              on_click=lambda rid=rid: act('select_run', rid)).props('data-testid=select-run')
                if state['selected_run_id'] is None:
                    ui.label('No run selected (explicit selection required).')
                else:
                    ui.label('Selected run: ' + state['selected_run_id']).props('data-testid=selected-run')
                    data = state['report']
                    if data is None:
                        ui.label('Report not available.')
                    else:
                        ui.label('Current run projection (may differ from the retained export).')
                        ui.label('Report status: ' + str(data['status'])).props('data-testid=report-status')
                        unique = data['counts']['totals'].get('global_unique_publications')
                        ui.label('Global unique publications: ' +
                                 ('unknown' if unique is None else str(unique))).props('data-testid=unique-count')
                        for item in data['queries']:
                            count = item['reported_matches']
                            ui.label('Exact query: ' + item['exact_query']).props('data-testid=exact-query')
                            ui.label('Reported matches: ' +
                                     ('unknown' if count is None else str(count))).props('data-testid=query-count')
                for item in state['exports']:
                    # Only offer requests belonging to the explicitly selected run.
                    if state['selected_run_id'] is None or item['run_id'] != state['selected_run_id']:
                        continue
                    eid = item['export_id']
                    ui.button('Select stored export ' + eid,
                              on_click=lambda eid=eid: act('select_export', eid)).props('data-testid=select-export')
                if state['selected_run_id'] is not None:
                    ui.label('Default workbook: strategy-summary-' +
                             state['selected_run_id'] + '.xlsx')
                    ui.button('Prepare strategy workbook',
                              on_click=lambda: act('prepare')).props('data-testid=prepare')
                if state['selected_export_id'] is not None:
                    ui.button('Resume publication', on_click=lambda: act('resume')).props('data-testid=resume')
                    ui.button('Verify workbook', on_click=lambda: act('observe')).props('data-testid=observe')
                    ui.label('Export request ID: ' + state['selected_export_id']).props('data-testid=export-id')
                retained = state['retained_export_report']
                if retained is not None:
                    ui.label('Retained original export report — frozen when prepared.')
                    ui.label('Retained report status: ' + str(retained['status']))
                    for item in retained['queries']:
                        ui.label('Retained exact query: ' + item['exact_query']).props('data-testid=retained-query')
                        count = item['reported_matches']
                        ui.label('Retained reported matches: ' +
                                 ('unknown' if count is None else str(count))).props('data-testid=retained-count')
                observed = state['observation']
                if observed is not None:
                    ui.label('Observed outcome: ' + observed['outcome']).props('data-testid=observation')
                    ui.label('Audited workbook success: ' + str(observed['audited_success']))
            if last_error['code']:
                ui.label('Operation error: ' + last_error['code']).props('data-testid=operation-error')

        @ui.page('/')
        def page():
            clients.append(ui.context.client)
            ui.label('RESEARCH-Y — trusted real-project feasibility').props('data-testid=title')
            ui.button('Open host-selected project', on_click=lambda: act('open')).props('data-testid=open')
            project_name = ui.input('New project name', value='New local project')
            ui.button('Create in host-selected parent',
                      on_click=lambda: act('create', project_name.value)).props('data-testid=create')
            panel()

        @app.get('/_probe/state')
        async def state():
            return view()

        @app.post('/_probe/start')
        async def step():
            index = len(events)
            if index >= len(sequence):
                return {'error': 'no_more_steps'}
            action = sequence[index]
            if action == 'select_run':
                return await act(action, select_id)
            if action == 'select_export':
                return await act(action, expected_export)
            return await act(action)

        @app.post('/_probe/stop')
        async def stop():
            asyncio.get_running_loop().call_later(.1, app.shutdown)
            return {'stop_requested': True}

        async def until(condition, deadline=30):
            limit = time.monotonic() + deadline
            while not condition():
                if time.monotonic() >= limit:
                    raise RuntimeError('native_action_timeout')
                await asyncio.sleep(.05)

        async def js(expression):
            return await asyncio.wait_for(app.native.main_window.evaluate_js(expression), timeout=8)

        async def native_probe():
            try:
                await until(lambda: session.redeemed and clients and clients[-1].has_socket_connection)
                for index, action in enumerate(sequence):
                    name = {'open': 'open', 'select_run': 'select-run', 'select_export': 'select-export',
                            'prepare': 'prepare', 'resume': 'resume', 'observe': 'observe'}[action]
                    await until(lambda: bool(clients) and not action_lock.locked())
                    await until_native_button(name, js)
                    await js("document.querySelector('[data-testid=" + name + "]').click(); true")
                    await until(lambda: len(events) > index or last_error['code'] is not None)
                    if last_error['code'] is not None or events[index] != action:
                        raise RuntimeError('native_action_failed')
                await until(lambda: flow.state()['observation'] is not None)
                current = flow.state()
                if current['observation']['outcome'] != 'published_verified':
                    raise RuntimeError('native_not_verified')
                check = await js("JSON.stringify({incomplete: document.querySelector('[data-testid=incomplete]').textContent,"
                                 "query: document.querySelector('[data-testid=exact-query]').textContent,"
                                 "retained: document.querySelector('[data-testid=retained-query]').textContent,"
                                 "injected: window.__researchy_injected === true})")
                if check is None:
                    raise RuntimeError('native_document_unavailable')
                data = json.loads(check)
                if ('INCOMPLETE' not in data['incomplete'] or 'Exact query:' not in data['query']
                        or 'Retained exact query:' not in data['retained'] or data['injected']):
                    raise RuntimeError('native_rendering_invalid')
                report['native_rendering_verified'] = True
                report['status'] = 'finished'
            except Exception as exc:
                report['status'] = 'failed'
                report['error'] = type(exc).__name__
            finally:
                app.native.main_window.destroy()

        async def until_native_button(name, js):
            limit = time.monotonic() + 15
            while time.monotonic() < limit:
                present = await js("Boolean(document.querySelector('[data-testid=" + name + "]'))")
                if present is True:
                    return
                await asyncio.sleep(.1)
            raise RuntimeError('native_button_unavailable')

        async def startup():
            if args.mode == 'native':
                tasks.append(asyncio.create_task(native_probe()))

        async def shutdown():
            await asyncio.to_thread(flow.close)
            session.revoke()
            state = flow.state()
            observed = state['observation']
            report.update(
                status='finished' if args.mode == 'transport' and not last_error['code'] else report['status'],
                actions=list(events), error=last_error['code'] or report.get('error'),
                selected_run_matches=state['selected_run_id'] == select_id,
                selected_export_matches=bool(state['selected_export_id']) and
                                        (not expected_export or state['selected_export_id'] == expected_export),
                export_id=state['selected_export_id'],
                observed_outcome=None if observed is None else observed['outcome'],
                observation_audited=False if observed is None else observed['audited_success'],
                project_id=None if state['project'] is None else state['project']['project_id'],
                session_revoked=not session.redeemed,
                worker_reaped=flow._worker._process is None,
                supervisor_stopped=flow._worker._thread is None or not flow._worker._thread.is_alive(),
            )
            write_report(destination, report)
            finished.set()

        app.add_middleware(PrototypeGuard, session=session)
        app.on_startup(startup)
        app.on_shutdown(shutdown)
        if args.mode == 'native':
            from nicegui.native import native_mode
            native_mode._open_window = guarded_open_window
            url = os.environ.pop('RESEARCHY_PROTOTYPE_NATIVE_URL')
            if url != expected_bootstrap:
                raise ValueError('invalid_native_bootstrap')
            app.native.window_args.update(url=url)
            app.native.start_args.update(gui='edgechromium', private_mode=True, debug=False)
        ui.run(host='127.0.0.1', port=args.port, native=args.mode == 'native',
               reload=False, show=False, on_air=None, tailwind=False,
               fastapi_docs=False, show_welcome_message=False, access_log=False,
               proxy_headers=False, uvicorn_logging_level='error')
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = type(exc).__name__
    finally:
        if flow is not None:
            try:
                flow.close()
            except Exception:
                report['status'] = 'failed'
                report['error'] = 'cleanup_failed'
        write_report(destination, report)
    return 0 if report.get('status') == 'finished' and report.get('worker_reaped') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('transport', 'native'), required=True)
    parser.add_argument('--scenario', choices=('publish', 'reopen'), required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
