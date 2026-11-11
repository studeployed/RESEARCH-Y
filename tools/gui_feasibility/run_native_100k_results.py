"""Actual native/loopback provisional-result paging on a real 100k-row project.

Synthetic original SQLite source rows are fully materialised through the
existing fixture-only audited writer before the GUI opens. The native window
must actually refresh, advance one 20-row keyset page and open source detail.
Neither this fixture nor the GUI proves global unique publications or AT-22.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from research_y import result_counts
from research_y.projects import open_project
from scripts.benchmark_original_project import materialise_remaining_fixture
from tools.gui_feasibility.run_materialisation_window import (
    _large_fixture, _ledger, LARGE_RECORDS,
)
from tools.gui_feasibility.run_real_project import (
    ExperimentFailure, require, run_app,
)

METHOD = "original-project-native-100k-results/1"
EXPECTED = LARGE_RECORDS


COUNT_STAGES = (
    ("original_source_validation", "_source_rows"),
    ("original_identity_link_validation", "_identity_rows"),
    ("query_membership_validation", "_query_rows"),
    ("original_review_receipt_validation", "_review_counts"),
)


def profile_original_count(project, run_id):
    """Time actual original count stages without bypassing a single validator.

    Temporary wrappers run in this disposable, isolated test process and are
    restored before the GUI worker is launched. They never access source text,
    retain a cached projection, or alter a database transaction.
    """
    measured = {}
    with ExitStack() as stack:
        for name, attribute in COUNT_STAGES:
            original = getattr(result_counts, attribute)

            def observed(*args, _original=original, _name=name, **kwargs):
                started = perf_counter()
                try:
                    return _original(*args, **kwargs)
                finally:
                    measured[_name] = round(
                        (perf_counter() - started) * 1000, 3)

            stack.enter_context(patch.object(result_counts, attribute, observed))
        started = perf_counter()
        projection = result_counts.read_run_counts(project, run_id)
        total = round((perf_counter() - started) * 1000, 3)
    # Validate original count semantics, never use a profiler-created count
    # as an independent or more authoritative scientific result.
    if (projection.run_id != run_id or
            projection.totals["metadata_source_records"] <= 0 or
            projection.totals["global_unique_publications"] is not None or
            projection.source_retrieval_verified is not False or
            projection.deduplication_complete is not False or
            projection.verified_complete is not False):
        raise ExperimentFailure("count_profile_original_evidence_invalid")
    return {
        "whole_run_ms": total,
        "stages_ms": measured,
        "other_validation_ms": round(
            max(0.0, total - sum(measured.values())), 3),
        "stage_count": len(measured),
        "full_original_validation_retained": True,
        "original_source_records": projection.totals[
            "metadata_source_records"],
        "provisional_identity_hypotheses": projection.totals[
            "global_publication_identities"],
        "global_unique_publications": None,
    }


def run(mode):
    with TemporaryDirectory(prefix="researchy-native-results-100k-") as dirname:
        root = Path(dirname)
        project, run_id = _large_fixture(root)
        initial = _ledger(project)
        require(initial["sources"] == EXPECTED and
                initial["memberships"] == EXPECTED and
                initial["provisional"] == 128 and
                initial["links"] == 128 and
                initial["identity_audits"] == 128 and
                initial["sqlite_integrity_check"] == "ok" and
                initial["foreign_key_check"] is True,
                "original_results_fixture_invalid")
        started = perf_counter()
        prepared = materialise_remaining_fixture(
            project, batch_size=256)
        project = open_project(project.root)
        before = _ledger(project)
        require(prepared["exhausted_sources"] is True and
                prepared["newly_materialised"] == EXPECTED - 128 and
                before["sources"] == EXPECTED and
                before["memberships"] == EXPECTED and
                before["provisional"] == EXPECTED and
                before["links"] == EXPECTED and
                before["identity_audits"] == EXPECTED and
                before["distinct_publications"] == EXPECTED and
                before["linked_order_exact"] is True and
                before["sqlite_integrity_check"] == "ok" and
                before["foreign_key_check"] is True and
                before["original_source_sha256"] ==
                    initial["original_source_sha256"] and
                before["original_membership_sha256"] ==
                    initial["original_membership_sha256"],
                "original_results_materialisation_unverified")
        materialise_seconds = round(perf_counter() - started, 3)
        count_profile = profile_original_count(project, run_id)
        require(count_profile["original_source_records"] == EXPECTED and
                count_profile["provisional_identity_hypotheses"] == EXPECTED and
                count_profile["stage_count"] == len(COUNT_STAGES),
                "count_profile_original_records_invalid")
        gui_started = perf_counter()
        observed = run_app(
            mode, "publication_results_large", project, root, run_id, "",
            expected_results=EXPECTED)
        gui_seconds = round(perf_counter() - gui_started, 3)
        after = _ledger(open_project(project.root))
        intact = (after == before)
        expected_actions = [
            "open", "select_run", "publication_refresh",
            "publication_next", "publication_detail"]
        service_actions = observed.get("results_action_service_ms")
        native_actions = observed.get("native_results_action_ms")
        service_valid = bool(
            type(service_actions) is list and
            [x.get("action") for x in service_actions if type(x) is dict]
                == expected_actions and len(service_actions) == 5 and
            all(type(x.get("elapsed_ms")) in (int, float) and
                0 < x["elapsed_ms"] < 120000 for x in service_actions))
        native_valid = bool(
            mode != "native" and native_actions is None or
            mode == "native" and type(native_actions) is list and
            len(native_actions) == 5 and
            all(type(x) in (int, float) and 0 < x < 120000
                for x in native_actions))
        passed = bool(
            service_valid and native_valid and
            observed.get("passed") is True and intact and
            observed.get("results_paging_verified") is True and
            observed.get("results_detail_verified") is True and
            (mode != "native" or
             observed.get("native_rendering_verified") is True))
        return {
            "mode": mode,
            "passed": passed,
            "original_sources": EXPECTED,
            "original_memberships": EXPECTED,
            "provisional_hypotheses": EXPECTED,
            "original_identity_audits": after["identity_audits"],
            "original_sources_unchanged": after["original_source_sha256"] ==
                initial["original_source_sha256"],
            "original_memberships_unchanged": after["original_membership_sha256"] ==
                initial["original_membership_sha256"],
            "post_gui_sqlite_intact": intact,
            "post_gui_sqlite_integrity_verified": after["sqlite_integrity_check"] == "ok",
            "post_gui_foreign_keys_verified": after["foreign_key_check"] is True,
            "gui_two_distinct_20_row_pages": observed.get("results_paging_verified"),
            "gui_bounded_original_source_detail": observed.get("results_detail_verified"),
            "native_rendering_verified": observed.get("native_rendering_verified", False),
            "observed_error": observed.get("observed_error"),
            "error": observed.get("error"),
            "fixture_preparation_elapsed_s": materialise_seconds,
            "gui_session_elapsed_s": gui_seconds,
            "original_count_stage_profile": count_profile,
            "results_action_service_ms": service_actions,
            "native_results_action_ms": native_actions,
            "results_action_profile_verified": service_valid and native_valid,
        }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", required=True, type=Path)
    p.add_argument("--native", action="store_true")
    args = p.parse_args()
    mode = "native" if args.native else "transport"
    if args.native and sys.platform != "win32":
        raise ValueError("Native rendering requires Windows")
    try:
        case = run(mode)
        accepted = case["passed"]
        evidence = {
            "method": METHOD,
            "mode": mode,
            "case": case,
            "passed": accepted,
            "real_original_sqlite": True,
            "real_application_worker": True,
            "real_native_window": mode == "native",
            "no_provider_network_requests": True,
            "unattended_user_materialisation": False,
            "synthetic_fixture_only_materialisation": True,
            "global_unique_publications": None,
            "deduplication_complete": False,
            "source_retrieval_verified": False,
            "verified_complete": False,
            "native_desktop_installer_tested": False,
            "full_AT_22_acceptance": False,
        }
    except (ExperimentFailure, ValueError, OSError, sqlite3.Error) as exc:
        accepted = False
        evidence = {
            "method": METHOD, "mode": mode, "passed": False,
            "error": str(exc) if isinstance(exc, ExperimentFailure)
                     else "native_results_probe_failed",
            "global_unique_publications": None,
            "full_AT_22_acceptance": False,
        }
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / "original-gui-results-evidence.json").write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    print("Original 100k GUI results:", "passed" if accepted else "failed", "|", mode)
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
