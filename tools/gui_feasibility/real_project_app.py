"""Isolated real-project NiceGUI adapter; selects paths only in the trusted host.

Uses real RESEARCH-Y project/inspection/worker/workbook services on disposable
projects. Not a product launcher, installer, production GUI or source search.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date
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
from research_y.desktop.actions import perform_action
from research_y.desktop.project_panel import render_project_panel
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.wos_host_profile import WoSHostProfile
from tools.gui_feasibility.native_folder_selection import NativeFolderError, select_from_native_window

LITERAL_NAME = '<img src=x onerror="window.__researchy_injected=true">'

# One UI action may execute three bounded, sequential 35-second worker calls.
# Keep short readiness checks separate from the longer action-completion wait.
NATIVE_ACTION_COMPLETION_TIMEOUT = 115
WINDOW_SCENARIOS = ('publication_window', 'publication_window_lost_reply')


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
        if args.scenario == 'worker_killed':
            # This swap is restricted to the disposable test runner process.
            # The real ApplicationWorker spawns our importable, test-only
            # callable; the browser cannot select a fault or filesystem path.
            if not os.environ.get('RESEARCHY_GUI_TEST_STAGE_MARKER'):
                raise RuntimeError('trusted_worker_fault_marker_required')
            owner_marker = os.environ.pop('RESEARCHY_GUI_TEST_OWNER_MARKER', '')
            if not owner_marker:
                raise RuntimeError('trusted_gui_owner_marker_required')
            from research_y import application_worker
            from tools.gui_feasibility.worker_death_fixture import (
                pause_during_retained_stage, publish_gui_owner_marker)
            publish_gui_owner_marker(Path(owner_marker))
            application_worker.execute_command = pause_during_retained_stage
        # In the ordinary experimental launcher this is private per-user
        # local state. The disposable CI driver overrides it with a temporary
        # trusted directory shared only between its restarted GUI processes.
        history_root = os.environ.pop('RESEARCHY_GUI_RECENTS_PARENT', '')
        if history_root:
            recents_parent = Path(history_root)
        elif os.name == 'nt':
            recents_parent = Path(os.environ.get(
                'LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')) / 'RESEARCH-Y' / 'gui-feasibility'
        else:
            recents_parent = Path(os.environ.get(
                'XDG_STATE_HOME') or str(Path.home() / '.local' / 'state')) / 'research-y' / 'gui-feasibility'
        # The host removes the optional prototype-only contact/key settings
        # from the environment before constructing any browser session.
        # No browser control or HTTP route can supply credentials.
        pubmed_profile = PubMedHostProfile.from_prototype_environment()
        wos_profile = WoSHostProfile.from_prototype_environment()
        flow = RealProjectFlow(selected_root=root, selected_parent=parent,
                               recent_parent=recents_parent,
                               pubmed_profile=pubmed_profile,
                               wos_profile=wos_profile)
        if args.scenario == 'publication_window_lost_reply':
            # Test-process-only failure injection. The *real* supervised child
            # commits both original transactions; only the reply to the GUI
            # host is deliberately lost. No browser action can enable this.
            original_window_operation = flow._operation
            def return_lost_after_commit(name, **kwargs):
                result = original_window_operation(name, **kwargs)
                if name == 'publication_window_confirm':
                    raise ProjectFlowError('worker_interrupted')
                return result
            flow._operation = return_lost_after_commit
        os.environ['RESEARCHY_PROTOTYPE_ALLOWED_ORIGIN'] = session.origin
        os.environ['RESEARCHY_PROTOTYPE_MARKER_DIR'] = str(args.directory)
        events, clients, tasks = [], [], []
        last_error = {'code': None}
        finished = asyncio.Event()
        sequence = (('open', 'select_run', 'manifest_history', 'manifest_inspect', 'manifest_save', 'manifest_check_file')
                    if args.scenario == 'manifest_publish' else
                    ('open', 'select_run', 'manifest_preview', 'manifest_confirm')
                    if args.scenario == 'manifest_consent' else
                    ('open', 'select_run', 'manifest_history', 'manifest_inspect')
                    if args.scenario == 'manifest_reopen' else
                    ('open', 'select_run', 'publication_window_offer',
                     'publication_window_confirm', 'publication_window_inspect')
                    if args.scenario in WINDOW_SCENARIOS else
                    ('open', 'select_run', 'publication_refresh',
                     'publication_next', 'publication_detail')
                    if args.scenario == 'publication_results_large' else
                    ('open', 'select_run', 'prepare', 'prepare', 'resume', 'observe')
                    if args.scenario == 'publish' else
                    ('recent_open', 'select_run', 'select_export', 'observe')
                    if args.scenario == 'recent_open' else
                    ('open', 'select_run', 'prepare', 'cancel', 'observe')
                    if args.scenario == 'cancel' else
                    ('open', 'select_run', 'select_export', 'resume', 'observe')
                    if args.scenario in ('receipt_recovered', 'render_recovered',
                                         'stage_recovered', 'worker_recovered') else
                    ('open', 'select_run', 'select_export', 'resume')
                    if args.scenario == 'worker_killed' else
                    ('open', 'select_run', 'select_export', 'observe'))
        action_lock = asyncio.Lock()
        probe_step_count = 0
        window_uncertain_error_observed = False
        # Source IDs/cursors stay in this disposable host's private memory;
        # only aggregate, source-free results evidence goes into the report.
        results_witness = dict(first_ids=None, first_cursor=None,
                               first_revision=None, second_ids=None,
                               detail_open=False, action_service_ms=[])
        # Disposable test-launcher assertions: never readable or selectable
        # through browser state, HTTP requests or an application preference.
        expected_window_remaining = int(os.environ.pop(
            'RESEARCHY_GUI_TEST_EXPECTED_WINDOW_REMAINING', '4'))
        expected_window_provisional = int(os.environ.pop(
            'RESEARCHY_GUI_TEST_EXPECTED_WINDOW_PROVISIONAL', '128'))
        if args.scenario in WINDOW_SCENARIOS and (
                not 0 <= expected_window_remaining <= 100000 or
                not 128 <= expected_window_provisional <= 100000):
            raise RuntimeError('native_window_test_expectation_invalid')
        select_id = os.environ.pop('RESEARCHY_GUI_EXPECTED_RUN_ID')
        expected_project_id = os.environ.pop('RESEARCHY_GUI_EXPECTED_PROJECT_ID', '')
        expected_export = os.environ.pop('RESEARCHY_GUI_EXPECTED_EXPORT_ID', '')

        async def act(name, value=None):
            async with action_lock:
                # Only aggregate duration and fixed action names enter
                # disposable evidence; no source, path, actor or cursor data.
                service_started = time.perf_counter()
                initial_events = len(events)
                try:
                    def perform():
                        if name == 'open':
                            return flow.open_selected()
                        if name == 'create':
                            return flow.create_selected(value)
                        return perform_action(flow, name, value)
                    if name in ('native_open', 'native_create') or name == 'native_export':
                        # The browser only requests the OS dialog; it cannot
                        # supply or replace the trusted host-selected path.
                        if args.mode != 'native':
                            raise ProjectFlowError('native_dialog_unavailable')
                        selected = await select_from_native_window(app.native.main_window)
                        if selected is not None:
                            if name == 'native_open':
                                await asyncio.to_thread(flow.open_native_folder, selected)
                            elif name == 'native_create':
                                await asyncio.to_thread(flow.create_native_parent,
                                                        selected, value)
                            else:
                                # The unforgeable OS dialog result is held by the
                                # Python host. It still needs an explicit second
                                # user confirmation before any export operation.
                                await asyncio.to_thread(flow.offer_external_directory, selected)
                            events.append(name)
                    else:
                        await asyncio.to_thread(perform)
                        if args.scenario == 'publication_results_large':
                            current = flow.state()
                            page = current.get('publication_page')
                            if name == 'publication_refresh':
                                if (page is None or len(page['rows']) != 20 or
                                        page['after_publication_id'] is not None):
                                    raise RuntimeError('results_first_page_invalid')
                                results_witness['first_ids'] = {
                                    x['publication_id'] for x in page['rows']}
                                results_witness['first_cursor'] = (
                                    page['next_after_publication_id'])
                                results_witness['first_revision'] = page['revision']
                            if name == 'publication_next':
                                if (page is None or len(page['rows']) != 20 or
                                        page['after_publication_id'] !=
                                        results_witness['first_cursor'] or
                                        page['revision'] !=
                                        results_witness['first_revision']):
                                    raise RuntimeError('results_second_page_invalid')
                                ids = {x['publication_id'] for x in page['rows']}
                                if (len(ids) != 20 or
                                        not ids.isdisjoint(results_witness['first_ids'])):
                                    raise RuntimeError('results_page_overlap')
                                results_witness['second_ids'] = ids
                            if name == 'publication_detail':
                                detail = current.get('publication_detail')
                                if (page is None or detail is None or
                                        page['revision'] != results_witness['first_revision'] or
                                        detail['publication']['publication_id'] !=
                                        page['rows'][0]['publication_id'] or
                                        detail['publication']['publication_id'] not in
                                        results_witness['second_ids'] or
                                        detail['abstract_text_displayed'] is not False or
                                        detail['redistribution_permission_established'] is not False):
                                    raise RuntimeError('results_detail_invalid')
                                results_witness['detail_open'] = True
                        if name != 'manifest_poll':
                            events.append(name)
                    last_error['code'] = None
                except NativeFolderError as exc:
                    last_error['code'] = str(exc)
                except ProjectFlowError as exc:
                    last_error['code'] = str(exc)
                    if (args.scenario == 'publication_window_lost_reply' and
                            name == 'publication_window_confirm' and
                            last_error['code'] == 'publication_window_reinspect_required'):
                        nonlocal window_uncertain_error_observed
                        window_uncertain_error_observed = True
                except Exception:
                    last_error['code'] = 'unhandled_action_failure'
                if (args.scenario == 'publication_results_large' and
                        len(events) == initial_events + 1 and
                        name in ('open', 'select_run', 'publication_refresh',
                                 'publication_next', 'publication_detail')):
                    results_witness['action_service_ms'].append({
                        'action': name,
                        'elapsed_ms': round(
                            (time.perf_counter() - service_started)*1000, 3)})
                if clients:
                    panel.refresh()
                return view()

        def view():
            return {'state': flow.state(), 'actions': list(events),
                    'error': last_error['code'], 'pending': action_lock.locked()}

        @ui.refreshable
        def panel():
            render_project_panel(ui, flow, act, native=args.mode == 'native', error=last_error['code'])

        @ui.page('/')
        def page():
            clients.append(ui.context.client)
            ui.label('RESEARCH-Y — trusted real-project feasibility').props('data-testid=title')
            ui.button('Open host-selected project', on_click=lambda: act('open')).props('data-testid=open')
            project_name = ui.input('New project name', value='New local project')
            ui.button('Create in host-selected parent',
                      on_click=lambda: act('create', project_name.value)).props('data-testid=create')
            if args.mode == 'native':
                ui.button('Choose project folder with Windows dialog',
                          on_click=lambda: act('native_open')).props('data-testid=native-open-folder')
                ui.button('Choose new-project parent folder with Windows dialog',
                          on_click=lambda: act('native_create', project_name.value)).props(
                              'data-testid=native-create-folder')
            else:
                ui.label('Native folder selection is available only in the desktop window.').props(
                    'data-testid=native-folder-unavailable')
            panel()

            async def refresh_running_verification():
                # Passive host polling is STRICTLY read-only. The sole source
                # network action remains the separate explicit Confirm button.
                # One timer per connected page, not per panel refresh.
                if not action_lock.locked():
                    if flow.state()['manifest_save_running']:
                        await act('manifest_poll')
                    elif flow.state()['wos_verification_pending']:
                        await act('wos_verification_poll')
                    elif flow.state()['pubmed_source_pending']:
                        await act('pubmed_identifier_poll')
                    elif flow.state()['pubmed_metadata_pending']:
                        await act('pubmed_metadata_poll')
                    elif flow.state()['run_coordination_pending']:
                        await act('run_coord_poll')

            ui.timer(2.0, refresh_running_verification)

        @app.get('/_probe/state')
        async def state():
            return view()

        @app.post('/_probe/start')
        async def step():
            nonlocal probe_step_count
            # For the dedicated test-only lost-reply scenario, an expected
            # failure does NOT enter the action success ledger. Advance the
            # fixed probe sequence separately; never replay the old consent.
            index = probe_step_count if args.scenario in WINDOW_SCENARIOS else len(events)
            if index >= len(sequence):
                return {'error': 'no_more_steps'}
            action = sequence[index]
            if args.scenario in WINDOW_SCENARIOS:
                probe_step_count += 1
            if action == 'recent_open':
                return await act(action, expected_project_id)
            if action == 'select_run':
                return await act(action, select_id)
            if action == 'select_export':
                return await act(action, expected_export)
            if action == 'manifest_preview':
                return await act(action, {'output_name': f'provenance-{select_id}.xlsx',
                                          'actor': 'Synthetic fixture researcher'})
            if action == 'manifest_confirm':
                return await act(action, flow.state()['manifest_offer']['offer_token'])
            if action == 'manifest_inspect':
                return await act(action, flow.state()['manifest_history']['entries'][0]['export_id'])
            if action in ('manifest_save', 'manifest_check_file'):
                result = await act(action, flow.state()['manifest_receipt']['export_id'])
                if action == 'manifest_save':
                    limit = time.monotonic() + 30
                    while flow.state()['manifest_save_running'] and time.monotonic() < limit:
                        await asyncio.to_thread(flow.poll_manifest_save)
                        await asyncio.sleep(.05)
                    return view()
                return result
            if action == 'publication_window_confirm':
                return await act(action, 'Synthetic fixture researcher')
            if args.scenario == 'publication_results_large':
                # Fixed test harness derives the next cursor and displayed
                # publication strictly from the currently verified host page.
                # HTTP callers provide NO identifiers, paths or query values.
                page = flow.state().get('publication_page')
                if action == 'publication_next' and page is not None:
                    return await act(action, {
                        'cursor': page['next_after_publication_id'],
                        'revision': page['revision']})
                if action == 'publication_detail' and page is not None and page['rows']:
                    return await act(action, {
                        'publication_id': page['rows'][0]['publication_id'],
                        'revision': page['revision']})
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

        async def native_window_probe():
            """Click actual finite-window buttons in a native Windows window."""
            await until(lambda: session.redeemed and clients and clients[-1].has_socket_connection)
            for index, action in enumerate(sequence):
                name = {'open': 'open', 'select_run': 'select-run',
                        'publication_window_offer': 'publication-window-offer',
                        'publication_window_confirm': 'publication-window-confirm',
                        'publication_window_inspect': (
                            'publication-window-reinspect'
                            if args.scenario == 'publication_window_lost_reply'
                            else 'publication-window-inspect')}[action]
                await until(lambda: not action_lock.locked())
                await until_native_button(name, js)
                if action == 'publication_window_confirm':
                    changed = await js(
                        "(function(){const host=document.querySelector("
                        "'[data-testid=publication-window-actor]');"
                        "const field=host&&(host.matches('input')?host:"
                        "host.querySelector('input'));"
                        "if(!field)return false;"
                        "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"
                        "'value').set.call(field,'Synthetic fixture researcher');"
                        "field.dispatchEvent(new Event('input',{bubbles:true}));"
                        "field.dispatchEvent(new Event('change',{bubbles:true}));"
                        "return true;})()")
                    if changed is not True:
                        raise RuntimeError('native_researcher_input_missing')
                    # Let Quasar propagate the actual input/change events
                    # to the NiceGUI host before clicking explicit CONFIRM.
                    await asyncio.sleep(.2)
                await js("document.querySelector('[data-testid=" + name + "]').click(); true")
                if (args.scenario == 'publication_window_lost_reply' and
                        action == 'publication_window_confirm'):
                    await until(
                        lambda: last_error['code'] ==
                            'publication_window_reinspect_required',
                        deadline=NATIVE_ACTION_COMPLETION_TIMEOUT)
                    await until_native_button('publication-window-recovery', js)
                    if (flow.state()['publication_window_last_outcome'] is not None or
                            not flow.state()['publication_window_reinspect_required']):
                        raise RuntimeError('native_uncertain_outcome_falsely_confirmed')
                    report['window_recovery_notice_verified'] = True
                else:
                    expected = index + 1 - int(
                        args.scenario == 'publication_window_lost_reply' and index >= 4)
                    if args.scenario == 'publication_window_lost_reply' and index >= 4:
                        # Previous expected error remains present until the
                        # new read-only inspection finishes. Do NOT allow that
                        # stale error to satisfy the completion predicate.
                        await until(lambda: len(events) >= expected,
                                    deadline=NATIVE_ACTION_COMPLETION_TIMEOUT)
                    else:
                        await until(lambda: len(events) >= expected or
                                    last_error['code'] is not None,
                                    deadline=NATIVE_ACTION_COMPLETION_TIMEOUT)
                    if last_error['code'] is not None:
                        raise RuntimeError('native_window_action_failed')
                    if action == 'publication_window_confirm':
                        await until_native_button('publication-window-outcome', js)
                    if action == 'publication_window_inspect':
                        await until_native_button('publication-window-inspection', js)
            state = flow.state()
            stored = state['publication_window_last_inspection']
            if (stored is None or
                    stored['unmaterialised_retrievals'] != expected_window_remaining or
                    stored['existing_publication_hypotheses'] != expected_window_provisional or
                    state['publication_window_offer'] is not None or
                    state['source_retrieval_verified'] is not False):
                raise RuntimeError('native_window_durable_evidence_invalid')
            if args.scenario == 'publication_window_lost_reply':
                if state['publication_window_last_outcome'] is not None:
                    raise RuntimeError('native_window_lost_reply_falsified_success')
            elif (state['publication_window_last_outcome'] is None or
                  state['publication_window_last_outcome']['materialised_in_session'] != 128):
                raise RuntimeError('native_window_receipt_missing')
            check = await js(
                "JSON.stringify({heading:!!document.querySelector("
                "'[data-testid=publication-window-heading]'),"
                "inspected:document.querySelector("
                "'[data-testid=publication-window-inspection]')?.textContent||'',"
                "injected:window.__researchy_injected===true})")
            if not check:
                raise RuntimeError('native_window_rendering_unavailable')
            shown = json.loads(check)
            if (not shown['heading'] or
                    ('remaining without publication identities: ' +
                     str(expected_window_remaining)) not in shown['inspected'] or
                    shown['injected']):
                raise RuntimeError('native_window_rendering_invalid')
            report['native_rendering_verified'] = True
            report['status'] = 'finished'

        async def native_results_probe():
            """Visit two genuine native 100k-project pages and one source detail."""
            await until(lambda: session.redeemed and clients and
                        clients[-1].has_socket_connection)
            names = {
                'open': 'open',
                'select_run': 'select-run',
                'publication_refresh': 'publication-refresh',
                'publication_next': 'publication-next',
                'publication_detail': 'publication-detail-open',
            }
            action_timings = []
            for index, action in enumerate(sequence):
                await until(lambda: not action_lock.locked())
                await until_native_button(names[action], js)
                t0 = time.monotonic()
                clicked = await js(
                    "document.querySelector('[data-testid=" +
                    names[action] + "]').click(); true")
                if clicked is not True:
                    raise RuntimeError('results_native_click_failed')
                await until(lambda: len(events) > index or
                            last_error['code'] is not None,
                            deadline=NATIVE_ACTION_COMPLETION_TIMEOUT)
                if (last_error['code'] is not None or events[index] != action):
                    raise RuntimeError('results_native_action_failed')
                action_timings.append(round((time.monotonic()-t0)*1000, 2))
                if action == 'publication_refresh':
                    await until_native_button('publication-next', js)
                if action == 'publication_detail':
                    await until_native_button('publication-detail-heading', js)
            current = flow.state()
            page = current['publication_page']
            detail = current['publication_detail']
            if (page is None or detail is None or
                    page['provisional_publication_identities'] != 100000 or
                    page['retrieved_source_records'] != 100000 or
                    page['unmaterialised_source_records'] != 0 or
                    page['global_unique_publications'] is not None or
                    page['deduplication_complete'] is not False or
                    page['verified_complete'] is not False or
                    len(page['rows']) != 20 or
                    not results_witness['detail_open'] or
                    len(results_witness['first_ids']) != 20 or
                    len(results_witness['second_ids']) != 20 or
                    not results_witness['first_ids'].isdisjoint(
                        results_witness['second_ids'])):
                raise RuntimeError('results_native_source_evidence_invalid')
            rendered = await js(
                "JSON.stringify({"
                "rows:document.querySelectorAll('[data-testid=publication-row]').length,"
                "counts:document.querySelector('[data-testid=publication-counts]')?.textContent||'',"
                "page:document.querySelector('[data-testid=publication-page-status]')?.textContent||'',"
                "heading:document.querySelector('[data-testid=publication-detail-heading]')?.textContent||'',"
                "source:document.querySelector('[data-testid=publication-source-detail]')?.textContent||'',"
                "incomplete:document.querySelector('[data-testid=incomplete]')?.textContent||'',"
                "injected:window.__researchy_injected===true})")
            if not rendered:
                raise RuntimeError('results_native_rendering_unavailable')
            visible = json.loads(rendered)
            if (visible['rows'] != 20 or
                    '100000' not in visible['counts'] or
                    'UNKNOWN' not in visible['counts'] or
                    'maximum 20' not in visible['page'] or
                    'LOCAL SOURCE PROVENANCE' not in visible['heading'] or
                    'rights' not in visible['source'] or
                    'INCOMPLETE' not in visible['incomplete'] or
                    visible['injected']):
                raise RuntimeError('results_native_rendering_invalid')
            report['native_results_action_ms'] = action_timings
            report['native_rendering_verified'] = True
            report['status'] = 'finished'

        async def native_probe():
            try:
                if args.scenario == 'publication_results_large':
                    await native_results_probe()
                    return
                if args.scenario in WINDOW_SCENARIOS:
                    await native_window_probe()
                    return
                await until(lambda: session.redeemed and clients and clients[-1].has_socket_connection)
                for index, action in enumerate(sequence):
                    name = {'open': 'open', 'recent_open': 'open-recent',
                            'select_run': 'select-run', 'select_export': 'select-export',
                            'prepare': 'prepare', 'resume': 'resume', 'cancel': 'cancel',
                            'observe': 'observe', 'manifest_preview': 'manifest-preview',
                            'manifest_confirm': 'manifest-confirm', 'manifest_history': 'manifest-history',
                            'manifest_inspect': 'manifest-inspect', 'manifest_save': 'manifest-save',
                            'manifest_check_file': 'manifest-check-file'}[action]
                    await until(lambda: bool(clients) and not action_lock.locked())
                    if action in ('manifest_preview', 'manifest_history'):
                        await until_native_button('manifest-panel', js)
                        await js("document.querySelector('[data-testid=manifest-panel] .q-item').click(); true")
                    if action == 'manifest_preview':
                        await until_native_button('manifest-actor', js)
                        await js("(()=>{const el=document.querySelector('[data-testid=manifest-actor] input, "
                                 "input[data-testid=manifest-actor]'); el.value='Synthetic fixture researcher'; "
                                 "el.dispatchEvent(new Event('input',{bubbles:true})); "
                                 "el.dispatchEvent(new Event('change',{bubbles:true})); return true})()")
                        await asyncio.sleep(.2)
                    await until_native_button(name, js)
                    await js("document.querySelector('[data-testid=" + name + "]').click(); true")
                    await until(lambda: len(events) > index or last_error['code'] is not None,
                                deadline=NATIVE_ACTION_COMPLETION_TIMEOUT)
                    if action == 'recent_open':
                        candidate = flow.state()
                        if (candidate['project'] is None or
                                candidate['project']['project_id'] != expected_project_id or
                                candidate['selected_run_id'] is not None or
                                candidate['selected_export_id'] is not None or
                                candidate['source_retrieval_verified']):
                            raise RuntimeError('native_recent_implicit_selection_or_wrong_identity')
                    if args.scenario == 'worker_killed' and action == 'resume':
                        if last_error['code'] != 'worker_interrupted' or len(events) != index:
                            raise RuntimeError('native_worker_death_not_observed')
                        current = flow.state()
                        if (current['selected_export_id'] != expected_export or
                                len(current['exports']) != 1 or
                                current['exports'][0]['recorded_state'] != 'staging' or
                                current['observation'] is not None or
                                current['source_retrieval_verified'] is not False):
                            raise RuntimeError('native_worker_death_false_success')
                        await until_native_button('operation-error', js)
                        await until_native_button('worker-recovery', js)
                        evidence = await js(
                            "JSON.stringify({error:document.querySelector('[data-testid=operation-error]').textContent,"
                            "recovery:document.querySelector('[data-testid=worker-recovery]').textContent,"
                            "injected:window.__researchy_injected===true})")
                        if not evidence:
                            raise RuntimeError('native_worker_error_not_rendered')
                        proof = json.loads(evidence)
                        if (not 'worker_interrupted' in proof['error'] or
                                'RECOVERY REQUIRED' not in proof['recovery'] or
                                proof['injected']):
                            raise RuntimeError('native_worker_recovery_notice_missing')
                        report['native_rendering_verified'] = True
                        report['status'] = 'finished'
                        return
                    if last_error['code'] is not None or events[index] != action:
                        raise RuntimeError('native_action_failed')
                    if action == 'manifest_save':
                        await until(lambda: not flow.state()['manifest_save_running'],
                                    deadline=NATIVE_ACTION_COMPLETION_TIMEOUT)
                if args.scenario in ('manifest_consent', 'manifest_reopen', 'manifest_publish'):
                    await until_native_button('manifest-receipt', js)
                    if not await js("document.querySelector('[data-testid=manifest-receipt]').textContent"
                                    ".includes('Current source revision')"):
                        raise RuntimeError('consent_receipt_missing')
                    if args.scenario == 'manifest_publish':
                        await until_native_button('manifest-file-verified', js)
                    report['native_rendering_verified'] = True
                    report['status'] = 'finished'
                    return
                await until(lambda: flow.state()['observation'] is not None)
                current = flow.state()
                expected_outcome = ('recorded_cancelled' if args.scenario in
                                    ('cancel', 'cancel_reopen') else
                                    'published_receipt_missing' if args.scenario == 'receipt_missing'
                                    else 'not_yet_staged' if args.scenario == 'render_fault'
                                    else 'retained_artifact_changed' if args.scenario == 'stage_fault'
                                    else 'published_verified')
                if (current['observation']['outcome'] != expected_outcome or
                        current['observation']['audited_success'] is not
                        (expected_outcome == 'published_verified')):
                    raise RuntimeError('native_not_verified')
                if args.scenario == 'receipt_missing':
                    await until_native_button('receipt-missing', js)
                if args.scenario in ('render_fault', 'stage_fault'):
                    await until_native_button('stage-recovery', js)
                    await until_native_button('export-error', js)
                check = await js("JSON.stringify({incomplete: document.querySelector('[data-testid=incomplete]').textContent,"
                                 "query: document.querySelector('[data-testid=exact-query]').textContent,"
                                 "retained: document.querySelector('[data-testid=retained-query]').textContent,"
                                 "receipt: Boolean(document.querySelector('[data-testid=receipt-missing]')),"
                                 "stage: Boolean(document.querySelector('[data-testid=stage-recovery]')),"
                                 "error: document.querySelector('[data-testid=export-error]')?.textContent || '',"
                                 "nativeOpen: Boolean(document.querySelector('[data-testid=native-open-folder]')),"
                                 "nativeCreate: Boolean(document.querySelector('[data-testid=native-create-folder]')),"
                                 "nativeExport: Boolean(document.querySelector('[data-testid=native-export-folder]')),"
                                 "injected: window.__researchy_injected === true})")
                if check is None:
                    raise RuntimeError('native_document_unavailable')
                data = json.loads(check)
                if ('INCOMPLETE' not in data['incomplete'] or 'Exact query:' not in data['query']
                        or 'Retained exact query:' not in data['retained'] or data['injected']
                        or data['receipt'] is not (args.scenario == 'receipt_missing')
                        or data['stage'] is not
                            (args.scenario in ('render_fault', 'stage_fault'))
                        or (args.scenario == 'render_fault'
                            and 'render_failed' not in data['error'])
                        or (args.scenario == 'stage_fault'
                            and 'storage_failed' not in data['error'])
                        or not data['nativeOpen'] or not data['nativeCreate']
                        or not data['nativeExport']):
                    raise RuntimeError('native_rendering_invalid')
                report['native_rendering_verified'] = True
                report['status'] = 'finished'
            except Exception as exc:
                report['status'] = 'failed'
                # The native fixture may return ONLY a fixed diagnostic code
                # owned by this test harness. Never pass exception text that
                # could contain a project path, source title or access token.
                allowed = {
                    'native_action_timeout',
                    'native_researcher_input_missing',
                    'native_window_action_failed',
                    'native_uncertain_outcome_falsely_confirmed',
                    'native_window_durable_evidence_invalid',
                    'native_window_lost_reply_falsified_success',
                    'native_window_receipt_missing',
                    'native_window_rendering_unavailable',
                    'native_window_rendering_invalid',
                    'native_button_unavailable',
                    'results_native_click_failed',
                    'results_native_action_failed',
                    'results_native_source_evidence_invalid',
                    'results_native_rendering_unavailable',
                    'results_native_rendering_invalid',
                    'results_first_page_invalid',
                    'results_second_page_invalid',
                    'results_page_overlap',
                    'results_detail_invalid',
                }
                reason = str(exc) if type(exc) is RuntimeError else ''
                report['error'] = reason if (
                    (args.scenario in WINDOW_SCENARIOS or
                     args.scenario == 'publication_results_large') and
                    reason in allowed
                ) else type(exc).__name__
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
                manifest_file_verified=bool((state['manifest_save_result'] or {}).get('audited_publication_success')),
                consent_event_id=(state['manifest_receipt'] or {}).get('audit_event_id'),
                results_action_service_ms=(
                    list(results_witness['action_service_ms'])
                    if args.scenario == 'publication_results_large' else None),
                results_page_rows=(
                    None if state['publication_page'] is None else
                    len(state['publication_page']['rows'])),
                results_provisional_count=(
                    None if state['publication_page'] is None else
                    state['publication_page']['provisional_publication_identities']),
                results_unmaterialised=(
                    None if state['publication_page'] is None else
                    state['publication_page']['unmaterialised_source_records']),
                results_detail_open=bool(
                    results_witness['detail_open'] and
                    state['publication_detail'] is not None),
                results_paging_verified=bool(
                    results_witness['first_ids'] is not None and
                    results_witness['second_ids'] is not None and
                    len(results_witness['first_ids']) == 20 and
                    len(results_witness['second_ids']) == 20 and
                    results_witness['first_ids'].isdisjoint(
                        results_witness['second_ids'])),
                window_remaining=(
                    None if state['publication_window_last_inspection'] is None
                    else state['publication_window_last_inspection']['unmaterialised_retrievals']),
                window_confirmed=bool(state['publication_window_last_outcome'] is not None),
                window_uncertain_error_observed=window_uncertain_error_observed,
                window_recovery_required=state['publication_window_reinspect_required'],
                status=('finished' if args.mode == 'transport' and
                        (not last_error['code'] or
                         (args.scenario == 'worker_killed' and
                          last_error['code'] == 'worker_interrupted'))
                        else report['status']),
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
    parser.add_argument('--scenario', choices=('publish', 'reopen', 'cancel', 'cancel_reopen',
                                               'receipt_missing', 'receipt_recovered',
                                               'render_fault', 'render_recovered',
                                               'stage_fault', 'stage_recovered',
                                               'worker_killed', 'worker_recovered',
                                               'recent_open',
                                               'manifest_consent', 'manifest_reopen', 'manifest_publish',
                                               'publication_window',
                                               'publication_window_lost_reply',
                                               'publication_results_large'), required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
