"""Measure a real local 100,000-publication master view using the original audited source fixture."""
import argparse
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter

from research_y import master_results
from research_y.projects import open_project
from scripts.benchmark_original_project import materialise_remaining_fixture
from tools.gui_feasibility.run_materialisation_window import _large_fixture


def measure(output):
    with TemporaryDirectory(prefix="research-y-master-benchmark-") as temp:
        project,run = _large_fixture(Path(temp))
        started=perf_counter()
        outcome=materialise_remaining_fixture(project,batch_size=256)
        if not outcome["exhausted_sources"]:
            raise RuntimeError("Fixture preparation incomplete")
        prepared=perf_counter()-started
        project=open_project(project.root)
        with closing(sqlite3.connect(project.database_path)) as db:
            before=[db.execute("SELECT count(*) FROM "+table).fetchone()[0] for table in
                    ("source_retrievals","query_retrievals","publication_retrievals","publications","audit_events")]
        if before[:4]!=[100_000]*4:
            raise RuntimeError("Original fixture does not cover 100,000 memberships and identities")
        started=perf_counter()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(master_results.MasterResults.capture,project,run)
            # The production desktop likewise dispatches the snapshot off its page event loop.
            from time import sleep
            intervals=[]
            previous=perf_counter()
            while not future.done():
                sleep(.1)
                now=perf_counter()
                intervals.append(now-previous)
                previous=now
            results=future.result()
        capture=perf_counter()-started
        with closing(results):
            if results.total!=100_000 or not intervals:
                raise RuntimeError("Master snapshot did not cover all records")
            started=perf_counter()
            opts=master_results.specification(text="Synthetic report",facets={"source":["pubmed"]},sort="title")
            first=results.page(opts)
            last=results.page(opts,offset=max(first["matching"]-25,0))
            results.select(opts,all_matching=True)
            chosen=results.page(opts)
            if (not first["rows"] or not last["rows"] or chosen["selected"]!=first["matching"] or
                    len({r["publication_id"] for r in first["rows"]+last["rows"]})!=50):
                raise RuntimeError("Filtered paging or bulk selection lost records")
            browse=perf_counter()-started
        with closing(sqlite3.connect(project.database_path)) as db:
            after=[db.execute("SELECT count(*) FROM "+table).fetchone()[0] for table in
                   ("source_retrievals","query_retrievals","publication_retrievals","publications","audit_events")]
            if before!=after or db.execute("PRAGMA integrity_check").fetchone()!=("ok",):
                raise RuntimeError("Master exploration changed the project")
        evidence=dict(platform=platform.platform(),python=platform.python_version(),records=before[0],
                      memberships=before[1],publications=before[3],matching=first["matching"],
                      selected=chosen["selected"],fixture_prepare_seconds=round(prepared,3),
                      capture_seconds=round(capture,3),filter_page_select_seconds=round(browse,3),
                      observations=len(intervals),longest_observed_interval_seconds=round(max(intervals),3),
                      original_counts_preserved=True,display_page_size=25,
                      scope="Production snapshot and search services on synthetic original source records")
        output.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(evidence))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    measure(parser.parse_args().output)
