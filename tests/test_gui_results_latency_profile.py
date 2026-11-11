"""Profiling must preserve canonical original count validation and privacy.

The full 100000-record native/loopback measurements run in a separate workflow.
These offline small fixtures prove the profiling wrappers have no authority to
alter a run, skip an integrity failure, or disclose bibliographic source text.
"""
from __future__ import annotations

from research_y import result_counts
from research_y.result_count_ledger import CountIntegrityError
from tools.gui_feasibility.run_materialisation_window import _fixture, _ledger
from tools.gui_feasibility.run_native_100k_results import (
    COUNT_STAGES, profile_original_count,
)

import pytest


def test_count_stage_profile_preserves_original_sources_and_revisions(tmp_path):
    project, run_id = _fixture(tmp_path)
    before = _ledger(project)
    originals = {
        name: getattr(result_counts, attribute)
        for name, attribute in COUNT_STAGES
    }
    profile = profile_original_count(project, run_id)
    assert profile["whole_run_ms"] > 0
    assert profile["stage_count"] == len(COUNT_STAGES) == 4
    assert set(profile["stages_ms"]) == set(originals)
    assert all(0 <= value < 120000 for value in
               profile["stages_ms"].values())
    assert 0 <= profile["other_validation_ms"] < 120000
    assert profile["full_original_validation_retained"] is True
    assert profile["original_source_records"] == 132
    assert profile["provisional_identity_hypotheses"] == 0
    assert profile["global_unique_publications"] is None
    assert _ledger(project) == before
    assert all(getattr(result_counts, attribute) is originals[name]
               for name, attribute in COUNT_STAGES)
    # No raw source field, absolute path, source identifier, hash or
    # personal/clinical text is returned by the timing envelope.
    assert set(profile) == {
        "whole_run_ms", "stages_ms", "other_validation_ms",
        "stage_count", "full_original_validation_retained",
        "original_source_records", "provisional_identity_hypotheses",
        "global_unique_publications"}
    assert "Identical original abstract title" not in repr(profile)
    assert str(project.root) not in repr(profile)


def test_profiler_rejects_corrupt_original_source_without_fallback(
        tmp_path, monkeypatch):
    project, run_id = _fixture(tmp_path)
    before = _ledger(project)
    original = result_counts._source_rows

    def corrupted(*_a, **_kw):
        raise CountIntegrityError("Synthetic original evidence corrupted")

    with monkeypatch.context() as m:
        m.setattr(result_counts, "_source_rows", corrupted)
        with pytest.raises(CountIntegrityError):
            profile_original_count(project, run_id)
        # The timing wrapper is removed even when the underlying validator
        # refuses the entire run; the original test fault remains in place.
        assert result_counts._source_rows is corrupted
    assert result_counts._source_rows is original
    assert _ledger(project) == before
