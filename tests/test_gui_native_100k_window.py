"""Source-scale native-GUI transport invariants (no live providers or GUI dependency).

The dedicated Windows/Linux workflow performs the real 100,000-original-source
GUI run. These fast tests require that the exact same transport validation
rejects false large-run source counts, including after an uncertain reply.
"""
from __future__ import annotations

import json

import pytest

from scripts.benchmark_original_project import RUN
from tools.gui_feasibility import run_real_project as driver
from tools.gui_feasibility import run_materialisation_window as window
from research_y.strategy_report import _strategy
from tools.gui_feasibility.run_prototype import ExperimentFailure


@pytest.mark.parametrize("lost", [False, True])
def test_large_original_window_validates_precise_durable_counts(monkeypatch, lost):
    source_count = 100000
    initial_links = 128
    expected_pending = source_count - initial_links
    expected_remaining = expected_pending - 128
    expected_links = initial_links + 128
    sequence = [
        {"state": {"source_retrieval_verified": False,
                   "selected_run_id": None}, "error": None},
        {"state": {"source_retrieval_verified": False,
                   "selected_run_id": RUN}, "error": None},
        {"state": {"source_retrieval_verified": False,
                   "publication_window_offer": {
                       "batch_sizes": [64, 64],
                       "proposed_source_records": 128,
                       "unmaterialised_retrievals": expected_pending,
                       "global_unique_publications": None}}, "error": None},
        {"state": {"source_retrieval_verified": False,
                   "publication_window_offer": None,
                   "publication_window_reinspect_required": lost,
                   "publication_window_last_outcome": None if lost else {
                       "committed_batches": 2,
                       "materialised_in_session": 128,
                       "global_unique_publications": None}},
         "error": "publication_window_reinspect_required" if lost else None},
        {"state": {"source_retrieval_verified": False,
                   "publication_window_last_inspection": {
                       "unmaterialised_retrievals": expected_remaining,
                       "existing_publication_hypotheses": expected_links},
                   "publication_window_offer": None,
                   "publication_window_reinspect_required": False,
                   "publication_window_last_outcome": None if lost else {
                       "committed_batches": 2,
                       "materialised_in_session": 128,
                       "global_unique_publications": None}},
         "error": None},
    ]
    cursor = iter(sequence)

    def next_response(*_args, **_kwargs):
        return 200, {}, json.dumps(next(cursor)).encode("utf-8")

    monkeypatch.setattr(driver, "request_action", next_response)
    monkeypatch.setattr(driver, "request", lambda *_a, **_kw: (200, {}, b""))
    actions = driver.transport_window_steps(
        5000, {}, "publication_window_lost_reply" if lost
        else "publication_window", RUN,
        expected_pending=expected_pending,
        expected_remaining=expected_remaining,
        expected_provisional=expected_links)
    assert len(actions) == 5
    assert actions[-1] == "publication_window_inspect"
    if lost:
        assert "publication_window_confirm_interrupted" in actions
    else:
        assert "publication_window_confirm" in actions


def test_large_window_transport_rejects_false_zero_remaining(monkeypatch):
    """A complete-looking report cannot pass with 99,744 originals outstanding."""
    emitted = [
        {"state": {"source_retrieval_verified": False,
                   "selected_run_id": None}, "error": None},
        {"state": {"source_retrieval_verified": False,
                   "selected_run_id": RUN}, "error": None},
        {"state": {"source_retrieval_verified": False,
                   "publication_window_offer": {
                       "batch_sizes": [64, 64],
                       "proposed_source_records": 128,
                       "unmaterialised_retrievals": 99872,
                       "global_unique_publications": None}}, "error": None},
        {"state": {"source_retrieval_verified": False,
                   "publication_window_offer": None,
                   "publication_window_last_outcome": {
                       "committed_batches": 2, "materialised_in_session": 128,
                       "global_unique_publications": None}}, "error": None},
        {"state": {"source_retrieval_verified": False,
                   "publication_window_offer": None,
                   "publication_window_reinspect_required": False,
                   "publication_window_last_outcome": {
                       "committed_batches": 2, "materialised_in_session": 128,
                       "global_unique_publications": None},
                   "publication_window_last_inspection": {
                       "unmaterialised_retrievals": 0,
                       "existing_publication_hypotheses": 256}}, "error": None},
    ]
    iterator = iter(emitted)
    monkeypatch.setattr(driver, "request_action",
                        lambda *_a, **_kw: (
                            200, {}, json.dumps(next(iterator)).encode("utf-8")))
    monkeypatch.setattr(driver, "request", lambda *_a, **_kw: (200, {}, b""))
    with pytest.raises(ExperimentFailure):
        driver.transport_window_steps(
            5000, {}, "publication_window", RUN,
            expected_pending=99872,
            expected_remaining=99744,
            expected_provisional=256)


def test_original_100k_fixture_approves_immutable_broad_or_snapshot(monkeypatch, tmp_path):
    captured = {}
    def inspect_seed(project, records, selected, matched, *, strategy_snapshot):
        assert records == selected == 100000 and matched == 64
        captured["snapshot"] = strategy_snapshot
        return 128

    monkeypatch.setattr(window, "_seed", inspect_seed)
    _, run_id = window._large_fixture(tmp_path)
    assert run_id == RUN
    snapshot = captured["snapshot"]
    assert snapshot["logic"] == "OR"
    assert snapshot["approved_by"] == "Synthetic test-only researcher"
    assert snapshot["groups"][0]["terms"][0]["approved"] is True
    _strategy(snapshot, [("all", "Biomedical synthetic OR-group", 0)])
