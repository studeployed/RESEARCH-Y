"""Deterministic *component-level* candidate queue performance probe.

Run offline with:
  python scripts/benchmark_candidate_queue.py --records 100000 --pairs 100000 --receipts 10000 --json-output evidence.json

Uses a disposable, actual on-disk SQLite database containing production-shaped
source-key and pair-index tables with the *same indexes*. It exercises actual
production SQL constants and the pure validated-receipt lookup builder.

IMPORTANT: This does NOT simulate canonical publication/audit validation or a
complete literature search; it is not the end-to-end AT-22 acceptance test.
No provider access, user data, credentials or permanent source records.
"""
from __future__ import annotations

import argparse
from collections import deque
from hashlib import sha256
import json
from pathlib import Path
import platform
import sqlite3
from statistics import median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import tracemalloc

from research_y import candidate_pair_checkpoints as pairs
from research_y import candidate_index_build as keys
from research_y import publication_candidate_queue as queue
from research_y import publication_candidates as review

SELECTED = "00000000-0000-4000-8000-000000000001"
HISTORICAL = "00000000-0000-4000-8000-000000000002"
GENERATION = "00000000-0000-4000-8000-000000000003"


def rid(number: int) -> str:
    if not 1 <= number < 2**48:
        raise ValueError("Synthetic record identifier outside UUID fixture range")
    return f"11111111-1111-4111-8111-{number:012x}"


def _digest(value: str) -> str:
    return sha256(value.encode("ascii")).hexdigest()


def _schema(db: sqlite3.Connection) -> None:
    # Mirror the production indexes and the exact columns exercised below.
    # These are deliberate SQL-kernel fixtures, not a second project schema.
    db.executescript("""
    CREATE TABLE source_retrievals (
        retrieval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL);
    CREATE TABLE candidate_index_records (
        retrieval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
        supported INTEGER NOT NULL, generation_id TEXT NOT NULL);
    CREATE INDEX candidate_index_records_by_run
        ON candidate_index_records(run_id,retrieval_id);
    CREATE TABLE candidate_index_keys (
        retrieval_id TEXT NOT NULL, field TEXT NOT NULL,
        value_sha256 TEXT NOT NULL, PRIMARY KEY(retrieval_id,field));
    CREATE INDEX candidate_index_keys_by_field
        ON candidate_index_keys(field,value_sha256,retrieval_id);
    CREATE TABLE publication_retrievals (
        retrieval_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL);
    CREATE TABLE candidate_pair_hints (
        run_id TEXT NOT NULL, generation_id TEXT NOT NULL,
        left_retrieval_id TEXT NOT NULL, right_retrieval_id TEXT NOT NULL,
        fields_mask INTEGER NOT NULL,
        PRIMARY KEY(run_id,left_retrieval_id,right_retrieval_id));
    """)


