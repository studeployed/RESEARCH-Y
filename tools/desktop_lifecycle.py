"""Exercise the installed Windows application in two disposable native processes."""
from __future__ import annotations

import asyncio
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
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
    from nicegui import app
    from research_y.desktop import app as desktop
    from research_y.desktop.flow import RealProjectFlow

    flow = RealProjectFlow(recent_parent=workspace / 'recents')
    choices = iter([workspace, folder] if stage == 'save' else [folder])
    passed = []
    tasks = []

    async def choose(window):
        return next(choices)

    # Replace only the OS dialog result in this test process. All rendered
    # controls, worker commands, files and project selection remain real.
    desktop.select_from_native_window = choose

    async def js(expression):
        return await asyncio.wait_for(app.native.main_window.evaluate_js(expression), timeout=8)

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

    async def observe():
        try:
            await wait_for(lambda: visible('[data-testid=desktop-title]'), 'desktop_start', timeout=55)
            if flow.state()['project'] is not None or flow.state()['selected_run_id'] is not None:
                raise RuntimeError('implicit_project_selection')
            if stage == 'save':
                await fill('[data-testid=desktop-name] input, input[data-testid=desktop-name]', 'Created in desktop')
                await click('[data-testid=desktop-create]')
                await wait_for(lambda: visible('[data-testid=open-recent]'), 'native_create')
            await click('[data-testid=desktop-open]')
            await click('[data-testid=select-run]')
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
        finally:
            try:
                await asyncio.wait_for(app.native.main_window.destroy(), timeout=10)
            except (TimeoutError, RuntimeError):
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
        filename = f'provenance-{run.run_id}.xlsx'
        checksums = []
        observations = []
        for stage in ('save', 'reopen'):
            subprocess.run([sys.executable, str(Path(__file__).resolve()), stage, str(workspace), str(folder),
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
