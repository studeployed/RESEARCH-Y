"""Original-project 100,000-source workload, count and review-path probe.

A limited *real SQLite project* test, NOT completion of specification AT-22:
- 100,000 retained source records and query/group memberships;
- 128 production-materialised provisional identities, 64 per run;
- 64 shared exact-key candidate pairs touching the selected run;
- original count, publication pages, candidate pages, spawned application worker,
  original database integrity and reopen/recovery checks.

The other retained source records are explicitly UNMATERIALISED. This exercises
the real project/source/identity evidence path and candidly reports its limits.
No clinical records, provider calls, credentials or source abstracts are used.

Run from a checkout installed with 'python -m pip install -e .':
  python scripts/benchmark_original_project.py --records 100000 \
    --selected 512 --matched 64 --json-output evidence.json
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import monotonic, perf_counter, sleep
from uuid import UUID

from research_y import publication_identity as identity
from research_y import publication_candidate_queue as queue
from research_y import publication_results as results
from research_y import result_counts as counts
from research_y.application_commands import ApplicationCommand
from research_y.application_worker import ApplicationWorker
from research_y.projects import create_project, open_project

METHOD="original-project-100k-source-workload/1"
RUN="88888888-8888-4888-8888-888888888801"
HISTORY="88888888-8888-4888-8888-888888888802"
STRATEGY="88888888-8888-4888-8888-888888888803"
QIDS={
    (RUN,"pubmed"):"88888888-8888-4888-8888-888888888811",
    (RUN,"wos"):"88888888-8888-4888-8888-888888888812",
    (HISTORY,"pubmed"):"88888888-8888-4888-8888-888888888813",
    (HISTORY,"wos"):"88888888-8888-4888-8888-888888888814",
}


def _rid(i: int)->str:
    if not 0<=i<2**48:
        raise ValueError("Bounded synthetic record index required")
    return f"99999999-9999-4999-8999-{i+1:012x}"


def _payload(i: int, total_selected: int, matched: int, source: str,
             source_id: str) -> str:
    shared = (i < matched or
              total_selected <= i < total_selected+matched)
    index=i if i < total_selected else i-total_selected
    key=(f"shared{index}" if shared else f"individual{i}")
    title=(f"Synthetic source abstract {index}" if shared
           else f"Synthetic report {i}")
    if source=="pubmed":
        body={
            "source":"NCBI PubMed EFetch XML",
            "record":{"pmid":source_id,"title":title,
                      "identifiers":{"doi":[f"10.9300/{key}"]},
                      "publication_types":["Conference Abstract"]},
            "rights_review_required_for_abstract_redistribution":True,
        }
    else:
        body={
            "provider":"wos_starter","database":"WOS",
            "record":{"uid":source_id,"title":title,
                      "identifiers":{"doi":f"10.9300/{key}"},
                      "types":["Conference Abstract"]},
            "rights_status":"licence_review_required",
        }
    return identity._json(body)


def _seed(project, records: int, selected: int, matched: int):
    """Commit real project source/membership rows in finite SQLite batches."""
    stamp=project.created_at_utc
    with closing(sqlite3.connect(project.database_path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)",
                   (STRATEGY,1,stamp,"{}"))
        db.execute("INSERT INTO strategy_groups VALUES(?,?,?,?)",
                   (STRATEGY,"all","Biomedical synthetic OR-group",0))
        for run_id in (RUN,HISTORY):
            db.execute("INSERT INTO search_runs VALUES(?,?,?,?,?)",
                       (run_id,STRATEGY,stamp,"incomplete",None))
            for source in ("pubmed","wos"):
                db.execute(
                    "INSERT INTO source_queries VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (QIDS[run_id,source],run_id,STRATEGY,"all",source,
                     '"synonyms"[All Fields]' if source=="pubmed"
                     else 'TS=("synonyms")',
                     "{}",None,"incomplete",None),
                )
        db.commit()
        insert_sql="INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)"
        member_sql="INSERT INTO query_retrievals VALUES(?,?,?,?)"
        for start in range(0,records,1000):
            source_rows=[]
            members=[]
            for i in range(start,min(start+1000,records)):
                run=RUN if i<selected else HISTORY
                # The first matched historical records deliberately come
                # from the opposite database to their selected-run partner.
                pubmed=(i%2==0) if i<selected else (i%2==1)
                provider="pubmed" if pubmed else "wos"
                source_id=(str(10000001+i) if pubmed
                           else f"WOS:{10000001+i}")
                rid=_rid(i)
                source_rows.append((
                    rid,run,provider,source_id,stamp,
                    _payload(i,selected,matched,provider,source_id),
                ))
                members.append((QIDS[run,provider],rid,run,provider))
            db.execute("BEGIN IMMEDIATE")
            try:
                db.executemany(insert_sql,source_rows)
                db.executemany(member_sql,members)
                db.commit()
            except BaseException:
                db.rollback()
                raise
    # Materialise only the known, bounded cross-source candidate workload
    # via the existing original audited publication service. This is NOT
    # a claim that the entire source search has been materialised.
    for i in (*range(matched),*range(selected,selected+matched)):
        identity.materialise_retrieval(
            project,_rid(i),actor="Synthetic performance fixture")
    return 2*matched


def _run_original(run_id, project, operation, **kwargs):
    cmd=ApplicationCommand.for_project(project,operation,run_id=run_id,**kwargs)
    return cmd


def _bench(name,fn,metrics):
    at=perf_counter()
    result=fn()
    metrics[name+"_ms"]=round((perf_counter()-at)*1000,3)
    return result


def _peak_rss_bytes() -> int|None:
    if os.name=="nt":
        try:
            import ctypes
            from ctypes import wintypes
            class Memory(ctypes.Structure):
                _fields_=[
                    ("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD),
                    ("PeakWorkingSetSize",ctypes.c_size_t),
                    ("WorkingSetSize",ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage",ctypes.c_size_t),
                    ("QuotaPagedPoolUsage",ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage",ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage",ctypes.c_size_t),
                    ("PagefileUsage",ctypes.c_size_t),
                    ("PeakPagefileUsage",ctypes.c_size_t),
                ]
            counter=Memory()
            counter.cb=ctypes.sizeof(Memory)
            get=ctypes.WinDLL("kernel32").GetCurrentProcess
            get.restype=wintypes.HANDLE
            query=ctypes.WinDLL("psapi").GetProcessMemoryInfo
            query.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),
                            wintypes.DWORD]
            query.restype=wintypes.BOOL
            if query(get(),ctypes.byref(counter),counter.cb):
                return counter.PeakWorkingSetSize
        except (OSError,ValueError,AttributeError):
            return None
    else:
        import resource
        # Linux reports ru_maxrss in KiB, whereas macOS reports bytes.
        size=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(size * (1024 if sys.platform.startswith("linux") else 1))
    return None


def _worker_read(project, run_id, maximum_seconds):
    """Use the *real spawned application worker*, polling without GUI work."""
    command=_run_original(run_id,project,"candidate_queue_page")
    before=perf_counter()
    ticks=0
    gaps=[]
    previous=perf_counter()
    with ApplicationWorker() as worker:
        op=worker.submit(command)
        status=None
        while perf_counter()-before<maximum_seconds:
            status=worker.poll(op)
            now=perf_counter()
            gaps.append((now-previous)*1000)
            previous=now
            ticks+=1
            if status.state!="running":
                break
            sleep(.015)
        if status is None or status.state=="running":
            # Existing GUI host's 35-second timeout has already been exceeded.
            # The read-only worker is stopped; this is not a completed review.
            return dict(status="timeout",error="worker_timeout",
                        wall_ms=round((perf_counter()-before)*1000,3),
                        poll_count=ticks,max_poll_gap_ms=max(gaps,default=0),
                        completed=False)
        value=status.result() if status.state=="returned" else None
        return dict(
            status=status.state,error=status.error,
            wall_ms=round((perf_counter()-before)*1000,3),
            poll_count=ticks,
            max_poll_gap_ms=round(max(gaps,default=0),3),
            completed=status.state=="returned",
            candidate_count=(value.get("candidate_pair_total")
                             if value is not None else None),
            response_rows=(len(value.get("rows",()))
                           if value is not None else None),
            global_unique_publications=(value.get("global_unique_publications")
                                        if value is not None else None),
            deduplication_complete=(value.get("deduplication_complete")
                                    if value is not None else None),
        )


def run(records=100000,selected=512,matched=64,
        worker_timeout_seconds=35):
    if (type(records) is not int or not 512<=records<=100000
            or type(selected) is not int or not 128<=selected<=records//2
            or selected%2 or type(matched) is not int
            or not 1<=matched<=min(64,selected//2,records-selected)
            or type(worker_timeout_seconds) not in (int,float)
            or not 1<=worker_timeout_seconds<=120):
        raise ValueError("A bounded, reproducible source scenario is required")
    timings={}
    before=perf_counter()
    with TemporaryDirectory(prefix="researchy-original-100k-") as parent:
        project=create_project(Path(parent),"Synthetic large original project")
        materialised=_bench(
            "original_source_and_audit_seeding",
            lambda:_seed(project,records,selected,matched),timings)
        project=open_project(project.root)
        with closing(sqlite3.connect(project.database_path)) as db:
            initial=dict(
                sources=db.execute(
                    "SELECT COUNT(*) FROM source_retrievals").fetchone()[0],
                membership_rows=db.execute(
                    "SELECT COUNT(*) FROM query_retrievals").fetchone()[0],
                publications=db.execute(
                    "SELECT COUNT(*) FROM publications").fetchone()[0],
                links=db.execute(
                    "SELECT COUNT(*) FROM publication_retrievals").fetchone()[0],
                audit_events=db.execute(
                    "SELECT COUNT(*) FROM audit_events").fetchone()[0],
                first_original_sha256=sha256(
                    db.execute("SELECT original_metadata_json FROM "
                               "source_retrievals WHERE retrieval_id=?",
                               (_rid(0),)).fetchone()[0].encode()).hexdigest(),
                last_original_sha256=sha256(
                    db.execute("SELECT original_metadata_json FROM "
                               "source_retrievals WHERE retrieval_id=?",
                               (_rid(records-1),)).fetchone()[0].encode()).hexdigest(),
            )
        if (initial["sources"]!=records or
                initial["membership_rows"]!=records or
                initial["links"]!=materialised or
                initial["publications"]!=materialised):
            raise AssertionError("Original synthetic source/audit records lost")
        projection=_bench(
            "original_run_count_read",
            lambda:counts.read_run_counts(project,RUN),timings)
        if (projection.totals["metadata_source_records"]!=selected or
                projection.totals["unmaterialised_retrievals"]!=selected-matched or
                projection.totals["global_publication_identities"]!=matched or
                projection.totals["global_unique_publications"] is not None):
            raise AssertionError("Original run projection was inconsistent")
        publication=_bench(
            "first_provisional_publication_page",
            lambda:results.read_publication_page(project,RUN),timings)
        if (len(publication["rows"])!=20 or
                publication["global_unique_publications"] is not None):
            raise AssertionError("Original publication page is invalid")
        listing=_bench(
            "first_source_backed_candidate_page",
            lambda:queue.read_candidate_queue(project,RUN),timings)
        if (listing["candidate_pair_total"]!=matched or
                listing["project_source_records"]!=records or
                len(listing["rows"])!=20 or
                listing["index_backend"]!="original_source_projection" or
                listing["global_unique_publications"] is not None or
                listing["deduplication_complete"] is not False):
            raise AssertionError("Full original source-based candidate page differs")
        next_page=_bench(
            "second_source_backed_candidate_page",
            lambda:queue.read_candidate_queue(
                project,RUN,after_pair=tuple(listing["next_after_pair"]),
                expected_revision=listing["revision"]),timings)
        if (next_page["revision"]!=listing["revision"] or
                set(tuple(r["retrieval_ids"]) for r in listing["rows"]) &
                set(tuple(r["retrieval_ids"]) for r in next_page["rows"])):
            raise AssertionError("Original keyset page changed/overlapped")
        worker=_worker_read(project,RUN,worker_timeout_seconds)
        # An independent project reopen must preserve the 100k originals
        # despite the read-only page operations and a spawned worker.
        reopened=open_project(project.root)
        with closing(sqlite3.connect(reopened.database_path)) as db:
            current=dict(
                sources=db.execute(
                    "SELECT COUNT(*) FROM source_retrievals").fetchone()[0],
                membership_rows=db.execute(
                    "SELECT COUNT(*) FROM query_retrievals").fetchone()[0],
                publications=db.execute(
                    "SELECT COUNT(*) FROM publications").fetchone()[0],
                links=db.execute(
                    "SELECT COUNT(*) FROM publication_retrievals").fetchone()[0],
                audit_events=db.execute(
                    "SELECT COUNT(*) FROM audit_events").fetchone()[0],
                first_original_sha256=sha256(db.execute(
                    "SELECT original_metadata_json FROM source_retrievals "
                    "WHERE retrieval_id=?",(_rid(0),)).fetchone()[0].encode()).hexdigest(),
                last_original_sha256=sha256(db.execute(
                    "SELECT original_metadata_json FROM source_retrievals "
                    "WHERE retrieval_id=?",(_rid(records-1),)).fetchone()[0].encode()).hexdigest(),
            )
            integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
            references=db.execute("PRAGMA foreign_key_check").fetchone()
        if current!=initial or integrity!="ok" or references is not None:
            raise AssertionError("Original evidence changed during read or worker restart")
        if worker["completed"] and (worker["candidate_count"]!=matched or
                worker["response_rows"]!=20 or
                worker["global_unique_publications"] is not None or
                worker["deduplication_complete"] is not False):
            raise AssertionError("Spawned worker diverged from original source evidence")
        bytes_total=project.database_path.stat().st_size
    return dict(
        method=METHOD,
        platform=platform.platform(),python=platform.python_version(),
        sqlite=sqlite3.sqlite_version,
        synthetic_original_source_records=records,
        selected_run_source_records=selected,
        historical_run_source_records=records-selected,
        original_provisional_identities=materialised,
        unmaterialised_source_records=records-materialised,
        matched_source_pairs=matched,
        restored_row_counts_match=True,
        original_sqlite_integrity_check=integrity,
        original_foreign_key_check="ok",
        aggregate_original_database_size_bytes=bytes_total,
        timings_ms=timings,
        worker=worker,
        observed_parent_peak_rss_bytes=_peak_rss_bytes(),
        combined_child_and_parent_peak_rss_measured=False,
        native_browser_rendering_measured=False,
        worker_poll_loop_measured=True,
        all_100k_source_records_materialised=False,
        original_sources_complete=False,
        source_retrieval_verified=False,
        verified_complete=False,
        deduplication_complete=False,
        global_unique_publications=None,
        full_AT_22_acceptance=False,
        no_network_requests=True,
        total_elapsed_ms=round((perf_counter()-before)*1000,3),
    )


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records",type=int,default=100000)
    parser.add_argument("--selected",type=int,default=512)
    parser.add_argument("--matched",type=int,default=64)
    parser.add_argument("--worker-timeout-seconds",type=float,default=35)
    parser.add_argument("--json-output",type=Path)
    a=parser.parse_args()
    report=run(a.records,a.selected,a.matched,a.worker_timeout_seconds)
    encoded=json.dumps(report,sort_keys=True,indent=2)
    if a.json_output is not None:
        a.json_output.parent.mkdir(parents=True,exist_ok=True)
        a.json_output.write_text(encoded+"\n",encoding="utf-8")
    print(encoded)


if __name__=="__main__":
    main()
