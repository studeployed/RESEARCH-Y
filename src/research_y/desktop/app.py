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

from research_y.desktop.actions import perform_action
from research_y.desktop.flow import ProjectFlowError, RealProjectFlow
from research_y.desktop.folders import NativeFolderError, select_from_native_window
from research_y.desktop.native import open_desktop_window
from research_y.desktop.project_panel import render_project_panel
from research_y.desktop.session import DesktopGuard, LaunchSession
from research_y.local_assistant import LocalAssistant, PACKAGE


def build_page(app, ui, flow, settings_warnings=()):
    lock = asyncio.Lock()

    @ui.page('/')
    def project_page():
        error = None
        study_edits = {}

        @ui.refreshable
        def panel():
            render_project_panel(ui, flow, act, native=True, error=error, study_edits=study_edits)

        async def act(action, value=None):
            nonlocal error
            if lock.locked():
                return
            async with lock:
                try:
                    if action in ('native_open', 'native_create', 'native_export'):
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
                except (ProjectFlowError, NativeFolderError) as exc:
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
        for warning in settings_warnings:
            ui.label(warning)
        ui.button('Open project folder', on_click=lambda: act('native_open')).props('data-testid=desktop-open')
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
    original_window = native_mode._open_window
    try:
        app.add_middleware(DesktopGuard, session=session)
        build_page(app, ui, flow, settings_warnings)
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
        from research_y.desktop.settings import source_profiles
        pubmed, starter, warnings = source_profiles()
        local = Path(os.environ['LOCALAPPDATA'])
        if not local.is_absolute():
            raise ValueError
        assistant = LocalAssistant(local / 'RESEARCH-Y' / 'models' / PACKAGE)
        flow = RealProjectFlow(recent_parent=local / 'RESEARCH-Y', pubmed_profile=pubmed, wos_profile=starter,
                               local_assistant=assistant)
        run_desktop(flow, settings_warnings=warnings)
    except Exception:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, 'RESEARCH-Y could not start. Check the desktop installation, WebView2 runtime, '
            'and saved source settings.', 'RESEARCH-Y', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
