"""Audited project-local publication of an explicitly approved provisional XLSX.

An independently confirmed source-revision intent (PR #97) and fully verified
private source-only stage (PR #98) must exist before a destination is touched.
Durable publishing intent PRECEDES any destination-side file creation; final
publication success requires an append-only published receipt AND reverified
file identity, length and SHA-256. This is internal backend functionality only:
not a graphical control, complete Master Results export or provider acceptance.
"""
from __future__ import annotations

from datetime import datetime
import re
import sqlite3
from uuid import uuid4

from research_y import result_counts
from research_y import provisional_manifest_intent as consent
from research_y import provisional_manifest_stage as stage
from research_y.export_files import Directory, ExportFileError
from research_y.publication_identity import _json, _object
from research_y.workbook_exports import _transaction

METHOD = "provisional-manifest-publication/1"
EVENT_PREFIX = "provisional_manifest_publish_v1:"
ERRORS = frozenset((
    "publication_invalid", "publication_not_staged",
    "publication_not_started", "publication_receipt_invalid",
    "publication_staging_changed", "publication_revision_stale",
    "publication_destination_conflict", "publication_artifact_changed",
    "publication_storage_failed", "publication_journal_failed",
))
_FIELDS = frozenset((
    "version", "method", "export_id", "run_revision",
    "consent_event_id", "consent_sha256", "stage_event_id", "stage_sha256",
    "artifact_sha256", "artifact_size", "copy_name", "at_utc",
    "action", "previous_event_id", "previous_sha256", "receipt_sha256",
))


class ManifestPublicationError(ValueError):
    """Never expose original metadata or local paths through errors."""

    def __init__(self, code: str):
        self.code = code if code in ERRORS else "publication_invalid"
        super().__init__(self.code)


SAVE_ERRORS = (ManifestPublicationError, stage.ManifestStageError, consent.ManifestIntentError)


def _type(export_id):
    return EVENT_PREFIX + export_id


def _copy_name(name, export_id):
    if (type(name) is not str or re.fullmatch(
            r"\.researchy-manifest-" + re.escape(export_id) +
            r"-[0-9a-f]{32}\.part", name) is None):
        raise ManifestPublicationError("publication_receipt_invalid")
    return name


def _load(db, approved, staged):
    """Decode at most two fully checked, independent publication receipts."""
    export_id = approved["export_id"]
    current = None
    prior_id = prior_sha = None
    rows = db.execute(
        "SELECT event_id,occurred_at_utc,details_json FROM audit_events "
        "WHERE event_type=? ORDER BY event_id LIMIT 3",
        (_type(export_id),),
    )
    for event_id, timestamp, raw in rows:
        try:
            body = _object(raw)
            checksum = body.pop("receipt_sha256")
            if (set(body) | {"receipt_sha256"} != _FIELDS or
                    type(body["version"]) is not int or body["version"] != 1 or
                    body["method"] != METHOD or
                    body["export_id"] != export_id or
                    body["run_revision"] != approved["run_revision"] or
                    body["consent_event_id"] != approved["audit_event_id"] or
                    body["consent_sha256"] != approved["receipt_sha256"] or
                    body["stage_event_id"] != staged["event_id"] or
                    body["stage_sha256"] != staged["event_sha256"] or
                    body["artifact_sha256"] != staged["artifact"]["sha256"] or
                    body["artifact_size"] != staged["artifact"]["size"] or
                    body["at_utc"] != timestamp or
                    body["previous_event_id"] != prior_id or
                    body["previous_sha256"] != prior_sha or
                    type(checksum) is not str or
                    checksum != stage._sha(_json(body).encode("utf-8")) or
                    raw != _json({**body, "receipt_sha256": checksum}) or
                    body["action"] not in ("publishing", "published")):
                raise ValueError
            when = datetime.fromisoformat(timestamp)
            if (when.utcoffset() is None or
                    when.utcoffset().total_seconds() != 0):
                raise ValueError
            _copy_name(body["copy_name"], export_id)
            if body["action"] == "publishing":
                if current is not None:
                    raise ValueError
                current = dict(phase="publishing", copy_name=body["copy_name"])
            else:
                if (current is None or current["phase"] != "publishing"
                        or body["copy_name"] != current["copy_name"]):
                    raise ValueError
                current["phase"] = "published"
            current.update(event_id=event_id, event_sha256=checksum)
            prior_id, prior_sha = event_id, checksum
        except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
            raise ManifestPublicationError("publication_receipt_invalid") from None
    return current


