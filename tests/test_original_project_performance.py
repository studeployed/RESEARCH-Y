"""Real original SQLite project source/identity/worker scale smoke tests.

Only the separate performance workflow runs the 100,000-source workload.
These smaller cases validate the semantics without raising CI time budgets.
"""
from __future__ import annotations

import pytest

from scripts.benchmark_original_project import run


def test_original_project_retains_independent_provisional_identities():
    report=run(records=512,selected=128,matched=32,
               worker_timeout_seconds=35)
    assert report["synthetic_original_source_records"]==512
    assert report["selected_run_source_records"]==128
    assert report["historical_run_source_records"]==384
    assert report["original_provisional_identities"]==64
    assert report["unmaterialised_source_records"]==448
    assert report["matched_source_pairs"]==32
    assert report["restored_row_counts_match"] is True
    assert report["original_sqlite_integrity_check"]=="ok"
    assert report["original_foreign_key_check"]=="ok"
    assert report["worker"]["completed"] is True
    assert report["worker"]["candidate_count"]==32
    assert report["worker"]["response_rows"]==20
    assert report["worker"]["poll_count"]>=1
    assert report["worker"]["global_unique_publications"] is None
    assert report["worker"]["deduplication_complete"] is False
    assert report["no_network_requests"] is True
    assert report["global_unique_publications"] is None
    assert report["deduplication_complete"] is False
    assert report["source_retrieval_verified"] is False
    assert report["full_AT_22_acceptance"] is False
    assert report["all_100k_source_records_materialised"] is False
    assert report["native_browser_rendering_measured"] is False
    assert report["aggregate_original_database_size_bytes"]>0
    assert report["observed_parent_peak_rss_bytes"] is None or (
        report["observed_parent_peak_rss_bytes"]>0)


@pytest.mark.parametrize("arguments",[
    dict(records=10,selected=128,matched=32),
    dict(records=100001,selected=512,matched=64),
    dict(records=512,selected=1024,matched=32),
    dict(records=512,selected=127,matched=32),
    dict(records=512,selected=128,matched=65),
    dict(records=512,selected=128,matched=0),
    dict(records=512,selected=128,matched=32,worker_timeout_seconds=0),
])
def test_original_source_benchmark_refuses_unbounded_input(arguments):
    with pytest.raises(ValueError):
        run(**arguments)
