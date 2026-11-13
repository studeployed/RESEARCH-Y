"""Exercise a full 100,000-publication master snapshot through the installed Windows window."""
import asyncio
import json
from pathlib import Path
import platform
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from tools.desktop_lifecycle import wait_for


def native(folder,run_id,output):
    from nicegui import app
    from research_y.desktop import app as desktop
    from research_y.desktop.flow import RealProjectFlow
    flow=RealProjectFlow()
    async def choose(window):
        return folder
    desktop.select_from_native_window=choose
    tasks=[]
    async def js(expression):
        return await asyncio.wait_for(app.native.main_window.evaluate_js(expression),10)
    async def visible(selector):
        return await js("Boolean(document.querySelector("+json.dumps(selector)+")?.getClientRects().length)")
    async def click(selector):
        await wait_for(lambda:visible(selector),selector,timeout=120)
        await js("document.querySelector("+json.dumps(selector)+").click(); true")
    async def body_has(value):
        return await js("document.body.innerText.includes("+json.dumps(value)+")")
    async def observe():
        try:
            await click("[data-testid=desktop-open]")
            await click("[data-testid=select-run]")
            await click("[data-testid=master-panel] .q-item")
            await js("window.masterTicks=0; window.masterInterval=setInterval(()=>window.masterTicks++,100); true")
            started=perf_counter()
            await click("[data-testid=master-refresh]")
            await wait_for(lambda:visible("[data-testid=master-table]"),"capture",timeout=180)
            elapsed=perf_counter()-started
            ticks=await js("clearInterval(window.masterInterval); window.masterTicks")
            if not await body_has("100000 of 100000") or ticks<5:
                raise RuntimeError("Incorrect native denominator or stalled browser timer")
            await js("Array.from(document.querySelectorAll('button')).find(b=>b.innerText.trim().toLowerCase()"
                     "==='next results').click(); true")
            await wait_for(lambda:body_has("Showing 26–50"),"next master page",timeout=90)
            await js("Array.from(document.querySelectorAll('button')).find(b=>b.innerText.trim().toLowerCase()"
                     "==='select all matching').click(); true")
            await wait_for(lambda:body_has("100000 selected"),"complete bulk selection",timeout=90)
            page=flow.state()["master_results"]
            if flow.selected_run_id!=run_id or (page["total"],page["selected"],len(page["rows"]))!=(100000,100000,25):
                raise RuntimeError("Incorrect native master rows")
            data=dict(records=page["total"],selected=page["selected"],page_rows=len(page["rows"]),
                      second_page_offset=page["offset"],browser_timer_ticks=ticks,
                      native_capture_seconds=round(elapsed,3),platform=platform.platform(),python=platform.python_version(),
                      scope="Real WebView2 window and production master controls on 100000 synthetic original publications")
            output.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
        except Exception as exc:
            print(type(exc).__name__,str(exc),flush=True)
        finally:
            try:
                await asyncio.wait_for(app.native.main_window.destroy(),10)
            except Exception:
                app.shutdown()
    app.on_startup(lambda:tasks.append(asyncio.create_task(observe())))
    desktop.run_desktop(flow)


if __name__=="__main__":
    if len(sys.argv)==5 and sys.argv[1]=="--window":
        native(Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]))
    else:
        from tools.gui_feasibility.run_materialisation_window import _large_fixture
        from scripts.benchmark_original_project import materialise_remaining_fixture
        # Use a fresh, unique result inside the disposable directory so any prior file cannot pass the check.
        with TemporaryDirectory(prefix="ry-native-master-") as tmp:
            project,run=_large_fixture(Path(tmp))
            materialise_remaining_fixture(project,batch_size=256)
            witnessed=Path(tmp)/"observed.json"
            subprocess.run([sys.executable,"-B","-m","tools.native_master_release_check","--window",
                            str(project.root),run,str(witnessed)],check=True,timeout=540)
            result=witnessed.read_text(encoding="utf-8")
            Path(sys.argv[1]).write_text(result,encoding="utf-8")
            print(result)