def _append(db, approved, staged, earlier, action, copy_name):
    if action not in ("publishing", "published"):
        raise ManifestPublicationError("publication_invalid")
    _copy_name(copy_name, approved["export_id"])
    body = dict(
        version=1, method=METHOD, export_id=approved["export_id"],
        run_revision=approved["run_revision"],
        consent_event_id=approved["audit_event_id"],
        consent_sha256=approved["receipt_sha256"],
        stage_event_id=staged["event_id"],
        stage_sha256=staged["event_sha256"],
        artifact_sha256=staged["artifact"]["sha256"],
        artifact_size=staged["artifact"]["size"],
        copy_name=copy_name, at_utc=consent._now(), action=action,
        previous_event_id=earlier["event_id"] if earlier else None,
        previous_sha256=earlier["event_sha256"] if earlier else None,
    )
    body["receipt_sha256"] = stage._sha(_json(body).encode("utf-8"))
    db.execute(
        "INSERT INTO audit_events(occurred_at_utc,event_type,details_json) "
        "VALUES(?,?,?)",
        (body["at_utc"], _type(approved["export_id"]), _json(body)),
    )


def _validated(db, project, export_id, *, writing, allow_unstaged=False):
    try:
        approved = stage._intent(db, project, export_id)
        staged = stage._load(db, project, approved)
        stage_ready = staged is not None and staged["phase"] == "staged"
        if not stage_ready and not allow_unstaged:
            raise ManifestPublicationError("publication_not_staged")
        projection = consent._counts(db, project, approved["run_id"])
        current = projection.revision == approved["run_revision"]
        if not stage_ready:
            if db.execute("SELECT 1 FROM audit_events WHERE event_type=? LIMIT 1",
                          (_type(export_id),)).fetchone():
                raise ManifestPublicationError("publication_receipt_invalid")
            return approved, staged, None, current
        if writing:
            if not current:
                raise ManifestPublicationError("publication_revision_stale")
            # Check EXACT source counts even after the canonical revision.
            stage._evidence(db, project, approved)
        if stage._file_state(project, staged) != "verified":
            raise ManifestPublicationError("publication_staging_changed")
        published = _load(db, approved, staged)
        return approved, staged, published, current
    except ManifestPublicationError:
        raise
    except stage.ManifestStageError as exc:
        raise ManifestPublicationError(
            "publication_staging_changed" if exc.code != "intent_not_found"
            else "publication_invalid") from None
    except consent.ManifestIntentError:
        raise ManifestPublicationError("publication_invalid") from None


def _files(project, approved, staged, publication):
    """Revalidate destination-side content and file identity without writing.

    A final filename that exists without the *same physical temporary copy*
    can never be silently adopted, EVEN if its bytes equal an approved stage.
    A corrupted copy is an error; an absent copy before writing is recoverable.
    """
    if publication is None:
        with Directory(project.root / "exports") as dest:
            if dest.exists(approved["output_name"]):
                raise ManifestPublicationError("publication_destination_conflict")
        return "not_created"
    copy = publication["copy_name"]
    artifact = staged["artifact"]
    try:
        with Directory(project.root / "exports") as dest:
            has_copy = dest.exists(copy)
            has_final = dest.exists(approved["output_name"])
            if has_final:
                if not has_copy or not dest.same_file(copy, approved["output_name"]):
                    raise ManifestPublicationError("publication_destination_conflict")
                dest.read(copy, digest=artifact["sha256"], size=artifact["size"])
                dest.read(approved["output_name"], digest=artifact["sha256"],
                          size=artifact["size"])
                return "verified_final"
            if has_copy:
                dest.read(copy, digest=artifact["sha256"], size=artifact["size"])
                return "verified_copy_only"
            if publication["phase"] == "published":
                raise ManifestPublicationError("publication_artifact_changed")
            return "missing_copy"
    except ManifestPublicationError:
        raise
    except (OSError, ValueError, ExportFileError):
        raise ManifestPublicationError("publication_artifact_changed") from None


