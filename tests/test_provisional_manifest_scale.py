"""Small original SQLite acceptance for the full-sized manifest benchmark path."""
from __future__ import annotations

import pytest

from scripts.benchmark_provisional_manifest import (
    METHOD, EvidenceFailure, _original_table_hash, run,
)


@pytest.mark.parametrize("records", [0, 511, 100001, 512.0, "512", True])
def test_manifest_scale_refuses_nonrepresentative_or_unbounded_input(records):
    with pytest.raises(ValueError):
        run(records=records)


def test_512_original_source_manifest_scale_both_states():
    """Exercise both actual Excel parsers, all source rows and full revisions.

    The separate Linux/Windows workflow runs 100000 originals; using 512 here
    keeps the full core Python matrix fast and tests the exact same verifier.
    """
    data = run(records=512)
    assert data["method"] == METHOD
    assert data["passed"] is True
    assert data["records"] == 512
    assert data["initial_provisional_identities"] == 128
    assert data["scenario_count"] == 2
    assert [x["scenario"] for x in data["cases"]] == [
        "partially_materialised", "all_independent_provisional",
    ]
    assert [x["provisional_identity_rows"] for x in data["cases"]] == [
        128, 512,
    ]
    assert [x["unmaterialised_originals"] for x in data["cases"]] == [
        384, 0,
    ]
    for case in data["cases"]:
        assert case["original_source_records"] == 512
        assert case["original_source_link_rows"] == 512
        assert case["original_query_membership_rows"] == 512
        assert case["workbook_bytes"] > 1000
        assert case["render_elapsed_ms"] > 0
        assert case["separate_workbook_verification_ms"] > 0
        assert case["all_original_sql_rows_reconciled"] is True
        assert case["source_and_membership_sqlite_unchanged"] is True
        assert case["original_source_and_membership_hashes_revalidated"] is True
        assert case["sqlite_integrity_verified"] is True
        assert case["foreign_keys_verified"] is True
        assert case["no_provider_metadata_exported"] is True
        assert case["no_excel_formulas"] is True
        assert case["incomplete_scientific_status_retained"] is True
    assert data["source_retrieval_verified"] is False
    assert data["deduplication_complete"] is False
    assert data["verified_complete"] is False
    assert data["global_unique_publications"] is None
    assert data["final_master_results_export_implemented"] is False
    assert data["user_published_export_or_recovery_tested"] is False
    assert data["full_AT_18_acceptance"] is False
    assert data["full_AT_22_acceptance"] is False
    assert data["no_provider_network_requests"] is True
    assert data["original_synthetic_fixture_only"] is True
    # Source-free diagnostics: private originals and local paths never enter
    # the aggregate CI artifact or any benchmark exception message.
    assert "Synthetic report" not in repr(data)
    assert "10.9300/" not in repr(data)
    assert "researchy-original-manifest-scale" not in repr(data)


def test_original_manifest_table_hash_allowlist(tmp_path):
    import sqlite3
    with sqlite3.connect(tmp_path / "unrelated.sqlite") as db:
        with pytest.raises(ValueError, match="Only original source"):
            _original_table_hash(db, "audit_events")
