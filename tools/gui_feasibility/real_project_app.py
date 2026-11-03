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
from tools.gui_feasibility.native_folder_selection import NativeFolderError, select_from_native_window

LITERAL_NAME = '<img src=x onerror="window.__researchy_injected=true">'

# One UI action may execute three bounded, sequential 35-second worker calls.
# Keep short readiness checks separate from the longer action-completion wait.
NATIVE_ACTION_COMPLETION_TIMEOUT = 115


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
        flow = RealProjectFlow(selected_root=root, selected_parent=parent,
                               recent_parent=recents_parent)
        os.environ['RESEARCHY_PROTOTYPE_ALLOWED_ORIGIN'] = session.origin
        os.environ['RESEARCHY_PROTOTYPE_MARKER_DIR'] = str(args.directory)
        events, clients, tasks = [], [], []
        last_error = {'code': None}
        finished = asyncio.Event()
        sequence = (('open', 'select_run', 'prepare', 'prepare', 'resume', 'observe')
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
        select_id = os.environ.pop('RESEARCHY_GUI_EXPECTED_RUN_ID')
        expected_project_id = os.environ.pop('RESEARCHY_GUI_EXPECTED_PROJECT_ID', '')
        expected_export = os.environ.pop('RESEARCHY_GUI_EXPECTED_EXPORT_ID', '')

        async def act(name, value=None):
            async with action_lock:
                try:
                    def perform():
                        if name == 'open':
                            return flow.open_selected()
                        if name == 'recent_open':
                            return flow.open_recent(value)
                        if name == 'recent_refresh':
                            return flow.refresh_recents()
                        if name == 'create':
                            return flow.create_selected(value)
                        if name == 'setup_edit':
                            if type(value) is not dict or set(value) != {'action', 'data'}:
                                raise ProjectFlowError('invalid_setup_action')
                            return flow.edit_setup(value['action'], value['data'])
                        if name == 'setup_preview':
                            return flow.preview_setup()
                        if name == 'setup_approve':
                            # An explicit researcher click is the only route
                            # to this approval operation. Never during typing
                            # or automatically after compiling a preview.
                            return flow.approve_setup()
                        if name == 'select_run':
                            return flow.select_run(value)
                        if name == 'select_export':
                            return flow.select_export(value)
                        if name == 'prepare':
                            return flow.prepare()
                        if name == 'external_confirm':
                            return flow.confirm_external_directory()
                        if name == 'external_clear':
                            return flow.clear_external_directory()
                        if name == 'resume':
                            return flow.resume()
                        if name == 'cancel':
                            return flow.cancel()
                        if name == 'observe':
                            return flow.observe()
                        raise ProjectFlowError('unsupported_action')
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
                        events.append(name)
                    last_error['code'] = None
                except NativeFolderError as exc:
                    last_error['code'] = str(exc)
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
            ui.label('Recent Projects (explicit selection; locations verified on open).').props(
                'data-testid=recent-heading')
            if state['recent_history_error']:
                ui.label('Recent project history is unavailable; select a folder to open.').props(
                    'data-testid=recent-history-error')
            elif not state['recent_projects']:
                ui.label('No recent projects recorded.').props('data-testid=recent-empty')
            else:
                for entry in state['recent_projects']:
                    project_id = entry['project_id']
                    ui.button('Open recent: ' + entry['name'] + ' — ' + entry['location'],
                              on_click=lambda project_id=project_id: act(
                                  'recent_open', project_id)).props('data-testid=open-recent')
            ui.button('Refresh recent projects',
                      on_click=lambda: act('recent_refresh')).props(
                          'data-testid=refresh-recents')
            if project is None:
                ui.label('No project open. A host-selected location is required.')
            else:
                ui.label('Project: ' + project['name']).props('data-testid=project-name')
                ui.label('Location: ' + project['location']).props('data-testid=project-location')
                # The source text enters only NiceGUI text widgets, not HTML.
                # All draft edits are host-memory mutations. A new preview is
                # mandatory after any edit, before the separate approval click.
                draft = state['strategy_draft']
                ui.separator()
                ui.label('Research Setup — draft only until explicitly approved').props(
                    'data-testid=setup-heading')
                ui.label('OR between all enabled terms AND NO hidden restrictions; '
                         'the group union is also OR. No provider has been queried.').props(
                             'data-testid=setup-broad-or')
                ui.label('Objectives, society sources, pilot counts, PRESS and '
                         'provider execution are not yet enabled in this prototype.')
                if state['strategy_reconciliation_required']:
                    ui.label('Approval outcome uncertain — retry the original request '
                             'unchanged to reconcile the saved run and query plans.').props(
                                 'data-testid=setup-recovery')
                    ui.button('Retry original strategy approval',
                              on_click=lambda: act('setup_approve')).props(
                                  'data-testid=setup-approval-retry')
                else:
                    if draft['preview'] is None:
                        theme_input = ui.input('Research theme', value=draft['theme']).props(
                            'data-testid=setup-theme')
                        approver_input = ui.input('Researcher approving', value=draft['approved_by']).props(
                            'data-testid=setup-approver')
                        ui.button('Save research heading',
                                  on_click=lambda: act('setup_edit', dict(
                                      action='heading', data=dict(
                                          theme=theme_input.value,
                                          approved_by=approver_input.value)))).props(
                                              'data-testid=setup-save-heading')
                        new_group = ui.input('New concept group name').props('data-testid=setup-group-input')
                        ui.button('Add concept group', on_click=lambda: act('setup_edit', dict(
                            action='add_group', data=dict(label=new_group.value)))).props(
                                'data-testid=setup-add-group')
                        for group in draft['groups']:
                            gid = group['group_id']
                            with ui.card():
                                label_input = ui.input('Group name', value=group['label'])
                                ui.button('Rename group', on_click=lambda gid=gid, box=label_input:
                                          act('setup_edit', dict(
                                              action='rename_group',
                                              data=dict(group_id=gid, label=box.value)))).props(
                                                  'data-testid=setup-rename-group')
                                ui.button('Move group up', on_click=lambda gid=gid:
                                          act('setup_edit', dict(action='move_group',
                                              data=dict(group_id=gid, direction=-1))))
                                ui.button('Move group down', on_click=lambda gid=gid:
                                          act('setup_edit', dict(action='move_group',
                                              data=dict(group_id=gid, direction=1))))
                                ui.button('Remove group', on_click=lambda gid=gid:
                                          act('setup_edit', dict(action='remove_group',
                                              data=dict(group_id=gid)))).props('data-testid=setup-remove-group')
                                new_term = ui.input('New atomic term (single literal)')
                                ui.button('Add researcher term', on_click=lambda gid=gid, box=new_term:
                                          act('setup_edit', dict(action='add_term',
                                              data=dict(group_id=gid, text=box.value)))).props(
                                                  'data-testid=setup-add-term')
                                for term in group['terms']:
                                    tid = term['term_id']
                                    with ui.card():
                                        term_input = ui.input('Atomic term', value=term['text'])
                                        origin_input = ui.select(
                                            {'researcher': 'Researcher', 'deterministic': 'Deterministic',
                                             'ai': 'AI-assisted (requires rationale)'},
                                            value=term['origin'], label='Term provenance')
                                        rationale_input = ui.input(
                                            'Origin rationale / notes', value=term['rationale'])
                                        enabled_input = ui.checkbox('Include term in OR union',
                                                                    value=term['enabled'])
                                        ui.button('Save term changes', on_click=lambda
                                                  gid=gid, tid=tid, box=term_input,
                                                  origin=origin_input, note=rationale_input,
                                                  enabled=enabled_input:
                                                  act('setup_edit', dict(action='edit_term',
                                                      data=dict(group_id=gid, term_id=tid,
                                                                text=box.value, origin=origin.value,
                                                                rationale=note.value,
                                                                enabled=enabled.value)))).props(
                                                                    'data-testid=setup-save-term')
                                        ui.button('Move term up', on_click=lambda gid=gid, tid=tid:
                                                  act('setup_edit', dict(action='move_term',
                                                      data=dict(group_id=gid, term_id=tid,
                                                                direction=-1))))
                                        ui.button('Move term down', on_click=lambda gid=gid, tid=tid:
                                                  act('setup_edit', dict(action='move_term',
                                                      data=dict(group_id=gid, term_id=tid,
                                                                direction=1))))
                                        ui.button('Remove term', on_click=lambda gid=gid, tid=tid:
                                                  act('setup_edit', dict(action='remove_term',
                                                      data=dict(group_id=gid, term_id=tid)))).props(
                                                          'data-testid=setup-remove-term')
                        ui.button('Preview exact broad-OR source queries',
                                  on_click=lambda: act('setup_preview')).props(
                                      'data-testid=setup-preview')
                    else:
                        ui.label('Exact-query preview is locked. To change any field, '
                                 'choose Revise draft and preview again.').props(
                                     'data-testid=setup-preview-locked')
                        ui.button('Revise draft before approval',
                                  on_click=lambda: act('setup_edit', dict(
                                      action='revise_preview', data={}))).props(
                                          'data-testid=setup-revise')
                        preview = draft['preview']
                        if preview is not None:
                            ui.label('Strategy preview — NOT EXECUTED').props(
                                'data-testid=setup-preview-active')
                            ui.label('Concept groups: ' + str(preview['group_count']) +
                                     '; enabled terms: ' + str(preview['active_term_count']))
                            ui.label('Filters/limits: ' + preview['limitations'])
                            for source in preview['sources']:
                                ui.label('Source: ' + source['name'] + ' — ' +
                                         source['coverage']).props('data-testid=setup-source-coverage')
                                ui.label('OR union preview: ' + source['union_query'])
                                for query in source['groups']:
                                    if query['exact_query'] is not None:
                                        ui.label('Group ' + query['label'] + ' exact query: ' +
                                                 query['exact_query']).props(
                                                     'data-testid=setup-exact-query')
                                    else:
                                        ui.label('Group ' + query['label'] +
                                                 ' disabled/empty — not executable.')
                                for warning in source['warnings']:
                                    ui.label('Compiler warning: ' + warning)
                            ui.label('Provider matches: UNKNOWN (not queried).').props(
                                'data-testid=setup-unknown-counts')
                            ui.button('Approve frozen strategy and create pending run',
                                      on_click=lambda: act('setup_approve')).props(
                                          'data-testid=setup-approve')
                if state['last_strategy_admission'] is not None:
                    done = state['last_strategy_admission']
                    ui.label('Strategy version ' + str(done['version_number']) +
                             ' stored; pending run ' + done['run_id'] +
                             '. Queries planned but NOT EXECUTED.').props(
                                 'data-testid=setup-approval-result')
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
                    if args.mode == 'native':
                        ui.button('Choose external workbook folder with Windows dialog',
                                  on_click=lambda: act('native_export')).props(
                                      'data-testid=native-export-folder')
                    else:
                        ui.label('External folder selection requires the desktop window.').props(
                            'data-testid=external-folder-unavailable')
                    if state['external_destination_candidate'] is not None:
                        ui.label('Proposed external folder: ' +
                                 state['external_destination_candidate']).props(
                                     'data-testid=external-candidate')
                        ui.button('Confirm this external destination',
                                  on_click=lambda: act('external_confirm')).props(
                                      'data-testid=confirm-external-folder')
                    if state['external_destination_confirmed']:
                        ui.label('Confirmed external destination: ' +
                                 state['external_destination_location']).props(
                                     'data-testid=external-confirmed')
                    if (state['external_destination_candidate'] is not None or
                            state['external_destination_confirmed']):
                        ui.button('Clear external folder selection',
                                  on_click=lambda: act('external_clear')).props(
                                      'data-testid=clear-external-folder')
                    ui.label('Default workbook: strategy-summary-' +
                             state['selected_run_id'] + '.xlsx')
                    ui.button('Prepare strategy workbook',
                              on_click=lambda: act('prepare')).props('data-testid=prepare')
                if state['export_reconciliation_required']:
                    ui.label('Export journal or inventory needs reconciliation. Retry Prepare '
                             'with the original request ID; do not start another export.').props(
                                 'data-testid=recovery-required')
                if state['selected_export_id'] is not None:
                    saved = next((item for item in state['exports']
                                  if item['export_id'] == state['selected_export_id']), None)
                    if saved is None:
                        ui.label('Export inventory unavailable — reinspection required.').props('data-testid=export-missing')
                    else:
                        ui.label('Recorded export phase: ' + saved['recorded_state']).props('data-testid=export-phase')
                        ui.label('Recorded destination: ' + saved['destination_kind']).props(
                            'data-testid=destination-kind')
                        if (saved['destination_kind'] == 'external' and
                                not state['external_destination_confirmed']):
                            ui.label('EXTERNAL DESTINATION CONFIRMATION REQUIRED — '
                                     'choose the original folder again; the path '
                                     'is never stored in the project.').props(
                                         'data-testid=external-reconfirm')
                        if saved['last_error'] is not None:
                            ui.label('Recorded export error: ' + saved['last_error']).props('data-testid=export-error')
                        if saved['recorded_state'] not in ('cancelled', 'published'):
                            ui.button('Cancel pending export', on_click=lambda: act('cancel')).props('data-testid=cancel')
                        if saved['recorded_state'] != 'cancelled':
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
                    if observed['outcome'] == 'destination_confirmation_required':
                        ui.label('EXTERNAL DESTINATION CONFIRMATION REQUIRED — '
                                 'the output cannot be verified without reselecting '
                                 'its original folder.').props('data-testid=external-observe')
                    if observed['outcome'] == 'published_receipt_missing':
                        ui.label('RECOVERY REQUIRED — the workbook is visible, but the '
                                 'final audited publication receipt is missing. '
                                 'This is not verified. Resume the existing export '
                                 'request to reconcile its original file.').props(
                                     'data-testid=receipt-missing')
                    if observed['outcome'] in ('not_yet_staged', 'retained_artifact_changed'):
                        ui.label('RECOVERY REQUIRED — rendering or staging did not '
                                 'produce a verified workbook. The original request '
                                 'and retained evidence remain available. Repair the '
                                 'failure and resume the same export; this observation '
                                 'is not success.').props('data-testid=stage-recovery')
            if last_error['code']:
                ui.label('Operation error: ' + last_error['code']).props('data-testid=operation-error')
                if (last_error['code'] == 'worker_interrupted' and
                        state['selected_export_id'] is not None):
                    ui.label('RECOVERY REQUIRED — the supervised export worker was '
                             'interrupted. No successful workbook is verified. '
                             'Reopen this saved request and inspect its durable '
                             'phase before retrying; do not start a new export.').props(
                                 'data-testid=worker-recovery')

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

        @app.get('/_probe/state')
        async def state():
            return view()

        @app.post('/_probe/start')
        async def step():
            index = len(events)
            if index >= len(sequence):
                return {'error': 'no_more_steps'}
            action = sequence[index]
            if action == 'recent_open':
                return await act(action, expected_project_id)
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
                    name = {'open': 'open', 'recent_open': 'open-recent',
                            'select_run': 'select-run', 'select_export': 'select-export',
                            'prepare': 'prepare', 'resume': 'resume', 'cancel': 'cancel',
                            'observe': 'observe'}[action]
                    await until(lambda: bool(clients) and not action_lock.locked())
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
                                               'recent_open'), required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
