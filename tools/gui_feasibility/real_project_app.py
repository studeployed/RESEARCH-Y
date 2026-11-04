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
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.wos_host_profile import WoSHostProfile
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
        # The host removes the optional prototype-only contact/key settings
        # from the environment before constructing any browser session.
        # No browser control or HTTP route can supply credentials.
        pubmed_profile = PubMedHostProfile.from_prototype_environment()
        wos_profile = WoSHostProfile.from_prototype_environment()
        flow = RealProjectFlow(selected_root=root, selected_parent=parent,
                               recent_parent=recents_parent,
                               pubmed_profile=pubmed_profile,
                               wos_profile=wos_profile)
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
                        if name == 'preflight_inspect':
                            return flow.inspect_preflight()
                        if name == 'preflight_offer':
                            if type(value) is not dict:
                                raise ProjectFlowError('preflight_review_invalid')
                            return flow.offer_preflight_review(**value)
                        if name == 'preflight_revise':
                            return flow.revise_preflight_review()
                        if name == 'preflight_record':
                            return flow.record_preflight_review()
                        if name == 'pubmed_pilot_offer':
                            return flow.offer_pubmed_pilot(value)
                        if name == 'pubmed_pilot_revise':
                            return flow.revise_pubmed_pilot()
                        if name == 'pubmed_pilot_confirm':
                            # This is the *only* action that may send a count
                            # request. A separate frozen-query offer is required.
                            return flow.confirm_pubmed_pilot()
                        if name == 'pubmed_pilot_reconcile':
                            # Read-only journal inspection; NEVER resend.
                            return flow.reconcile_pubmed_pilot()
                        if name == 'wos_pilot_offer':
                            return flow.offer_wos_pilot(value)
                        if name == 'wos_pilot_revalidation_offer':
                            return flow.offer_wos_pilot(value, revalidate_quota=True)
                        if name == 'wos_pilot_revise':
                            return flow.revise_wos_pilot()
                        if name == 'wos_pilot_confirm':
                            # Only a separate confirmed click may send Starter GET.
                            return flow.confirm_wos_pilot()
                        if name == 'wos_pilot_reconcile':
                            # No network; read original UUID's immutable journal.
                            return flow.reconcile_wos_pilot()
                        if name == 'pilot_history_refresh':
                            # Read-only; never reconstruct or resend a pilot.
                            return flow.inspect_pilot_history()
                        if name == 'pilot_history_older':
                            return flow.inspect_pilot_history(before_event_id=value)
                        if name == 'pilot_history_detail':
                            return flow.inspect_saved_pilot(value)
                        if name == 'wos_acquisition_offer':
                            return flow.offer_wos_acquisition(value)
                        if name == 'wos_acquisition_dismiss':
                            return flow.dismiss_wos_acquisition()
                        if name == 'wos_acquisition_prepare':
                            # No provider request: explicit retention consent only.
                            return flow.confirm_wos_acquisition()
                        if name == 'wos_acquisition_prepare_reconcile':
                            return flow.reconcile_wos_acquisition()
                        if name == 'wos_acquisition_read':
                            return flow.inspect_stored_wos_acquisition(value)
                        if name == 'wos_acquisition_tick_offer':
                            return flow.offer_wos_acquisition_tick()
                        if name == 'wos_acquisition_revalidate_offer':
                            return flow.offer_wos_acquisition_tick(revalidate_quota=True)
                        if name == 'wos_acquisition_tick_dismiss':
                            return flow.dismiss_wos_acquisition_tick()
                        if name == 'wos_acquisition_tick_confirm':
                            # Only explicit separate consent authorises HTTPS.
                            return flow.confirm_wos_acquisition_tick()
                        if name == 'wos_acquisition_tick_reconcile':
                            # Read-only checkpoint inspection; NEVER resend.
                            return flow.reconcile_wos_acquisition_tick()
                        if name == 'wos_verification_offer':
                            return flow.offer_wos_verification()
                        if name == 'wos_verification_revalidate_offer':
                            return flow.offer_wos_verification(revalidate_quota=True)
                        if name == 'wos_verification_dismiss':
                            return flow.dismiss_wos_verification()
                        if name == 'wos_verification_confirm':
                            # ONLY a separate explicit click authorises transport.
                            # The separate worker starts without blocking the GUI.
                            return flow.confirm_wos_verification()
                        if name == 'wos_verification_poll':
                            # Read-only supervisor + durable original checkpoint.
                            return flow.poll_wos_verification()
                        if name == 'wos_verification_pause':
                            # Explicit cooperative pause, NEVER network initiation.
                            return flow.pause_wos_verification()
                        if name == 'wos_verification_reconcile':
                            # Terminal child evidence AND durable source receipt.
                            return flow.reconcile_wos_verification()
                        if name == 'pubmed_identifier_read':
                            return flow.inspect_stored_pubmed_source(value)
                        if name == 'pubmed_identifier_offer':
                            if type(value) is not dict or set(value) != {
                                    'query_id','coverage_start','coverage_end'}:
                                raise ProjectFlowError('pubmed_coverage_invalid')
                            return flow.offer_pubmed_source(**value)
                        if name == 'pubmed_identifier_dismiss':
                            return flow.dismiss_pubmed_source()
                        if name == 'pubmed_identifier_confirm':
                            # Only explicit separate confirmation starts ESearch.
                            return flow.confirm_pubmed_source()
                        if name == 'pubmed_identifier_poll':
                            # No PubMed request; original disk checkpoint only.
                            return flow.poll_pubmed_source()
                        if name == 'pubmed_identifier_pause':
                            return flow.pause_pubmed_source()
                        if name == 'pubmed_identifier_reconcile':
                            return flow.reconcile_pubmed_source()
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
                ui.separator()
                ui.label('Saved source-pilot audit history — read-only, including '
                         'earlier sessions and runs. Not verified source retrieval.').props(
                             'data-testid=pilot-history-heading')
                ui.button('Refresh saved pilot history (no network)',
                          on_click=lambda: act('pilot_history_refresh')).props(
                              'data-testid=pilot-history-refresh')
                history = state['pilot_history']
                if state['pilot_history_error'] is not None:
                    ui.label('Pilot audit could NOT be verified. Historical '
                             'attempts may exist; do not assume zero prior '
                             'requests. No provider call was made.').props(
                                 'data-testid=pilot-history-error')
                elif history is None:
                    ui.label('Pilot history not yet inspected; previous attempts '
                             'may exist.').props('data-testid=pilot-history-unread')
                else:
                    ui.label('Total saved request EVENTS (not publication '
                             'matches): ' + str(history['request_events_total']) +
                             '; newest ' + str(len(history['entries'])) +
                             ' on this page.').props('data-testid=pilot-history-total')
                    if not history['entries']:
                        ui.label('No pilot requests on this page.').props(
                            'data-testid=pilot-history-empty')
                    for row in history['entries']:
                        ui.label(
                            row['source'] + ' • ' + row['requested_at_utc'] +
                            ' • run ' + row['run_id'] + ' • status ' + row['status'] +
                            ' • provisional matches ' +
                            ('UNKNOWN' if row['reported_matches'] is None
                             else str(row['reported_matches']))).props(
                                 'data-testid=pilot-history-entry')
                        if row['status']=='requested_indeterminate':
                            ui.label('OUTCOME UNKNOWN: request may have reached '
                                     'the provider. Do NOT automatically retry. '
                                     'Starter quota may remain blocked until '
                                     'separately authorised recovery.').props(
                                         'data-testid=pilot-history-indeterminate')
                        pid = row['pilot_id']
                        ui.button('Inspect original saved receipt ' + pid,
                                  on_click=lambda pid=pid: act(
                                      'pilot_history_detail', pid)).props(
                                          'data-testid=pilot-history-detail')
                    if history['next_before_event_id'] is not None:
                        older = history['next_before_event_id']
                        ui.label('Older requests not displayed on this page; '
                                 'absence of an entry here is not proof that '
                                 'a prior attempt never occurred.')
                        ui.button('Inspect older pilot requests (no network)',
                                  on_click=lambda older=older: act(
                                      'pilot_history_older', older)).props(
                                          'data-testid=pilot-history-older')
                    detail = state['saved_pilot_detail']
                    if detail is not None:
                        ui.label('Selected ORIGINAL audited receipt: ' +
                                 detail['pilot_id'] + ' — ' + detail['status']).props(
                                     'data-testid=pilot-history-selected')
                        ui.label('Original exact source query: ' +
                                 detail['exact_query']).props(
                                     'data-testid=pilot-history-query')
                        ui.label('Pilot-only reported matches: ' +
                                 ('UNKNOWN' if detail['reported_matches'] is None
                                  else str(detail['reported_matches'])) +
                                 '; search execution remains unverified.').props(
                                     'data-testid=pilot-history-provisional')
                        if detail.get('accepted_translation') is not None:
                            ui.label('Source translation: ' +
                                     detail['accepted_translation'])
                        if detail.get('quota_status') is not None:
                            ui.label('Observed provider quota status: ' +
                                     detail['quota_status'])
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
                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('Pre-run verification — no source searches are executed.').props(
                        'data-testid=preflight-heading')
                    if not state['preflight_review_reconciliation_required']:
                        ui.button('Verify saved exact source plan',
                                  on_click=lambda: act('preflight_inspect')).props(
                                      'data-testid=preflight-inspect')
                    preview = state['preflight_report']
                    if preview is None:
                        ui.label('The approved source plan has not yet been verified '
                                 'in this session. No PRESS review is recorded here.')
                    else:
                        ui.label('Validated frozen plan SHA-256: ' +
                                 preview['plan_sha256']).props('data-testid=preflight-hash')
                        ui.label('Strategy version: ' + str(preview['version_number']) +
                                 '; concept groups: ' + str(preview['group_count']) +
                                 '; active terms: ' + str(preview['active_term_count']))
                        ui.label('Boolean logic: OR across terms and groups; '
                                 'no automatic exclusions.')
                        ui.label('Recorded limits: ' + preview['limitations'])
                        ui.label('Provider counts: UNKNOWN; workload estimate: UNKNOWN '
                                 '(no pilot counts obtained).').props('data-testid=preflight-unknown')
                        ui.label('Automated compiler checks are not independent PRESS peer review. '
                                 'Known-relevant records and PubMed translation have NOT been checked.')
                        for group in preview['groups']:
                            ui.label('Approved concept group: ' + group['label']).props(
                                'data-testid=preflight-group')
                            for term in group['terms']:
                                ui.label('Atomic term: ' + term['text'] + ' | origin: ' +
                                         term['origin'] + ' | ' +
                                         ('active' if term['enabled'] else 'disabled') +
                                         ' | rationale: ' + term['rationale']).props(
                                             'data-testid=preflight-term')
                        for source in preview['sources']:
                            ui.label('Source coverage: ' + source['source_name'] +
                                     ' — ' + source['source_coverage']).props(
                                         'data-testid=preflight-coverage')
                            for query in source['queries']:
                                ui.label('Exact stored query (' + query['group_id'] + '): ' +
                                         query['exact_query']).props(
                                             'data-testid=preflight-query')
                            for warning in source['warnings']:
                                ui.label('Compiler warning: ' + warning)
                        for warning in preview['warnings']:
                            ui.label('Pre-run warning: ' + warning)
                        previous = preview['last_review']
                        if previous is not None:
                            ui.label('Last recorded PRESS checklist: ' +
                                     previous['occurred_at_utc'] + ' — ' +
                                     previous['reviewer_name'] + ' (' +
                                     previous['reviewer_role'] + ', self-reported).').props(
                                         'data-testid=preflight-last-review')
                            ui.label('No independent review has been verified, '
                                     'and no search execution is authorised by this receipt.')
                            for item, result in previous['press_items'].items():
                                ui.label('PRESS ' + item + ': ' + result)
                            if previous['known_relevant']:
                                ui.label('Known-relevant items: provided, NOT tested '
                                         'against a search provider.')
                        candidate = state['preflight_candidate']
                        if state['preflight_review_reconciliation_required']:
                            ui.label('Review outcome uncertain: retry the exact same '
                                     'review request to reconcile the audit journal.').props(
                                         'data-testid=preflight-retry-required')
                            ui.button('Retry original pre-run review',
                                      on_click=lambda: act('preflight_record')).props(
                                          'data-testid=preflight-retry')
                        elif candidate is None:
                            ui.label('PRESS checklist — researcher observations. '
                                     'Not reviewed / Needs revision do not imply a pass.')
                            reviewer = ui.input('Reviewing researcher', value='').props(
                                'data-testid=preflight-reviewer')
                            reviewer_role = ui.select({
                                'researcher_self_check': 'Researcher self-check',
                                'independent_peer_reported':
                                    'External peer review (user-reported, not verified)'},
                                value='researcher_self_check', label='Review role')
                            press = {}
                            for item in preview['press_items']:
                                press[item] = ui.select({
                                    'not_reviewed': 'Not reviewed',
                                    'reviewed': 'Reviewed by named person',
                                    'needs_revision': 'Needs revision'},
                                    value='not_reviewed', label='PRESS: ' + item).props(
                                        'data-testid=preflight-press-item')
                            note = ui.textarea('Review notes, concerns, or limitations')
                            known = ui.textarea(
                                'Known-relevant record identifiers (one per line; '
                                'will NOT be checked against provider records)')
                            ui.button('Review and lock these checklist answers',
                                      on_click=lambda: act('preflight_offer', dict(
                                          reviewer_name=reviewer.value,
                                          reviewer_role=reviewer_role.value,
                                          press_items={key:box.value
                                                       for key, box in press.items()},
                                          review_note=note.value or '',
                                          known_relevant=tuple(
                                              line.strip() for line in (known.value or '').splitlines()
                                              if line.strip())))).props(
                                                  'data-testid=preflight-offer')
                        else:
                            ui.label('Review answers locked — check before recording.').props(
                                'data-testid=preflight-confirmation')
                            ui.label('Reviewer: ' + candidate['reviewer_name'] +
                                     '; role: ' + candidate['reviewer_role'])
                            for item, value in candidate['press_items'].items():
                                ui.label('PRESS ' + item + ': ' + value)
                            ui.label('Note: ' + candidate['review_note'])
                            if candidate['known_relevant']:
                                ui.label('Known-relevant items: ' +
                                         str(len(candidate['known_relevant'])) +
                                         ', not tested against provider.')
                            ui.button('Revise checklist before recording',
                                      on_click=lambda: act('preflight_revise')).props(
                                          'data-testid=preflight-revise')
                            ui.button('Confirm and record pre-run checklist',
                                      on_click=lambda: act('preflight_record')).props(
                                          'data-testid=preflight-record')
                if (state['selected_run_id'] is not None and
                        state['preflight_report'] is not None):
                    ui.separator()
                    ui.label('PubMed pilot counts — optional single-query '
                             'ESearch requests; NOT a literature retrieval.').props(
                                 'data-testid=pubmed-pilot-heading')
                    ui.label('All source-run counts remain UNKNOWN until the '
                             'real retrieval pipeline verifies them. A pilot '
                             'count is not a final count and is never added '
                             'across overlapping concept groups.')
                    if not state['pubmed_profile_configured']:
                        ui.label('Pilot unavailable: no host-configured NCBI '
                                 'contact email. The API key/contact cannot '
                                 'be supplied by browser controls.').props(
                                     'data-testid=pubmed-profile-unavailable')
                    elif state['pubmed_pilot_reconciliation_required']:
                        ui.label('Pilot outcome uncertain — read original '
                                 'audit attempt. NEVER repeat the provider '
                                 'request automatically.').props(
                                     'data-testid=pubmed-pilot-uncertain')
                        ui.button('Inspect original pilot receipt (no network)',
                                  on_click=lambda: act('pubmed_pilot_reconcile')).props(
                                      'data-testid=pubmed-pilot-reconcile')
                    elif state['wos_pilot_reconciliation_required']:
                        ui.label('Resolve the Web of Science pilot receipt before '
                                 'starting a PubMed pilot.')
                    elif state['pubmed_pilot_candidate'] is not None:
                        candidate = state['pubmed_pilot_candidate']
                        ui.label('Unsent, locked pilot candidate for group ' +
                                 candidate['group_id']).props(
                                     'data-testid=pubmed-pilot-candidate')
                        ui.label('Exact query: ' + candidate['exact_query']).props(
                            'data-testid=pubmed-pilot-query')
                        ui.label('This confirmation will make ONE count-only '
                                 'HTTPS request to the official PubMed ESearch '
                                 'service. No identifiers/metadata will be retrieved. '
                                 'Provider rate limits apply.')
                        ui.button('Cancel without sending a request',
                                  on_click=lambda: act('pubmed_pilot_revise')).props(
                                      'data-testid=pubmed-pilot-cancel')
                        ui.button('Confirm one PubMed count-only request',
                                  on_click=lambda: act('pubmed_pilot_confirm')).props(
                                      'data-testid=pubmed-pilot-confirm')
                    else:
                        ui.label('Select one approved PubMed group query. '
                                 'Selecting only previews; a separate click '
                                 'must authorise the network request.')
                        for source in state['preflight_report']['sources']:
                            if source['source_name'] != 'pubmed':
                                continue
                            for query in source['queries']:
                                qid = query['query_id']
                                ui.label('PubMed ' + query['group_id'] +
                                         ': ' + query['exact_query']).props(
                                             'data-testid=pubmed-pilot-saved-query')
                                ui.button('Preview pilot for group ' +
                                          query['group_id'],
                                          on_click=lambda qid=qid: act(
                                              'pubmed_pilot_offer', qid)).props(
                                                  'data-testid=pubmed-pilot-offer')
                    prior = state['last_pubmed_pilot']
                    if prior is not None:
                        ui.label('Last audited pilot attempt: ' +
                                 prior['status']).props(
                                     'data-testid=pubmed-pilot-status')
                        count = prior['reported_matches']
                        ui.label('Provider-reported PILOT matches: ' +
                                 ('UNKNOWN' if count is None else str(count)) +
                                 '. No records retrieved or search completed.').props(
                                     'data-testid=pubmed-pilot-count')
                        if prior.get('accepted_translation'):
                            ui.label('Accepted PubMed translation: ' +
                                     prior['accepted_translation']).props(
                                         'data-testid=pubmed-pilot-translation')
                        for warning in prior.get('warnings', []):
                            ui.label('PubMed provider warning: ' + warning)
                        for reason in prior.get('review_reasons', []):
                            ui.label('Translation review required: ' + reason)
                        if prior['status'] in ('requested_indeterminate',
                                               'not_recorded'):
                            ui.label('Do not automatically retry this UUID. '
                                     'A NEW pilot requires a fresh two-step '
                                     'selection and confirmation.').props(
                                         'data-testid=pubmed-pilot-no-auto-retry')
                        if prior.get('error_code') is not None:
                            ui.label('Pilot failure code: ' + prior['error_code'])
                        ui.label('Pilot results never establish final '
                                 'retrieval or PRESS peer review.').props(
                                     'data-testid=pubmed-pilot-incomplete')
                if (state['selected_run_id'] is not None and
                        state['preflight_report'] is not None):
                    ui.separator()
                    ui.label('Web of Science Starter — optional one-record '
                             'count/quota pilot; NOT a count-only request or '
                             'literature retrieval.').props(
                                 'data-testid=wos-pilot-heading')
                    ui.label('Starter Topic (TS) includes titles, abstracts '
                             'and indexed keywords; not web-interface All Fields '
                             'or article full text. Pilot counts do NOT '
                             'become verified source/group counts.')
                    if not state['wos_profile_configured']:
                        ui.label('Pilot unavailable: no trusted host-only '
                                 'Starter API key. Browser controls cannot '
                                 'supply credentials.').props(
                                     'data-testid=wos-profile-unavailable')
                    elif state['wos_pilot_reconciliation_required']:
                        ui.label('Uncertain original Starter request: inspect '
                                 'the SAME audit UUID without any network call. '
                                 'A lost outcome can leave the shared quota '
                                 'guard blocked pending separate recovery.').props(
                                     'data-testid=wos-pilot-uncertain')
                        ui.button('Inspect original Starter receipt (no network)',
                                  on_click=lambda: act('wos_pilot_reconcile')).props(
                                      'data-testid=wos-pilot-reconcile')
                    elif state['pubmed_pilot_reconciliation_required']:
                        ui.label('Resolve the PubMed pilot receipt before '
                                 'starting a Starter pilot.')
                    elif state['wos_pilot_candidate'] is not None:
                        candidate = state['wos_pilot_candidate']
                        ui.label('Unsent, locked Starter group: ' +
                                 candidate['group_id']).props(
                                     'data-testid=wos-pilot-candidate')
                        ui.label('Exact Topic query: ' +
                                 candidate['exact_query']).props(
                                     'data-testid=wos-pilot-query')
                        if candidate['revalidate_quota']:
                            ui.label('EXPLICIT QUOTA REVALIDATION: another '
                                     'provider request is being authorised '
                                     'after previously observed exhaustion. '
                                     'This does not override server cooldowns '
                                     'or unknown in-flight attempts.')
                        ui.label('Confirmation sends ONE HTTPS GET to the '
                                 'official Starter service (page 1, limit 1). '
                                 'It can transiently return ONE licensed '
                                 'bibliographic record; RESEARCH-Y immediately '
                                 'discards it. Only safe count/quota/audit '
                                 'evidence is retained. An API request is '
                                 'consumed. This is NOT a zero-record '
                                 'count-only operation.')
                        ui.button('Cancel without sending a Starter request',
                                  on_click=lambda: act('wos_pilot_revise')).props(
                                      'data-testid=wos-pilot-cancel')
                        ui.button('Confirm ONE Starter one-record request',
                                  on_click=lambda: act('wos_pilot_confirm')).props(
                                      'data-testid=wos-pilot-confirm')
                    else:
                        ui.label('Preview one approved pending Starter group '
                                 'query without contacting the provider. '
                                 'A separate confirmation authorises the '
                                 'one-record request and quota use.')
                        for source in state['preflight_report']['sources']:
                            if source['source_name'] != 'wos':
                                continue
                            for query in source['queries']:
                                qid = query['query_id']
                                ui.label('Starter ' + query['group_id'] +
                                         ': ' + query['exact_query']).props(
                                             'data-testid=wos-pilot-saved-query')
                                ui.button('Preview Starter one-record pilot for ' +
                                          query['group_id'],
                                          on_click=lambda qid=qid: act(
                                              'wos_pilot_offer', qid)).props(
                                                  'data-testid=wos-pilot-offer')
                                ui.button('Preview explicit quota revalidation for ' +
                                          query['group_id'],
                                          on_click=lambda qid=qid: act(
                                              'wos_pilot_revalidation_offer', qid)).props(
                                                  'data-testid=wos-pilot-revalidation-offer')
                    prior = state['last_wos_pilot']
                    if prior is not None:
                        ui.label('Last audited Starter pilot: ' +
                                 prior['status']).props(
                                     'data-testid=wos-pilot-status')
                        count = prior['reported_matches']
                        ui.label('Provisional provider-reported matches: ' +
                                 ('UNKNOWN' if count is None else str(count)) +
                                 '; zero records retained; not verified retrieval.').props(
                                     'data-testid=wos-pilot-count')
                        quota = prior.get('quota')
                        if isinstance(quota, dict):
                            ui.label('Observed daily quota: allowance=' +
                                     str(quota.get('daily_limit')) +
                                     ', remaining=' +
                                     str(quota.get('daily_remaining')) +
                                     ', entitlement=' +
                                     str(prior.get('quota_status')))
                        if prior.get('retry_after_seconds') is not None:
                            ui.label('Server-directed retry delay recorded; '
                                     'new provider requests remain restricted.')
                        if prior.get('retry_after_unverifiable'):
                            ui.label('Server retry deadline not representable; '
                                     'further requests are blocked.')
                        if prior['status'] in ('requested_indeterminate',
                                               'not_recorded'):
                            ui.label('Never resend this UUID. An indeterminate '
                                     'provider reservation may remain blocked '
                                     'even after a new preview.').props(
                                         'data-testid=wos-pilot-no-auto-retry')
                        if prior.get('error_code') is not None:
                            ui.label('Static failure code: ' +
                                     prior['error_code'])
                        ui.label('Starter does not expose accepted query '
                                 'translation. This pilot neither verifies '
                                 'source retrieval nor completes PRESS review.').props(
                                     'data-testid=wos-pilot-incomplete')
                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('Web of Science Starter — checkpointed source '
                             'acquisition (EXPERIMENTAL).').props(
                                 'data-testid=wos-acquisition-heading')
                    ui.label('Unlike a pilot, this workflow can store licensed '
                             'source metadata in the local project. Explicit '
                             'retention consent and a separate provider-session '
                             'confirmation are both required. Verify your '
                             'institutional licence before using it.')
                    ui.label('One confirmed session uses at most THREE Starter '
                             'requests (a count/identity recheck where required '
                             'and up to two further 50-record pages). '
                             'Provider quota, cooldowns and interruption '
                             'recovery are enforced by the existing checkpoint '
                             'engine. No automatic unattended sessions.')
                    ui.label('A reconciled Starter enumeration is NOT a '
                             'verified whole-run search, full abstracts, '
                             'publication deduplication or an atomic provider '
                             'snapshot. Progress is based on durable source '
                             'checkpoint evidence only.')
                    if state['wos_acquisition_prepare_pending']:
                        ui.label('Local retention plan outcome uncertain. '
                                 'Inspect the original checkpoint — never '
                                 'silently re-authorise or start a request.').props(
                                     'data-testid=wos-acquisition-prepare-uncertain')
                        ui.button('Inspect originally authorised checkpoint (no network)',
                                  on_click=lambda: act(
                                      'wos_acquisition_prepare_reconcile')).props(
                                          'data-testid=wos-acquisition-prepare-reconcile')
                    elif state['wos_acquisition_tick_pending']:
                        ui.label('Bounded source request session outcome '
                                 'uncertain. Do not repeat until checkpoint '
                                 'state is reconciled. A lost worker may '
                                 'require explicit supervised recovery.').props(
                                     'data-testid=wos-acquisition-tick-uncertain')
                        ui.button('Read original source checkpoint (no network)',
                                  on_click=lambda: act(
                                      'wos_acquisition_tick_reconcile')).props(
                                          'data-testid=wos-acquisition-tick-reconcile')
                    elif state['wos_acquisition_offer'] is not None:
                        candidate = state['wos_acquisition_offer']
                        ui.label('Locked exact Starter Topic query: ' +
                                 candidate['exact_query']).props(
                                     'data-testid=wos-acquisition-exact-query')
                        ui.label('You are authorising local retention of all '
                                 'provider-returned metadata permitted by your '
                                 'institutional licence. This preparation '
                                 'itself makes NO network request and does '
                                 'not authorise future sessions automatically.')
                        ui.button('Cancel retention consent without preparing',
                                  on_click=lambda: act('wos_acquisition_dismiss')).props(
                                      'data-testid=wos-acquisition-cancel')
                        ui.button('Confirm local metadata retention and prepare checkpoint',
                                  on_click=lambda: act('wos_acquisition_prepare')).props(
                                      'data-testid=wos-acquisition-prepare')
                    else:
                        if state['report'] is not None:
                            for row in state['report']['queries']:
                                if row['source_name'] != 'wos':
                                    continue
                                qid = row['query_id']
                                ui.label('Saved Starter group ' + row['group_id'] +
                                         ': ' + row['exact_query']).props(
                                             'data-testid=wos-acquisition-saved-query')
                                ui.button('Inspect checkpoint for group ' +
                                          row['group_id'],
                                          on_click=lambda qid=qid: act(
                                              'wos_acquisition_read',qid)).props(
                                                  'data-testid=wos-acquisition-read')
                                if (state['wos_profile_configured'] and
                                        row['status'] == 'pending'):
                                    ui.button('Preview full-source retention for ' +
                                              row['group_id'],
                                              on_click=lambda qid=qid: act(
                                                  'wos_acquisition_offer',qid)).props(
                                                      'data-testid=wos-acquisition-offer')
                        if not state['wos_profile_configured']:
                            ui.label('Source execution unavailable without the '
                                     'trusted host-only Starter API key. Existing '
                                     'checkpoints remain readable.')
                    acquisition = state['wos_acquisition']
                    if acquisition is not None:
                        job = acquisition['checkpoint']
                        ui.label('Selected source checkpoint: ' +
                                 acquisition['query_id']).props(
                                     'data-testid=wos-acquisition-selected')
                        ui.label('Durable status: ' + job['status'] +
                                 '; stage: ' + job['stage'] +
                                 '; reason: ' + job['reason_code']).props(
                                     'data-testid=wos-acquisition-status')
                        ui.label('Provider matches: ' +
                                 ('UNKNOWN' if job['reported_matches'] is None
                                  else str(job['reported_matches'])) +
                                 '; records actually stored: ' +
                                 str(job['records_committed']) +
                                 '; pages acquired: ' +
                                 str(job['pages_committed']) +
                                 '; pages verified: ' +
                                 str(job['verification_pages'])).props(
                                     'data-testid=wos-acquisition-progress')
                        ui.label('Unknown attempted requests: ' +
                                 str(job['requests_unknown']) +
                                 '; worker reservation active: ' +
                                 str(job['worker_active']) +
                                 '; next allowed time: ' +
                                 str(job['not_before_utc']))
                        ui.label('Observed daily quota status (provider facts): ' +
                                 str(job['quota']))
                        if job['worker_active'] or job['requests_unknown']:
                            ui.label('Worker/transport outcome may be unknown. '
                                     'Do NOT automatically retry; separate '
                                     'verified recovery is required.').props(
                                         'data-testid=wos-acquisition-recovery-required')
                        elif not acquisition['approved_gui_retention']:
                            ui.label('Historical non-GUI checkpoint: no matching '
                                     'explicit graphical retention admission; '
                                     'view-only in this increment.')
                        elif job['enumeration_reconciled']:
                            ui.label('Source identifier enumeration reconciled '
                                     'WITH WARNINGS. Full bibliography and '
                                     'whole search remain incomplete.').props(
                                         'data-testid=wos-acquisition-partial-complete')
                        elif (job['pages_expected'] is not None and
                              job['pages_expected'] > 1 and
                              job['stage'] in ('verify','final')):
                            ui.label('Acquisition pages retained. Multi-page '
                                     'identity verification needs a longer '
                                     'uninterrupted supervised worker session. '
                                     'Short GUI sessions are DISABLED here to '
                                     'prevent repeated quota-consuming loops.').props(
                                         'data-testid=wos-acquisition-long-verification-required')
                        elif job['status']=='cancelled':
                            ui.label('Checkpoint cancelled; no further requests '
                                     'from this interface.')
                        elif state['wos_acquisition_tick_offer'] is None:
                            if state['wos_profile_configured']:
                                ui.button('Preview next bounded session (up to THREE requests)',
                                          on_click=lambda: act(
                                              'wos_acquisition_tick_offer')).props(
                                                  'data-testid=wos-acquisition-tick-offer')
                                ui.button('Preview explicit quota revalidation session',
                                          on_click=lambda: act(
                                              'wos_acquisition_revalidate_offer')).props(
                                                  'data-testid=wos-acquisition-revalidate-offer')
                        else:
                            offered = state['wos_acquisition_tick_offer']
                            ui.label('Unsent bounded session for source query ' +
                                     offered['query_id'] + ', maximum THREE '
                                     'requests. It may retain up to three pages '
                                     'of licensed metadata, without silently '
                                     'changing your OR-only query.').props(
                                         'data-testid=wos-acquisition-tick-preview')
                            if offered['revalidate_quota']:
                                ui.label('EXPLICIT quota revalidation requested. '
                                         'Does not bypass server cooldown or '
                                         'indeterminate provider reservations.')
                            ui.button('Cancel unsent source session',
                                      on_click=lambda: act(
                                          'wos_acquisition_tick_dismiss')).props(
                                              'data-testid=wos-acquisition-tick-cancel')
                            ui.button('CONFIRM bounded Starter source request session',
                                      on_click=lambda: act(
                                          'wos_acquisition_tick_confirm')).props(
                                              'data-testid=wos-acquisition-tick-confirm')
                ui.separator()
                ui.label('Web of Science — longer supervised identity verification '
                         '(experimental)').props('data-testid=wos-verification-heading')
                if state['wos_verification_pending']:
                    ui.label('An explicitly authorised verification worker is '
                             'running or needs final receipt reconciliation. '
                             'Other project/run operations remain locked.')
                    ui.label('Supervisor status: ' +
                             state['wos_verification_worker_state'] +
                             '; error: ' +
                             str(state['wos_verification_worker_error'])).props(
                                 'data-testid=wos-verification-worker-state')
                    active = state['wos_acquisition']
                    if active is not None:
                        progress = active['checkpoint']
                        ui.label('Durable verification progress: ' +
                                 str(progress['verification_pages']) + ' / ' +
                                 ('UNKNOWN' if progress['pages_expected'] is None
                                  else str(progress['pages_expected'])) +
                                 ' pages; recorded source hits ' +
                                 str(progress['records_committed']) +
                                 '; unknown requests ' +
                                 str(progress['requests_unknown'])).props(
                                     'data-testid=wos-verification-progress')
                        if progress['worker_active'] or progress['requests_unknown']:
                            ui.label('Do not repeat provider calls: the original '
                                     'worker or an HTTP outcome may be unknown.')
                    ui.button('Refresh source verification status (no provider request)',
                              on_click=lambda: act('wos_verification_poll')).props(
                                  'data-testid=wos-verification-poll')
                    if state['wos_verification_worker_state'] == 'running':
                        ui.button('Request graceful pause after current page',
                                  on_click=lambda: act('wos_verification_pause')).props(
                                      'data-testid=wos-verification-pause')
                    else:
                        ui.button('Reconcile stopped worker with durable checkpoint',
                                  on_click=lambda: act('wos_verification_reconcile')).props(
                                      'data-testid=wos-verification-reconcile')
                elif state['wos_verification_offer'] is not None:
                    proposal = state['wos_verification_offer']
                    ui.label('Locked exact query: ' + proposal['exact_query']).props(
                        'data-testid=wos-verification-locked-query')
                    ui.label('Previously captured pages requiring verification: ' +
                             str(proposal['pages_to_verify']) +
                             '; exact maximum provider requests in this session: ' +
                             str(proposal['expected_requests']) +
                             ' (one initial recheck, all verification pages, '
                             'one final recheck). Up to 512 requests supported. '
                             'Rate limits, quota, server Retry-After or source '
                             'change can pause or fail this sweep.').props(
                                 'data-testid=wos-verification-budget')
                    ui.label('No source request has been sent by this preview. '
                             'Confirmation stores permitted validation evidence '
                             'in the original project and may consume institutional quota. '
                             'The app must remain open; closing it interrupts '
                             'the child and may require explicit recovery.')
                    if proposal['revalidate_quota']:
                        ui.label('Explicit revalidation requested, but server '
                                 'cooldown and unknown previous provider '
                                 'requests cannot be bypassed.')
                    ui.button('Cancel unsent verification',
                              on_click=lambda: act('wos_verification_dismiss')).props(
                                  'data-testid=wos-verification-dismiss')
                    ui.button('CONFIRM one bounded supervised verification session',
                              on_click=lambda: act('wos_verification_confirm')).props(
                                  'data-testid=wos-verification-confirm')
                else:
                    acquired = state['wos_acquisition']
                    if (acquired is not None and
                            acquired['approved_gui_retention'] is True and
                            state['wos_profile_configured'] and
                            acquired['checkpoint']['stage'] in ('verify', 'final') and
                            not acquired['checkpoint']['enumeration_reconciled'] and
                            not acquired['checkpoint']['worker_active'] and
                            acquired['checkpoint']['requests_unknown'] == 0):
                        ui.label('The existing short-session limit cannot '
                                 'finish this verification sweep. A separate '
                                 'longer supervised worker can verify the '
                                 'already captured pages in one explicit session.')
                        ui.button('Preview full source verification workload',
                                  on_click=lambda: act('wos_verification_offer')).props(
                                      'data-testid=wos-verification-offer')
                        ui.button('Preview verification with explicit quota revalidation',
                                  on_click=lambda: act(
                                      'wos_verification_revalidate_offer')).props(
                                          'data-testid=wos-verification-revalidate')
                if state['wos_verification_last_outcome'] is not None:
                    outcome = state['wos_verification_last_outcome']
                    ui.label('Last supervised session: ' +
                             outcome['worker_state'] +
                             '; source status: ' + outcome['durable_source_status'] +
                             '; enumeration reconciled: ' +
                             str(outcome['enumeration_reconciled']) +
                             '; whole search verified: FALSE').props(
                                 'data-testid=wos-verification-outcome')
                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('PubMed ESearch — supervised identifier retrieval '
                             '(EXPERIMENTAL; metadata is a separate stage).').props(
                                 'data-testid=pubmed-source-heading')
                    ui.label('Every approved group remains independent and '
                             'the conceptual search is OR-only. No language, '
                             'species or study-type exclusion is applied. '
                             'Identifiers are stored in the project with a '
                             'source checkpoint, NOT treated as a finished '
                             'bibliographic search.').props(
                                 'data-testid=pubmed-source-method')
                    ui.label('One explicitly confirmed session is limited to '
                             '128 source requests, including count probes; '
                             'individual identifier pages are capped at 200. '
                             'A broader query may need Create Date partitioning, '
                             'but its initial unfiltered count must equal the '
                             'count over the researcher-confirmed date coverage. '
                             'Otherwise results remain INCOMPLETE.')
                    if state['pubmed_source_pending']:
                        ui.label('Supervised identifier worker: ' +
                                 state['pubmed_source_worker_state'] +
                                 '; error: ' + str(
                                     state['pubmed_source_worker_error'])).props(
                                         'data-testid=pubmed-source-worker-state')
                        ui.label('Do not repeat an uncertain source request. '
                                 'The original checkpoint must be inspected '
                                 'after the worker stops.')
                        progress = state['pubmed_source']
                        if progress is not None and progress['checkpoint'] is not None:
                            cp=progress['checkpoint']
                            ui.label('Saved source results: ' +
                                     str(cp['identifiers_committed']) + ' / ' +
                                     str(cp['reported_matches']) + ' PMIDs; ' +
                                     str(cp['pages_committed']) + ' / ' +
                                     str(cp['pages_expected']) + ' pages; ' +
                                     'identifier reconciliation: ' +
                                     str(cp['identifiers_reconciled'])).props(
                                         'data-testid=pubmed-source-progress')
                        else:
                            ui.label('No durable source checkpoint yet: count '
                                     'planning may still be in progress, or '
                                     'the source outcome is unknown.').props(
                                         'data-testid=pubmed-source-no-checkpoint')
                        ui.button('Refresh original PubMed checkpoint (no HTTP)',
                                  on_click=lambda: act('pubmed_identifier_poll')).props(
                                      'data-testid=pubmed-source-poll')
                        if (state['pubmed_source_worker_state']=='running' and
                                progress is not None and
                                progress['checkpoint'] is not None):
                            ui.button('Request graceful pause after committed page',
                                      on_click=lambda: act('pubmed_identifier_pause')).props(
                                          'data-testid=pubmed-source-pause')
                        if state['pubmed_source_worker_state'] != 'running':
                            ui.button('Reconcile terminal worker and saved checkpoint',
                                      on_click=lambda: act(
                                          'pubmed_identifier_reconcile')).props(
                                              'data-testid=pubmed-source-reconcile')
                    elif state['pubmed_source_offer'] is not None:
                        choice=state['pubmed_source_offer']
                        ui.label('Frozen PubMed All Fields exact query: ' +
                                 choice['exact_query']).props(
                                     'data-testid=pubmed-source-exact-query')
                        ui.label('Explicit administrative Create Date coverage: ' +
                                 choice['coverage_start'] + ' to ' +
                                 choice['coverage_end'] +
                                 '. The range is used only if a large search '
                                 'must be partitioned; unfiltered counts must '
                                 'reconcile with this coverage.').props(
                                     'data-testid=pubmed-source-coverage')
                        ui.label('This PREVIEW has made NO provider requests. '
                                 'Confirming starts one bounded, supervised '
                                 'ESearch session and uses trusted host-only '
                                 'NCBI contact settings. The application must '
                                 'remain open for source work to continue.')
                        ui.button('Cancel unsent PubMed session',
                                  on_click=lambda: act('pubmed_identifier_dismiss')).props(
                                      'data-testid=pubmed-source-dismiss')
                        ui.button('CONFIRM bounded PubMed identifier retrieval',
                                  on_click=lambda: act('pubmed_identifier_confirm')).props(
                                      'data-testid=pubmed-source-confirm')
                    else:
                        pubmed_start = ui.input(
                            'Administrative Create Date coverage start (YYYY-MM-DD)',
                            value='1800-01-01').props(
                                'data-testid=pubmed-source-start')
                        pubmed_end = ui.input(
                            'Administrative Create Date coverage end (YYYY-MM-DD)',
                            value=date.today().isoformat()).props(
                                'data-testid=pubmed-source-end')
                        for row in (state['report']['queries'] if state['report']
                                    is not None else ()):
                            if row['source_name'] != 'pubmed':
                                continue
                            qid=row['query_id']
                            ui.label('Saved PubMed query: ' + row['exact_query']).props(
                                'data-testid=pubmed-source-saved-query')
                            ui.button('Read existing checkpoint for ' + row['group_id'],
                                      on_click=lambda qid=qid: act(
                                          'pubmed_identifier_read',qid)).props(
                                              'data-testid=pubmed-source-read')
                            if state['pubmed_profile_configured']:
                                ui.button('Preview identifier session for ' +
                                          row['group_id'],
                                          on_click=lambda qid=qid: act(
                                              'pubmed_identifier_offer',dict(
                                                  query_id=qid,
                                                  coverage_start=pubmed_start.value,
                                                  coverage_end=pubmed_end.value))).props(
                                                      'data-testid=pubmed-source-offer')
                        if not state['pubmed_profile_configured']:
                            ui.label('NCBI ESearch requests require a trusted '
                                     'host contact email. Saved checkpoints '
                                     'remain readable without credentials.')
                    if state['pubmed_source'] is not None and not state['pubmed_source_pending']:
                        cp=state['pubmed_source']['checkpoint']
                        if cp is not None:
                            ui.label('Last inspected PubMed checkpoint: ' +
                                     cp['status'] + '; ' +
                                     str(cp['identifiers_committed']) +
                                     ' identifiers saved; pages ' +
                                     str(cp['pages_committed']) + '/' +
                                     str(cp['pages_expected']) + '; metadata '
                                     'records linked ' +
                                     str(cp['metadata_records_linked'])).props(
                                         'data-testid=pubmed-source-saved-progress')
                            if cp['identifiers_reconciled']:
                                ui.label('Identifiers reconciled only. EFetch '
                                         'bibliography/abstract acquisition, '
                                         'deduplication and complete whole-run '
                                         'acceptance remain OUTSTANDING.')
                    if state['pubmed_source_last_outcome'] is not None:
                        outcome=state['pubmed_source_last_outcome']
                        ui.label('Last PubMed worker: ' +
                                 outcome['worker_state'] +
                                 '; requests reserved: ' +
                                 ('UNKNOWN' if outcome['requests_reserved'] is None
                                  else str(outcome['requests_reserved'])) +
                                 '; whole search verified: FALSE').props(
                                     'data-testid=pubmed-source-outcome')
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

            async def refresh_running_verification():
                # Passive host polling is STRICTLY read-only. The sole source
                # network action remains the separate explicit Confirm button.
                # One timer per connected page, not per panel refresh.
                if not action_lock.locked():
                    if flow.state()['wos_verification_pending']:
                        await act('wos_verification_poll')
                    elif flow.state()['pubmed_source_pending']:
                        await act('pubmed_identifier_poll')

            ui.timer(2.0, refresh_running_verification)

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
