"""Read-only, unlicensed-text-free provisional publication provenance workbook.

This is a PREPARATORY internal renderer, not the audited export publisher and
not the specification's complete deduplicated Master Results workbook. It
reports every original run source (including unmaterialised records), and the
original source links/memberships of each provisional identity in one SQLite
read transaction. No title, abstract, accession, DOI, author or licensed
provider metadata is emitted; no queries, mutations or background operations.
"""
from __future__ import annotations

from io import BytesIO
import os
import sqlite3

from research_y import publication_identity as identity, result_counts
from research_y.export_files import MAX_ARTIFACT_BYTES
from research_y.strategy_workbook import WorkbookLimitError, _literal, ROW_LIMIT

METHOD = "original-provisional-manifest-xlsx/1"
STATUS = "INCOMPLETE — PROVISIONAL IDENTITIES, NOT UNIQUE PUBLICATIONS"


class ProvisionalManifestError(ValueError):
    """Fail safely without publishing unverified or private source data."""


def _columns(sheet, header, widths):
    from openpyxl.utils import get_column_letter
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A4"
    for i, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = width
    from openpyxl.styles import Font, PatternFill
    from openpyxl.cell import WriteOnlyCell

    def styled(values, *, heading=False):
        items = []
        for value in values:
            cell = WriteOnlyCell(sheet)
            _literal(cell, value)
            if heading:
                cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="183153")
            else:
                cell.font = Font(name="Aptos", size=10, color="203148")
            items.append(cell)
        sheet.append(items)

    styled([sheet.title], heading=True)
    styled([STATUS])
    styled(header, heading=True)
    return styled



def _discard_unsaved_worksheets(workbook) -> None:
    """Release OpenPyXL 3.1.5 write-only XML files if save never completed.

    Workbook.close() closes the workbook archive, but NOT the temporary files
    created by write-only worksheet append(). The normal ExcelWriter cleans
    these only after it has saved each worksheet. On a row-limit, invalid
    source or interrupted writer failure, close active XML generators/handles
    and remove *every* remaining worksheet file before propagating the error.
    This uses the worksheet writer's pinned-OpenPyXL cleanup contract, not
    application-managed paths, and does not touch any retained original data.
    """
    cleanup_failed = False
    for sheet in workbook.worksheets:
        writer = sheet._writer
        if writer is None:
            continue
        # The archive writer may have already cleaned some sheets if save
        # failed halfway through; never delete or reopen a completed output.
        if not os.path.exists(writer.out):
            continue
        try:
            if sheet._rows is not None:
                sheet._rows.close()
        except Exception:
            cleanup_failed = True
        try:
            writer.close()
        except Exception:
            cleanup_failed = True
        try:
            writer.cleanup()
        except (OSError, ValueError):
            cleanup_failed = True
    if cleanup_failed:
        raise ProvisionalManifestError("provisional_temporary_cleanup_failed")


