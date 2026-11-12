"""Full-size original SQLite provisional-manifest export evidence (offline only).

Exercises BOTH 100000 original source records with only 128 fixture-audited
provisional identities and the same project after fixture-only completion of
100000 independent provisional identities. Every source/group association is
checked against the original SQLite rows; none is declared a unique paper.
No real source network access, researcher consent, export publication, or GUI.
Only aggregate, source-free JSON is retained by continuous integration.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter
from zipfile import ZipFile

from openpyxl import load_workbook

from research_y import publication_identity as identity
from research_y.projects import create_project, open_project
from research_y.provisional_manifest_workbook import (
    METHOD as WORKBOOK_METHOD, render_provisional_manifest,
)
from scripts.benchmark_original_project import (
    RUN, _peak_rss_bytes, _seed, materialise_remaining_fixture,
)

METHOD = "original-provisional-manifest-100k-evidence/1"
FIXTURE_INITIAL_LINKS = 128
MAX_RECORDS = 100000
SHEET_NAMES = (
    "Evidence & Limits", "Provisional Identities",
    "Original Source Links", "Query Memberships",
)
NO_METADATA = (b"10.9300/", b"Synthetic report ",
               b"Synthetic source abstract ")


class EvidenceFailure(RuntimeError):
    """A static failure means incomplete test evidence, not safe publication."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceFailure(code)


def _original_table_hash(db, table: str) -> str:
    if table not in ("source_retrievals", "query_retrievals"):
        raise ValueError("Only original source evidence tables may be hashed")
    h = sha256()
    for row in db.execute(f"SELECT * FROM {table} ORDER BY 1"):
        h.update(identity._json(row).encode("utf-8") + b"\\n")
    return h.hexdigest()


