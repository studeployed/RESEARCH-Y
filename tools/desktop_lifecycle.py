"""Exercise the installed Windows application in two disposable native processes."""
from __future__ import annotations

import asyncio
from contextlib import closing
from hashlib import sha256
import json
import multiprocessing
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from research_y.projects import create_project
from research_y.storage import ApprovedTerm, StrategyGroup
from research_y.strategy_admission import commit_approved_strategy


async def wait_for(predicate, label, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(.1)
    raise RuntimeError(label)


def run_window(stage, workspace, folder, run_id):
    from nicegui import app, Client, ui
    from research_y.desktop import app as desktop
    from research_y.desktop.flow import RealProjectFlow

    flow = RealProjectFlow(recent_parent=workspace / 'recents')
    choices = iter([workspace, workspace / 'Redirected'])
    selections = asyncio.Queue()
    real_dialog = desktop.select_from_native_window
    passed = []
    tasks = []

    async def choose(window):
        if stage == 'save':
            return next(choices)
        class FixtureWindow:
            async def create_file_dialog(self, **options):
                options["directory"] = str(folder.parent)
                return await window.create_file_dialog(**options)

        selected = await real_dialog(FixtureWindow())
        selections.put_nowait(selected)
        return selected

    # Supply the failure fixture on the first launch. Observe the real native
    # picker result on reopening before issuing another native request.
    desktop.select_from_native_window = choose
    if stage == 'save':
        async def choose_index(window):
            return folder / 'project.ryproj'
        desktop.select_project_index = choose_index
    if stage == 'reopen':
        # Reproduce the observed title-only first document before the user acts.
        ui.add_head_html("""<script>
            if (!sessionStorage.getItem('fixture-partial-start')) {
                sessionStorage.setItem('fixture-partial-start', '1');
                const style = document.createElement('style');
                style.textContent = '[data-testid=desktop-open] {display:none !important}';
                document.head.appendChild(style);
            }
        </script>""", shared=True)

    async def js(expression):
        clients = [client for client in Client.instances.values() if client.has_socket_connection]
        if len(clients) != 1:
            raise RuntimeError('desktop_client_not_connected')
        return await asyncio.wait_for(clients[0].run_javascript(expression, timeout=8), timeout=9)

    async def visible(selector):
        key = json.dumps(selector)
        return await js(f"Boolean(document.querySelector({key})?.getClientRects().length)")

    async def click(selector):
        await wait_for(lambda: visible(selector), selector)
        await js(f"document.querySelector({json.dumps(selector)}).click(); true")

    async def fill(selector, value):
        await wait_for(lambda: visible(selector), selector)
        await js("(()=>{const box=document.querySelector(" + json.dumps(selector) + ");"
                 "box.value=" + json.dumps(value) + ";"
                 "box.dispatchEvent(new Event('input',{bubbles:true}));"
                 "box.dispatchEvent(new Event('change',{bubbles:true}));return true})()")
        await asyncio.sleep(.25)

    async def check_first_search_page():
        await click('[data-testid=quick-start] .q-item')
        guide = await js("document.querySelector('[data-testid=quick-start] .nicegui-markdown').innerText")
        if 'Save research heading' not in guide or 'Confirm one PubMed count-only request' not in guide:
            raise RuntimeError('first_search_guide_unavailable')
        await click('[data-testid=quick-start] .q-item')
        await fill('[data-testid=setup-theme] input, input[data-testid=setup-theme]', 'RV Failure')
        for width in (520, 1200):
            app.native.main_window.resize(width, 850)
            await wait_for(lambda: js(f'window.innerWidth {"<" if width == 520 else ">"} 650'), 'window_resize')
            await js("document.querySelector('[data-testid=setup-objectives] textarea, textarea[data-testid=setup-objectives]').focus(); true")
            clipped = await js("""(() => {
                const errors = [];
                for (const id of ['setup-theme','setup-objectives','setup-approver','setup-group-input']) {
                    const field = document.querySelector('[data-testid='+id+']').closest('.q-field');
                    const label = field.querySelector('.q-field__label');
                    const editor = field.querySelector('input, textarea');
                    const range = document.createRange();
                    range.selectNodeContents(label);
                    const text = range.getBoundingClientRect(), box = label.getBoundingClientRect();
                    if (text.left < box.left-1 || text.right > box.right+1 ||
                        box.right > document.documentElement.clientWidth+1 || box.left < 0 ||
                        text.bottom > editor.getBoundingClientRect().top+1) errors.push(id);
                }
                return errors;
            })()""")
            if clipped:
                raise RuntimeError(f'clipped or overlapping field labels at width {width}: {clipped}')
        print('Checked first-search guide and labelled fields at narrow and wide window sizes.', flush=True)

    async def observe():
        try:
            async def ready():
                try:
                    return await js("Boolean(window.did_handshake && window.socket?.connected && "
                                    "document.querySelector('[data-testid=desktop-open]')?.getClientRects().length)")
                except (TimeoutError, RuntimeError):
                    return False
            await wait_for(ready, 'desktop_start', timeout=55)
            if flow.state()['project'] is not None or flow.state()['selected_run_id'] is not None:
                raise RuntimeError('implicit_project_selection')
            if stage == 'save':
                await fill('[data-testid=desktop-name] input, input[data-testid=desktop-name]', 'Created in desktop')
                await click('[data-testid=desktop-create]')
                await wait_for(lambda: visible('[data-testid=open-recent]'), 'native_create')
                await check_first_search_page()
                active = flow.state()['project']['project_id']
                await click('[data-testid=desktop-open]')
                await wait_for(lambda: visible('[data-testid=operation-error]'), 'redirected_project_rejection')
                message = await js("document.querySelector('[data-testid=operation-error]').textContent")
                if 'invalid_project' not in message or flow.state()['project']['project_id'] != active:
                    raise RuntimeError('redirected_project_selection')
            if stage == 'reopen':
                if await js("sessionStorage.getItem('research-y-startup-retries')") != "1":
                    raise RuntimeError('partial_start_not_recovered')
                chooser = runpy.run_path(str(Path(__file__).with_name("windows_folder_dialog.py")))
                children = {child.pid for child in multiprocessing.active_children() if child.daemon}
                for choice in (None, folder):
                    print('Opening native picker for ' + ('cancel' if choice is None else 'selection'), flush=True)
                    await click('[data-testid=desktop-open]')
                    await asyncio.to_thread(chooser["choose_fixture_folder"], children, choice)
                    selected = await asyncio.wait_for(selections.get(), timeout=10)
                    if ((choice is None and selected is not None) or
                            (choice is not None and (selected is None or not selected.samefile(choice)))):
                        raise RuntimeError('native_folder_choice_mismatch')
                    if choice is None:
                        if flow.state()['project'] is not None:
                            raise RuntimeError('cancel_selected_project')
                print('Cancelled and selected the relocated project in the native folder dialog.', flush=True)
            else:
                await click('[data-testid=desktop-open-index]')
            await click('[data-testid=select-run]')
            await click('[data-testid=society-panel] .q-item')
            await fill('[data-testid=society-terms] textarea, textarea[data-testid=society-terms]', 'ECMO')
            await click('[data-testid=society-search]')
            await wait_for(lambda: visible('[data-testid=society-library]'), 'official_library')
            if stage == 'save':
                await fill('[data-testid=society-actor] input, input[data-testid=society-actor]', 'Fixture researcher')
                await fill('[data-testid=society-name] input, input[data-testid=society-name]', 'Fixture Society')
                await fill('[data-testid=society-url] input, input[data-testid=society-url]', 'https://society.example')
                await click('[data-testid=society-save]')
                await wait_for(lambda: visible('[data-testid=current-society]'), 'society_saved')
            directory = flow.state()['specialist']['directory']
            if [entry['name'] for entry in directory] != ['Fixture Society']:
                raise RuntimeError('project_society_directory_mismatch')
            await click('[data-testid=master-panel] .q-item')
            await click('[data-testid=master-refresh]')
            await wait_for(lambda: visible('[data-testid=master-table]'), 'accessible_master_table')
            if flow.state()['master_results']['total'] != 0:
                raise RuntimeError('unexpected_fixture_publications')
            await click('[data-testid=manifest-panel] .q-item')
            if flow.state()['selected_run_id'] != run_id:
                raise RuntimeError('wrong_selected_run')
            if stage == 'save':
                await fill('[data-testid=manifest-actor] input, input[data-testid=manifest-actor]', 'Fixture researcher')
                await click('[data-testid=manifest-preview]')
                await click('[data-testid=manifest-confirm]')
                await click('[data-testid=manifest-save]')
            else:
                await click('[data-testid=manifest-history]')
                await click('[data-testid=manifest-inspect]')
                await click('[data-testid=manifest-check-file]')
            await wait_for(lambda: visible('[data-testid=manifest-file-verified]'), 'verified_workbook', timeout=65)
            result = flow.state()['manifest_save_result']
            if not result['audited_publication_success']:
                raise RuntimeError('missing_publication_receipt')
            (workspace / f'{stage}-verified.json').write_text(json.dumps({
                'run_id': result['run_id'], 'export_id': result['export_id'],
                'publication_receipt_id': result['publication_receipt_id'],
            }), encoding='utf-8')
            passed.append(True)
        except Exception as error:
            print(f'Native {stage} stage failed: {type(error).__name__}: {error}', flush=True)
            if hasattr(flow,"desktop_startup_stages"):
                print("Local startup stages:",flow.desktop_startup_stages(),flush=True)
        finally:
            try:
                app.native.main_window.destroy()
            except RuntimeError:
                app.shutdown()

    def start():
        tasks.append(asyncio.create_task(observe()))

    app.on_startup(start)
    desktop.run_desktop(flow)
    if not passed:
        raise RuntimeError('native_lifecycle_incomplete')


def main():
    if len(sys.argv) == 5:
        stage, workspace, folder, run_id = sys.argv[1:]
        run_window(stage, Path(workspace), Path(folder), run_id)
        return
    from openpyxl import load_workbook

    with tempfile.TemporaryDirectory(prefix='ry-desktop-') as directory:
        workspace = Path(directory)
        project = create_project(workspace, 'Native workbook fixture')
        run = commit_approved_strategy(
            project, request_id=str(uuid4()), theme='Offline desktop acceptance', approved_by='Fixture',
            groups=(StrategyGroup('g1', 'Group', (ApprovedTerm('ECMO', 'researcher', True),)),),
            approval_confirmed=True)
        folder = project.root
        redirected = create_project(workspace, 'Redirected')
        data = redirected.root / 'data'
        data.rename(redirected.root / 'original-data')
        if sys.platform == 'win32':
            from _winapi import CreateJunction
            CreateJunction(str(folder / 'exports'), str(data))
        else:
            data.symlink_to(folder / 'exports', target_is_directory=True)
        filename = f'provenance-{run.run_id}.xlsx'
        checksums = []
        observations = []
        for stage in ('save', 'reopen'):
            flags = ["-I", "-B"] if sys.flags.isolated else []
            subprocess.run([sys.executable, *flags, str(Path(__file__).resolve()), stage, str(workspace), str(folder),
                            run.run_id], timeout=210, check=True)
            observation = json.loads((workspace / f'{stage}-verified.json').read_text(encoding='utf-8'))
            if observation['run_id'] != run.run_id or not observation['publication_receipt_id']:
                raise RuntimeError('native_receipt_mismatch')
            observations.append(observation)
            artifact = folder / 'exports' / filename
            checksums.append(sha256(artifact.read_bytes()).hexdigest())
            with closing(load_workbook(artifact, read_only=True)) as workbook:
                if dict(list(workbook['Evidence & Limits'].values)[3:])['Report status'] != 'INCOMPLETE':
                    raise RuntimeError('incorrect_workbook_status')
            if stage == 'save':
                relocated = workspace / 'relocated'
                folder.rename(relocated)
                folder = relocated
        if checksums[0] != checksums[1] or observations[0] != observations[1]:
            raise RuntimeError('relocated_workbook_changed')
        print('Passed native create, select, save, restart, relocate and independent workbook verification.')


if __name__ == '__main__':
    main()
