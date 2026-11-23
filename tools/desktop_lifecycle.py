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
    choices = iter([workspace, workspace / 'Created-in-desktop', workspace / 'Redirected'])
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
        if await visible('[data-testid=run-board-heading]') or await visible('[data-testid=export-id]'):
            raise RuntimeError('advanced_controls_visible_in_setup')
        await click('[data-testid=quick-start] .q-item')
        guide = await js("document.querySelector('[data-testid=quick-start] .nicegui-markdown').innerText")
        if 'Save question' not in guide or 'Confirm one PubMed count-only request' not in guide:
            raise RuntimeError('first_search_guide_unavailable')
        await click('[data-testid=quick-start] .q-item')
        await fill('[data-testid=setup-theme] input, input[data-testid=setup-theme]', 'RV Failure')
        await click('[data-testid=stage-details]')
        await click('[data-testid=stage-plan]')
        if await js("document.querySelector('[data-testid=setup-theme] input, input[data-testid=setup-theme]').value") != 'RV Failure':
            raise RuntimeError('navigating_away_discarded_unsaved_theme')
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
            layout_ok = await js("""(() => {
                const box = node => node.getBoundingClientRect();
                const page = box(document.querySelector('.nicegui-content'));
                const cards = [...document.querySelectorAll('.plan-card')].map(box);
                const button = box(document.querySelector('[data-testid=setup-save-heading]'));
                const fits = Math.abs(page.left - (document.documentElement.clientWidth - page.right)) < 2;
                const columns = window.innerWidth > 740 ? Math.abs(cards[0].top - cards[1].top) < 2
                                                        : cards[1].top >= cards[0].bottom;
                return fits && columns && button.width < cards[0].width * .85;
            })()""")
            if not layout_ok:
                raise RuntimeError(f'project layout or button width at {width}')
        print('Checked first-search guide and labelled fields at narrow and wide window sizes.', flush=True)
        objective = '[data-testid=setup-objectives] textarea, textarea[data-testid=setup-objectives]'
        reviewer = '[data-testid=setup-approver] input, input[data-testid=setup-approver]'
        await fill(objective, 'First objective')
        await click('[data-testid=setup-save-heading]')
        async def message_contains(text):
            return await js("document.querySelector('[data-testid=question-message]')?.textContent.includes("
                            + json.dumps(text) + ")")
        await wait_for(lambda: message_contains('Enter your name'), 'missing_researcher_feedback')
        await fill(reviewer, 'Fixture researcher')
        await click('[data-testid=setup-save-heading]')
        await wait_for(lambda: visible('[data-testid=question-saved]'), 'first_question_save')
        if await visible(objective) or flow.state()['saved_question']['objectives'] != 'First objective':
            raise RuntimeError('question_not_collapsed_or_persisted')
        await click('[data-testid=question-edit]')
        if await js('document.querySelector(' + json.dumps(objective) + ').value') != 'First objective':
            raise RuntimeError('saved_objective_missing_from_editor')
        await fill(objective, 'Revised objective')
        await fill(reviewer, 'x' * 2049)
        await click('[data-testid=setup-save-heading]')
        await wait_for(lambda: message_contains('Check your theme'), 'rejected_question_save')
        if await js('document.querySelector(' + json.dumps(objective) + ').value') != 'Revised objective':
            raise RuntimeError('failed_save_lost_edit')
        await fill(reviewer, 'Fixture researcher')
        await click('[data-testid=setup-save-heading]')
        await wait_for(lambda: visible('[data-testid=question-saved]'), 'revised_question_save')
        await click('[data-testid=switch-project]')
        await click('[data-testid=desktop-open]')
        await wait_for(lambda: js("document.querySelector('[data-testid=project-picker-status]').textContent "
                                  "=== 'Opened Created in desktop.'"), 'reopened_same_project')
        await wait_for(lambda: visible('[data-testid=question-saved]'), 'reopened_question')
        if await js("document.querySelector('.question-objectives').textContent") != 'Revised objective':
            raise RuntimeError('reopened_question_not_current')
        if await js("document.querySelector('.search-path [aria-current=step]').textContent") != 'Next · Add search terms':
            raise RuntimeError('incorrect_next_milestone')
        if await visible('[data-testid=desktop-open]'):
            await click('[data-testid=switch-project]')
        if flow.state()['strategy_draft']['approved_by'] != 'Fixture researcher':
            raise RuntimeError('reopened_project_lost_researcher')
        await check_keyboard_and_navigation()
        print('Checked inline save, failure, editing, reopening and next search milestone.', flush=True)

    async def check_keyboard_and_navigation():
        group_input = '[data-testid=setup-group-input] input, input[data-testid=setup-group-input]'
        term_input = '[data-testid^=setup-term-] input, input[data-testid^=setup-term-]'
        async def enter(selector):
            await js("document.querySelector(" + json.dumps(selector)
                     + ").dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true})); true")
        await fill(group_input, 'Example group')
        await enter(group_input)
        await wait_for(lambda: visible(term_input), 'keyboard_group_entry')
        for count, term in enumerate(('right ventricular failure', 'right heart failure'), start=1):
            await fill(term_input, term)
            await enter(term_input)
            async def added():
                return (len(flow.state()['strategy_draft']['groups'][0]['terms']) == count
                        and await js("document.activeElement === document.querySelector(" + json.dumps(term_input)
                                     + ") && document.activeElement.value === ''"))
            await wait_for(added, 'keyboard_term_entry_and_focus')
        await fill(term_input, 'right heart failure')
        await enter(term_input)
        await wait_for(lambda: js("document.querySelector(" + json.dumps(term_input) + ").disabled === false"),
                       'duplicate_term_retry')
        if len(flow.state()['strategy_draft']['groups'][0]['terms']) != 2:
            raise RuntimeError('duplicate_keyboard_term')
        if await js("document.querySelector(" + json.dumps(term_input) + ").value") != 'right heart failure':
            raise RuntimeError('duplicate_term_input_lost')
        for width in (520, 1200):
            app.native.main_window.resize(width, 850)
            await asyncio.sleep(.3)
            await js("window.scrollTo(0,document.body.scrollHeight); true")
            await asyncio.sleep(.3)
            if not await js("""(() => {
                const header = document.querySelector('.workspace-header').getBoundingClientRect();
                return header.top >= -1 && header.top < 2 && header.bottom < window.innerHeight / 2;
            })()"""):
                raise RuntimeError('sticky_navigation_out_of_view')
            if await js("getComputedStyle(document.querySelector('.question-theme')).userSelect") == 'none':
                raise RuntimeError('output_text_not_selectable')
        await js("window.scrollTo(0,0); true")
        await fill(term_input, '')
        await click('[data-testid=setup-preview]')
        await wait_for(lambda: visible('[data-testid=setup-approve]'), 'keyboard_plan_preview')
        await click('[data-testid=setup-approve]')
        await click('[data-testid=select-run]')
        await click('[data-testid=preflight-inspect]')
        reviewer_input = '[data-testid=preflight-reviewer] input, input[data-testid=preflight-reviewer]'
        await wait_for(lambda: visible(reviewer_input), 'plain_search_checks')
        if await js("document.querySelector(" + json.dumps(reviewer_input) + ").value") != 'Fixture researcher':
            raise RuntimeError('self_check_lost_researcher')
        if not await visible('[data-testid=press-help]'):
            raise RuntimeError('search_check_help_missing')
        print('Checked Enter entry, retry focus, persistent navigation, selectable output and researcher reuse.', flush=True)

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
                await wait_for(lambda: visible('[data-testid=project-name]'), 'native_create')
                await check_first_search_page()
                active = flow.state()['project']['project_id']
                await click('[data-testid=switch-project]')
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
            await click('[data-testid=stage-search]')
            await click('[data-testid=select-run]')
            await wait_for(lambda: visible('[data-testid=selected-run]'), 'selected_search')
            if run_id in await js("document.querySelector('.workspace-panels').innerText"):
                raise RuntimeError('technical_run_id_in_primary_workflow')
            await click('[data-testid=stage-results]')
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
            await click('[data-testid=stage-export]')
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
