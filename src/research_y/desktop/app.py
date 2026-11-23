"""Windows GUI entry point for the local RESEARCH-Y application."""
from __future__ import annotations

import asyncio
from importlib.metadata import version
from importlib.resources import files
import multiprocessing
import os
from pathlib import Path
import secrets
import socket
import sys
import webbrowser
from contextlib import asynccontextmanager
from research_y.desktop.feedback import explain, SUCCESS

from research_y.desktop.actions import perform_action
from research_y.desktop.flow import ProjectFlowError, RealProjectFlow
from research_y.desktop.folders import NativeFolderError, select_from_native_window, select_conference_document
from research_y.desktop.folders import select_project_archive, select_project_index
from research_y.desktop.folders import select_ris_document
from research_y.project_archive import ArchiveError
from research_y.desktop.native import open_desktop_window
from research_y.desktop.project_panel import render_project_panel
from research_y.desktop.workspace import ProjectWorkspace
from research_y.desktop.session import DesktopGuard, LaunchSession
from research_y.local_assistant import LocalAssistant, PACKAGE


HOME_STARTUP = """(() => {
    let interacted = false;
    for (const event of ['pointerdown', 'keydown', 'input', 'click']) {
        document.addEventListener(event, e => {
            const control = e.target.closest?.('button,input,textarea,select,a,[role=button]');
            if (control && !control.disabled) interacted = true;
        }, true);
    }
    setTimeout(() => {
        const open = document.querySelector('[data-testid=desktop-open]');
        if (interacted || (open?.getClientRects().length && !open.disabled &&
                           window.did_handshake && window.socket?.connected)) return;
        const key = 'research-y-startup-retries';
        const attempts = Number(sessionStorage.getItem(key) || 0);
        if (attempts < 2) {
            sessionStorage.setItem(key, String(attempts + 1));
            location.reload();
        }
    }, 12000);
})()"""


async def recover_missing_home(window, session, *, delay=12):
    """Retry the trusted home navigation if redemption never reached its HTTP route."""
    for _ in range(2):
        await asyncio.sleep(delay)
        stages = session.startup_stages()
        if stages["page_accepted"]:
            return
        if stages["session_redeemed"]:
            # NiceGUI's native navigation is a one-way, synchronous command.
            window.load_url(session.origin + "/")


