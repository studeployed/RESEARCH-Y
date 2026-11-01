"""Frozen strategy/count report inputs, captured on one existing read transaction.

No provider calls, original record text, mutable report dictionary, source-status
promotion, filesystem publication or schema changes. This freezes a current
projection; it does not recreate an earlier historical identity state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from research_y.projects import Project

REPORT_METHOD = "strategy-count-report/1"
# A report-input safety bound, NOT a source retrieval or result limit.
MAX_REPORT_BYTES = 64 * 1024 * 1024
_SAFE_PARAMETERS = frozenset(("database", "page_size", "max_query_bytes", "sort",
                              "sort_field", "retmax", "retstart"))


class ReportIntegrityError(ValueError):
    """Cannot safely capture a coherent report; research data is unchanged."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def digest(value: str | bytes) -> str:
    return sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReportIntegrityError("Duplicate report object key")
        result[key] = value
    return result


def decode(raw: str) -> dict:
    try:
        result = json.loads(raw, object_pairs_hook=_pairs)
        if not isinstance(result, dict):
            raise ValueError
        canonical(result)
        return result
    except (ValueError, TypeError, RecursionError):
        raise ReportIntegrityError("Invalid report object") from None


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ReportIntegrityError("Canonical report identity required")


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ReportIntegrityError("Report timestamp must be Coordinated Universal Time") from None


def _strategy(snapshot, rows):
    """Accept the approved storage contract, not an arbitrary legacy dictionary."""
    if (set(snapshot) != {"format_version", "theme", "logic", "approved_by", "groups"}
            or type(snapshot.get("format_version")) is not int or snapshot["format_version"] != 1
            or snapshot.get("logic") != "OR" or not isinstance(snapshot.get("theme"), str)
            or not isinstance(snapshot.get("approved_by"), str)
            or not isinstance(snapshot.get("groups"), list) or not snapshot["groups"]):
        raise ReportIntegrityError("Unsupported approved strategy snapshot")
    expected = []
    for order, group in enumerate(snapshot["groups"]):
        if (not isinstance(group, dict) or set(group) != {"group_id", "label", "group_order", "terms"}
                or group.get("group_order") != order
                or type(group.get("group_order")) is not int
                or not isinstance(group.get("group_id"), str) or not group["group_id"]
                or not isinstance(group.get("label"), str)
                or not isinstance(group.get("terms"), list)):
            raise ReportIntegrityError("Malformed approved strategy group")
        expected.append((group["group_id"], group["label"], order))
        seen = set()
        for term in group["terms"]:
            if (not isinstance(term, dict) or set(term) != {"text", "origin", "rationale", "enabled", "approved"}
                    or term.get("approved") is not True
                    or not isinstance(term.get("text"), str) or not term["text"].strip()
                    or term.get("origin") not in ("researcher", "deterministic", "ai")
                    or type(term.get("enabled")) is not bool
                    or not isinstance(term.get("rationale"), str)
                    or term["text"] in seen):
                raise ReportIntegrityError("Unapproved or malformed strategy term")
            seen.add(term["text"])
    if expected != [tuple(row) for row in rows] or len({r[0] for r in expected}) != len(expected):
        raise ReportIntegrityError("Approved strategy and group index disagree")


