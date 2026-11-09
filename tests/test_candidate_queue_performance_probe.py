"""Fast synthetic checks for the opt-in 100,000-record SQL benchmark.

These prove fixture integrity and query plan direction; do not use fixed
latency thresholds on shared continuous-integration runners.
"""
from __future__ import annotations

from scripts.benchmark_candidate_queue import run


def test_small_sql_kernel_smoke_is_reproducible_and_non_destructive():
    report=run(1000,800,100,4)
    assert report["method"]=="synthetic-candidate-index-sql-performance/1"
    assert report["parameters"]=={
        "records":1000,"pair_hints":800,
        "synthetic_receipts":100,"repetitions":4,
    }
    assert report["reopened_integrity_check"]=="ok"
    assert report["sqlite_fixture_size_bytes"]>0
    assert report["first_page"]["returned_rows"]==21
    assert report["page_near_tail"]["returned_rows"]==21
    assert report["dense_key_peer_seek"]["returned_rows"]>0
    assert report["source_key_resume"]["returned_rows"]==128
    assert report["receipt_lookup"]["synthetic_receipt_groups"]==100
    assert report["no_network_requests"] is True
    assert report["end_to_end_acceptance_AT_22"] is False
    assert report["original_audit_receipts_validated"] is False
    assert report["global_unique_publications"] is None
    assert report["deduplication_complete"] is False
    for query in ("candidate_pair_page","candidate_pair_near_tail",
                  "peer_hash_seek","source_key_resume"):
        assert report["query_plans"][query]
    # The stage gives no absolute wall-clock performance guarantee.
    assert report["first_page"]["median_ms"]>=0
    assert report["receipt_lookup"]["group_build_ms"]>=0


def test_perf_probe_reports_a_bounded_dense_cache_on_small_input():
    report=run(101,100,20,2)
    assert report["parameters"]["records"]==101
    assert report["source_key_resume"]["returned_rows"]==51  # 101 - 50 rows after the cursor
    assert report["dense_key_peer_seek"]["returned_rows"]==100
    assert report["page_near_tail"]["returned_rows"]==21


def test_perf_probe_rejects_unbounded_or_missing_workloads():
    import pytest
    for args in ((0,1,1,1),(100001,1,1,1),(100,101,1,1),
                 (100,1,101,1),(100,1,1,0),(100,1,1,1001)):
        with pytest.raises(ValueError):
            run(*args)
