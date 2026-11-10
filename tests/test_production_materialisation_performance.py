"""Small, offline original SQLite and real-worker checks for production-scale probe.

Full 100,000-source workloads execute in the dedicated performance workflow,
not in the ordinary four-platform test suite. This is a simulated explicit
researcher confirmation, never real user approval or a final publication count.
"""
import pytest

from scripts.benchmark_production_materialisation import run


def test_two_supervised_consent_batches_keep_originals_and_reject_replay():
    data = run(records=512, matched=4, worker_timeout_seconds=35)
    assert data["synthetic_original_source_records"] == 512
    assert data["initial_original_provisional_identities"] == 8
    assert data["batch_size"] == 64
    assert data["planned_confirmations"] == 2
    assert data["actual_production_confirmations"] == 2
    assert data["completed_two_batches"] is True
    assert data["fixture_only_bulk_materialiser_used"] is False
    assert data["no_real_researcher_consent_claimed"] is True
    initial = data["initial_evidence"]
    final = data["final_evidence"]
    assert initial["source_identity_links"] == 8
    assert final["source_identity_links"] == 136
    assert final["provisional_publications"] == 136
    assert final["identity_audit_events"] == 136
    assert final["selected_run_identity_links"] == 136
    assert final["selected_run_pending"] == 376
    assert final["source_rows_sha256"] == initial["source_rows_sha256"]
    assert final["membership_rows_sha256"] == initial["membership_rows_sha256"]
    assert final["sqlite_integrity_check"] == "ok"
    assert final["foreign_key_check"] == "ok"
    assert [s["preview_pending"] for s in data["stages"]] == [504, 440]
    for step in data["stages"]:
        assert step["preview_worker"]["state"] == "returned"
        assert step["preview_worker"]["returned"] is True
        assert step["confirm_worker"]["state"] == "returned"
        assert step["confirm_worker"]["returned"] is True
        assert step["reopened_after_commit"] is True
        assert step["replay_error"] == "publication_materialisation_stale"
        assert step["stale_replay_no_mutation"] is True
    assert data["global_unique_publications"] is None
    assert data["deduplication_complete"] is False
    assert data["source_retrieval_verified"] is False
    assert data["verified_complete"] is False
    assert data["full_AT_22_acceptance"] is False
    assert data["no_network_requests"] is True


@pytest.mark.parametrize("arguments", [
    {"records": 511, "matched": 4},
    {"records": 100001, "matched": 4},
    {"records": True, "matched": 4},
    {"records": 512, "matched": 0},
    {"records": 512, "matched": 65},
    {"records": 512, "matched": 4, "worker_timeout_seconds": 0},
    {"records": 512, "matched": 4, "worker_timeout_seconds": True},
])
def test_production_materialisation_probe_refuses_invalid_workload(arguments):
    with pytest.raises(ValueError):
        run(**arguments)