def render_provisional_manifest(project, run_id: str) -> bytes:
    """Generate ALL unfiltered original-run provenance rows, or fail completely.

    Not an application command, export journal, final master list, authorised
    evidence release or independent source verification. Caller must never
    present the returned bytes as a researcher-approved published workbook.
    """
    try:
        identity._identifier(run_id)
        from openpyxl import Workbook

        with result_counts._read_connection(project) as db:
            projection = result_counts._snapshot(db, project, run_id)
            if (projection.status != "incomplete" or
                    projection.totals["global_unique_publications"] is not None):
                raise ProvisionalManifestError("provisional_status_invalid")
            # The current projection is the only source of run denominators.
            # Query/group membership rows are re-read from this same snapshot.
            workbook = Workbook(write_only=True)
            try:
                evidence = workbook.create_sheet("Evidence & Limits")
                identities = workbook.create_sheet("Provisional Identities")
                sources = workbook.create_sheet("Original Source Links")
                memberships = workbook.create_sheet("Query Memberships")
                emit_evidence = _columns(
                    evidence, ("Evidence", "Value"), (49, 92))
                emit_identity = _columns(
                    identities,
                    ("Provisional publication ID", "Selected-run sources",
                     "Additional historical sources", "Confirmed source links",
                     "Review-required source links", "Selected-run group memberships",
                     "Scientific status"),
                    (42, 24, 32, 25, 31, 34, 40))
                emit_source = _columns(
                    sources,
                    ("Internal source retrieval ID", "Source run ID", "Provider",
                     "Provisional publication ID", "Selected run",
                     "Original association status"),
                    (42, 42, 24, 42, 19, 38))
                emit_member = _columns(
                    memberships,
                    ("Internal source retrieval ID", "Source run ID", "Query ID",
                     "Group ID", "Provider", "Query state", "Run state"),
                    (42, 42, 42, 38, 24, 27, 27))

                facts = (
                    ("Report method", METHOD),
                    ("Project ID", str(project.identifier)),
                    ("Project name", project.name),
                    ("Selected run ID", run_id),
                    ("Original count revision (SHA-256)", projection.revision),
                    ("Report scope", "Whole selected run; no filters applied"),
                    ("Report status", "INCOMPLETE"),
                    ("Saved original run source records",
                     projection.totals["metadata_source_records"]),
                    ("Provisional publication identities in run",
                     projection.totals["global_publication_identities"]),
                    ("Unmaterialised original run source records",
                     projection.totals["unmaterialised_retrievals"]),
                    ("Verified unique publications", "UNKNOWN"),
                    ("Source retrieval verified", False),
                    ("Deduplication complete", False),
                    ("Publication identity verified", False),
                    ("Source metadata and abstract text",
                     "NOT EXPORTED: redistribution permissions unverified"),
                    ("Publisher", "NOT PUBLISHED: no export receipt or authorisation"),
                    ("Limit", "Not the completed Master Results workbook or AT-18"),
                )
                for row in facts:
                    emit_evidence(row)

                sheet_rows = {"identities": 0, "sources": 0, "memberships": 0}

                def add(tab, writer, fields):
                    sheet_rows[tab] += 1
                    if sheet_rows[tab] > ROW_LIMIT - 3:
                        raise WorkbookLimitError("Provisional sheet exceeds Excel row limit")
                    writer(fields)

                count_identities = 0
                included = set()
                count_source_links = 0
                count_memberships = 0
                count_selected_links = 0
                # The cursor selects exactly the SQL union of the original run,
                # not arbitrary app/page cursors or provider title matches.
                sql = (
                    "SELECT DISTINCT l.publication_id FROM publication_retrievals l "
                    "JOIN source_retrievals r ON r.retrieval_id=l.retrieval_id "
                    "WHERE r.run_id=? ORDER BY l.publication_id"
                )
                for (pub_id,) in db.execute(sql, (run_id,)):
                    snapshot = identity._snapshot(db, pub_id)
                    selected = [s for s in snapshot.retrievals if s["run_id"] == run_id]
                    if not selected:
                        raise ProvisionalManifestError("identity_not_in_original_run")
                    groups = {
                        (m["group_id"], m["source_name"])
                        for src in selected for m in src["memberships"]
                        if m["run_id"] == run_id
                    }
                    confirmed = sum(
                        s["decision"]["status"] == "confirmed_match"
                        for s in selected)
                    add("identities", emit_identity, (
                        pub_id, len(selected),
                        len(snapshot.retrievals) - len(selected),
                        confirmed, len(selected) - confirmed, len(groups),
                        "PROVISIONAL: independent source review outstanding"))
                    count_identities += 1
                    for src in snapshot.retrievals:
                        rid = src["retrieval_id"]
                        if rid in included:
                            raise ProvisionalManifestError("original_source_duplicate")
                        included.add(rid)
                        add("sources", emit_source, (
                            rid, src["run_id"], src["source_name"], pub_id,
                            src["run_id"] == run_id, src["decision"]["status"]))
                        count_source_links += 1
                        for member in src["memberships"]:
                            add("memberships", emit_member, (
                                rid, member["run_id"], member["query_id"],
                                member["group_id"], member["source_name"],
                                member["status"], member["run_status"]))
                            count_memberships += 1
                        if src["run_id"] == run_id:
                            count_selected_links += 1
                if count_identities != projection.totals["global_publication_identities"]:
                    raise ProvisionalManifestError("identity_count_mismatch")
                # Include every selected original without a provisional identity.
                # Original count projection already independently verified source
                # hashes, names, source IDs and all query memberships.
                for rid, source_run, name in db.execute(
                    "SELECT r.retrieval_id,r.run_id,r.source_name "
                    "FROM source_retrievals r "
                    "LEFT JOIN publication_retrievals l "
                    "ON l.retrieval_id=r.retrieval_id "
                    "WHERE r.run_id=? AND l.retrieval_id IS NULL "
                    "ORDER BY r.retrieval_id", (run_id,)
                ):
                    if rid in included:
                        raise ProvisionalManifestError("original_source_duplicate")
                    included.add(rid)
                    add("sources", emit_source,
                        (rid, source_run, name, None, True,
                         "UNMATERIALISED: no publication hypothesis"))
                    count_source_links += 1
                    for member in db.execute(
                        "SELECT m.run_id,m.query_id,q.group_id,q.source_name,"
                        "q.status,s.status FROM query_retrievals m "
                        "JOIN source_queries q ON q.query_id=m.query_id "
                        "AND q.run_id=m.run_id AND q.source_name=m.source_name "
                        "JOIN search_runs s ON s.run_id=q.run_id "
                        "AND s.strategy_version_id=q.strategy_version_id "
                        "WHERE m.retrieval_id=? ORDER BY m.query_id", (rid,)
                    ):
                        add("memberships", emit_member, (rid, *member))
                        count_memberships += 1
                if (count_selected_links +
                        projection.totals["unmaterialised_retrievals"] !=
                        projection.totals["metadata_source_records"]):
                    raise ProvisionalManifestError("selected_original_count_mismatch")
                if (sheet_rows != {
                        "identities": count_identities,
                        "sources": count_source_links,
                        "memberships": count_memberships}):
                    raise ProvisionalManifestError("manifest_sheet_counts_mismatch")
                output = BytesIO()
                workbook.save(output)
                result = output.getvalue()
                if len(result) > MAX_ARTIFACT_BYTES:
                    raise WorkbookLimitError("Workbook exceeds existing export byte limit")
                return result
            except BaseException:
                # A failed generation must not accumulate the OpenPyXL
                # write-only sheet XML files in a long-running process.
                # Preserve the original error unless cleanup itself fails.
                _discard_unsaved_worksheets(workbook)
                raise
            finally:
                workbook.close()
    except (ProvisionalManifestError, WorkbookLimitError):
        raise
    except (ValueError, sqlite3.DatabaseError, TypeError, KeyError, IndexError):
        raise ProvisionalManifestError("Original provisional evidence unavailable") from None