def _view(approved, staged, publication, current, file_status):
    recorded = publication is not None and publication["phase"] == "published"
    verified = recorded and file_status == "verified_final"
    state = "not_published"
    if publication is not None:
        if recorded:
            state = "published_verified" if current else "published_previous_revision"
        elif file_status == "verified_final":
            state = "awaiting_publication_receipt"
        elif file_status == "verified_copy_only":
            state = "publishing_copy_ready"
        else:
            state = "publishing_interrupted"
    if not current and not recorded:
        state = "stale_reapproval_required"
    return dict(
        method=METHOD, export_id=approved["export_id"],
        run_id=approved["run_id"], output_name=approved["output_name"],
        state=state, approved_original_revision=approved["run_revision"],
        current_original_revision_matches=current,
        stage_receipt_id=staged["event_id"],
        publication_receipt_id=publication["event_id"] if publication else None,
        original_source_only_export=True,
        original_source_text_exported=False,
        workbook_published=bool(verified),
        audited_publication_success=bool(verified and current),
        historical_artifact_verified=bool(verified),
        source_retrieval_verified=False,
        deduplication_complete=False, verified_complete=False,
        global_unique_publications=None,
        no_provider_network_requests=True,
    )


def inspect_manifest_publication(project, export_id: str) -> dict:
    """Read-only, no-migration inspection; a visible file is not a receipt."""
    return _inspect(project, export_id, allow_unstaged=False)


def _inspect(project, export_id, *, allow_unstaged):
    consent._uuid(export_id)
    try:
        with result_counts._read_connection(project) as db:
            approved, staged, publication, current = _validated(
                db, project, export_id, writing=False, allow_unstaged=allow_unstaged)
            if staged is None or staged["phase"] != "staged":
                return stage._view(approved, staged, stage._file_state(project, staged),
                                   original_current=current)
            file_status = _files(project, approved, staged, publication)
            if publication is not None and publication["phase"] == "published":
                if file_status != "verified_final":
                    raise ManifestPublicationError("publication_artifact_changed")
            return _view(approved, staged, publication, current, file_status)
    except ManifestPublicationError:
        raise
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
        raise ManifestPublicationError("publication_invalid") from None


def _begin(project, export_id):
    """Commit publishing intent before creating any destination-side bytes."""
    try:
        with _transaction(project) as db:
            approved, staged, state, _ = _validated(
                db, project, export_id, writing=True)
            if state is None:
                with Directory(project.root / "exports") as dest:
                    if dest.exists(approved["output_name"]):
                        raise ManifestPublicationError("publication_destination_conflict")
                _append(
                    db, approved, staged, None, "publishing",
                    f".researchy-manifest-{export_id}-{uuid4().hex}.part")
            resulting = _load(db, approved, staged)
            if resulting is None:
                raise ManifestPublicationError("publication_journal_failed")
            return resulting["phase"]
    except ManifestPublicationError:
        raise
    except (sqlite3.DatabaseError, OSError, ExportFileError, ValueError, TypeError):
        raise ManifestPublicationError("publication_journal_failed") from None


