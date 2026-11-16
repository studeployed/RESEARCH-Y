"""Windows GUI entry point for the local RESEARCH-Y application."""
from __future__ import annotations

import asyncio
from importlib.metadata import version
import multiprocessing
import os
from pathlib import Path
import secrets
import socket
import sys
import webbrowser

from research_y.desktop.actions import perform_action
from research_y.desktop.flow import ProjectFlowError, RealProjectFlow
from research_y.desktop.folders import NativeFolderError, select_from_native_window, select_conference_document
from research_y.desktop.folders import select_project_archive, select_project_index
from research_y.desktop.folders import select_ris_document
from research_y.project_archive import ArchiveError
from research_y.desktop.native import open_desktop_window
from research_y.desktop.project_panel import render_project_panel
from research_y.desktop.session import DesktopGuard, LaunchSession
from research_y.local_assistant import LocalAssistant, PACKAGE


HOME_STARTUP = """(() => {
    let interacted = false;
    for (const event of ['pointerdown', 'keydown', 'input', 'click']) {
        document.addEventListener(event, e => {
            if (e.target.closest?.('button,input,textarea,select,a,[role=button]')) interacted = true;
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
    lock = asyncio.Lock()

    @ui.page('/')
    def project_page():
        error = None
        study_edits = {}
        # Run in the authenticated document. Native window RPC shares a response
        # queue with folder selection, so a background probe must never use it.
        if flow.project is None:
            ui.add_head_html('<script>' + HOME_STARTUP + '</script>')

        @ui.refreshable
        def panel():
            render_project_panel(ui, flow, act, native=True, error=error, study_edits=study_edits)

        async def act(action, value=None):
            nonlocal error
            if lock.locked():
                return
            async with lock:
                try:
                    if action == "native_install_local_model":
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
                            return
                        await asyncio.to_thread(flow.open_native_ris,chosen)
                    elif action == "native_attach_pdf":
                        chosen = await select_conference_document(app.native.main_window,pdf=True)
                        if chosen is None:
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
                            return
                        await asyncio.to_thread(flow.export_master_to,folder,**value)
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
                            return
                        await asyncio.to_thread(flow.open_native_pdf,chosen,**value)
                    elif action == "native_conference":
                        chosen = await select_conference_document(app.native.main_window)
                        if chosen is None:
                            return
                        await asyncio.to_thread(flow.preview_native_conference, chosen, **value)
                    elif action == 'native_open_index':
                        index = await select_project_index(app.native.main_window)
                        if index is None:
                            return
                        await asyncio.to_thread(flow.open_native_folder, index.parent)
                    elif action in ('native_open', 'native_create', 'native_export'):
                        folder = await select_from_native_window(app.native.main_window)
                        if folder is None:
                            return
                        if action == 'native_open':
                            await asyncio.to_thread(flow.open_native_folder, folder)
                        elif action == 'native_create':
                            await asyncio.to_thread(flow.create_native_parent, folder, value)
                        else:
                            await asyncio.to_thread(flow.offer_external_directory, folder)
                    else:
                        await asyncio.to_thread(perform_action, flow, action, value)
                    error = None
                except (ProjectFlowError, NativeFolderError, ArchiveError) as exc:
                    error = str(exc)
                except Exception:
                    error = 'operation_unavailable'
                panel.refresh()

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

        ui.query('.nicegui-content').classes('q-pa-md q-mx-auto').style('max-width: 75rem; width: 100%')
        ui.label('RESEARCH-Y').classes('text-h4').props('data-testid=desktop-title')
        from research_y.desktop.settings import render_settings
        render_settings(ui,flow)
        for warning in settings_warnings:
            ui.label(warning)
        ui.button('Open project folder', on_click=lambda: act('native_open')).props('data-testid=desktop-open')
        ui.button('Open project index file', on_click=lambda: act('native_open_index')).props(
            'data-testid=desktop-open-index')
        with ui.expansion("Import project archive").props("data-testid=import-archive-panel"):
            restored_name = ui.input("New folder name (optional)")
            ui.button("Choose .researchy archive and destination folder",on_click=lambda:
                      act("native_import_archive",restored_name.value)).props("data-testid=import-archive")
        with ui.row().classes('items-center'):
            name = ui.input('New project name').props('data-testid=desktop-name')
            ui.button('Create project in folder', on_click=lambda: act('native_create', name.value)).props(
                'data-testid=desktop-create')
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
        app.native.window_args.update(url=session.origin + '/bootstrap#' + launch)
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
