"""One explicitly approved 128-record window against 100,000 original sources.

Exercises the actual trusted ApplicationCommand, spawned ApplicationWorker,
original 64-record writer and independently reopened schema-v6 SQLite project.
A complete selected-run production materialisation is NOT tested. No provider
calls, private clinical data, automated approvals or final publication count.
Run as a module: python -m scripts.benchmark_materialisation_window
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter

from research_y.application_commands import (
    ApplicationCommand, ApplicationCommandError, execute_command,
)
from research_y.projects import create_project, open_project
from scripts.benchmark_original_project import RUN, _seed
from scripts.benchmark_production_materialisation import (
    _ledger, _worker_command,
)

METHOD = "production-two-batch-materialisation-probe/1"


def run(records=100000, matched=64, worker_timeout_seconds=35):
    if (type(records) is not int or not 512 <= records <= 100000
            or records % 2 or type(matched) is not int
            or not 1 <= matched <= min(64, records // 4)
            or type(worker_timeout_seconds) not in (int, float)
            or not 1 <= worker_timeout_seconds <= 120):
        raise ValueError("Bounded synthetic consent window required")
    started = perf_counter()
    with TemporaryDirectory(prefix="researchy-window-100k-") as tmp:
        project = create_project(Path(tmp), "Two-batch synthetic source stress")
        baseline_linked = _seed(project, records, records, matched)
        baseline = _ledger(project)
        if (baseline["source_records"] != records or
                baseline["membership_rows"] != records or
                baseline["source_identity_links"] != baseline_linked or
                baseline["identity_audit_events"] != baseline_linked or
                baseline["selected_run_pending"] != records - baseline_linked or
                baseline["sqlite_integrity_check"] != "ok" or
                baseline["foreign_key_check"] != "ok"):
            raise AssertionError("Original source baseline invalid")
        project = open_project(project.root)
        pre_cmd = ApplicationCommand.for_project(
            project, "publication_window_preview", run_id=RUN)
        preview_worker, preview = _worker_command(
            pre_cmd, worker_timeout_seconds)
        command_worker = None
        reply = None
        if preview is not None:
            confirm_cmd = ApplicationCommand.for_project(
                project, "publication_window_confirm", run_id=RUN,
                publication_view_revision=preview["revision"],
                publication_actor="Synthetic, explicitly approved performance fixture",
                publication_confirmed=True)
            command_worker, reply = _worker_command(
                confirm_cmd, worker_timeout_seconds)
        reopened = open_project(project.root)
        after = _ledger(reopened)
        replay_error = None
        replay_no_mutation = None
        if reply is not None:
            try:
                execute_command(confirm_cmd)
            except ApplicationCommandError as exc:
                replay_error = exc.code
            replay_no_mutation = _ledger(reopened) == after
        scope_same = (
            baseline["source_rows_sha256"] == after["source_rows_sha256"] and
            baseline["membership_rows_sha256"] == after["membership_rows_sha256"])
        complete = bool(
            preview is not None and reply is not None and
            preview["batch_sizes"] == [64, 64] and
            preview["proposed_source_records"] == 128 and
            preview["unmaterialised_retrievals"] == records - baseline_linked and
            reply["committed_batches"] == 2 and
            reply["materialised_in_session"] == 128 and
            reply["unmaterialised_retrievals_remaining"] == records - baseline_linked - 128 and
            after["source_identity_links"] == baseline_linked + 128 and
            after["selected_run_identity_links"] == baseline_linked + 128 and
            after["provisional_publications"] == baseline_linked + 128 and
            after["identity_audit_events"] == baseline_linked + 128 and
            after["selected_run_pending"] == records - baseline_linked - 128 and
            after["sqlite_integrity_check"] == "ok" and
            after["foreign_key_check"] == "ok" and
            scope_same and replay_error == "publication_materialisation_stale" and
            replay_no_mutation is True and
            command_worker["returned"] is True and
            preview_worker["returned"] is True
        )
    return {
        "method": METHOD,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "synthetic_original_source_records": records,
        "initial_provisional_identities": baseline_linked,
        "final_provisional_identities": after["provisional_publications"],
        "initial_pending": baseline["selected_run_pending"],
        "final_pending": after["selected_run_pending"],
        "batch_sizes": None if preview is None else preview["batch_sizes"],
        "preview_worker": preview_worker,
        "confirm_worker": command_worker,
        "confirmed_window_commits": None if reply is None else reply["committed_batches"],
        "committed_source_records": None if reply is None else reply["materialised_in_session"],
        "original_source_and_membership_hashes_unchanged": scope_same,
        "identity_audit_events": after["identity_audit_events"],
        "sqlite_integrity_check": after["sqlite_integrity_check"],
        "foreign_key_check": after["foreign_key_check"],
        "replay_error": replay_error,
        "replay_no_mutation": replay_no_mutation,
        "complete_two_batch_probe": complete,
        "native_browser_rendering_measured": False,
        "full_100k_production_materialisation_exercised": False,
        "real_researcher_consent_exercised": False,
        "unattended_processing": False,
        "source_retrieval_verified": False,
        "deduplication_complete": False,
        "verified_complete": False,
        "global_unique_publications": None,
        "full_AT_22_acceptance": False,
        "no_network_requests": True,
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100000)
    parser.add_argument("--matched", type=int, default=64)
    parser.add_argument("--worker-timeout-seconds", type=float, default=35)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    report = run(args.records, args.matched, args.worker_timeout_seconds)
    output = json.dumps(report, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