def _finish(project, export_id):
    """One guarded write transaction with physical publication and receipt.

    The successful, same-inode final hardlink is created only after the
    independently checked destination-side copy. A process termination after
    the link but before receipt is repaired by exact inode/checksum evidence,
    never by adopting a convenient, unrelated (even byte-identical) file.
    """
    try:
        with _transaction(project) as db:
            approved, staged, publication, _ = _validated(
                db, project, export_id, writing=True)
            if publication is None:
                raise ManifestPublicationError("publication_not_started")
            if publication["phase"] == "published":
                if _files(project, approved, staged, publication) != "verified_final":
                    raise ManifestPublicationError("publication_artifact_changed")
                return
            artifact = staged["artifact"]
            status = _files(project, approved, staged, publication)
            with stage._store(project) as source:
                retained = source.read(
                    artifact["name"], digest=artifact["sha256"],
                    size=artifact["size"])
            with Directory(project.root / "exports") as dest:
                if status == "verified_final":
                    # Crash after hardlink: the exact recorded copy and final
                    # name are already verified same-inode. No second link.
                    dest.flush(publication["copy_name"])
                else:
                    if status == "missing_copy":
                        dest.write_new(publication["copy_name"], retained)
                    elif status != "verified_copy_only":
                        raise ManifestPublicationError("publication_artifact_changed")
                    dest.read(publication["copy_name"], digest=artifact["sha256"],
                              size=artifact["size"])
                    dest.flush(publication["copy_name"])
                    dest.publish_link(publication["copy_name"],
                                      approved["output_name"])
                dest.read(approved["output_name"], digest=artifact["sha256"],
                          size=artifact["size"])
                if not dest.same_file(publication["copy_name"],
                                      approved["output_name"]):
                    raise ManifestPublicationError("publication_destination_conflict")
                dest.flush(publication["copy_name"])
            _append(db, approved, staged, publication, "published",
                    publication["copy_name"])
    except ManifestPublicationError:
        raise
    except FileExistsError:
        raise ManifestPublicationError("publication_destination_conflict") from None
    except (ExportFileError, OSError):
        raise ManifestPublicationError("publication_storage_failed") from None
    except (sqlite3.DatabaseError, ValueError, TypeError):
        raise ManifestPublicationError("publication_journal_failed") from None


def resume_manifest_publication(project, export_id: str) -> dict:
    """Resume existing publishing intent; NEVER implicitly start an export."""
    consent._uuid(export_id)
    before = inspect_manifest_publication(project, export_id)
    if not before["current_original_revision_matches"]:
        raise ManifestPublicationError("publication_revision_stale")
    if before["state"] == "not_published":
        raise ManifestPublicationError("publication_not_started")
    if before["state"] == "published_verified":
        return before
    _finish(project, export_id)
    return inspect_manifest_publication(project, export_id)


def publish_manifest_workbook(project, export_id: str) -> dict:
    """Explicit backend publication of an already-staged, consented XLSX."""
    consent._uuid(export_id)
    before = inspect_manifest_publication(project, export_id)
    if not before["current_original_revision_matches"]:
        raise ManifestPublicationError("publication_revision_stale")
    if before["state"] != "not_published":
        return resume_manifest_publication(project, export_id)
    _begin(project, export_id)
    return resume_manifest_publication(project, export_id)


def save_consented_manifest(project, run_id, export_id, expected_revision):
    """Fulfil the displayed receipt using the original guarded staging and publishing services."""
    receipt = consent.inspect_manifest_intent(project, export_id)
    if receipt["run_id"] != run_id or receipt["approved_original_revision"] != expected_revision:
        raise ManifestPublicationError("publication_invalid")
    if not receipt["current_revision_matches"]:
        raise ManifestPublicationError("publication_revision_stale")
    stage.stage_manifest_workbook(project, export_id)
    return publish_manifest_workbook(project, export_id)


def inspect_manifest_save(project, export_id):
    """Inspect the publication, or show staging progress if there is no completed stage yet."""
    return _inspect(project, export_id, allow_unstaged=True)
