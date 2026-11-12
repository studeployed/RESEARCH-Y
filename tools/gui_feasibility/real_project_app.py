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
        sequence = (('open', 'select_run', 'publication_window_offer',
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
                        if name == 'pubmed_metadata_read':
                            return flow.inspect_stored_pubmed_metadata(value)
                        if name == 'pubmed_metadata_offer':
                            return flow.offer_pubmed_metadata(value)
                        if name == 'pubmed_metadata_dismiss':
                            return flow.dismiss_pubmed_metadata()
                        if name == 'pubmed_metadata_confirm':
                            # Explicit user consent; the ONLY EFetch HTTP path.
                            return flow.confirm_pubmed_metadata()
                        if name == 'pubmed_metadata_poll':
                            # Original durable record counts, no network.
                            return flow.poll_pubmed_metadata()
                        if name == 'pubmed_metadata_reconcile':
                            # Read-only final verification of stopped worker.
                            return flow.reconcile_pubmed_metadata()
                        if name == 'run_board_refresh':
                            # One explicit whole-run inspection. No provider
                            # traffic, query execution or background scheduling.
                            return flow.inspect_run_execution_board()
                        if name == 'run_board_select':
                            if type(value) is not dict or set(value) != {
                                    'query_id','revision'}:
                                raise ProjectFlowError('run_board_invalid')
                            return flow.choose_run_execution_step(**value)
                        if name == 'publication_refresh':
                            return flow.inspect_publications()
                        if name == 'publication_next':
                            if type(value) is not dict or set(value) != {'cursor', 'revision'}:
                                raise ProjectFlowError('publication_view_invalid')
                            return flow.inspect_publications(
                                after_publication_id=value['cursor'], revision=value['revision'])
                        if name == 'publication_detail':
                            if type(value) is not dict or set(value) != {'publication_id', 'revision'}:
                                raise ProjectFlowError('publication_view_invalid')
                            return flow.inspect_publication_detail(**value)
                        if name == 'publication_materialise_offer':
                            # No write. The next CONFIRM is a separate, bounded,
                            # deliberately initiated local SQLite transaction.
                            return flow.offer_publication_materialisation()
                        if name == 'publication_materialise_dismiss':
                            return flow.dismiss_publication_materialisation()
                        if name == 'publication_materialise_confirm':
                            return flow.confirm_publication_materialisation(value)
                        if name in ('publication_window_inspect',
                                    'publication_window_offer',
                                    'publication_window_dismiss'):
                            # Only fixed actions; browser cannot supply a run,
                            # consent hash, source IDs, work limit or path.
                            if value is not None:
                                raise ProjectFlowError('publication_window_invalid')
                            if name == 'publication_window_inspect':
                                return flow.inspect_publication_window()
                            if name == 'publication_window_offer':
                                return flow.offer_publication_window()
                            return flow.dismiss_publication_window()
                        if name == 'publication_window_confirm':
                            if type(value) is not str or not value.strip():
                                raise ProjectFlowError(
                                    'publication_window_confirmation_required')
                            return flow.confirm_publication_window(value)
                        if name == 'candidate_index_inspect':
                            # Local source-key cache status only. No writes.
                            return flow.inspect_candidate_index()
                        if name == 'candidate_index_offer':
                            if value not in ('start','advance'):
                                raise ProjectFlowError('candidate_index_invalid')
                            return flow.offer_candidate_index(value)
                        if name == 'candidate_index_dismiss':
                            return flow.dismiss_candidate_index()
                        if name == 'candidate_index_confirm':
                            # Only a separate confirmation click authorises one
                            # transaction of at most 128 original source records.
                            return flow.confirm_candidate_index(value)
                        if name == 'candidate_pairs_inspect':
                            # Read-only saved pair checkpoint for selected run.
                            return flow.inspect_candidate_pairs()
                        if name == 'candidate_pairs_offer':
                            if type(value) is not str or value not in ('start','advance'):
                                raise ProjectFlowError('candidate_pair_invalid')
                            return flow.offer_candidate_pairs(value)
                        if name == 'candidate_pairs_dismiss':
                            return flow.dismiss_candidate_pairs()
                        if name == 'candidate_pairs_confirm':
                            # Separate explicit click, one bounded transaction
                            # and independent saved-state reconciliation.
                            return flow.confirm_candidate_pairs(value)
                        if name == 'candidate_queue_refresh':
                            # Full project candidate index, original SQLite only.
                            return flow.inspect_candidate_queue()
                        if name == 'candidate_queue_next':
                            if (type(value) is not dict or
                                    set(value) != {'cursor','revision'} or
                                    type(value['cursor']) is not list or
                                    len(value['cursor']) != 2):
                                raise ProjectFlowError('candidate_queue_invalid')
                            return flow.inspect_candidate_queue(
                                cursor=tuple(value['cursor']),
                                revision=value['revision'])
                        if name == 'candidate_queue_review':
                            if (type(value) is not dict or
                                    set(value) != {'left','right','revision'}):
                                raise ProjectFlowError('candidate_queue_invalid')
                            return flow.inspect_queue_candidate_pair(**value)
                        if name == 'candidate_choose_source':
                            return flow.choose_candidate_source(value)
                        if name == 'candidate_review_dismiss':
                            return flow.dismiss_candidate_review()
                        if name == 'candidate_reversal_offer':
                            return flow.offer_candidate_reversal(value)
                        if name == 'candidate_review_decide':
                            if type(value) is not dict or set(value) != {
                                    'decision', 'move_retrieval_id', 'actor',
                                    'evidence', 'acknowledged'}:
                                raise ProjectFlowError('publication_review_invalid')
                            return flow.confirm_candidate_decision(**value)
                        if name == 'candidate_reversal_confirm':
                            if type(value) is not dict or set(value) != {
                                    'actor', 'evidence'}:
                                raise ProjectFlowError('publication_review_invalid')
                            return flow.confirm_candidate_reversal(**value)
                        if name == 'run_coord_offer':
                            return flow.offer_run_coordination()
                        if name == 'run_coord_dismiss':
                            return flow.dismiss_run_coordination()
                        if name == 'run_coord_confirm':
                            # Only this separately confirmed click can begin
                            # a bounded source-work sequence.
                            return flow.confirm_run_coordination()
                        if name == 'run_coord_poll':
                            # Original source checkpoint reads ONLY.
                            return flow.poll_run_coordination()
                        if name == 'run_coord_reconcile':
                            return flow.reconcile_run_coordination()
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
                    ui.label('Combined PubMed + Web of Science execution board '
                             '— all approved OR groups, without new source calls.').props(
                                 'data-testid=run-board-heading')
                    ui.button('Refresh whole-run evidence (offline, no provider calls)',
                              on_click=lambda: act('run_board_refresh')).props(
                                  'data-testid=run-board-refresh')
                    board = state['run_execution_board']
                    if state['run_board_error'] is not None:
                        ui.label('The run board could not validate the original '
                                 'local ledger. Source status UNKNOWN; no '
                                 'result or count is being inferred.').props(
                                     'data-testid=run-board-error')
                    elif board is None:
                        ui.label('Select Refresh to read all source/group '
                                 'checkpoints. No provider request is made.').props(
                                     'data-testid=run-board-unread')
                    else:
                        ui.label('RUN INCOMPLETE — this is one read-only '
                                 'reconciliation of saved evidence, not a source '
                                 'query or an automatic search.').props(
                                     'data-testid=run-board-incomplete')
                        ui.label('Saved source records, across group unions: ' +
                                 str(board['totals']['source_record_sum']) +
                                 '; identifiers lacking metadata: ' +
                                 str(board['totals']['identifiers_missing_metadata']) +
                                 '; global UNIQUE publications: NOT ESTABLISHED.').props(
                                     'data-testid=run-board-totals')
                        ui.label('Primary source enumerations reconciled: ' +
                                 str(board['primary_source_enumerations_reconciled']) +
                                 '; available source metadata retained: ' +
                                 str(board['available_primary_metadata_acquired']) +
                                 '; complete research search: FALSE.').props(
                                     'data-testid=run-board-coverage')
                        if not board['approved_query_inventory_matches']:
                            ui.label('Stored queries could not be matched to the approved strategy. '
                                     'Run-wide retrieval coverage is unknown.').props(
                                         'data-testid=run-board-plan-mismatch')
                        ui.label('Provisional publication identity hypotheses: ' +
                                 str(board['totals']['publication_identity_hypotheses']) +
                                 ' (NOT a final deduplicated result).')
                        for group in board['groups']:
                            ui.label('Concept group ' + group['label'] +
                                     ' — group unique publications: NOT ESTABLISHED.').props(
                                         'data-testid=run-board-group')
                            for item in group['sources']:
                                provider = ('PubMed' if item['source_name']=='pubmed'
                                            else 'Web of Science Starter')
                                reported = ('UNKNOWN' if
                                            item['reported_matches'] is None else
                                            str(item['reported_matches']))
                                ui.label(provider + ' • ' + item['source_stage'] +
                                         ' • reported hits ' + reported +
                                         ' • retrieved source IDs ' +
                                         str(item['identifiers_retrieved']) +
                                         ' • saved metadata ' +
                                         str(item['metadata_records_retained']) +
                                         ' • count check ' +
                                         item['count_reconciliation']).props(
                                             'data-testid=run-board-source-row')
                                ui.label('Exact stored source expression: ' +
                                         item['exact_query']).props(
                                             'data-testid=run-board-exact-query')
                                if item['warnings']:
                                    ui.label('Pending source issues: ' +
                                             ', '.join(item['warnings']))
                                step = item['next_step']
                                allowed = True
                                if step == 'preview_wos':
                                    allowed = state['wos_profile_configured']
                                elif step == 'preview_pubmed_metadata':
                                    allowed = state['pubmed_profile_configured']
                                if allowed:
                                    qid = item['query_id']
                                    revision = board['revision']
                                    ui.button('Open safe next-step preview / saved '
                                              'checkpoint: ' + provider,
                                              on_click=lambda qid=qid, revision=revision:
                                                  act('run_board_select',
                                                      {'query_id':qid,'revision':revision})).props(
                                                          'data-testid=run-board-next-step')
                                else:
                                    ui.label('Provider profile not configured; '
                                             'original local counts remain readable '
                                             'without external requests.')
                        ui.label('This board cannot certify full source snapshots, '
                                 'missing abstracts, deduplication, official society '
                                 'coverage or completed Preferred Reporting Items for '
                                 'Systematic Reviews and Meta-Analyses searches.')

                if state['project'] is not None:
                    ui.separator()
                    ui.label('Durable candidate-key index — optional LOCAL '
                             'derivative of original source records. It is not '
                             'a deduplicated result or a completed search.').props(
                                 'data-testid=candidate-index-heading')
                    ui.button('Inspect current index status (READ-ONLY)',
                              on_click=lambda: act('candidate_index_inspect')).props(
                                  'data-testid=candidate-index-inspect')
                    if state['candidate_index_error'] is not None:
                        ui.label('Index receipt not independently verified. '
                                 'An interrupted writer may have committed. '
                                 'Inspect current durable status before choosing '
                                 'another action; never replay an old consent.').props(
                                     'data-testid=candidate-index-error')
                    index=state['candidate_index_state']
                    if index is None:
                        ui.label('Index status has not been inspected in this '
                                 'session. The original source-based candidate '
                                 'queue remains available offline.')
                    else:
                        ui.label('Index: ' + index['status'] +
                                 ' • original source records: ' +
                                 str(index['source_records']) +
                                 ' • processed: ' +
                                 str(index['processed_records']) +
                                 ' • cached keys: ' +
                                 str(index['indexed_keys']) +
                                 ' • unsupported layouts: ' +
                                 str(index['unsupported_records']) +
                                 ' • search verified: NO • final unique '
                                 'publications: UNKNOWN.').props(
                                     'data-testid=candidate-index-status')
                        if index['status']=='stale':
                            ui.label('Original source evidence changed. '
                                     'This generation is not usable; '
                                     'explicit rebuild required.').props(
                                         'data-testid=candidate-index-stale')
                        if index['status']=='ready':
                            ui.label('Cache is ready for exact-key candidate '
                                     'hints only. Reviewer decisions remain '
                                     'separate and source-backed.').props(
                                         'data-testid=candidate-index-ready')
                        offer=state['candidate_index_offer']
                        if offer is None:
                            ui.button('Preview a NEW project-wide source-key '
                                      'generation (NO network)',on_click=lambda:
                                      act('candidate_index_offer','start')).props(
                                          'data-testid=candidate-index-start-offer')
                            if index['status']=='building':
                                ui.button('Preview ONE bounded continuation '
                                          'batch (up to 128 records)',on_click=lambda:
                                          act('candidate_index_offer','advance')).props(
                                              'data-testid=candidate-index-advance-offer')
                        else:
                            ui.label('Unsent ' + offer['action'] +
                                     ' • source records ' +
                                     str(offer['source_records']) +
                                     ' • already processed ' +
                                     str(offer['processed_records']) +
                                     '. Confirmation writes only derived '
                                     'index rows and an audit receipt.').props(
                                         'data-testid=candidate-index-offer')
                            researcher=ui.input('Researcher confirming local index '
                                                'work',value='Researcher')
                            ui.button('CONFIRM ' + offer['action'] +
                                      ' (ONE bounded SQLite transaction)',
                                      on_click=lambda box=researcher:
                                          act('candidate_index_confirm',box.value)).props(
                                              'data-testid=candidate-index-confirm')
                            ui.button('Dismiss uncommitted index action',
                                      on_click=lambda:
                                      act('candidate_index_dismiss')).props(
                                          'data-testid=candidate-index-dismiss')
                    last=state['candidate_index_last_receipt']
                    if last is not None:
                        ui.label('Last independently reconciled index action: ' +
                                 last['action'] + ' • status at receipt: ' +
                                 last['status'] + ' • processed: ' +
                                 str(last['processed_records']) +
                                 '. This does not establish deduplication.').props(
                                     'data-testid=candidate-index-outcome')

                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('Run-specific durable potential-duplicate PAIR '
                             'index — local candidate hints, never a unique '
                             'publication count or automatic merge.').props(
                                 'data-testid=candidate-pairs-heading')
                    ui.button('Inspect selected-run pair checkpoint '
                              '(READ-ONLY, OFFLINE)',on_click=lambda:
                              act('candidate_pairs_inspect')).props(
                                  'data-testid=candidate-pairs-inspect')
                    if state['candidate_pair_error'] is not None:
                        ui.label('Pair index outcome must be re-inspected from '
                                 'the original project database. An interrupted '
                                 'writer may already have committed. No prior '
                                 'confirmation can be replayed.').props(
                                     'data-testid=candidate-pairs-error')
                    pair_state=state['candidate_pair_state']
                    if pair_state is None:
                        ui.label('No pair-index checkpoint inspected for this '
                                 'run in the current session. The original '
                                 'source-backed review queue remains usable.')
                    else:
                        ui.label('Pair index: '+pair_state['status']+
                                 ' • processed source/field keys: '+
                                 str(pair_state['processed_source_keys'])+
                                 ' • matching-key hints examined: '+
                                 str(pair_state['emitted_hints'])+
                                 ' • distinct candidate pairs: '+
                                 str(pair_state['unique_pairs'])+
                                 ' • source-key cache ready: '+
                                 ('YES' if pair_state['index_ready'] else 'NO')+
                                 '. All numbers are provisional evidence '
                                 'counts, not verified publications.').props(
                                     'data-testid=candidate-pairs-status')
                        if not pair_state['index_ready']:
                            ui.label('PREREQUISITE: Complete the project-wide '
                                     'source-key index above first. An empty, '
                                     'building or stale source-key index cannot '
                                     'be used to build pair hints.').props(
                                         'data-testid=candidate-pairs-prerequisite')
                        if pair_state['status']=='stale':
                            ui.label('Original source/index/association/review '
                                     'evidence has changed. This pair generation '
                                     'cannot be used; an explicit rebuild is '
                                     'required.').props(
                                         'data-testid=candidate-pairs-stale')
                        if pair_state['status']=='ready_keys_only':
                            ui.label('Exact-key pair hints are indexed. The '
                                     'researcher review queue separately joins '
                                     'all original audited match/rejection '
                                     'receipts; the pair cache alone is not '
                                     'the complete reviewer history.').props(
                                         'data-testid=candidate-pairs-ready')
                        pair_offer=state['candidate_pair_offer']
                        if pair_offer is None:
                            if pair_state['index_ready']:
                                ui.button(
                                    'Preview a NEW pair-index generation '
                                    '(replaces derived hints for THIS run only)',
                                    on_click=lambda:
                                        act('candidate_pairs_offer','start')
                                ).props('data-testid=candidate-pairs-start-offer')
                            if (pair_state['index_ready'] and
                                    pair_state['status']=='building'):
                                ui.button(
                                    'Preview ONE bounded pair-index batch '
                                    '(up to 64 keys / 128 matching hints)',
                                    on_click=lambda:
                                        act('candidate_pairs_offer','advance')
                                ).props('data-testid=candidate-pairs-advance-offer')
                        else:
                            ui.label('Uncommitted '+pair_offer['action']+
                                     ' • selected run '+pair_offer['run_id']+
                                     ' • previously emitted matching hints '+
                                     str(pair_offer['emitted_hints'])+
                                     '. Exactly ONE confirmed local transaction '
                                     'will run. Start may clear only derived '
                                     'pair hints; original sources and reviewer '
                                     'decisions remain unchanged.').props(
                                         'data-testid=candidate-pairs-offer')
                            researcher=ui.input('Researcher confirming '
                                                'pair-index work',value='Researcher')
                            ui.button('CONFIRM '+pair_offer['action']+
                                      ' — ONE bounded, audited transaction',
                                      on_click=lambda box=researcher:
                                          act('candidate_pairs_confirm',box.value)
                            ).props('data-testid=candidate-pairs-confirm')
                            ui.button('Dismiss uncommitted pair-index action',
                                      on_click=lambda:
                                          act('candidate_pairs_dismiss')).props(
                                              'data-testid=candidate-pairs-dismiss')
                    last_pair=state['candidate_pair_last_receipt']
                    if last_pair is not None:
                        ui.label('Last independently reconciled pair-index '
                                 'receipt: '+last_pair['action']+
                                 ' • state '+last_pair['status']+
                                 ' • distinct candidate pairs '+
                                 str(last_pair['unique_pairs'])+
                                 '. This does not establish deduplication.').props(
                                     'data-testid=candidate-pairs-outcome')

                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('Project-wide POTENTIAL DUPLICATE queue — exact '
                             'citation-key hints and historical reviewer receipts, '
                             'NOT automatically merged publications.').props(
                                 'data-testid=candidate-queue-heading')
                    ui.label('Every retained project run contributes to detection; '
                             'only pairs touching the current run are listed. '
                             'Title, Digital Object Identifier (DOI), PubMed '
                             'identifier and accession matches are not proof. '
                             'Unmaterialised/unsupported records and excessive '
                             'candidate volumes are disclosed or refused, never '
                             'silently skipped. No fuzzy discovery yet.').props(
                                 'data-testid=candidate-queue-scope')
                    ui.button('Refresh potential duplicates (READ-ONLY, OFFLINE)',
                              on_click=lambda: act('candidate_queue_refresh')).props(
                                  'data-testid=candidate-queue-refresh')
                    if state['candidate_queue_error'] is not None:
                        ui.label('The project candidate queue could not be '
                                 'validated. Reinspect current source, identity '
                                 'and audit evidence before making decisions.').props(
                                     'data-testid=candidate-queue-error')
                    candidate_queue = state['candidate_queue']
                    if candidate_queue is not None:
                        ui.label('Candidate retrieval backend: ' +
                                 candidate_queue['index_backend'] +
                                 ' • index status: ' +
                                 candidate_queue['index_status'] +
                                 '. When a generation is not ready, the '
                                 'original source-based read is used, not an '
                                 'incomplete cache.').props(
                                     'data-testid=candidate-queue-backend')
                        ui.label('Potential source-record pairs touching this run: ' +
                                 str(candidate_queue['candidate_pair_total']) +
                                 '; total project records: ' +
                                 str(candidate_queue['project_source_records']) +
                                 '; not yet materialised: ' +
                                 str(candidate_queue['unmaterialised_project_records']) +
                                 '; unsupported layouts: ' +
                                 str(candidate_queue['unsupported_project_records']) +
                                 '. Final unique publications: UNKNOWN.').props(
                                     'data-testid=candidate-queue-counts')
                        ui.label('Showing ' + str(len(candidate_queue['rows'])) +
                                 ' candidate pairs (up to 20). This is exact-key '
                                 'or previous-receipt discovery, NOT exhaustive '
                                 'biomedical deduplication.').props(
                                     'data-testid=candidate-queue-page')
                        for entry in candidate_queue['rows']:
                            with ui.card():
                                ui.label('Possible source pair • ' +
                                         ' / '.join(s['source_name'] + ':' +
                                                   s['source_record_id']
                                                   for s in entry['sources'])).props(
                                                       'data-testid=candidate-queue-row')
                                ui.label('Matching original fields: ' +
                                         (', '.join(entry['matched_exact_fields'])
                                          if entry['matched_exact_fields'] else
                                          '(previous reviewer receipt only)') +
                                         ' • decision state ' +
                                         entry['candidate_status'] +
                                         ' • recorded pair decisions ' +
                                         str(entry['prior_decisions_recorded'])).props(
                                             'data-testid=candidate-queue-evidence')
                                for warning in entry['warnings']:
                                    ui.label('Candidate review warning: ' +
                                             warning).props(
                                                 'data-testid=candidate-queue-warning')
                                if entry['both_in_selected_run']:
                                    first, second = entry['retrieval_ids']
                                    queue_revision = candidate_queue['revision']
                                    ui.button(
                                        'Review this exact pair using existing safeguards',
                                        on_click=lambda a=first,b=second,r=queue_revision:
                                            act('candidate_queue_review',{
                                                'left':a,'right':b,'revision':r})).props(
                                                    'data-testid=candidate-queue-review')
                                else:
                                    ui.label('Cross-run possible match. Currently '
                                             'READ-ONLY: a separately validated '
                                             'cross-run decision workflow is still '
                                             'required.').props(
                                                 'data-testid=candidate-queue-crossrun')
                        if candidate_queue['next_after_pair'] is not None:
                            next_pair = candidate_queue['next_after_pair']
                            queue_revision = candidate_queue['revision']
                            ui.button('Next 20 project candidate pairs (OFFLINE)',
                                      on_click=lambda p=next_pair,r=queue_revision:
                                          act('candidate_queue_next',{
                                              'cursor':p,'revision':r})).props(
                                                  'data-testid=candidate-queue-next')
                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('Provisional publication results — local, paginated, '
                             'and NOT a verified deduplicated master list.').props(
                                 'data-testid=publication-heading')
                    ui.label('Each saved source record initially represents a '
                             'separate REVIEW-REQUIRED publication identity. '
                             'Identical titles, digital object identifiers or '
                             'supplement references are NOT merged automatically. '
                             'Original provider records, counts and memberships '
                             'remain unchanged. No abstracts or source metadata '
                             'are exported by this view.').props(
                                 'data-testid=publication-scope')
                    ui.button('Refresh provisional results from first page (OFFLINE)',
                              on_click=lambda: act('publication_refresh')).props(
                                  'data-testid=publication-refresh')
                    if state['publication_error'] is not None:
                        ui.label('Publication results or preparation cannot be '
                                 'verified against the current local source/identity '
                                 'evidence. Refresh and inspect original records; '
                                 'do not claim success or retry a stale confirmation.').props(
                                     'data-testid=publication-error')
                    offer = state['publication_materialisation_offer']
                    if offer is not None:
                        ui.label('Unsent local preparation: ' +
                                 str(offer['batch_count']) +
                                 ' individual source records, out of ' +
                                 str(offer['unmaterialised_retrievals']) +
                                 ' still without publication identities. '
                                 'This creates only provisional REVIEW-REQUIRED '
                                 'identities; it sends ZERO provider requests and '
                                 'makes NO deduplication decision.').props(
                                     'data-testid=publication-materialise-preview')
                        if offer['batch_count']:
                            researcher = ui.input('Researcher recording provisional '
                                                  'materialisation',value='Researcher')
                            ui.button('CONFIRM one bounded local identity batch',
                                      on_click=lambda box=researcher:
                                          act('publication_materialise_confirm',box.value)).props(
                                              'data-testid=publication-materialise-confirm')
                        else:
                            ui.label('All currently saved source records in this '
                                     'run already have identity links. This does NOT '
                                     'mean duplicates have been resolved.').props(
                                         'data-testid=publication-materialise-none')
                        ui.button('Dismiss unsent preparation',on_click=lambda:
                                  act('publication_materialise_dismiss')).props(
                                      'data-testid=publication-materialise-dismiss')
                    else:
                        ui.button('Preview creation of up to 64 review-required '
                                  'identities from saved records (NO NETWORK)',
                                  on_click=lambda: act('publication_materialise_offer')).props(
                                      'data-testid=publication-materialise-offer')
                    last = state['publication_materialisation_last_outcome']
                    if last is not None:
                        ui.label('Last confirmed local batch: ' +
                                 str(last['materialised_in_batch']) +
                                 ' identity hypotheses committed; unmaterialised '
                                 'source records remaining at receipt: ' +
                                 str(last['unmaterialised_retrievals_remaining']) +
                                 '. Refresh to read CURRENT results. Verified '
                                 'global unique publications: UNKNOWN.').props(
                                     'data-testid=publication-materialise-outcome')
                    ui.separator()
                    ui.label('Optional bounded 128-record preparation — '
                             'ONE explicit approval, at most TWO original '
                             '64-record transactions. The first transaction '
                             'may have committed even if the second fails. '
                             'NO automatic duplicate merging or further '
                             'batch execution.').props(
                                 'data-testid=publication-window-heading')
                    if state['publication_window_error'] is not None:
                        ui.label('Two-batch preparation is not currently verified. '
                                 'No success can be inferred from an uncertain '
                                 'worker response. Inspect the original saved '
                                 'project before preparing anything else.').props(
                                     'data-testid=publication-window-error')
                    if state['publication_window_reinspect_required']:
                        ui.label('RECOVERY REQUIRED: zero, one or two 64-record '
                                 'batches may have committed. The previous '
                                 'approval was consumed and MUST NOT be retried.').props(
                                     'data-testid=publication-window-recovery')
                        ui.button('Inspect durable source/identity counts '
                                  'after interrupted preparation (READ-ONLY)',
                                  on_click=lambda:
                                      act('publication_window_inspect')).props(
                                          'data-testid=publication-window-reinspect')
                    else:
                        window_offer=state['publication_window_offer']
                        if window_offer is not None:
                            ui.label('UNSENT original-source approval: ' +
                                     str(window_offer['proposed_source_records']) +
                                     ' review-required provisional identities in ' +
                                     str(window_offer['batch_count']) +
                                     ' separate commits of up to 64 each. ' +
                                     'Currently unmaterialised originals: ' +
                                     str(window_offer['unmaterialised_retrievals']) +
                                     '. NO provider requests, verified unique '
                                     'count or unattended processing.').props(
                                         'data-testid=publication-window-preview')
                            if window_offer['proposed_source_records'] > 0:
                                author=ui.input('Researcher explicitly authorising '
                                                'THIS finite original-source window',
                                                value='').props('data-testid=publication-window-actor')
                                ui.button('CONFIRM this finite two-batch '
                                          'publication preparation',
                                          on_click=lambda field=author:
                                              act('publication_window_confirm',
                                                  field.value)).props(
                                                      'data-testid=publication-window-confirm')
                            else:
                                ui.label('No unmaterialised originals remain '
                                         'in this run. This does NOT indicate '
                                         'completed deduplication.').props(
                                             'data-testid=publication-window-no-work')
                            ui.button('Dismiss two-batch offer without writing',
                                      on_click=lambda:
                                          act('publication_window_dismiss')).props(
                                              'data-testid=publication-window-dismiss')
                        else:
                            ui.button('Preview up to 128 new provisional '
                                      'identities in one finite consent window '
                                      '(READ-ONLY)',
                                      on_click=lambda:
                                          act('publication_window_offer')).props(
                                              'data-testid=publication-window-offer')
                            ui.button('Inspect current unmaterialised originals '
                                      '(READ-ONLY)',
                                      on_click=lambda:
                                          act('publication_window_inspect')).props(
                                              'data-testid=publication-window-inspect')
                    last_window=state['publication_window_last_outcome']
                    if last_window is not None:
                        ui.label('Last independently verified local two-batch '
                                 'receipt: ' +
                                 str(last_window['materialised_in_session']) +
                                 ' independent provisional identities in ' +
                                 str(last_window['committed_batches']) +
                                 ' original transactions. Originals still '
                                 'unmaterialised at receipt: ' +
                                 str(last_window['unmaterialised_retrievals_remaining']) +
                                 '. Verified unique publications: UNKNOWN.').props(
                                     'data-testid=publication-window-outcome')
                    inspected_window=state['publication_window_last_inspection']
                    if inspected_window is not None:
                        ui.label('Durable source records: ' +
                                 str(inspected_window['source_records_retained']) +
                                 '; remaining without publication identities: ' +
                                 str(inspected_window['unmaterialised_retrievals']) +
                                 '; current provisional publication hypotheses: ' +
                                 str(inspected_window['existing_publication_hypotheses']) +
                                 '. Inspection did NOT authorise any change.').props(
                                     'data-testid=publication-window-inspection')
                    view = state['publication_page']
                    if view is None:
                        ui.label('No CURRENT results snapshot displayed. Choose '
                                 'Refresh; a saved record without an identity '
                                 'is reported separately, never silently omitted.')
                    else:
                        ui.label('Current run: saved source-record metadata ' +
                                 str(view['retrieved_source_records']) +
                                 '; provisional linked publication identities ' +
                                 str(view['provisional_publication_identities']) +
                                 '; still unmaterialised ' +
                                 str(view['unmaterialised_source_records']) +
                                 '; VERIFIED global unique publications: UNKNOWN.').props(
                                     'data-testid=publication-counts')
                        ui.label('This page has ' + str(len(view['rows'])) +
                                 ' entries, maximum 20. All remain provisional; '
                                 'unseen later pages are not zero results.').props(
                                     'data-testid=publication-page-status')
                        if not view['rows']:
                            ui.label('No provisional identities on this page. '
                                     'Inspect any unmaterialised records before '
                                     'interpreting an empty view.').props(
                                         'data-testid=publication-page-empty')
                        for row in view['rows']:
                            with ui.card():
                                ui.label('Publication hypothesis: ' +
                                         row['publication_id']).props(
                                             'data-testid=publication-row')
                                ui.label('Title: ' +
                                         (row['title'] if row['title'] is not None
                                          else '(not resolved from original sources)') +
                                         ' • title evidence: ' + row['title_status']).props(
                                             'data-testid=publication-title')
                                ui.label('Sources: ' + ', '.join(row['source_names']) +
                                         '; source records ' +
                                         str(row['original_source_records_in_run']) +
                                         '; review-required links ' +
                                         str(row['review_required_links']) +
                                         '; confirmed individual links ' +
                                         str(row['confirmed_links']) +
                                         '; final identity NOT VERIFIED.').props(
                                             'data-testid=publication-provisional')
                                for membership in row['group_memberships']:
                                    ui.label('Original group membership: ' +
                                             membership['group_label'] +
                                             ' • ' + membership['source_name']).props(
                                                 'data-testid=publication-membership')
                                pid = row['publication_id']
                                revision = view['revision']
                                ui.button('Inspect original source evidence',
                                          on_click=lambda pid=pid, revision=revision:
                                              act('publication_detail',
                                                  {'publication_id':pid,'revision':revision})).props(
                                                      'data-testid=publication-detail-open')
                        if view['next_after_publication_id'] is not None:
                            cursor = view['next_after_publication_id']
                            revision = view['revision']
                            ui.button('Next 20 provisional publications (OFFLINE)',
                                      on_click=lambda cursor=cursor, revision=revision:
                                          act('publication_next',
                                              {'cursor':cursor,'revision':revision})).props(
                                                  'data-testid=publication-next')
                        detail = state['publication_detail']
                        if detail is not None:
                            ui.separator()
                            ui.label('LOCAL SOURCE PROVENANCE — ' +
                                     detail['publication']['publication_id'] +
                                     '. A displayed value is not validation of '
                                     'bibliographic identity or export rights.').props(
                                         'data-testid=publication-detail-heading')
                            for omitted in detail['suppressed_chosen_fields']:
                                ui.label('Saved field ' + omitted['field'] +
                                         ' deliberately WITHHELD: its source path '
                                         'is not a validated citation-only path; '
                                         'it may refer to protected abstract '
                                         'or other non-display content.').props(
                                             'data-testid=publication-field-withheld')
                            for chosen in detail['chosen_source_fields']:
                                ui.label('Researcher-chosen ' + chosen['field'] +
                                         ' = ' + str(chosen['value']) +
                                         ' • state ' + chosen['status'] +
                                         ' • source retrieval ' +
                                         chosen['retrieval_id']).props(
                                             'data-testid=publication-chosen-field')
                            for source in detail['source_retrievals']:
                                ui.label('Original source: ' + source['source_name'] +
                                         ' • provider identifier ' + source['source_record_id'] +
                                         ' • link status ' + source['decision_status'] +
                                         ' • abstract availability ' +
                                         source['abstract_status'] +
                                         ' • rights ' + source['rights_status']).props(
                                             'data-testid=publication-source-detail')
                                for field in source['fields']:
                                    ui.label(field['field'] + ': ' +
                                             ('(unavailable)' if field['value'] is None
                                              else field['value']) +
                                             ' • original field status ' +
                                             field['status'] +
                                             ' • source path ' +
                                             str(field['source_path'])).props(
                                                 'data-testid=publication-field-detail')
                                for membership in source['memberships']:
                                    ui.label('Source/group provenance: ' +
                                             membership['group_label'] +
                                             ' • original query state ' +
                                             membership['query_status']).props(
                                                 'data-testid=publication-source-membership')
                                if source['included_in_selected_run']:
                                    current_retrieval = source['retrieval_id']
                                    ui.button(
                                        'Select this exact source record for duplicate comparison',
                                        on_click=lambda rid=current_retrieval:
                                            act('candidate_choose_source', rid)).props(
                                                'data-testid=candidate-choose-source')
                                    if source['decision_status'] == 'confirmed_match':
                                        ui.button(
                                            'Preview reversal of CURRENT association (OFFLINE)',
                                            on_click=lambda rid=current_retrieval:
                                                act('candidate_reversal_offer', rid)).props(
                                                    'data-testid=candidate-reversal-offer')
                            ui.label('Full abstract display and permission-aware '
                                     'bibliography export remain future work. '
                                     'No duplicate-candidate decision has been '
                                     'made by reading this page.').props(
                                         'data-testid=publication-not-exported')
                        if state['candidate_error'] is not None:
                            ui.label('Candidate decision outcome cannot be verified. '
                                     'Reopen the current source receipts and audit '
                                     'history; do NOT resend an old confirmation.').props(
                                         'data-testid=candidate-error')
                        if state['candidate_first'] is not None:
                            ui.label('First selected exact source retrieval: ' +
                                     state['candidate_first']['retrieval_id'] +
                                     '. Open another publication source detail '
                                     'on THIS page and select a second record.').props(
                                         'data-testid=candidate-first')
                        pair = state['candidate_offer']
                        if pair is not None:
                            ui.separator()
                            ui.label('Publication comparison — explicit HUMAN REVIEW. '
                                     'No automatic DOI/title/supplement merge. '
                                     'Every matching field is only evidence.').props(
                                         'data-testid=candidate-heading')
                            for source in pair['sources']:
                                ui.label('Reviewed source: ' + source['source_name'] +
                                         ' • ' + source['source_record_id'] +
                                         ' • retrieval ' + source['retrieval_id']).props(
                                             'data-testid=candidate-source')
                            for field in pair['comparison']:
                                ui.label(field['field'] + ': ' +
                                         field['comparison'] +
                                         ' • source A ' + str(field['left']['value']) +
                                         ' (' + field['left']['status'] + ')' +
                                         ' • source B ' + str(field['right']['value']) +
                                         ' (' + field['right']['status'] + ')').props(
                                             'data-testid=candidate-comparison')
                            for warning in pair['warnings']:
                                ui.label('WARNING — ' + warning).props(
                                    'data-testid=candidate-warning')
                            ui.label('Pair status: ' + pair['status'] +
                                     '; previous decision receipts: ' +
                                     str(pair['prior_decision_count']) +
                                     '; earlier receipts not shown here: ' +
                                     str(pair['prior_decisions_omitted']) +
                                     '. The full immutable history remains in the project.')
                            for previous in pair['recent_decisions']:
                                ui.label('Previous audit ' + str(previous['event_id']) +
                                         ': ' + previous['status'] + ' • ' +
                                         previous['actor'] + ' • ' +
                                         previous['evidence']).props(
                                             'data-testid=candidate-audit')
                            reviewer = ui.input('Researcher recording this decision',
                                                value='Researcher')
                            rationale = ui.input(
                                'Specific bibliographic evidence or reason '
                                'for this decision', value='')
                            acknowledge = ui.checkbox(
                                'I reviewed and acknowledge every displayed '
                                'comparison warning', value=False)
                            if not pair['pair_already_associated']:
                                first_source, second_source = pair['retrieval_ids']
                                ui.button('CONFIRM MATCH: associate first source '
                                          'with second publication', on_click=
                                          lambda rid=first_source, box=reviewer,
                                          note=rationale, ack=acknowledge:
                                          act('candidate_review_decide', {
                                              'decision':'confirmed_match',
                                              'move_retrieval_id':rid,
                                              'actor':box.value,'evidence':note.value,
                                              'acknowledged':ack.value})).props(
                                                  'data-testid=candidate-match-first')
                                ui.button('CONFIRM MATCH: associate second source '
                                          'with first publication', on_click=
                                          lambda rid=second_source, box=reviewer,
                                          note=rationale, ack=acknowledge:
                                          act('candidate_review_decide', {
                                              'decision':'confirmed_match',
                                              'move_retrieval_id':rid,
                                              'actor':box.value,'evidence':note.value,
                                              'acknowledged':ack.value})).props(
                                                  'data-testid=candidate-match-second')
                                ui.button('CONFIRM NOT THE SAME PUBLICATION '
                                          '(no source record moved)', on_click=
                                          lambda box=reviewer, note=rationale,
                                          ack=acknowledge:
                                          act('candidate_review_decide', {
                                              'decision':'rejected_match',
                                              'move_retrieval_id':None,
                                              'actor':box.value,'evidence':note.value,
                                              'acknowledged':ack.value})).props(
                                                  'data-testid=candidate-reject')
                            else:
                                ui.label('Both records currently share one '
                                         'publication identity. Rejection requires '
                                         'a separate review of the CURRENT reversible '
                                         'association first.')
                            ui.button('Dismiss this uncommitted comparison',
                                      on_click=lambda:
                                      act('candidate_review_dismiss')).props(
                                          'data-testid=candidate-dismiss')
                        undo = state['reversal_offer']
                        if undo is not None:
                            ui.separator()
                            ui.label('Reversal PREVIEW only — retrieval ' +
                                     undo['retrieval_id'] +
                                     ', current association audit event ' +
                                     str(undo['association_event_id']) +
                                     '. Restores its original publication identity. '
                                     'No source metadata or audit event is deleted.').props(
                                         'data-testid=candidate-reversal-preview')
                            ui.label('Original association evidence: ' +
                                     undo['original_decision_evidence']).props(
                                         'data-testid=candidate-reversal-evidence')
                            reverser = ui.input(
                                'Researcher recording reversal', value='Researcher')
                            reason = ui.input(
                                'Reason for reversing current association', value='')
                            ui.button('CONFIRM reverse CURRENT association',
                                      on_click=lambda a=reverser, e=reason:
                                      act('candidate_reversal_confirm', {
                                          'actor':a.value,
                                          'evidence':e.value})).props(
                                              'data-testid=candidate-reversal-confirm')
                            ui.button('Dismiss unsent reversal', on_click=lambda:
                                      act('candidate_review_dismiss')).props(
                                          'data-testid=candidate-reversal-dismiss')
                        outcome = state['candidate_last_outcome']
                        if outcome is not None:
                            ui.label('Last decision independently reconciled '
                                     'against original SQLite audit event ' +
                                     str(outcome['verified_audit_event_id']) +
                                     ' • action ' + outcome['action'] +
                                     '. Final unique-publication count remains '
                                     'UNKNOWN; refresh source evidence for next review.').props(
                                         'data-testid=candidate-result')

                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('Bounded whole-run source coordination — '
                             'EXPLICIT CONFIRMATION required before ANY provider '
                             'request. Experimental, not unattended.').props(
                                 'data-testid=run-coordination-heading')
                    ui.label('Already prepared provider stages may run in sequence, '
                             'at most TWO stages per consent. The original source '
                             'services enforce the request budgets and stop on '
                             'unknown outcomes. Untouched PubMed queries still '
                             'require explicit Create Date coverage; unprepared '
                             'Web of Science queries still require separate '
                             'licensed metadata retention consent.')
                    if state['run_coordination_pending']:
                        ui.label('Supervised coordinator state: ' +
                                 state['run_coordination_worker_state'] +
                                 '; error: ' +
                                 str(state['run_coordination_worker_error'])).props(
                                     'data-testid=run-coordination-worker')
                        ui.label('Running does NOT imply provider access succeeded. '
                                 'An interrupted process or uncertain request '
                                 'must be inspected, never automatically repeated.')
                        progress=state['run_execution_board']
                        if progress is not None:
                            for item in progress['queries']:
                                ui.label(item['source_name'] + ' • ' +
                                         item['group_id'] + ' • ' +
                                         item['source_stage'] +
                                         ' • IDs saved ' +
                                         str(item['identifiers_retrieved']) +
                                         ' • metadata rows ' +
                                         str(item['metadata_records_retained'])).props(
                                             'data-testid=run-coordination-progress')
                        ui.button('Read durable run progress (NO provider call)',
                                  on_click=lambda: act('run_coord_poll')).props(
                                      'data-testid=run-coordination-poll')
                        if state['run_coordination_worker_state'] != 'running':
                            ui.button('Reconcile STOPPED source coordinator with '
                                      'original saved checkpoint evidence',
                                      on_click=lambda: act('run_coord_reconcile')).props(
                                          'data-testid=run-coordination-reconcile')
                    elif state['run_coordination_offer'] is not None:
                        offer=state['run_coordination_offer']
                        tasks=offer['tasks']
                        if tasks:
                            ui.label('Frozen, unsent work: ' + str(len(tasks)) +
                                     ' source stages. Maximum combined external '
                                     'HTTP requests: ' +
                                     str(offer['max_external_requests']) +
                                     '. Each original provider limiter may stop '
                                     'earlier due to quotas, network errors, '
                                     'count drift or an interrupted request.').props(
                                         'data-testid=run-coordination-budget')
                            for item in tasks:
                                ui.label('To execute after confirmation: ' +
                                         item['source_name'] + ' • group ' +
                                         item['group_id'] + ' • ' +
                                         item['action'] + ' • exact query ' +
                                         item['exact_query'] +
                                         ' • at most ' +
                                         str(item['max_requests']) +
                                         ' source requests.').props(
                                             'data-testid=run-coordination-proposal')
                            ui.label('One approval authorises ONLY the above '
                                     'displayed existing source stages. No '
                                     'new WoS retention is authorised, no '
                                     'filters are applied, and no provider '
                                     'quota revalidation is assumed. Your '
                                     'application must remain open.').props(
                                         'data-testid=run-coordination-consent')
                            ui.button('CONFIRM one bounded source-coordination session',
                                      on_click=lambda: act('run_coord_confirm')).props(
                                          'data-testid=run-coordination-confirm')
                        else:
                            ui.label('No already-authorised executable source '
                                     'stages are available with current local '
                                     'provider configuration. Complete the '
                                     'existing source-specific preparation or '
                                     'recovery actions first.').props(
                                         'data-testid=run-coordination-no-work')
                        for item in offer['preview']['blocked_tasks']:
                            ui.label('Manual prerequisite: ' +
                                     item['source_name'] + ' • ' +
                                     item['group_id'] + ' • ' +
                                     item['blocker']).props(
                                         'data-testid=run-coordination-blocked')
                        for item in offer['unavailable']:
                            ui.label('Missing local provider profile: ' +
                                     item['source_name'] + ' • ' +
                                     item['query_id']).props(
                                         'data-testid=run-coordination-no-profile')
                        ui.button('Cancel unsent run coordination',
                                  on_click=lambda: act('run_coord_dismiss')).props(
                                      'data-testid=run-coordination-dismiss')
                    else:
                        ui.button('Preview next eligible run-wide source jobs '
                                  '(OFFLINE, no source requests)',
                                  on_click=lambda: act('run_coord_offer')).props(
                                      'data-testid=run-coordination-offer')
                    if state['run_coordination_last_outcome'] is not None:
                        outcome=state['run_coordination_last_outcome']
                        ui.label('Last supervised session: ' +
                                 outcome['worker_state'] +
                                 '; planned stages ' +
                                 str(outcome['planned_step_count']) +
                                 '; dispatched stages ' +
                                 ('UNKNOWN' if
                                  outcome['dispatched_step_count'] is None
                                  else str(outcome['dispatched_step_count'])) +
                                 '; stop reason ' +
                                 str(outcome['stopped_reason']) +
                                 '; whole search verified: FALSE.').props(
                                     'data-testid=run-coordination-outcome')

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
                             '512 source requests, including count probes; '
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
                            if not cp['resume_budget_sufficient']:
                                ui.label('This existing checkpoint requires at least ' +
                                         str(cp['minimum_resume_requests']) +
                                         ' count verification / forward-progress requests. '
                                         'The GUI limit is 512, so another session '
                                         'would make NO progress. Use the original '
                                         'higher-budget PubMed checkpoint resume service '
                                         'outside this experimental GUI, or obtain a '
                                         'separate longer-worker implementation.').props(
                                             'data-testid=pubmed-source-budget-blocked')
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
                if state['selected_run_id'] is not None:
                    ui.separator()
                    ui.label('PubMed — full EFetch bibliographic metadata and abstracts '
                             '(experimental)').props('data-testid=pubmed-metadata-heading')
                    ui.label('This stage begins ONLY after the selected PubMed ESearch '
                             'identifier checkpoint reconciles. The source records and '
                             'abstract text are stored privately in the local project; '
                             'their copyright/redistribution status remains distinct. '
                             'Never confuse EFetch metadata with a complete two-source '
                             'research search.')
                    if state['pubmed_metadata_pending']:
                        ui.label('EFetch worker: ' +
                                 state['pubmed_metadata_worker_state'] +
                                 '; error: ' +
                                 str(state['pubmed_metadata_worker_error'])).props(
                                     'data-testid=pubmed-metadata-worker-state')
                        saved=state['pubmed_metadata']
                        if saved is not None:
                            ui.label('Saved full metadata: ' +
                                     str(saved['metadata_records_committed']) + ' / ' +
                                     ('UNKNOWN' if saved['identifier_count'] is None
                                      else str(saved['identifier_count'])) +
                                     ' identifier-linked records; abstract present: ' +
                                     str(saved['abstract_present']) +
                                     '; abstract not supplied in response: ' +
                                     str(saved['abstract_not_supplied'])).props(
                                         'data-testid=pubmed-metadata-progress')
                        else:
                            ui.label('No metadata observation yet. An already-sent '
                                     'request may have an uncertain outcome.')
                        ui.button('Refresh saved EFetch progress (NO HTTP)',
                                  on_click=lambda: act('pubmed_metadata_poll')).props(
                                      'data-testid=pubmed-metadata-poll')
                        if state['pubmed_metadata_worker_state'] != 'running':
                            ui.button('Reconcile terminal EFetch worker with original ledger',
                                      on_click=lambda: act(
                                          'pubmed_metadata_reconcile')).props(
                                              'data-testid=pubmed-metadata-reconcile')
                    elif state['pubmed_metadata_offer'] is not None:
                        proposed=state['pubmed_metadata_offer']
                        ui.label('Frozen exact PubMed All Fields query: ' +
                                 proposed['exact_query']).props(
                                     'data-testid=pubmed-metadata-exact-query')
                        ui.label('Original confirmed source identifiers: ' +
                                 str(proposed['identifier_count']) +
                                 '; already retained metadata records: ' +
                                 str(proposed['metadata_records_committed']) +
                                 '; still missing: ' +
                                 str(proposed['metadata_records_pending'])).props(
                                     'data-testid=pubmed-metadata-preview')
                        ui.label('One manually confirmed session sends up to ' +
                                 str(proposed['max_session_batches']) +
                                 ' EFetch requests of at most ' +
                                 str(proposed['max_batch_size']) +
                                 ' PubMed IDs each. Each successful batch is '
                                 'transactional and already saved IDs are '
                                 'skipped on a subsequent manual session. '
                                 'This preview sends NO request. An interrupted '
                                 'POST may consume quota without returning a '
                                 'verified result; it will NOT be automatically '
                                 'reissued. Keep the app open until the worker stops.')
                        ui.button('Cancel unsent EFetch metadata session',
                                  on_click=lambda: act('pubmed_metadata_dismiss')).props(
                                      'data-testid=pubmed-metadata-dismiss')
                        ui.button('CONFIRM bounded EFetch metadata and abstract retrieval',
                                  on_click=lambda: act('pubmed_metadata_confirm')).props(
                                      'data-testid=pubmed-metadata-confirm')
                    else:
                        current=state['pubmed_metadata']
                        for query in (state['report']['queries'] if
                                      state['report'] is not None else ()):
                            if query['source_name'] != 'pubmed':
                                continue
                            qid=query['query_id']
                            ui.button('Inspect saved EFetch metadata for ' +
                                      query['group_id'],
                                      on_click=lambda qid=qid: act(
                                          'pubmed_metadata_read',qid)).props(
                                              'data-testid=pubmed-metadata-read')
                            if (state['pubmed_profile_configured'] and
                                    state['pubmed_source'] is not None and
                                    state['pubmed_source']['query_id']==qid and
                                    state['pubmed_source']['checkpoint'] is not None and
                                    state['pubmed_source']['checkpoint'][
                                        'identifiers_reconciled']):
                                ui.button('Preview EFetch metadata session for ' +
                                          query['group_id'],
                                          on_click=lambda qid=qid: act(
                                              'pubmed_metadata_offer',qid)).props(
                                                  'data-testid=pubmed-metadata-offer')
                        if current is not None:
                            ui.label('EFetch source state: ' + current['status'] +
                                     '; metadata records: ' +
                                     str(current['metadata_records_committed']) +
                                     '; pending: ' +
                                     ('UNKNOWN' if current['metadata_records_pending']
                                      is None else str(
                                          current['metadata_records_pending']))).props(
                                              'data-testid=pubmed-metadata-saved')
                            ui.label('Abstract supplied: ' +
                                     str(current['abstract_present']) +
                                     '; not supplied by EFetch: ' +
                                     str(current['abstract_not_supplied']))
                            if current['metadata_records_reconciled']:
                                ui.label('Every previously reconciled PubMed identifier '
                                         'has a saved EFetch record. This does NOT '
                                         'establish complete abstract availability, '
                                         'global publication deduplication or a '
                                         'verified whole-run search.').props(
                                             'data-testid=pubmed-metadata-not-whole-run')
                        if not state['pubmed_profile_configured']:
                            ui.label('Without configured local PubMed contact '
                                     'details, saved EFetch progress is readable '
                                     'but new network sessions are unavailable.')
                    if state['pubmed_metadata_last_outcome'] is not None:
                        last=state['pubmed_metadata_last_outcome']
                        ui.label('Last EFetch worker: ' + last['worker_state'] +
                                 '; successfully committed batches: ' +
                                 ('UNKNOWN' if last['successful_batches'] is None
                                  else str(last['successful_batches'])) +
                                 '; whole run verified: FALSE').props(
                                     'data-testid=pubmed-metadata-outcome')
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
                                               'publication_window',
                                               'publication_window_lost_reply',
                                               'publication_results_large'), required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