def _populate(db: sqlite3.Connection, records: int, pair_count: int) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        for base in range(1, records+1, 2000):
            items = range(base, min(base+2000,records+1))
            source_records = []
            key_records = []
            membership = []
            materialised = []
            for i in items:
                record_id = rid(i)
                run = SELECTED if i <= max(2, records//10) else HISTORICAL
                # Dense first 1,000 records and reproducible small
                # four-record buckets elsewhere. No abstracts/identifiers.
                bucket = "dense" if i <= min(1000,records) else f"k{i//4:08d}"
                source_records.append((record_id,run))
                key_records.append((record_id,run,1,GENERATION))
                membership.append((record_id, "doi", _digest(bucket)))
                materialised.append((record_id,record_id))
            db.executemany("INSERT INTO source_retrievals VALUES (?,?)",source_records)
            db.executemany("INSERT INTO candidate_index_records VALUES (?,?,?,?)",
                           key_records)
            db.executemany("INSERT INTO candidate_index_keys VALUES (?,?,?)",
                           membership)
            db.executemany("INSERT INTO publication_retrievals VALUES (?,?)",
                           materialised)
        for base in range(1,pair_count+1,2000):
            rows=[]
            for i in range(base,min(base+2000,pair_count+1)):
                a,b=rid(i),rid(i+1 if i < records else 1)
                left,right=sorted((a,b))
                rows.append((SELECTED,GENERATION,left,right,1))
            db.executemany(
                "INSERT INTO candidate_pair_hints VALUES (?,?,?,?,?)",rows)
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _observed(db, query, args, repetitions):
    timings=[]
    sample=None
    for _ in range(repetitions):
        before=perf_counter()
        rows=db.execute(query,args).fetchall()
        timings.append((perf_counter()-before)*1000)
        if sample is None:
            sample=rows
        elif rows != sample:
            raise AssertionError("Repeated indexed reads returned inconsistent rows")
    ordered=sorted(timings)
    return dict(
        median_ms=round(median(timings),3),
        p95_ms=round(ordered[max(0, int(len(ordered)*.95+.999999)-1)],3),
        max_ms=round(max(timings),3),
        returned_rows=len(sample),
        sample_sha256=sha256(repr(sample).encode("utf-8")).hexdigest(),
    )


def _plan(db, query, args):
    return [row[3] for row in db.execute("EXPLAIN QUERY PLAN "+query,args)]


def _receipt_lookup(receipt_count, repetitions):
    # Synthetic *already-validated-shaped* receipt dictionaries. Measuring
    # the grouping cost here is NOT a substitute for measuring the original
    # audit-validation service on real data.
    receipts = [
        {"source_keys": sorted((
            ["pubmed","","PMID:"+str(i)],
            ["wos","WOS","WOS:"+str(i)],
        )), "event_id":i}
        for i in range(1,receipt_count+1)
    ]
    tracemalloc.start()
    started=perf_counter()
    lookup=review._index_validated_receipts(receipts)
    construction_ms=(perf_counter()-started)*1000
    peak=tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    if len(lookup)!=receipt_count:
        raise AssertionError("Distinct historic source keys were lost")
    keys_list=list(lookup)
    start=perf_counter()
    checksum=0
    for i in range(repetitions*20):
        key=keys_list[i%len(keys_list)]
        checksum+=len(lookup.get(key,()))
    elapsed_ms=(perf_counter()-start)*1000
    if checksum!=repetitions*20:
        raise AssertionError("Receipt lookups lost decision references")
    return {
        "synthetic_receipt_groups":len(lookup),
        "group_build_ms":round(construction_ms,3),
        "20_pair_lookup_ms":round(elapsed_ms/repetitions,6),
        "python_grouping_peak_bytes":peak,
    }


def run(records, pair_count, receipt_count, repetitions):
    if (not 100 <= records <= 100000 or
            not 1 <= pair_count <= records or
            not 1 <= receipt_count <= records or
            not 1 <= repetitions <= 1000):
        raise ValueError("Bounded synthetic workload is required")
    begin=perf_counter()
    with TemporaryDirectory(prefix="research-y-synthetic-benchmark-") as root:
        dbpath=Path(root)/"synthetic.sqlite3"
        db=sqlite3.connect(dbpath)
        try:
            _schema(db)
            _populate(db,records,pair_count)
            bulk_ms=(perf_counter()-begin)*1000
            db.close()
            db=sqlite3.connect(dbpath)
            assert db.execute("PRAGMA integrity_check").fetchone()==("ok",)
            assert db.execute("SELECT COUNT(*) FROM source_retrievals").fetchone()==(records,)
            assert db.execute("SELECT COUNT(*) FROM candidate_index_keys").fetchone()==(records,)
            assert db.execute("SELECT COUNT(*) FROM candidate_pair_hints").fetchone()==(pair_count,)
            first_id,last_id=rid(1),rid(records)
            first_pair=("", "")
            last_pair=tuple(sorted((rid(pair_count),rid(pair_count+1 if pair_count<records else 1))))
            page_first=_observed(
                db,queue._PAIR_PAGE_SQL,
                (SELECTED,first_pair[0],first_pair[1],21),repetitions)
            page_near_tail=_observed(
                db,queue._PAIR_PAGE_SQL,
                (SELECTED,*last_pair,21),repetitions)
            peer=_observed(
                db,pairs.PEERS_SQL,
                ("doi",_digest("dense"),"",first_id,SELECTED,first_id,129),
                repetitions)
            resume=_observed(
                db,keys._RESUME_SQL,(rid(max(1,records//2)),128),repetitions)
            plans={
                "candidate_pair_page":_plan(
                    db,queue._PAIR_PAGE_SQL,(SELECTED,"","",21)),
                "candidate_pair_near_tail":_plan(
                    db,queue._PAIR_PAGE_SQL,(SELECTED,*last_pair,21)),
                "peer_hash_seek":_plan(
                    db,pairs.PEERS_SQL,
                    ("doi",_digest("dense"),"",first_id,SELECTED,first_id,129)),
                "source_key_resume":_plan(
                    db,keys._RESUME_SQL,(rid(max(1,records//2)),128)),
            }
            if not any("SEARCH candidate_pair_hints" in s
                       for s in plans["candidate_pair_page"]):
                raise AssertionError("Pair pagination lost its indexed seek")
            if not any("SEARCH candidate_index_keys" in s
                       for s in plans["peer_hash_seek"]):
                raise AssertionError("Dense-key peers lost their indexed seek")
            db_size=dbpath.stat().st_size
        finally:
            db.close()
    receipts=_receipt_lookup(receipt_count,repetitions)
    return {
        "method":"synthetic-candidate-index-sql-performance/1",
        "scope":"SQL/index kernels and already-validated-shaped receipt grouping only",
        "end_to_end_acceptance_AT_22":False,
        "production_native_gui_tested":False,
        "original_audit_receipts_validated":False,
        "no_network_requests":True,
        "source_retrieval_verified":False,
        "deduplication_complete":False,
        "global_unique_publications":None,
        "platform":platform.platform(),
        "python_version":platform.python_version(),
        "sqlite_version":sqlite3.sqlite_version,
        "parameters":dict(records=records,pair_hints=pair_count,
                          synthetic_receipts=receipt_count,repetitions=repetitions),
        "sqlite_fixture_build_ms":round(bulk_ms,3),
        "sqlite_fixture_size_bytes":db_size,
        "reopened_integrity_check":"ok",
        "first_page":page_first,
        "last_page_after_final_pair":page_near_tail,
        "dense_key_peer_seek":peer,
        "source_key_resume":resume,
        "receipt_lookup":receipts,
        "query_plans":plans,
        "total_elapsed_ms":round((perf_counter()-begin)*1000,3),
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records",type=int,default=100000)
    parser.add_argument("--pairs",type=int,default=100000)
    parser.add_argument("--receipts",type=int,default=10000)
    parser.add_argument("--repetitions",type=int,default=40)
    parser.add_argument("--json-output",type=Path)
    args=parser.parse_args()
    report=run(args.records,args.pairs,args.receipts,args.repetitions)
    raw=json.dumps(report,sort_keys=True,indent=2)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True,exist_ok=True)
        args.json_output.write_text(raw+"\n",encoding="utf-8")
    print(raw)


if __name__=="__main__":
    main()
