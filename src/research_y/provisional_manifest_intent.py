"""Durable, source-revision-fenced researcher consent for an INTERNAL manifest.

P1-06l3 records explicit consent to a future original-source provisional Excel
manifest. It NEVER renders, stages, uploads, exports, or publishes a workbook.
Separate reviewed increments must implement the bounded, recoverable publisher.
No provider/source text, abstract, DOI or other licensed metadata enters a
journal receipt. The original strategy/count exporter is unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re
import sqlite3
from uuid import UUID

from research_y import result_counts
from research_y.export_files import Directory, ExportFileError, filename
from research_y.publication_identity import _json
from research_y.workbook_exports import _transaction

METHOD = "provisional-manifest-consent/1"
EVENT_PREFIX = "provisional_manifest_intent_v1:"
STATE = "authorised_not_rendered"
REQUIRED = frozenset({
    "version", "method", "project_id", "export_id", "run_id",
    "output_name", "run_revision", "source_records", "provisional_identities",
    "unmaterialised_sources", "authorised_at_utc", "actor", "state",
    "whole_run", "licensed_metadata_exported", "deduplication_complete",
    "source_retrieval_verified", "verified_complete", "unique_publications",
    "receipt_sha256",
})
ERRORS = frozenset({
    "invalid_request", "confirmation_required", "stale_original_revision",
    "destination_conflict", "intent_conflict", "intent_not_found",
    "invalid_intent_receipt", "source_evidence_unavailable",
    "journal_unavailable",
})


class ManifestIntentError(ValueError):
    """Static, source-free error for internal approval preparation."""

    def __init__(self, code: str):
        self.code = code if code in ERRORS else "source_evidence_unavailable"
        super().__init__(self.code)


def _uuid(value) -> str:
    if type(value) is not str:
        raise ManifestIntentError("invalid_request")
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except ValueError:
        raise ManifestIntentError("invalid_request") from None
    return value


def _revision(value) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ManifestIntentError("invalid_request")
    return value


def _actor(value) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 160
            or value.strip() != value or not value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ManifestIntentError("invalid_request")
    return value


def _output(value) -> str:
    try:
        return filename(value, workbook=True)
    except (ValueError, TypeError):
        raise ManifestIntentError("invalid_request") from None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _counts(db, project, run_id):
    try:
        projection = result_counts._snapshot(db, project, run_id)
        if (projection.verified_complete is not False or
                projection.source_retrieval_verified is not False or
                projection.deduplication_complete is not False or
                projection.totals["global_unique_publications"] is not None or
                projection.status != "incomplete"):
            raise ManifestIntentError("source_evidence_unavailable")
        return projection
    except ManifestIntentError:
        raise
    except (sqlite3.DatabaseError, TypeError, KeyError, ValueError, RecursionError):
        raise ManifestIntentError("source_evidence_unavailable") from None


def _preview(project, run_id: str, projection) -> dict:
    return dict(
        method=METHOD, project_id=str(project.identifier), run_id=run_id,
        original_revision=projection.revision,
        selected_run_original_sources=projection.totals["metadata_source_records"],
        provisional_publication_identities=projection.totals["global_publication_identities"],
        unmaterialised_original_sources=projection.totals["unmaterialised_retrievals"],
        report_scope="whole_run", state="INCOMPLETE",
        global_unique_publications=None, verified_complete=False,
        source_retrieval_verified=False, deduplication_complete=False,
        original_source_text_exported=False,
        publication_identity_verified=False, workbook_published=False,
        requires_explicit_researcher_confirmation=True,
    )


def preview_manifest_intent(project, run_id: str) -> dict:
    """Read original count/identity evidence without creating any receipt."""
    _uuid(run_id)
    try:
        # The workbook export writer's _transaction helper is intentionally
        # migration-capable, even in its BEGIN (non-IMMEDIATE) mode. A read
        # preview MUST use the count engine's strict read-only URI connection:
        # old schema versions are refused, never silently upgraded or backed up.
        with result_counts._read_connection(project) as db:
            return _preview(project, run_id, _counts(db, project, run_id))
    except ManifestIntentError:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
        raise ManifestIntentError("source_evidence_unavailable") from None


def _event_type(export_id: str) -> str:
    return EVENT_PREFIX + export_id


def _load(db, project, export_id: str) -> dict | None:
    events = db.execute(
        "SELECT event_id,occurred_at_utc,details_json FROM audit_events "
        "WHERE event_type=? ORDER BY event_id LIMIT 2", (_event_type(export_id),)
    ).fetchall()
    if not events:
        return None
    if len(events) != 1:
        raise ManifestIntentError("invalid_intent_receipt")
    event_id, at, raw = events[0]
    try:
        from research_y.publication_identity import _object
        event = _object(raw)
        checksum = event.pop("receipt_sha256")
        canonical = _json(event)
        expected = sha256(canonical.encode("utf-8")).hexdigest()
        if (set(event) | {"receipt_sha256"} != REQUIRED or
                checksum != expected or
                raw != _json({**event, "receipt_sha256": checksum}) or
                event["version"] != 1 or type(event["version"]) is not int or
                event["method"] != METHOD or
                event["project_id"] != str(project.identifier) or
                _uuid(event["export_id"]) != export_id or
                _uuid(event["run_id"]) != event["run_id"] or
                _output(event["output_name"]) != event["output_name"] or
                _revision(event["run_revision"]) != event["run_revision"] or
                _actor(event["actor"]) != event["actor"] or
                event["authorised_at_utc"] != at or
                event["state"] != STATE or
                event["whole_run"] is not True or
                event["licensed_metadata_exported"] is not False or
                event["deduplication_complete"] is not False or
                event["source_retrieval_verified"] is not False or
                event["verified_complete"] is not False or
                event["unique_publications"] is not None or
                any(type(event[key]) is not int or event[key] < 0 for key in
                    ("source_records", "provisional_identities",
                     "unmaterialised_sources")) or
                event["provisional_identities"] > event["source_records"] or
                event["unmaterialised_sources"] > event["source_records"] or
                db.execute("SELECT 1 FROM search_runs WHERE run_id=?",
                           (event["run_id"],)).fetchone() is None):
            raise ValueError
        parsed = datetime.fromisoformat(at)
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
    except (TypeError, KeyError, ValueError, RecursionError):
        raise ManifestIntentError("invalid_intent_receipt") from None
    event["receipt_sha256"] = checksum
    return dict(event, audit_event_id=event_id)


def _view(receipt, *, current_revision_matches: bool) -> dict:
    """Never return an actor or a current authority to publish any workbook."""
    return dict(
        method=METHOD, export_id=receipt["export_id"],
        run_id=receipt["run_id"], output_name=receipt["output_name"],
        approved_original_revision=receipt["run_revision"],
        source_records=receipt["source_records"],
        provisional_identities=receipt["provisional_identities"],
        unmaterialised_originals=receipt["unmaterialised_sources"],
        audit_event_id=receipt["audit_event_id"],
        state=STATE if current_revision_matches else "stale_reapproval_required",
        current_revision_matches=current_revision_matches,
        explicit_confirmation_recorded=True, workbook_rendered=False,
        workbook_published=False, output_bytes_written=False,
        source_retrieval_verified=False, deduplication_complete=False,
        verified_complete=False, global_unique_publications=None,
    )


def prepare_manifest_intent(project, run_id: str, output_name: str, *,
                            export_id: str, expected_revision: str,
                            actor: str, confirmed: bool) -> dict:
    """Durably record ONE explicit, whole-run original revision consent.

    The operation is idempotent only for an identical export ID and request;
    changed or stale evidence never becomes a new approval by implicit replay.
    Existing published strategy/count export semantics are untouched.
    """
    _uuid(export_id)
    _uuid(run_id)
    _revision(expected_revision)
    _output(output_name)
    _actor(actor)
    if confirmed is not True:
        raise ManifestIntentError("confirmation_required")
    # Approval is not authorisation to migrate a legacy project. Refuse
    # unmigrated/stale stores via the original read-only version gate before
    # entering the journal writer. Read failures are evidence failures, not
    # false claims of a failed journal write.
    try:
        with result_counts._read_connection(project) as readonly:
            _counts(readonly, project, run_id)
    except ManifestIntentError:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
        raise ManifestIntentError("source_evidence_unavailable") from None
    try:
        with _transaction(project) as db:
            existing = _load(db, project, export_id)
            if existing is not None:
                if (existing["run_id"], existing["output_name"],
                        existing["run_revision"], existing["actor"]) != (
                        run_id, output_name, expected_revision, actor):
                    raise ManifestIntentError("intent_conflict")
                projection = _counts(db, project, run_id)
                return _view(existing,
                    current_revision_matches=projection.revision == expected_revision)

            projection = _counts(db, project, run_id)
            if projection.revision != expected_revision:
                raise ManifestIntentError("stale_original_revision")
            with Directory(project.root / "exports") as target:
                if target.exists(output_name):
                    raise ManifestIntentError("destination_conflict")
            payload = dict(
                version=1, method=METHOD, project_id=str(project.identifier),
                export_id=export_id, run_id=run_id, output_name=output_name,
                run_revision=expected_revision,
                source_records=projection.totals["metadata_source_records"],
                provisional_identities=projection.totals["global_publication_identities"],
                unmaterialised_sources=projection.totals["unmaterialised_retrievals"],
                authorised_at_utc=_now(), actor=actor, state=STATE,
                whole_run=True, licensed_metadata_exported=False,
                deduplication_complete=False, source_retrieval_verified=False,
                verified_complete=False, unique_publications=None,
            )
            checksum = sha256(_json(payload).encode("utf-8")).hexdigest()
            db.execute(
                "INSERT INTO audit_events(occurred_at_utc,event_type,details_json) "
                "VALUES(?,?,?)", (payload["authorised_at_utc"],
                                 _event_type(export_id),
                                 _json({**payload, "receipt_sha256": checksum}))
            )
            saved = _load(db, project, export_id)
            if saved is None:
                raise ManifestIntentError("journal_unavailable")
            result = _view(saved, current_revision_matches=True)
        return result
    except ManifestIntentError:
        raise
    except (sqlite3.DatabaseError, OSError, ExportFileError, ValueError, TypeError):
        raise ManifestIntentError("journal_unavailable") from None


def inspect_manifest_intent(project, export_id: str) -> dict:
    """Recheck the recorded source revision without writing or resuming a job."""
    _uuid(export_id)
    try:
        # Never use the export writer's migration-capable connection while
        # merely inspecting a retained receipt.
        with result_counts._read_connection(project) as db:
            saved = _load(db, project, export_id)
            if saved is None:
                raise ManifestIntentError("intent_not_found")
            projection = _counts(db, project, saved["run_id"])
            return _view(saved,
                current_revision_matches=projection.revision == saved["run_revision"])
    except ManifestIntentError:
        raise
    except (sqlite3.DatabaseError, OSError, ExportFileError, ValueError, TypeError):
        raise ManifestIntentError("source_evidence_unavailable") from None