def _db_state(project) -> dict:
    """Independently inspect actual original tables and project-file bytes."""
    with closing(sqlite3.connect(project.database_path)) as db:
        db.execute("PRAGMA query_only=ON")
        count = lambda sql: db.execute(sql).fetchone()[0]
        return dict(
            original_sources=count("SELECT COUNT(*) FROM source_retrievals"),
            original_memberships=count("SELECT COUNT(*) FROM query_retrievals"),
            provisional_publications=count("SELECT COUNT(*) FROM publications"),
            links=count("SELECT COUNT(*) FROM publication_retrievals"),
            original_identity_audits=count(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE event_type='publication_identity_v1'"),
            integrity=db.execute("PRAGMA integrity_check").fetchone()[0],
            foreign_keys=db.execute("PRAGMA foreign_key_check").fetchone() is None,
            original_source_sha256=_original_table_hash(db, "source_retrievals"),
            original_membership_sha256=_original_table_hash(db, "query_retrievals"),
            bytes_sha256=sha256(project.database_path.read_bytes()).hexdigest(),
        )


def _values_without_formulas(sheet):
    """Bounded read-only Excel iteration; never trust formulas or skip rows."""
    rows = iter(sheet)
    for _ in range(3):
        require(next(rows, None) is not None, "workbook_header_truncated")
    for row in rows:
        require(all(cell.data_type != "f" for cell in row),
                "workbook_formula_disallowed")
        yield tuple(cell.value for cell in row)


def _assert_no_provider_text(workbook_bytes: bytes) -> None:
    # Read every actual decompressed sheet XML in bounded chunks, rather than
    # looking for these tokens in compressed ZIP bytes (which proves nothing).
    with ZipFile(BytesIO(workbook_bytes)) as archive:
        sheet_files = [
            name for name in archive.namelist()
            if name.startswith("xl/worksheets/") and name.endswith(".xml")
        ]
        require(len(sheet_files) == 4, "unexpected_worksheet_archive")
        for name in sheet_files:
            with archive.open(name) as file:
                previous = b""
                while True:
                    block = file.read(1024 * 1024)
                    if not block:
                        break
                    combined = previous + block
                    require(all(token not in combined for token in NO_METADATA),
                            "provider_metadata_redistributed")
                    previous = combined[-64:]


def _verify_workbook(raw: bytes, project, run_id: str, records: int,
                     expected_pubs: int) -> dict:
    _assert_no_provider_text(raw)
    with closing(sqlite3.connect(project.database_path)) as db:
        db.execute("PRAGMA query_only=ON")
        expected_pub_ids = {
            pub for (pub,) in db.execute(
                "SELECT DISTINCT l.publication_id FROM publication_retrievals l "
                "JOIN source_retrievals r ON r.retrieval_id=l.retrieval_id "
                "WHERE r.run_id=?", (run_id,))}
        expected_links = {
            (rid, run, provider, pub or "Unknown", True,
             "review_required" if pub is not None else
             "UNMATERIALISED: no publication hypothesis")
            for rid, run, provider, pub in db.execute(
                "SELECT r.retrieval_id,r.run_id,r.source_name,l.publication_id "
                "FROM source_retrievals r LEFT JOIN publication_retrievals l "
                "ON l.retrieval_id=r.retrieval_id WHERE r.run_id=?",
                (run_id,))
        }
        expected_memberships = set(db.execute(
            "SELECT m.retrieval_id,m.run_id,m.query_id,q.group_id,"
            "q.source_name,q.status,s.status "
            "FROM query_retrievals m "
            "JOIN source_queries q ON q.query_id=m.query_id "
            "AND q.run_id=m.run_id AND q.source_name=m.source_name "
            "JOIN search_runs s ON s.run_id=q.run_id "
            "AND s.strategy_version_id=q.strategy_version_id "
            "WHERE m.run_id=?", (run_id,)
        ))
    require(len(expected_pub_ids) == expected_pubs,
            "sqlite_original_identity_count_invalid")
    require(len(expected_links) == len(expected_memberships) == records,
            "sqlite_original_scope_invalid")
    workbook = load_workbook(BytesIO(raw), read_only=True, data_only=False)
    try:
        require(tuple(workbook.sheetnames) == SHEET_NAMES,
                "workbook_sheets_invalid")
        evidence = dict(_values_without_formulas(workbook["Evidence & Limits"]))
        require(
            evidence["Report method"] == WORKBOOK_METHOD and
            evidence["Selected run ID"] == run_id and
            evidence["Report scope"] == "Whole selected run; no filters applied" and
            evidence["Report status"] == "INCOMPLETE" and
            evidence["Verified unique publications"] == "UNKNOWN" and
            evidence["Deduplication complete"] is False and
            evidence["Source retrieval verified"] is False and
            evidence["Provisional publication identities in run"] == expected_pubs and
            evidence["Saved original run source records"] == records and
            evidence["Unmaterialised original run source records"] ==
                records - expected_pubs,
            "workbook_scientific_scope_invalid")

        original_pub_rows = 0
        observed_pub_ids = set()
        for row in _values_without_formulas(workbook["Provisional Identities"]):
            original_pub_rows += 1
            require(len(row) == 7 and row[1:6] == (1, 0, 0, 1, 1) and
                    row[6] ==
                    "PROVISIONAL: independent source review outstanding",
                    "workbook_provisional_row_invalid")
            observed_pub_ids.add(row[0])
        require(original_pub_rows == expected_pubs and
                observed_pub_ids == expected_pub_ids,
                "workbook_provisional_rows_lost")

        source_rows = 0
        observed_links = set()
        for row in _values_without_formulas(workbook["Original Source Links"]):
            source_rows += 1
            require(len(row) == 6, "workbook_source_row_shape_invalid")
            observed_links.add(row)
        require(source_rows == records and observed_links == expected_links,
                "workbook_original_source_rows_lost")

        membership_rows = 0
        observed_memberships = set()
        for row in _values_without_formulas(workbook["Query Memberships"]):
            membership_rows += 1
            require(len(row) == 7, "workbook_membership_row_shape_invalid")
            observed_memberships.add(row)
        require(membership_rows == records and
                observed_memberships == expected_memberships,
                "workbook_original_query_memberships_lost")
    finally:
        workbook.close()
    return dict(
        evidence_rows=len(evidence),
        provisional_identity_rows=original_pub_rows,
        original_source_link_rows=source_rows,
        original_query_membership_rows=membership_rows,
        all_original_sql_rows_reconciled=True,
        no_provider_metadata_exported=True,
        no_excel_formulas=True,
        incomplete_scientific_status_retained=True,
    )


def run(*, records: int = MAX_RECORDS) -> dict:
    """Run bounded synthetic before/after materialisation scenarios in one project."""
    if type(records) is not int or not 512 <= records <= MAX_RECORDS:
        raise ValueError("Explicit 512..100000 synthetic records required")
    with TemporaryDirectory(prefix="researchy-original-manifest-scale-") as dirname:
        project = create_project(Path(dirname), "Synthetic provisional XLSX scale")
        started = perf_counter()
        seeded = _seed(project, records, records, 64)
        require(seeded == FIXTURE_INITIAL_LINKS,
                "original_fixture_seed_invalid")
        original = _db_state(project)
        require(original["original_sources"] == records and
                original["original_memberships"] == records and
                original["provisional_publications"] ==
                    original["links"] ==
                    original["original_identity_audits"] ==
                    FIXTURE_INITIAL_LINKS and
                original["integrity"] == "ok" and
                original["foreign_keys"] is True,
                "original_fixture_invalid")
        seed_elapsed_ms = round((perf_counter() - started) * 1000, 3)

        cases = []
        for label, expected_pubs in (("partially_materialised", seeded),
                                     ("all_independent_provisional", records)):
            if label == "all_independent_provisional":
                prepared = materialise_remaining_fixture(
                    project, batch_size=512)
                require(prepared["exhausted_sources"] is True and
                        prepared["newly_materialised"] == records - seeded,
                        "fixture_materialisation_incomplete")
                project = open_project(project.root)
            before = _db_state(project)
            require(
                    before["original_source_sha256"] ==
                        original["original_source_sha256"] and
                    before["original_membership_sha256"] ==
                        original["original_membership_sha256"] and
                    before["provisional_publications"] == expected_pubs and
                    before["links"] == before["original_identity_audits"] ==
                    expected_pubs and before["original_sources"] == records and
                    before["original_memberships"] == records and
                    before["integrity"] == "ok" and
                    before["foreign_keys"] is True,
                    "original_identity_provenance_invalid")
            t0 = perf_counter()
            raw = render_provisional_manifest(project, RUN)
            render_ms = round((perf_counter() - t0) * 1000, 3)
            size = len(raw)
            require(0 < size <= 128 * 1024 * 1024,
                    "workbook_original_size_limit_invalid")
            t1 = perf_counter()
            inspected = _verify_workbook(raw, project, RUN, records,
                                         expected_pubs)
            verification_ms = round((perf_counter() - t1) * 1000, 3)
            after = _db_state(open_project(project.root))
            require(before == after,
                    "original_sqlite_changed_during_manifest_render")
            del raw
            cases.append(dict(
                scenario=label,
                original_source_records=records,
                independently_audited_provisional_identities=expected_pubs,
                unmaterialised_originals=records - expected_pubs,
                render_elapsed_ms=render_ms,
                separate_workbook_verification_ms=verification_ms,
                workbook_bytes=size,
                source_and_membership_sqlite_unchanged=True,
                original_source_and_membership_hashes_revalidated=True,
                sqlite_integrity_verified=True,
                foreign_keys_verified=True,
                **inspected,
            ))
        return dict(
            method=METHOD, records=records, initial_provisional_identities=seeded,
            scenario_count=len(cases), cases=cases,
            source_original_seeding_ms=seed_elapsed_ms,
            measured_parent_peak_rss_bytes=_peak_rss_bytes(),
            passed=all(x["all_original_sql_rows_reconciled"] for x in cases),
            source_retrieval_verified=False, deduplication_complete=False,
            verified_complete=False, global_unique_publications=None,
            final_master_results_export_implemented=False,
            user_published_export_or_recovery_tested=False,
            native_gui_interaction_tested=False, full_AT_18_acceptance=False,
            full_AT_22_acceptance=False, no_provider_network_requests=True,
            original_synthetic_fixture_only=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=MAX_RECORDS)
    parser.add_argument("--json-output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(records=args.records)
    except Exception:
        # A failed benchmark is not a partial passing result; never print
        # original source content, private paths, or the raw exception body.
        result = dict(method=METHOD, passed=False,
                      error="original_manifest_scale_unverified",
                      records=args.records, global_unique_publications=None,
                      source_retrieval_verified=False,
                      deduplication_complete=False,
                      full_AT_18_acceptance=False, full_AT_22_acceptance=False)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print("Original provisional workbook evidence:",
          "passed" if result["passed"] else "failed")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