def build_page(app, ui, flow, settings_warnings=()):
    from research_y.desktop.glossary import ExplainedUi
    ui = ExplainedUi(ui)
    resources = files('research_y.desktop')
    field_styles = resources.joinpath('forms.css').read_text(encoding='utf-8')
    quick_start = resources.joinpath('QUICK_START.md').read_text(encoding='utf-8')
    lock = asyncio.Lock()
    inference = asyncio.Lock()
    crossref = asyncio.Lock()
    provider = asyncio.Lock()

    @ui.page('/')
    def project_page():
        error = None
        study_edits = {}
        workspace = ProjectWorkspace()
        busy_count = 0

        @asynccontextmanager
        async def feedback(action):
            nonlocal busy_count
            busy_count += 1
            action_surface.props('inert aria-busy=true')
            launcher.props('inert aria-busy=true')
            action_status.set_text('Working…')
            action_status.classes(remove='error success', add='info')
            yield_ok = False
            outcome = {}
            try:
                yield outcome
                yield_ok = error is None
            finally:
                busy_count -= 1
                if not busy_count:
                    action_surface.props(remove='inert aria-busy')
                    launcher.props(remove='inert aria-busy')
                action_status.set_text(outcome.get('message') or (SUCCESS.get(action, 'Action finished.') if yield_ok else explain(error or 'operation_unavailable')))
                action_status.classes(remove='info error success', add='success' if yield_ok else 'error')
        # Run in the authenticated document. Native window RPC shares a response
        # queue with folder selection, so a background probe must never use it.
        if flow.project is None:
            ui.add_head_html('<script>' + HOME_STARTUP + '</script>')

        @ui.refreshable
        def panel():
            if flow.project is not None and workspace.project_id != str(flow.project.identifier):
                launcher.set_visibility(False)
                branding.set_visibility(False)
                picker_status.set_visibility(False)
                switch_project.set_text('Switch project')
                switch_project.set_visibility(True)
            render_project_panel(ui, flow, act, native=True, error=error, study_edits=study_edits,
                                 workspace=workspace)

        async def act(action, value=None):
            nonlocal error
            repeat_entry = action == 'setup_edit' and value.get('action') in ('add_group', 'add_term')
            project_picker = action in ('native_open', 'native_create', 'native_open_index')
            action_lock = lock
            if action in ("cloud_confirm", "local_suggest", "study_suggest", "native_install_local_model"):
                action_lock = inference
            elif action in ("pubmed_pilot_confirm","wos_pilot_confirm","wos_acquisition_tick_confirm"):
                action_lock = provider
            elif isinstance(value, dict) and (
                    (action == "specialist" and value.get("action") == "enrichment_lookup")
                    or (action == "master_results" and value.get("operation") == "lookup")):
                action_lock = crossref
            queue_selection = action == 'master_results' and value.get('operation') == 'select_page'
            if (lock.locked() or action_lock.locked()) and not queue_selection:
                action_status.set_text('Another action is in progress. Finish any open picker, or wait for the current action.')
                if action == 'save_question' or repeat_entry:
                    return 'Another action is in progress. Try Save question again in a moment.'
                if project_picker:
                    ui.notify('Another action is in progress. If a Windows picker is open, finish or cancel it first.')
                return
            async with action_lock, feedback(action) as outcome:
                error = None
                try:
                    if action == 'save_question':
                        project_id, values = value
                        if flow.project is None or project_id != str(flow.project.identifier):
                            error = 'The open project has changed. Open the intended project before saving.'
                            return 'The open project has changed. Open the intended project before saving.'
                        try:
                            await asyncio.to_thread(flow.edit_setup, 'heading', values)
                        except ProjectFlowError as exc:
                            error = str(exc)
                            if str(exc) == 'invalid_setup_input':
                                return 'Check your theme and name for length or unusual characters, then save again.'
                            return 'Could not confirm the save. ' + str(exc)
                        workspace.question_inputs = None
                    elif action == "native_install_local_model":
                        from research_y.install_local_assistant import download_local_package
                        if value is not True:
                            raise ProjectFlowError("Confirm the optional local model download.")
                        local = Path(os.environ["LOCALAPPDATA"])
                        if not local.is_absolute():
                            raise ProjectFlowError("Local installation folder is unavailable.")
                        ui.notify("Downloading and verifying the optional local assistant.")
                        try:
                            await asyncio.to_thread(download_local_package,local/"RESEARCH-Y"/"models")
                        except (OSError,ValueError):
                            raise ProjectFlowError("The download or verification failed. You can retry setup.") from None
                        await asyncio.to_thread(flow.set_local_mode,True)
                    elif action == "native_ris":
                        chosen = await select_ris_document(app.native.main_window)
                        if chosen is None:
                            outcome['message'] = 'Selection cancelled.'
                            return
                        await asyncio.to_thread(flow.open_native_ris,chosen)
                    elif action == "native_attach_pdf":
                        chosen = await select_conference_document(app.native.main_window,pdf=True)
                        if chosen is None:
                            outcome['message'] = 'Selection cancelled.'
                            return
                        await asyncio.to_thread(flow.attach_master_pdf,chosen,**value)
                    elif action == "native_diagnostics":
                        parent=await select_from_native_window(app.native.main_window)
                        if parent is None:
                            return
                        await asyncio.to_thread(flow.save_project_diagnostic,parent,value)
                        ui.notify("Saved project diagnostic report.")
                    elif action == "native_master_export":
                        folder = await select_from_native_window(app.native.main_window)
                        if folder is None:
                            outcome['message'] = 'Selection cancelled.'
                            return
                        await asyncio.to_thread(flow.export_master_to,folder,**value)
                    elif action == 'native_workbook_save':
                        folder = await select_from_native_window(app.native.main_window)
                        if folder is None:
                            outcome['message'] = 'Selection cancelled.'
                            return
                        await asyncio.to_thread(flow.save_workbook_to, folder, value['name'], reviewed=value['reviewed'])
                    elif action == 'native_workbook_continue':
                        current = next((r for r in flow.state()['exports'] if r['export_id'] == flow.state()['selected_export_id']), None)
                        folder = None
                        if current and current['destination_kind'] == 'external':
                            folder = await select_from_native_window(app.native.main_window)
                            if folder is None:
                                return
                        await asyncio.to_thread(flow.continue_workbook, folder)
                    elif action == 'native_open_output':
                        target = await asyncio.to_thread(flow.output_path, value is True)
                        await asyncio.to_thread(os.startfile, target)
                    elif action == "native_import_archive":
                        path = await select_project_archive(app.native.main_window)
                        if path is None:
                            return
                        parent = await select_from_native_window(app.native.main_window)
                        if parent is None:
                            return
                        await asyncio.to_thread(flow.import_native_archive,path,parent,directory_name=value or None)
                    elif action == "native_export_archive":
                        parent = await select_from_native_window(app.native.main_window)
                        if parent is None:
                            return
                        await asyncio.to_thread(flow.export_native_archive,parent,**value)
                    elif action in ("native_society_site","native_master_link"):
                        url = flow.official_society_url(**value) if action=="native_society_site" else flow.master_source_url(**value)
                        if not await asyncio.to_thread(webbrowser.open_new_tab, url):
                            raise ProjectFlowError("external_browser_unavailable")
                    elif action == "native_pdf":
                        chosen = await select_conference_document(app.native.main_window,pdf=True)
                        if chosen is None:
                            outcome['message'] = 'Selection cancelled.'
                            return
                        await asyncio.to_thread(flow.open_native_pdf,chosen,**value)
                    elif action == "native_conference":
                        chosen = await select_conference_document(app.native.main_window)
                        if chosen is None:
                            outcome['message'] = 'Selection cancelled.'
                            return
                        await asyncio.to_thread(flow.preview_native_conference, chosen, **value)
                    elif project_picker:
                        if action == 'native_create' and not (value or '').strip():
                            raise ProjectFlowError('Enter a new project name before choosing a folder.')
                        prompt = {
                            'native_create': 'Choose where to create the new project folder.',
                            'native_open': 'Choose the project folder containing project.ryproj.',
                            'native_open_index': 'Choose the project.ryproj file.',
                        }
                        picker_status.set_text(prompt[action])
                        if action == 'native_open_index':
                            index = await select_project_index(app.native.main_window)
                            folder = index.parent if index is not None else None
                        else:
                            folder = await select_from_native_window(app.native.main_window)
                        if folder is None:
                            error = None
                            picker_status.set_text('Selection cancelled.')
                            panel.refresh()
                            return
                        if action == 'native_create':
                            saved = await asyncio.to_thread(flow.create_native_parent, folder, value)
                            picker_status.set_text('Created and opened ' + saved['project']['name'] + '.')
                        else:
                            saved = await asyncio.to_thread(flow.open_native_folder, folder)
                            picker_status.set_text('Opened ' + saved['project']['name'] + '.')
                        workspace.question_inputs = None
                    elif action == 'native_export':
                        folder = await select_from_native_window(app.native.main_window)
                        if folder is not None:
                            await asyncio.to_thread(flow.offer_external_directory, folder)
                    else:
                        if action == 'setup_preview' and workspace.question_inputs is not None:
                            outcome['message'] = 'Save your question before previewing the search.'
                            ui.notify(outcome['message'])
                            return
                        await asyncio.to_thread(perform_action, flow, action, value)
                        if action in ('select_run', 'preflight_record'):
                            await asyncio.to_thread(flow.inspect_run_execution_board)
                        if action == 'run_board_step':
                            from research_y.desktop.collection_panel import TITLES
                            board = flow.state().get('run_execution_board') or {}
                            step = next((r['next_step'] for r in board.get('queries', []) if r['query_id'] == value['query_id']), None)
                            workspace.collection_section = TITLES.get(step)
                            workspace.stage = 'search'
                        if action == 'preflight_inspect':
                            workspace.review_open = True
                            workspace.review_saved = bool(flow.state()['preflight_report']['last_review'])
                        elif action == 'preflight_record':
                            workspace.review_saved = True
                        elif action == 'preflight_revise':
                            workspace.review_saved = False
                        if action == 'recent_open':
                            workspace.question_inputs = None
                        if repeat_entry:
                            workspace.entry_values[workspace.focus_entry] = ''
                        if action == 'setup_approve':
                            workspace.stage = 'search'
                        if action == 'cloud_offer':
                            workspace.open_sections[('plan', 'Optional search assistant')] = True
                        if action in ('candidate_queue_review', 'study_inspect', 'study_suggest'):
                            workspace.stage = 'results'
                            workspace.open_sections[('results', 'Provisional publications and comparisons')] = True
                    error = None
                except (ProjectFlowError, NativeFolderError, ArchiveError) as exc:
                    error = str(exc)
                except Exception:
                    error = 'operation_unavailable'
                if action == 'save_question' and error:
                    return 'Could not confirm the save. Check the project folder and try again.'
                if repeat_entry and error:
                    return 'Could not add this entry. Check for duplicate terms or unusual characters and try again.'
                if project_picker and error:
                    picker_status.set_text({
                        'native_dialog_unavailable': 'Windows could not open the picker. Try again.',
                        'invalid_project': 'Choose the project folder that contains project.ryproj.',
                        'project_creation_failed': 'Could not create the project. Check that the parent folder is writable and the new folder name is available.',
                        'native_selection_unsafe': 'Choose a local folder that the application can open directly.',
                    }.get(error, error))
                if not error or action not in ('save_question', 'setup_edit'):
                    panel.refresh()
                    if action == 'candidate_queue_review':
                        ui.timer(.1, lambda: ui.run_javascript("document.querySelector('[data-testid=candidate-heading]')?.scrollIntoView({block:'center'})"), once=True)
                    if action == 'run_board_step':
                        ui.timer(.1, lambda: ui.run_javascript("document.querySelector('[data-testid=collection-current]')?.scrollIntoView({block:'start'})"), once=True)
                if error:
                    ui.notify(explain(error), type='negative')
                return not bool(error)

        async def refresh_workers():
            state = flow.state()
            for pending, action in (
                ('manifest_save_running', 'manifest_poll'),
                ('wos_verification_pending', 'wos_verification_poll'),
                ('pubmed_source_pending', 'pubmed_identifier_poll'),
                ('pubmed_metadata_pending', 'pubmed_metadata_poll'),
                ('run_coordination_pending', 'run_coord_poll'),
            ):
                if state[pending]:
                    await act(action)
                    break

        ui.add_css(field_styles)
        branding = ui.label('RESEARCH-Y').classes('app-title').props('data-testid=desktop-title')
        branding.set_visibility(flow.project is None)
        with ui.element('div').classes('app-tools') as app_tools:
            with ui.expansion('How to use RESEARCH-Y', icon='help_outline').props('dense data-testid=quick-start'):
                ui.markdown(quick_start)
            from research_y.desktop.settings import render_settings
            render_settings(ui,flow)
        for warning in settings_warnings:
            ui.label(warning).classes('message warning')
        def toggle_launcher():
            launcher.set_visibility(not launcher.visible)
            switch_project.set_text('Close project chooser' if launcher.visible else 'Switch project')

        with app_tools:
            switch_project = ui.button('Switch project', on_click=toggle_launcher).props('flat data-testid=switch-project')
        switch_project.set_visibility(flow.project is not None)
        with ui.column().classes('project-launcher').props('data-testid=project-launcher') as launcher:
            with ui.element('div').classes('project-choices'):
                with ui.column():
                    ui.label('Open a project').classes('section-title')
                    open_folder = ui.button('Open project folder', on_click=lambda: act('native_open')).props('data-testid=desktop-open')
                    open_index = ui.button('Open project index file', on_click=lambda: act('native_open_index')).props(
                        'flat data-testid=desktop-open-index')
                with ui.column():
                    ui.label('Create a project').classes('section-title')
                    name = ui.input('New project name').props('data-testid=desktop-name')
                    create = ui.button('Create project in folder', on_click=lambda: act('native_create', name.value)).props(
                        'data-testid=desktop-create')
                    name.on('keydown.enter', lambda: act('native_create', name.value))
            with ui.expansion("Import project archive").props("dense data-testid=import-archive-panel"):
                restored_name = ui.input("New folder name (optional)")
                ui.button("Choose .researchy archive and destination folder",on_click=lambda:
                          act("native_import_archive",restored_name.value)).props("data-testid=import-archive")
        launcher.set_visibility(flow.project is None)
        picker_status = ui.label('Connecting to the desktop…').props('role=status aria-live=polite data-testid=project-picker-status')
        action_status = ui.label('').classes('message action-status').props('role=status aria-live=polite data-testid=action-status')
        project_buttons = (open_folder, open_index, create)
        for button in project_buttons:
            button.disable()

        def ready():
            for button in project_buttons:
                button.enable()
            if picker_status.text == 'Connecting to the desktop…':
                picker_status.set_text('')

        ui.context.client.on_connect(ready)
        with ui.column().props('data-testid=action-surface') as action_surface:
            panel()
        ui.timer(2, refresh_workers)


