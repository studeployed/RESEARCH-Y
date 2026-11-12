"""Finite host-owned GUI browsing contract on a 100k original-source result set.

Ordinary four-platform Python CI tests only the guarded transport assertions.
The dedicated pinned graphical workflow exercises real SQLite, workers and
native Windows button clicks against 100000 audited provisional identities.
"""
from __future__ import annotations

import json

import pytest

from scripts.benchmark_original_project import RUN
from tools.gui_feasibility import run_real_project as driver
from tools.gui_feasibility.run_prototype import ExperimentFailure


def _row(i):
    return {
        "publication_id": f"hypothesis-{i:04d}",
        "publication_identity_verified": False,
        "identity_status": "provisional_review_required",
        "original_source_records_in_run": 1,
        "additional_source_records_in_other_runs": 0,
    }


def _page(start, *, after=None, revision="a" * 64, count=100000):
    rows = [_row(i) for i in range(start, start + 20)]
    return {
        "run_id": RUN,
        "revision": revision,
        "rows": rows,
        "page_size": 20,
        "after_publication_id": after,
        "next_after_publication_id": rows[-1]["publication_id"],
        "has_more": True,
        "provisional_publication_identities": count,
        "retrieved_source_records": count,
        "unmaterialised_source_records": 0,
        "global_unique_publications": None,
        "deduplication_complete": False,
        "source_retrieval_verified": False,
        "verified_complete": False,
        "no_network_requests": True,
    }


def _replies(*, overlap=False, false_unique=False):
    first = _page(0)
    second = _page(0 if overlap else 20,
                   after=first["next_after_publication_id"])
    second["revision"] = first["revision"]
    detail = {
        "run_id": RUN,
        "revision": first["revision"],
        "publication": {
            "publication_id": second["rows"][0]["publication_id"]},
        "abstract_text_displayed": False,
        "redistribution_permission_established": False,
        "global_unique_publications": 100000 if false_unique else None,
        "deduplication_complete": False,
        "source_retrieval_verified": False,
        "verified_complete": False,
        "no_network_requests": True,
        "source_retrievals": [{"included_in_selected_run": True}],
    }
    return [
        {"error": None, "state": {"source_retrieval_verified": False,
                                  "selected_run_id": None}},
        {"error": None, "state": {"source_retrieval_verified": False,
                                  "selected_run_id": RUN}},
        {"error": None, "state": {"source_retrieval_verified": False,
                                  "publication_page": first}},
        {"error": None, "state": {"source_retrieval_verified": False,
                                  "publication_page": second}},
        {"error": None, "state": {"source_retrieval_verified": False,
                                  "publication_page": second,
                                  "publication_detail": detail}},
    ]


def _run(monkeypatch, responses):
    iterator = iter(responses)
    def action(*_args, **_kwargs):
        return 200, {}, json.dumps(next(iterator)).encode("utf-8")
    monkeypatch.setattr(driver, "request_action", action)
    monkeypatch.setattr(driver, "request",
                        lambda *_a, **_kw: (200, {}, b""))
    return driver.transport_results_steps(5000, {}, RUN, 100000)


def test_original_100k_two_distinct_pages_and_bounded_source_detail(monkeypatch):
    assert _run(monkeypatch, _replies()) == [
        "open", "select_run", "publication_refresh",
        "publication_next", "publication_detail",
    ]


@pytest.mark.parametrize("kind", ["overlap", "false_unique", "wrong_count"])
def test_native_100k_browser_cannot_claim_success_for_invalid_result_evidence(
        monkeypatch, kind):
    responses = _replies(overlap=(kind == "overlap"),
                         false_unique=(kind == "false_unique"))
    if kind == "wrong_count":
        responses[2]["state"]["publication_page"]["provisional_publication_identities"] = 99999
    with pytest.raises(ExperimentFailure):
        _run(monkeypatch, responses)


def test_native_results_100k_scenario_never_accepts_browser_source_identifiers():
    from pathlib import Path
    root = Path(__file__).parents[1]
    from desktop_source import project_ui_source
    source = project_ui_source()
    runner = (root / "tools/gui_feasibility/run_native_100k_results.py").read_text(
        encoding="utf-8")
    assert "args.scenario == 'publication_results_large'" in source
    assert "await native_results_probe()" in source
    assert "await until_native_button('publication-next', js)" in source
    assert "'global_unique_publications'] is not None" in source
    assert "'cursor': page['next_after_publication_id']" in source
    assert "'publication_id': page['rows'][0]['publication_id']" in source
    assert 'materialise_remaining_fixture(' in runner
    assert '"native_desktop_installer_tested": False' in runner
    assert '"full_AT_22_acceptance": False' in runner
