"""Offline Windows acceptance journey; all projects and exports are disposable."""
import asyncio
import json
import multiprocessing
import subprocess
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if '--installed' not in sys.argv:
    sys.path.insert(0, str(ROOT / 'src'))
OUTPUT = ROOT / 'build' / 'usability-native'
if '--case' in sys.argv:
    OUTPUT = OUTPUT.with_name('usability-native-' + Path(sys.argv[sys.argv.index('--case') + 1]).name)


def prepare():
    sys.path[:0] = [str(ROOT / 'tests'), str(ROOT)]
    from test_reviewed_master import populated
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'project').mkdir()
    project, run, _, _ = populated(OUTPUT / 'project')
    (OUTPUT / 'exports').mkdir()
    (OUTPUT / 'fixture.json').write_text(json.dumps(dict(project=str(project.root), run=run)))


def run():
    import research_y
    if '--installed' in sys.argv and Path(sys.executable).resolve().parent not in Path(research_y.__file__).resolve().parents:
        raise RuntimeError('Installed acceptance must import the packaged application')
    from nicegui import app, Client
    from research_y.desktop import app as desktop
    from research_y.desktop.flow import RealProjectFlow
    fixture = json.loads((OUTPUT / 'fixture.json').read_text())
    flow = RealProjectFlow(recent_parent=OUTPUT / 'recents')
    selected = {'folder': Path(fixture['project'])}
    async def choose(window):
        return selected['folder']
    desktop.select_from_native_window = choose
    checks = []
    tasks = []

    async def js(expression):
        clients = [c for c in Client.instances.values() if c.has_socket_connection]
        if len(clients) != 1:
            return None
        return await clients[0].run_javascript(expression, timeout=12)

    async def visible(selector):
        return await js('Boolean(document.querySelector(' + json.dumps(selector) + ')?.getClientRects().length)')

    async def wait(predicate, label):
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            value = predicate()
            if await value if asyncio.iscoroutine(value) else value:
                return
            await asyncio.sleep(.15)
        raise RuntimeError('Timed out: ' + label)

    async def click(selector):
        await wait(lambda: visible(selector), selector)
        await wait(lambda: js('!document.querySelector(' + json.dumps(selector) + ')?.closest("[inert]")'), 'action ready')
        await js('document.querySelector(' + json.dumps(selector) + ').click(); true')
        await asyncio.sleep(.25)

    async def text_button(text):
        await wait(lambda: js('!document.querySelector("[data-testid=action-surface]")?.inert'), 'action ready')
        found = await js('(()=>{let e=[...document.querySelectorAll("button")].find(e=>e.getClientRects().length&&e.innerText.trim()===' + json.dumps(text) + '); if(!e)return false;e.click();return true;})()')
        assert found, text
        await asyncio.sleep(.25)

    async def section(text):
        found = await js('(()=>{let e=[...document.querySelectorAll(".q-expansion-item")].find(e=>e.getClientRects().length&&e.querySelector(".q-item__section--main")?.innerText.trim()===' + json.dumps(text) + ');if(!e)return false;if(e.className.includes("--collapsed"))e.querySelector(".q-item").click();return true;})()')
        assert found, text
        await asyncio.sleep(.3)

    async def snapshot(name):
        await asyncio.sleep(.4)
        state = await js('({text:document.body.innerText, width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth,header:document.querySelector(".workspace-header")?.getBoundingClientRect().height})')
        (OUTPUT / (name + '.json')).write_text(json.dumps(state, indent=2))
        await asyncio.to_thread(capture, OUTPUT / (name + '.png'))
        assert not state['overflow'], name + ' horizontal overflow'

    async def select_option(label, text):
        await js('(()=>{let e=[...document.querySelectorAll(".q-field")].find(e=>e.getClientRects().length&&e.querySelector(".q-field__label")?.innerText===' + json.dumps(label) + ');e.querySelector(".q-field__control").click();return true;})()')
        await asyncio.sleep(.4)
        assert await js('(()=>{let e=[...document.querySelectorAll(".q-menu .q-item")].find(e=>e.getClientRects().length&&e.innerText.includes(' + json.dumps(text) + '));if(!e)return false;e.click();return true;})()')
        await asyncio.sleep(.4)

    async def observe():
        try:
            await wait(lambda: visible('[data-testid=desktop-open]'), 'launcher')
            await asyncio.sleep(1)
            await click('[data-testid=desktop-open]')
            await wait(lambda: flow.state()['project'] is not None, 'open')
            await click('[data-testid=select-run]')
            await wait(lambda: flow.state()['run_execution_board'] is not None, 'collection board')
            await click('[data-testid=stage-results]')
            await wait(lambda: visible('[data-testid=master-table]'), 'automatic results')
            checks.append('Results automatically show saved articles')
            await snapshot('01-results')
            await click('[data-testid=master-table] tbody tr .q-checkbox')
            await wait(lambda: flow.state()['master_results']['selected'] == 1, 'direct checkbox selection')
            checks.append('Checkbox immediately updates selection')
            await text_button('Open')
            await wait(lambda: flow.state()['master_results'].get('detail'), 'article details')
            checks.append('Article row opens its details')
            await click('[data-testid=stage-export]')
            selected['folder'] = OUTPUT / 'exports'
            await click('[data-testid=export-save]')
            await wait(lambda: flow.state()['saved_output'], 'verified export')
            assert flow.output_path().exists()
            checks.append('One save writes and verifies an article workbook')
            await snapshot('02-export')
            await click('[data-testid=stage-plan]')
            await wait(lambda: visible('[data-testid=setup-copy]'), 'saved plan')
            checks.append('Saved groups stay visible after approval and reopening')
            await snapshot('03-saved-plan')
            await click('[data-testid=setup-copy]')
            await wait(lambda: flow.state()['planning_mode'] == 'draft', 'editable copy')
            assert len(flow.state()['strategy_draft']['groups']) == 2
            checks.append('Edit a copy retains terms and creates an unapproved draft')
            if not flow.state()['saved_question']:
                await click('[data-testid=setup-save-heading]')
                await wait(lambda: flow.state()['saved_question'], 'saved question')
            await click('[data-testid=setup-preview]')
            await wait(lambda: visible('[data-testid=setup-approve]'), 'draft preview')
            await click('[data-testid=setup-approve]')
            await wait(lambda: len(flow.state()['runs']) == 2, 'revised search saved')
            await select_option('Choose a saved search', 'Search 2')
            await click('[data-testid=select-run]')
            await wait(lambda: flow.state()['selected_run_id'] != fixture['run'], 'new saved search')
            await click('[data-testid=preflight-inspect]')
            await wait(lambda: visible('[data-testid=search-review]'), 'focused review')
            await snapshot('04-review-wide')
            app.native.main_window.resize(520, 760)
            await asyncio.sleep(.7)
            await snapshot('05-review-narrow')
            layout = await js('({outer:getComputedStyle(document.querySelector(".review-comparison")).overflowY,inner:getComputedStyle(document.querySelector(".review-answers")).overflowY})')
            assert layout == dict(outer='auto', inner='visible'), layout
            checks.append('Narrow review uses one scroll area')
            await click('[data-testid=review-close]')
            app.native.main_window.resize(1200, 850)
            await select_option('Choose a saved search', 'Search 1')
            await click('[data-testid=select-run]')
            await wait(lambda: flow.state()['selected_run_id'] == fixture['run'], 'original saved search')
            await click('[data-testid=stage-results]')
            await section('Review potential duplicates')
            await click('[data-testid=candidate-queue-refresh]')
            await wait(lambda: visible('[data-testid=candidate-queue-review]'), 'candidate queue')
            await click('[data-testid=candidate-queue-review]')
            await wait(lambda: visible('[data-testid=candidate-heading]'), 'revealed comparison')
            checks.append('Comparison action reveals its result')
            await snapshot('06-comparison')
            await section('Study review queue and filters')
            await text_button('Apply review filters')
            await wait(lambda: bool(flow.state()['study_queue']), 'review filter')
            assert await js('([...document.querySelectorAll(".q-expansion-item")].find(e=>e.querySelector(".q-item__section--main")?.innerText.trim()==="Study review queue and filters")?.className||"").includes("--expanded")')
            checks.append('Review filters leave the updated queue open')
            app.native.main_window.resize(800, 600)
            await snapshot('07-short-window')
            result = dict(passed=True, checks=checks, provider_requests=0)
        except Exception as exc:
            import traceback
            result = dict(passed=False, checks=checks, error=str(exc), traceback=traceback.format_exc())
            try:
                await snapshot('failure')
            except Exception:
                pass
        finally:
            (OUTPUT / 'acceptance.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
            try:
                await asyncio.wait_for(app.native.main_window.destroy(), timeout=8)
            finally:
                app.shutdown()
    app.on_startup(lambda: tasks.append(asyncio.create_task(observe())))
    desktop.run_desktop(flow)


def capture(target):
    ids = [p.pid for p in multiprocessing.active_children() if p.daemon]
    command = r'''
param([string]$ids,[string]$target)
Add-Type -AssemblyName System.Drawing
Add-Type 'using System; using System.Runtime.InteropServices;
public static class AuditCapture {
[StructLayout(LayoutKind.Sequential)] public struct Rect {public int Left, Top, Right, Bottom;}
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect r);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);}'
[AuditCapture]::SetProcessDPIAware() | Out-Null
$proc=Get-Process -Id ($ids.Split(',') | ForEach-Object {[int]$_}) | Where-Object {$_.MainWindowTitle -eq 'RESEARCH-Y'} | Select-Object -First 1
if (-not $proc) {throw 'Audit window unavailable'}
$rect=[AuditCapture+Rect]::new()
[AuditCapture]::GetWindowRect($proc.MainWindowHandle,[ref]$rect) | Out-Null
$bitmap=[Drawing.Bitmap]::new($rect.Right-$rect.Left,$rect.Bottom-$rect.Top)
$graphics=[Drawing.Graphics]::FromImage($bitmap)
$dc=$graphics.GetHdc()
try {if (-not [AuditCapture]::PrintWindow($proc.MainWindowHandle,$dc,2)) {throw 'Capture failed'}}
finally {$graphics.ReleaseHdc($dc)}
$bitmap.Save($target,[Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
'''
    invocation = '& {' + command + "} -ids '" + ','.join(map(str, ids)) + "' -target '" + str(target).replace("'", "''") + "'"
    subprocess.run(['powershell.exe','-NoProfile','-Command', invocation], check=True, creationflags=subprocess.CREATE_NO_WINDOW)

if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--prepare' in sys.argv:
        prepare()
    else:
        run()
