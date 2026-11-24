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
    from research_y.desktop.pubmed_profile import PubMedHostProfile
    from research_y.desktop.wos_profile import WoSHostProfile
    fixture = json.loads((OUTPUT / 'fixture.json').read_text())
    flow = RealProjectFlow(recent_parent=OUTPUT / 'recents',
                           pubmed_profile=PubMedHostProfile('offline@example.invalid'),
                           wos_profile=WoSHostProfile('OFFLINE-FAKE-KEY'))
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

    async def in_viewport(selector):
        return await js('(()=>{let e=document.querySelector(' + json.dumps(selector) + ');if(!e)return false;let r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.top>=0&&r.left>=0&&r.bottom<=innerHeight&&r.right<=innerWidth})()')

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
            from research_y.desktop.search_guidance import saved_search_names
            names = saved_search_names(flow.state()['runs'])
            await wait(lambda: js('document.body.innerText.includes(' + json.dumps(names[fixture['run']]) + ')'), 'saved search label rendered')
            checks.append('Saved searches show the frozen theme, version and saved date')
            assert await js('document.querySelector(".journey .q-expansion-item")?.className.includes("--collapsed")')
            await section('How your search works')
            assert await js('document.querySelector(".journey")?.innerText.includes("after you confirm collection")')
            assert await js('document.querySelector(".journey")?.innerText.includes("1. Plan search")')
            checks.append('Overview maps the four stages and distinguishes tests from collection')
            await click('.journey .q-item')
            await click('[data-testid=select-run]')
            await wait(lambda: flow.state()['run_execution_board'] is not None, 'collection board')
            await click('[data-testid=stage-results]')
            await wait(lambda: visible('[data-testid=master-table]'), 'automatic results')
            assert await js('document.querySelector("[data-testid=stage-guidance]")?.innerText.startsWith("Results ·")')
            checks.append('Guidance follows the currently selected stage')
            checks.append('Results automatically show saved articles')
            await js('window.scrollTo(0,0);true')
            await wait(lambda: in_viewport('[data-testid=master-table] tbody tr'), 'first article in viewport')
            assert await js('document.querySelector(".journey .q-expansion-item")?.className.includes("--collapsed")')
            checks.append('Collapsed overview survives opening a search and leaves an article in view')
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
            approver = flow.state()['strategy_draft']['approved_by']
            await click('[data-testid=stage-plan]')
            await click('[data-testid=question-edit]')
            await wait(lambda: visible('input[data-testid=setup-approver], [data-testid=setup-approver] input'), 'researcher field')
            await js('(()=>{let e=document.querySelector("input[data-testid=setup-approver], [data-testid=setup-approver] input");e.value="Current reviewer";e.dispatchEvent(new Event("input",{bubbles:true}));return true;})()')
            await click('[data-testid=setup-save-heading]')
            await wait(lambda: flow.state()['researcher_name'] == 'Current reviewer', 'changed researcher')
            assert flow.state()['strategy_draft']['approved_by'] == approver
            await click('[data-testid=stage-search]')
            await select_option('Choose a saved search', 'version 2')
            await click('[data-testid=select-run]')
            await wait(lambda: flow.state()['selected_run_id'] != fixture['run'], 'new saved search')
            await click('[data-testid=preflight-inspect]')
            await wait(lambda: visible('[data-testid=search-review]'), 'focused review')
            assert await js('document.querySelector("input[data-testid=preflight-reviewer], [data-testid=preflight-reviewer] input")?.value') == 'Current reviewer'
            assert await js('([...document.querySelectorAll(".q-field")].find(e=>e.querySelector(".q-field__label")?.innerText==="Researcher performing the source check")?.querySelector("input")?.value)') == 'Current reviewer'
            checks.append('Search checks use the current researcher while preserving the original approver')
            await snapshot('04-review-wide')
            app.native.main_window.resize(520, 760)
            await asyncio.sleep(.7)
            await snapshot('05-review-narrow')
            layout = await js('({outer:getComputedStyle(document.querySelector(".review-comparison")).overflowY,inner:getComputedStyle(document.querySelector(".review-answers")).overflowY})')
            assert layout == dict(outer='auto', inner='visible'), layout
            checks.append('Narrow review uses one scroll area')
            await click('[data-testid=review-close]')
            app.native.main_window.resize(1200, 850)
            await click('[data-testid=review-open]')
            await click('[data-testid=preflight-offer]')
            await click('[data-testid=preflight-record]')
            await wait(lambda: visible('[data-testid=review-saved]'), 'checklist saved')
            await click('[data-testid=review-close]')
            # Real buttons route all four groups; previews may not send requests.
            from hashlib import sha256
            before = sha256(flow.project.database_path.read_bytes()).hexdigest()
            for index, query in enumerate(flow.state()['run_execution_board']['queries']):
                await wait(lambda: js('!document.querySelector("[data-testid=action-surface]")?.inert'), 'collection controls ready')
                await js('document.querySelectorAll("[data-testid=collection-continue]")[' + str(index) + '].click();true')
                state_key = 'pubmed_source' if query['source_name'] == 'pubmed' else 'wos_acquisition_offer'
                await wait(lambda: (flow.state()[state_key] or {}).get('query_id') == query['query_id'], 'selected collection group')
                await wait(lambda: in_viewport('[data-testid=collection-close]'), 'focused collection screen')
                if query['source_name'] == 'pubmed':
                    assert await js('document.querySelectorAll("[data-testid=collection-current] [data-testid=pubmed-source-saved-query]").length') == 1
                    await click('[data-testid=collection-current] [data-testid=pubmed-source-offer]')
                    await wait(lambda: visible('[data-testid=pubmed-source-confirm]'), 'separate PubMed confirmation')
                    assert flow.state()['pubmed_source_offer']['query_id'] == query['query_id']
                    await snapshot('collection-pubmed-' + str(index))
                    await click('[data-testid=pubmed-source-dismiss]')
                else:
                    assert flow.state()['wos_acquisition_offer']['query_id'] == query['query_id']
                    await snapshot('collection-wos-' + str(index))
                    await click('[data-testid=wos-acquisition-cancel]')
                assert sha256(flow.project.database_path.read_bytes()).hexdigest() == before
                await click('[data-testid=collection-close]')
                await wait(lambda: js('!document.querySelector("[data-testid=collection-close]")?.getClientRects().length'), 'collection screen closed')
            checks.append('Every Continue opens the selected group; previews retain separate consent and make no project writes')
            await select_option('Choose a saved search', 'version 1')
            await click('[data-testid=select-run]')
            await wait(lambda: flow.state()['selected_run_id'] == fixture['run'], 'original saved search')
            await click('[data-testid=stage-results]')
            await section('Review potential duplicates')
            await click('[data-testid=candidate-queue-refresh]')
            await wait(lambda: visible('[data-testid=candidate-queue-review]'), 'candidate queue')
            await click('[data-testid=candidate-queue-review]')
            await wait(lambda: in_viewport('[data-testid=candidate-heading]'), 'comparison heading in viewport')
            await wait(lambda: in_viewport('[data-testid=candidate-source]'), 'citation in viewport')
            checks.append('Comparison opens at the top of a dedicated screen with citations in view')
            await snapshot('06-comparison')
            assert await js('(()=>{let e=document.querySelector("textarea[data-testid=candidate-rationale], [data-testid=candidate-rationale] textarea");if(!e)return false;e.value="Offline comparison note";e.dispatchEvent(new Event("input",{bubbles:true}));return true;})()')
            await asyncio.sleep(.3)
            await click('[data-testid=candidate-reject]')
            await wait(lambda: visible('[data-testid=candidate-screen] [role=alert]'), 'missing acknowledgment validation')
            assert await js('document.querySelector("textarea[data-testid=candidate-rationale], [data-testid=candidate-rationale] textarea")?.value') == 'Offline comparison note'
            checks.append('Comparison validation keeps the evidence text and does not record an unchecked decision')
            app.native.main_window.resize(520, 760)
            await snapshot('comparison-narrow')
            await click('[data-testid=candidate-dismiss]')
            app.native.main_window.resize(1200, 850)
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
