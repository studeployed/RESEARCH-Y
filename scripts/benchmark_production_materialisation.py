"""Stress the *production* explicitly confirmed, 64-source materialisation path.

Unlike benchmark_original_project.py --materialise-all, this does NOT use its
fixture-only bulk identity writer. It creates 100,000 original synthetic sources,
then exercises the existing trusted ApplicationCommand preview and confirmation
services, including genuinely spawned ApplicationWorker children, a strict
35-second per-operation host budget, restart, stale-token rejection and SQLite
data/audit reconciliation. Only TWO independently confirmed batches are tested.
No live provider calls, user interaction or full 100k-run completion is implied.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import platform
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter, sleep

from research_y.application_commands import (
    ApplicationCommand, ApplicationCommandError, execute_command,
)
from research_y.application_worker import ApplicationWorker
from research_y import publication_identity as identity
from research_y.projects import create_project, open_project
from scripts.benchmark_original_project import RUN, _rid, _seed

METHOD = "production-confirmed-original-materialisation-probe/1"
ACTOR = "Explicitly confirmed synthetic performance fixture"
BATCH_SIZE = 64
STAGES = 2


def _digest_rows(db, sql: str) -> str:
    value = sha256()
    for row in db.execute(sql):
        value.update(identity._json(row).encode("utf-8"))
        value.update(b"\n")
    return value.hexdigest()


def _ledger(project) -> dict:
    """Independent SQLite evidence, never deduced from command replies."""
    with closing(sqlite3.connect(project.database_path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        def count(sql, *params):
            return db.execute(sql, params).fetchone()[0]
        source_hash = _digest_rows(
            db, "SELECT retrieval_id,run_id,source_name,source_record_id,"
                "retrieved_at_utc,original_metadata_json FROM source_retrievals "
                "ORDER BY retrieval_id")
        membership_hash = _digest_rows(
            db, "SELECT query_id,retrieval_id,run_id,source_name "
                "FROM query_retrievals ORDER BY query_id,retrieval_id")
        evidence = {
            "source_records": count("SELECT COUNT(*) FROM source_retrievals"),
            "selected_run_records": count(
                "SELECT COUNT(*) FROM source_retrievals WHERE run_id=?", RUN),
            "membership_rows": count("SELECT COUNT(*) FROM query_retrievals"),
            "provisional_publications": count("SELECT COUNT(*) FROM publications"),
            "source_identity_links": count("SELECT COUNT(*) FROM publication_retrievals"),
            "selected_run_identity_links": count(
                "SELECT COUNT(*) FROM publication_retrievals l "
                "JOIN source_retrievals r ON r.retrieval_id=l.retrieval_id "
                "WHERE r.run_id=?", RUN),
            "identity_audit_events": count(
                "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                identity.IDENTITY_EVENT),
            "selected_run_pending": count(
                "SELECT COUNT(*) FROM source_retrievals r "
                "LEFT JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
                "WHERE r.run_id=? AND l.retrieval_id IS NULL", RUN),
            "source_rows_sha256": source_hash,
            "membership_rows_sha256": membership_hash,
            "sqlite_integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_check": "ok" if db.execute("PRAGMA foreign_key_check").fetchone() is None
                                 else "failed",
        }
        return evidence


def _linked_ids(project, start: int, end: int) -> bool:
    with closing(sqlite3.connect(project.database_path)) as db:
        rows = list(db.execute(
            "SELECT r.retrieval_id,l.publication_id FROM source_retrievals r "
            "JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
            "WHERE r.retrieval_id>=? AND r.retrieval_id<? ORDER BY r.retrieval_id",
            (_rid(start), _rid(end)),
        ))
    # Exactly the intended source IDs, each independently associated.
    return (len(rows) == end - start and
            [row[0] for row in rows] == [_rid(i) for i in range(start, end)] and
            len({row[1] for row in rows}) == len(rows))


def _worker_command(command, timeout_seconds: float) -> tuple[dict, dict | None]:
    """Run an actual trusted operation in a spawned supervised child."""
    start = perf_counter()
    polls = 0
    with ApplicationWorker() as worker:
        operation_id = worker.submit(command)
        while perf_counter() - start < timeout_seconds:
            status = worker.poll(operation_id)
            polls += 1
            if status.state != "running":
                elapsed = (perf_counter() - start) * 1000
                result = status.result() if status.state == "returned" else None
                return ({
                    "state": status.state, "error": status.error,
                    "elapsed_ms": round(elapsed, 3), "poll_count": polls,
                    "returned": status.state == "returned",
                }, result)
            sleep(.015)
    return ({
        "state": "timeout", "error": "worker_timeout",
        "elapsed_ms": round((perf_counter() - start) * 1000, 3),
        "poll_count": polls, "returned": False,
    }, None)


def _base(records: int, matched: int, timeout_seconds: float) -> None:
    if (type(records) is not int or not 512 <= records <= 100_000
            or records % 2 or type(matched) is not int
            or not 1 <= matched <= min(64, records // 4)
            or type(timeout_seconds) not in (int, float)
            or not 1 <= timeout_seconds <= 120):
        raise ValueError("A bounded synthetic same-run fixture is required")


def run(records=100_000, matched=64, worker_timeout_seconds=35) -> dict:
    _base(records, matched, worker_timeout_seconds)
    started = perf_counter()
    report = {
        "method": METHOD, "platform": platform.platform(),
        "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        "synthetic_original_source_records": records,
        "initial_candidate_pairs": matched,
        "batch_size": BATCH_SIZE, "planned_confirmations": STAGES,
        "actual_production_confirmations": 0,
        "fixture_only_bulk_materialiser_used": False,
        "no_real_researcher_consent_claimed": True,
        "native_browser_rendering_measured": False,
        "source_retrieval_verified": False,
        "deduplication_complete": False,
        "verified_complete": False,
        "global_unique_publications": None,
        "full_AT_22_acceptance": False,
        "no_network_requests": True,
        "stages": [],
    }
    with TemporaryDirectory(prefix="researchy-production-100k-") as parent:
        project = create_project(Path(parent), "Synthetic consented 100k source project")
        initial_materialised = _seed(project, records, records, matched)
        assert initial_materialised == 2 * matched
        report["initial_original_provisional_identities"] = initial_materialised
        initial = _ledger(project)
        report["initial_evidence"] = initial
        if (initial["source_records"] != records
                or initial["selected_run_records"] != records
                or initial["membership_rows"] != records
                or initial["source_identity_links"] != initial_materialised
                or initial["identity_audit_events"] != initial_materialised
                or initial["selected_run_pending"] != records - initial_materialised
                or initial["sqlite_integrity_check"] != "ok"
                or initial["foreign_key_check"] != "ok"):
            raise AssertionError("Source/identity baseline failed original data gates")

        for stage_index in range(1, STAGES + 1):
            project = open_project(project.root)
            preview_command = ApplicationCommand.for_project(
                project, "publication_materialisation_preview", run_id=RUN)
            preview_worker, preview = _worker_command(preview_command, worker_timeout_seconds)
            step = {"batch_number": stage_index, "preview_worker": preview_worker}
            report["stages"].append(step)
            if preview is None:
                report["failure"] = "preview_worker_not_returned"
                break
            remaining_before = records - initial_materialised - (stage_index - 1) * BATCH_SIZE
            if (preview["source_records_retained"] != records
                    or preview["unmaterialised_retrievals"] != remaining_before
                    or preview["batch_count"] != BATCH_SIZE
                    or preview["batch_size"] != BATCH_SIZE
                    or preview["existing_publication_hypotheses"] != records - remaining_before
                    or preview["global_unique_publications"] is not None
                    or preview["deduplication_complete"] is not False
                    or preview["verified_complete"] is not False):
                raise AssertionError("Production preview did not match original scope")
            step["preview_pending"] = preview["unmaterialised_retrievals"]
            confirm_command = ApplicationCommand.for_project(
                project, "publication_materialisation_confirm", run_id=RUN,
                publication_view_revision=preview["revision"],
                publication_actor=ACTOR, publication_confirmed=True)
            confirm_worker, committed = _worker_command(confirm_command, worker_timeout_seconds)
            step["confirm_worker"] = confirm_worker
            if committed is None:
                report["failure"] = "confirm_worker_not_returned"
                break
            if (committed["materialised_in_batch"] != BATCH_SIZE
                    or committed["unmaterialised_retrievals_remaining"]
                        != remaining_before - BATCH_SIZE
                    or committed["requires_new_preview_for_next_batch"] is not True
                    or committed["global_unique_publications"] is not None
                    or committed["deduplication_complete"] is not False
                    or committed["verified_complete"] is not False):
                raise AssertionError("Production confirmation did not return 64 independent links")
            report["actual_production_confirmations"] += 1
            project = open_project(project.root)
            step["reopened_after_commit"] = True
            # Simulate a lost successful reply: the exact same confirmed
            # request MUST refuse to reapply the stale batch on reopened data.
            stale_before = _ledger(project)
            try:
                execute_command(confirm_command)
            except ApplicationCommandError as exc:
                step["replay_error"] = exc.code
                if exc.code != "publication_materialisation_stale":
                    raise AssertionError("Unexpected replay rejection reason") from exc
            else:
                raise AssertionError("Previously consumed approval was replayed")
            fresh = _ledger(project)
            step["reopened_evidence"] = fresh
            step["stale_replay_no_mutation"] = fresh == stale_before
            expected_links = initial_materialised + stage_index * BATCH_SIZE
            if (fresh["source_rows_sha256"] != initial["source_rows_sha256"]
                    or fresh["membership_rows_sha256"] != initial["membership_rows_sha256"]
                    or fresh["source_identity_links"] != expected_links
                    or fresh["selected_run_identity_links"] != expected_links
                    or fresh["provisional_publications"] != expected_links
                    or fresh["identity_audit_events"] != expected_links
                    or fresh["selected_run_pending"] != records - expected_links
                    or fresh["sqlite_integrity_check"] != "ok"
                    or fresh["foreign_key_check"] != "ok"
                    or not step["stale_replay_no_mutation"]
                    or not _linked_ids(project, 0, expected_links)):
                raise AssertionError("Original identity/membership/rollback evidence changed")
        report["completed_two_batches"] = report["actual_production_confirmations"] == STAGES
        report["final_evidence"] = _ledger(open_project(project.root))
    report["total_elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100_000)
    parser.add_argument("--matched", type=int, default=64)
    parser.add_argument("--worker-timeout-seconds", type=float, default=35)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    report = run(args.records, args.matched, args.worker_timeout_seconds)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