@dataclass(frozen=True, slots=True)
class StrategyReport:
    """Immutable canonical bytes; as_dict returns a fresh independent object."""
    payload_json: str

    def __post_init__(self):
        if not isinstance(self.payload_json, str):
            raise ReportIntegrityError("Report input must be canonical text")
        if len(self.payload_json.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ReportIntegrityError("Report exceeds the explicit input safety limit")
        data = decode(self.payload_json)
        if (canonical(data) != self.payload_json or data.get("method") != REPORT_METHOD
                or data.get("format_version") != 1 or type(data.get("format_version")) is not int
                or data.get("scope") != "whole_run_strategy_and_counts"
                or data.get("status") != "incomplete"):
            raise ReportIntegrityError("Unsupported or noncanonical report input")
        try:
            _uuid(data["project"]["project_id"])
            _uuid(data["run"]["run_id"])
            _uuid(data["run"]["strategy_version_id"])
            _stamp(data["captured_at_utc"])
            counts = data["counts"]
            if (counts["project_id"] != data["project"]["project_id"]
                    or counts["run_id"] != data["run"]["run_id"]
                    or counts["strategy_version_id"] != data["run"]["strategy_version_id"]
                    or counts["stored_run_status"] != data["run"]["status"]
                    or counts["status"] != "incomplete"
                    or any(counts[k] is not False for k in ("verified_complete", "deduplication_complete",
                            "source_retrieval_verified", "candidate_discovery_complete", "historical_snapshot",
                            "full_checkpoint_validation_performed", "export_permissions_verified"))
                    or not re.fullmatch(r"[0-9a-f]{64}", counts["revision"])
                    or not isinstance(data["queries"], list)
                    or not isinstance(data["partitions"], list)
                    or not isinstance(data["warnings"], list)):
                raise ValueError
            _strategy(data["strategy"]["snapshot"], data["strategy"]["group_index"])
        except (KeyError, TypeError, ValueError):
            raise ReportIntegrityError("Report identities, strategy or acceptance boundaries disagree") from None

    @property
    def sha256(self) -> str:
        return digest(self.payload_json)

    def as_dict(self) -> dict[str, Any]:
        return decode(self.payload_json)


def _capture(db, project, run_id, captured_at):
    # This deliberately reuses the count implementation on the SAME handle.
    # Calling read_run_counts then opening another handle would mix snapshots.
    from research_y import result_counts
    counts = result_counts._snapshot(db, project, run_id).as_dict()
    run = db.execute("SELECT run_id,strategy_version_id,created_at_utc,status,completed_at_utc "
                     "FROM search_runs WHERE run_id=?", (run_id,)).fetchone()
    if run is None:
        raise ReportIntegrityError("Unknown report run")
    version = db.execute("SELECT version_number,approved_at_utc,snapshot_json FROM strategy_versions "
                         "WHERE strategy_version_id=?", (run[1],)).fetchone()
    if version is None:
        raise ReportIntegrityError("Missing approved strategy")
    snapshot = decode(version[2])
    index = db.execute("SELECT group_id,label,group_order FROM strategy_groups WHERE strategy_version_id=? "
                       "ORDER BY group_order,group_id", (run[1],)).fetchall()
    _strategy(snapshot, index)
    queries, partitions = [], []
    columns = ("query_id", "group_id", "source_name", "exact_query", "parameters_json",
               "reported_matches", "status", "executed_at_utc")
    query_count_ids = {q["query_id"] for q in counts["queries"]}
    for row in db.execute("SELECT query_id,group_id,source_name,exact_query,parameters_json,"
                          "reported_matches,status,executed_at_utc FROM source_queries "
                          "WHERE run_id=? ORDER BY query_id", (run_id,)):
        q = dict(zip(columns, row))
        params = decode(q.pop("parameters_json"))
        # Never silently export provider credentials hidden in arbitrary parameters.
        # Refuse unreviewed keys rather than redact part of an allegedly exact report.
        if set(params) - _SAFE_PARAMETERS or any(not isinstance(v, (str, int, bool, type(None))) for v in params.values()):
            raise ReportIntegrityError("Query parameters require export-policy review")
        q["parameters"] = params
        q["timestamp_scope"] = "stored_query_timestamp_not_independent_request_verification"
        q["execution_evidence"] = "timestamp_not_recorded" if q["executed_at_utc"] is None else "timestamp_recorded"
        if q["query_id"] not in query_count_ids:
            raise ReportIntegrityError("Queries and counts differ within report snapshot")
        queries.append(q)
        plan_row = db.execute("SELECT plan_json FROM pubmed_checkpoint_runs WHERE query_id=?",
                              (q["query_id"],)).fetchone()
        if plan_row is not None:
            plan = decode(plan_row[0])
            for node in plan.get("partitions", []):
                # Exact stored partition expression and rationale, not a newly compiled query.
                partitions.append({"query_id": q["query_id"], "source_name": q["source_name"],
                    "group_id": q["group_id"], "evidence_scope": "stored_count_plan_not_final_source_acceptance",
                    **{key: node[key] for key in ("index", "parent_index", "start", "end", "exact_subquery",
                                                 "reported_matches", "decision", "depth", "rationale")}})
    if {q["query_id"] for q in queries} != query_count_ids:
        raise ReportIntegrityError("Report omitted a query")
    from research_y import __version__
    data = dict(format_version=1, method=REPORT_METHOD, software_version=__version__,
                captured_at_utc=captured_at, scope="whole_run_strategy_and_counts", status="incomplete",
                project={"project_id": str(project.identifier), "name": project.name},
                run=dict(zip(("run_id", "strategy_version_id", "created_at_utc", "status", "completed_at_utc"), run)),
                strategy={"version_number": version[0], "approved_at_utc": version[1],
                          "snapshot": snapshot, "group_index": [list(r) for r in index]},
                counts=counts, queries=queries, partitions=partitions,
                warnings=sorted(set(counts["warnings"]) | {"not_a_historical_run_reconstruction",
                    "licensed_record_text_not_exported", "methodology_review_not_established",
                    "source_query_translation_details_not_in_this_workbook"}))
    return StrategyReport(canonical(data))


def capture_strategy_report(project: Project, run_id: str, *, scope: str = "whole_run") -> StrategyReport:
    """Freeze current full-run strategy/count evidence, never a filtered subset."""
    if scope != "whole_run":
        raise ValueError("Filtered export is not implemented; no filter has been applied")
    _uuid(run_id)
    from research_y import result_counts
    captured_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    try:
        with result_counts._read_connection(project) as db:
            return _capture(db, project, run_id, captured_at)
    except (sqlite3.DatabaseError, KeyError, TypeError, ValueError, RecursionError):
        raise ReportIntegrityError("Report could not be captured consistently; no export was published") from None
