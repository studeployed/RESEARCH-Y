"""Native Windows / local transport GUI test of original two-batch consent.

A disposable project holds 132 actual original source retrievals and original
query memberships. Test-only CLI scenarios click the REAL finite-window UI
controls; both confirmed and lost-reply-after-commit paths are independently
checked against reopened SQLite. No sources, credentials or private paths leave
the runner. This is not a product-scale 100,000-row GUI latency acceptance.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from tools.gui_feasibility.run_real_project import (
    ExperimentFailure, fixture, require, run_app,
)
from research_y import publication_identity as identity
from research_y.projects import open_project
from research_y.storage import plan_source_query

METHOD = "original-project-finite-window-gui-probe/1"
RECORDS = 132
CONFIRMED = 128


def _retrieval_id(i):
    return f"99999999-9999-4999-8999-{i+1:012x}"


def _digest(db, table):
    sha = sha256()
    for row in db.execute(f"SELECT * FROM {table} ORDER BY 1"):
        sha.update(identity._json(row).encode("utf-8") + b"\n")
    return sha.hexdigest()


def _fixture(parent):
    project, run_id = fixture(parent)
    # Original approved OR-only strategy, with both planned source queries.
    plan_source_query(project, run_id=run_id, group_id="group",
                      source_name="wos", exact_query='TS=("ECMO")')
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        queries = dict(db.execute(
            "SELECT source_name,query_id FROM source_queries WHERE run_id=?",
            (run_id,)).fetchall())
        require(set(queries) == {"pubmed", "wos"}, "window_original_queries_missing")
        sources, members = [], []
        for i in range(RECORDS):
            pubmed = i % 2 == 0
            source = "pubmed" if pubmed else "wos"
            record_id = str(25000001+i) if pubmed else f"WOS:{25000001+i}"
            record = {
                "pmid" if pubmed else "uid": record_id,
                "title": "Identical original abstract title" if i < 2
                         else f"Synthetic original source {i}",
                "identifiers": {"doi": ["10.8800/shared"] if pubmed
                                else "10.8800/shared"},
            }
            payload = ({"source": "NCBI PubMed EFetch XML", "record": record,
                        "rights_review_required_for_abstract_redistribution": True}
                       if pubmed else
                       {"provider": "wos_starter", "database": "WOS", "record": record,
                        "rights_status": "licence_review_required"})
            sources.append((_retrieval_id(i), run_id, source, record_id,
                            project.created_at_utc, identity._json(payload)))
            members.append((queries[source], _retrieval_id(i), run_id, source))
        db.executemany("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)", sources)
        db.executemany("INSERT INTO query_retrievals VALUES(?,?,?,?)", members)
    return project, run_id


def _ledger(project):
    with closing(sqlite3.connect(project.database_path)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        def count(sql):
            return db.execute(sql).fetchone()[0]
        links = db.execute(
            "SELECT l.retrieval_id,l.publication_id FROM publication_retrievals l "
            "ORDER BY l.retrieval_id").fetchall()
        return {
            "sources": count("SELECT COUNT(*) FROM source_retrievals"),
            "memberships": count("SELECT COUNT(*) FROM query_retrievals"),
            "provisional": count("SELECT COUNT(*) FROM publications"),
            "links": len(links),
            "identity_audits": count(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='publication_identity_v1'"),
            "distinct_publications": len({row[1] for row in links}),
            "linked_order_exact":
                [row[0] for row in links] == [_retrieval_id(i) for i in range(len(links))],
            "original_source_sha256": _digest(db, "source_retrievals"),
            "original_membership_sha256": _digest(db, "query_retrievals"),
            "sqlite_integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_check":
                db.execute("PRAGMA foreign_key_check").fetchone() is None,
        }


def run(mode):
    result = []
    for scenario in ("publication_window", "publication_window_lost_reply"):
        with TemporaryDirectory(prefix="researchy-native-window-case-") as tmp:
            root = Path(tmp)
            project, run_id = _fixture(root)
            before = _ledger(project)
            require(before["sources"] == RECORDS and
                    before["memberships"] == RECORDS and
                    before["links"] == 0 and
                    before["provisional"] == 0 and
                    before["identity_audits"] == 0 and
                    before["sqlite_integrity_check"] == "ok" and
                    before["foreign_key_check"] is True,
                    "window_fixture_original_evidence_invalid")
            observed = run_app(mode, scenario, project, root, run_id, "")
            after = _ledger(open_project(project.root))
            retained = (after["original_source_sha256"] ==
                        before["original_source_sha256"] and
                        after["original_membership_sha256"] ==
                        before["original_membership_sha256"])
            correct = bool(
                observed.get("passed") is True and
                observed.get("window_sources_reconciled") is True and
                after["sources"] == RECORDS and
                after["memberships"] == RECORDS and
                after["provisional"] == CONFIRMED and
                after["links"] == CONFIRMED and
                after["identity_audits"] == CONFIRMED and
                after["distinct_publications"] == CONFIRMED and
                after["linked_order_exact"] is True and
                retained and
                after["sqlite_integrity_check"] == "ok" and
                after["foreign_key_check"] is True and
                (mode != "native" or
                 observed.get("native_rendering_verified") is True))
            result.append({
                "scenario": scenario,
                "mode": mode,
                "passed": correct,
                "real_gui_actions": observed.get("observed_actions"),
                "native_rendering_verified":
                    observed.get("native_rendering_verified", False),
                "error": observed.get("error"),
                "observed_error": observed.get("observed_error"),
                "original_sources_and_memberships_unchanged": retained,
                "all_128_source_links_independently_audited":
                    after["links"] == after["identity_audits"] ==
                    after["distinct_publications"] == CONFIRMED,
                "no_automatic_duplicate_merge":
                    after["distinct_publications"] == CONFIRMED,
                "sql_integrity_verified":
                    after["sqlite_integrity_check"] == "ok" and
                    after["foreign_key_check"] is True,
                "original_sources": after["sources"],
                "remaining_without_provisional_identity":
                    after["sources"] - after["links"],
                "provisional_identities": after["provisional"],
            })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    if args.native and sys.platform != "win32":
        raise ValueError("Native graphical test requires Windows")
    mode = "native" if args.native else "transport"
    try:
        cases = run(mode)
        outcome = bool(cases and len(cases) == 2 and
                       all(x["passed"] for x in cases))
        evidence = {
            "method": METHOD,
            "tested_mode": mode,
            "original_source_count": RECORDS,
            "approved_provisional_identities_per_case": CONFIRMED,
            "cases": cases,
            "all_passed": outcome,
            "no_network_provider_requests": True,
            "real_original_sqlite": True,
            "real_application_worker": True,
            "native_desktop_installer_tested": False,
            "full_AT_22_acceptance": False,
            "source_retrieval_verified": False,
            "deduplication_complete": False,
            "verified_complete": False,
            "global_unique_publications": None,
        }
    except (ExperimentFailure, ValueError, OSError, sqlite3.DatabaseError) as exc:
        outcome = False
        evidence = {
            "method": METHOD, "tested_mode": mode, "all_passed": False,
            "error": str(exc) if isinstance(exc, ExperimentFailure)
                     else "window_gui_probe_unavailable",
            "full_AT_22_acceptance": False,
            "source_retrieval_verified": False,
            "global_unique_publications": None,
        }
    args.directory.mkdir(parents=True, exist_ok=True)
    (args.directory / "window-gui-evidence.json").write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("Finite-window GUI acceptance:", "passed" if outcome else "failed",
          "|", mode)
    return 0 if outcome else 1


if __name__ == "__main__":
    raise SystemExit(main())