def run_desktop(flow, *, settings_warnings=()):
    """Start one authenticated native session and close all owned workers on exit."""
    from nicegui import ui, app
    from nicegui.native import native_mode

    if (version('nicegui'), version('pywebview')) != ('3.18.0', '6.2.1'):
        raise RuntimeError('desktop_dependency_version')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    launch = secrets.token_hex(32)
    session = LaunchSession(port, launch)
    flow.desktop_startup_stages = session.startup_stages
    original_window = native_mode._open_window
    try:
        app.add_middleware(DesktopGuard, session=session)
        build_page(app, ui, flow, settings_warnings)
        def start_recovery():
            task = asyncio.create_task(recover_missing_home(app.native.main_window, session))
            app.on_shutdown(task.cancel)
        app.on_startup(start_recovery)
        app.on_shutdown(session.revoke)
        app.on_shutdown(flow.close)
        native_mode._open_window = open_desktop_window
        app.native.window_args.update(url=session.origin + '/bootstrap#' + launch, text_select=True)
        app.native.settings.update(ALLOW_FILE_URLS=False, ALLOW_DOWNLOADS=False,
                                   OPEN_EXTERNAL_LINKS_IN_BROWSER=False)
        app.native.start_args.update(gui='edgechromium', private_mode=True, debug=False)
        ui.run(title='RESEARCH-Y', host='127.0.0.1', port=port, native=True,
               window_size=(1200, 850), reload=False, show=False, on_air=None,
               tailwind=False, fastapi_docs=False, show_welcome_message=False,
               access_log=False, proxy_headers=False, uvicorn_logging_level='error')
    finally:
        native_mode._open_window = original_window
        session.revoke()
        flow.close()


def main():
    multiprocessing.freeze_support()
    if sys.platform != 'win32':
        raise SystemExit('The RESEARCH-Y desktop application requires Windows.')
    try:
        from research_y.desktop.settings import source_profiles, cloud_profile
        pubmed, starter, warnings = source_profiles()
        cloud, cloud_warnings = cloud_profile()
        local = Path(os.environ['LOCALAPPDATA'])
        if not local.is_absolute():
            raise ValueError
        assistant = LocalAssistant(local / 'RESEARCH-Y' / 'models' / PACKAGE)
        flow = RealProjectFlow(recent_parent=local / 'RESEARCH-Y', pubmed_profile=pubmed, wos_profile=starter,
                               local_assistant=assistant, cloud_assistant=cloud)
        run_desktop(flow, settings_warnings=warnings + cloud_warnings)
    except Exception:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, 'RESEARCH-Y could not start. Check the desktop installation, WebView2 runtime, '
            'and saved source settings.', 'RESEARCH-Y', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
