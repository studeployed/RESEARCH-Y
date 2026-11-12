"""Recoverable *internal* staging for explicitly approved provisional workbooks.

The approval from provisional_manifest_intent remains a separate immutable
event. This service holds source-only XLSX bytes in a guarded, private stage
file with a separate append-only staging/staged receipt chain. It never
publishes a final export, grants data rights, or exposes a GUI/worker command.
A stage is never silently re-bound to different original source evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import re
import sqlite3
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from research_y import provisional_manifest_intent as intent, result_counts
from research_y.export_files import Directory, ExportFileError, MAX_ARTIFACT_BYTES
from research_y.provisional_manifest_workbook import (
    METHOD as RENDER_METHOD, render_provisional_manifest,
)
from research_y.publication_identity import _json, _object
from research_y.workbook_exports import _transaction

METHOD = "provisional-manifest-stage/1"
PREFIX = "provisional_manifest_stage_v1:"
STORE = ".researchy-manifest-stages"
ERRORS = frozenset({
    "stage_invalid", "intent_not_found", "stage_not_found",
    "stage_revision_stale", "stage_receipt_invalid", "stage_artifact_changed",
    "stage_busy_retry", "stage_destination_conflict", "stage_render_failed",
    "stage_journal_failed", "stage_storage_failed",
})
STAGES = frozenset(("staging", "staged"))
_FIELDS = frozenset((
    "version", "method", "export_id", "intent_event_id",
    "intent_sha256", "original_revision", "at_utc", "action",
    "artifact", "previous_event_id", "previous_sha256", "receipt_sha256",
))


class ManifestStageError(ValueError):
    """Fixed diagnostic without original records, local paths or credentials."""

    def __init__(self, code: str):
        self.code = code if code in ERRORS else "stage_invalid"
        super().__init__(self.code)


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _event_type(export_id: str) -> str:
    return PREFIX + export_id


def _intent(db, project, export_id):
    approved = intent._load(db, project, export_id)
    if approved is None:
        raise ManifestStageError("intent_not_found")
    return approved


def _evidence(db, project, approved):
    original = intent._counts(db, project, approved["run_id"])
    if original.revision != approved["run_revision"]:
        raise ManifestStageError("stage_revision_stale")
    if (original.totals["metadata_source_records"] != approved["source_records"]
            or original.totals["global_publication_identities"] != approved["provisional_identities"]
            or original.totals["unmaterialised_retrievals"] != approved["unmaterialised_sources"]):
        raise ManifestStageError("stage_revision_stale")
    return original


def _artifact(value, export_id):
    if (type(value) is not dict or set(value) != {"name", "sha256", "size"}
            or type(value["name"]) is not str
            or re.fullmatch(
                r"retained-" + re.escape(export_id) + r"-[0-9a-f]{32}\.xlsx",
                value["name"]) is None
            or type(value["sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
            or type(value["size"]) is not int
            or not 0 < value["size"] <= MAX_ARTIFACT_BYTES):
        raise ManifestStageError("stage_receipt_invalid")
    return value


def _load(db, project, approved):
    """Verify all append-only stage receipts; never trust an optimistic last row."""
    export_id = approved["export_id"]
    state = None
    previous_id = previous_sha = None
    for event_id, at, raw in db.execute(
        "SELECT event_id,occurred_at_utc,details_json FROM audit_events "
        "WHERE event_type=? ORDER BY event_id LIMIT 3",
        (_event_type(export_id),),
    ):
        try:
            payload = _object(raw)
            recorded = payload.pop("receipt_sha256")
            if (set(payload) | {"receipt_sha256"} != _FIELDS
                    or type(payload["version"]) is not int or payload["version"] != 1
                    or payload["method"] != METHOD or payload["export_id"] != export_id
                    or payload["intent_event_id"] != approved["audit_event_id"]
                    or payload["intent_sha256"] != approved["receipt_sha256"]
                    or payload["original_revision"] != approved["run_revision"]
                    or payload["at_utc"] != at
                    or payload["previous_event_id"] != previous_id
                    or payload["previous_sha256"] != previous_sha
                    or type(recorded) is not str
                    or recorded != _sha(_json(payload).encode("utf-8"))
                    or raw != _json({**payload, "receipt_sha256": recorded})
                    or payload["action"] not in STAGES):
                raise ValueError
            at_time = datetime.fromisoformat(at)
            if at_time.utcoffset() is None or at_time.utcoffset().total_seconds() != 0:
                raise ValueError
            if payload["action"] == "staging":
                if state is not None:
                    raise ValueError
                stage = _artifact(payload["artifact"], export_id)
                state = dict(phase="staging", artifact=stage)
            else:
                if state is None or state["phase"] != "staging" or payload["artifact"] != {}:
                    raise ValueError
                state["phase"] = "staged"
            state.update(event_id=event_id, event_sha256=recorded)
            previous_id, previous_sha = event_id, recorded
        except (KeyError, ValueError, TypeError, AttributeError, RecursionError):
            raise ManifestStageError("stage_receipt_invalid") from None
    return state


def _append(db, approved, prior, action, artifact):
    body = dict(
        version=1, method=METHOD, export_id=approved["export_id"],
        intent_event_id=approved["audit_event_id"],
        intent_sha256=approved["receipt_sha256"],
        original_revision=approved["run_revision"],
        at_utc=intent._now(), action=action, artifact=artifact,
        previous_event_id=prior["event_id"] if prior else None,
        previous_sha256=prior["event_sha256"] if prior else None,
    )
    body["receipt_sha256"] = _sha(_json(body).encode("utf-8"))
    db.execute(
        "INSERT INTO audit_events(occurred_at_utc,event_type,details_json) "
        "VALUES(?,?,?)",
        (body["at_utc"], _event_type(approved["export_id"]), _json(body)),
    )


@contextmanager
def _store(project, *, create=False):
    with Directory(project.root / "exports") as parent:
        if create:
            parent.mkdir(STORE)
        with Directory(project.root / "exports" / STORE) as location:
            yield location


def _file_state(project, state):
    if state is None:
        return "not_created"
    try:
        with _store(project) as location:
            if not location.exists(state["artifact"]["name"]):
                return "missing"
            stage = state["artifact"]
            location.read(stage["name"], digest=stage["sha256"], size=stage["size"])
            return "verified"
    except FileNotFoundError:
        # A crash may occur after the staging receipt was committed but
        # before even the private stage directory could be created.
        return "missing"
    except (ExportFileError, OSError, ValueError):
        raise ManifestStageError("stage_artifact_changed") from None


def _view(approved, state, file_state, *, original_current):
    phase = state["phase"] if state is not None else "not_staged"
    if not original_current:
        phase = "stale_reapproval_required"
    elif state is not None and file_state == "missing":
        phase = "staging_interrupted"
    return dict(
        method=METHOD, export_id=approved["export_id"],
        run_id=approved["run_id"], output_name=approved["output_name"],
        approved_original_revision=approved["run_revision"],
        state=phase, current_original_revision_matches=original_current,
        stage_receipt_event_id=state["event_id"] if state else None,
        staged_artifact_sha256=state["artifact"]["sha256"] if state else None,
        staged_artifact_bytes=state["artifact"]["size"] if state else None,
        retained_artifact_verified=file_state == "verified",
        workbook_staged=bool(state is not None and state["phase"] == "staged"
                             and file_state == "verified" and original_current),
        workbook_published=False, published_filename_available=False,
        audited_publication_success=False, no_network_requests=True,
        original_source_text_exported=False,
        global_unique_publications=None, deduplication_complete=False,
        source_retrieval_verified=False, verified_complete=False,
    )


def _read_state(project, export_id):
    try:
        with result_counts._read_connection(project) as db:
            approved = _intent(db, project, export_id)
            state = _load(db, project, approved)
            projection = intent._counts(db, project, approved["run_id"])
            current = projection.revision == approved["run_revision"]
            file_state = _file_state(project, state)
            if state is not None and state["phase"] == "staged" and file_state != "verified":
                raise ManifestStageError("stage_artifact_changed")
            return approved, state, current, file_state
    except ManifestStageError:
        raise
    except intent.ManifestIntentError as exc:
        raise ManifestStageError(
            "intent_not_found" if exc.code == "intent_not_found"
            else "stage_receipt_invalid") from None
    except (OSError, ValueError, sqlite3.DatabaseError, TypeError):
        raise ManifestStageError("stage_invalid") from None


def inspect_manifest_stage(project, export_id: str) -> dict:
    """Strict read-only inspection; no migration, file repair or audit writes."""
    intent._uuid(export_id)
    try:
        approved, state, current, file_state = _read_state(project, export_id)
        return _view(approved, state, file_state, original_current=current)
    except (ManifestStageError, intent.ManifestIntentError):
        raise
    except (OSError, ValueError, sqlite3.DatabaseError, TypeError):
        raise ManifestStageError("stage_invalid") from None


_CORE_NS = "http://purl.org/dc/terms/"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _stable_package(raw: bytes, approved: dict) -> bytes:
    """Repackage an INTERNAL generated XLSX with consent-bound core metadata.

    Both OpenPyXL workbook creation timestamps AND ZIP entry timestamps differ
    across processes. The exact-byte staging receipt must be recoverable on a
    later day without re-approving new original records. Keep the content and
    sheet XML untouched; normalize only package timestamps, from the immutable
    original authorisation time (not wall-clock time at each render).
    This is NOT an arbitrary untrusted ZIP import or archival extraction.
    """
    original_time = datetime.fromisoformat(approved["authorised_at_utc"])
    if (original_time.utcoffset() is None or
            original_time.utcoffset().total_seconds() != 0):
        raise ManifestStageError("stage_render_failed")
    fixed = original_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    buffer = BytesIO()
    with ZipFile(BytesIO(raw), "r") as source, ZipFile(
            buffer, "w", compression=ZIP_DEFLATED, compresslevel=6) as output:
        names = set()
        replaced = False
        for original in source.infolist():
            name = original.filename
            if (name in names or name.startswith("/") or "\\" in name or
                    any(part in ("", ".", "..") for part in name.split("/")) or
                    original.is_dir()):
                raise ManifestStageError("stage_render_failed")
            names.add(name)
            content = source.read(original)
            if name == "docProps/core.xml":
                root = ET.fromstring(content)
                for field in ("created", "modified"):
                    node = root.find("{" + _CORE_NS + "}" + field)
                    if node is None:
                        raise ManifestStageError("stage_render_failed")
                    node.text = fixed
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                replaced = True
            entry = ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            entry.create_system = 0
            entry.compress_type = ZIP_DEFLATED
            output.writestr(entry, content, compress_type=ZIP_DEFLATED,
                            compresslevel=6)
        if not replaced or "xl/workbook.xml" not in names:
            raise ManifestStageError("stage_render_failed")
    stable = buffer.getvalue()
    if not 0 < len(stable) <= MAX_ARTIFACT_BYTES:
        raise ManifestStageError("stage_render_failed")
    return stable


def _render(project, approved):
    """Revalidate before/after actual rendering; accept exact original version."""
    try:
        with result_counts._read_connection(project) as db:
            _evidence(db, project, approved)
        raw = render_provisional_manifest(project, approved["run_id"])
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_ARTIFACT_BYTES:
            raise ManifestStageError("stage_render_failed")
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(raw), read_only=True, data_only=False)
        try:
            if wb.sheetnames != [
                "Evidence & Limits", "Provisional Identities",
                "Original Source Links", "Query Memberships",
            ]:
                raise ManifestStageError("stage_render_failed")
            evidence = dict(wb["Evidence & Limits"].iter_rows(
                min_row=4, max_row=25, values_only=True))
            if (evidence.get("Report method") != RENDER_METHOD
                    or evidence.get("Selected run ID") != approved["run_id"]
                    or evidence.get("Original count revision (SHA-256)") != approved["run_revision"]
                    or evidence.get("Report status") != "INCOMPLETE"
                    or evidence.get("Verified unique publications") != "UNKNOWN"
                    or evidence.get("Source retrieval verified") is not False
                    or evidence.get("Deduplication complete") is not False
                    or evidence.get("Saved original run source records") != approved["source_records"]
                    or evidence.get("Provisional publication identities in run") != approved["provisional_identities"]
                    or evidence.get("Unmaterialised original run source records") != approved["unmaterialised_sources"]):
                raise ManifestStageError("stage_render_failed")
        finally:
            wb.close()
        with result_counts._read_connection(project) as db:
            _evidence(db, project, approved)
        return _stable_package(raw, approved)
    except ManifestStageError:
        raise
    except (OSError, ValueError, TypeError, KeyError, sqlite3.DatabaseError,
            ImportError, RecursionError, ET.ParseError):
        raise ManifestStageError("stage_render_failed") from None


def _writer(project, export_id, *, content=None, completion=False):
    """One append-only, revision-checked transaction, never a file publication."""
    try:
        with _transaction(project) as db:
            approved = _intent(db, project, export_id)
            _evidence(db, project, approved)
            state = _load(db, project, approved)
            if completion:
                if state is None or state["phase"] != "staging":
                    raise ManifestStageError("stage_busy_retry")
                verified = _file_state(project, state)
                if verified != "verified":
                    raise ManifestStageError("stage_storage_failed")
                with _store(project) as location:
                    stage = state["artifact"]
                    location.flush(stage["name"])
                    location.read(stage["name"], digest=stage["sha256"],
                                  size=stage["size"])
                _append(db, approved, state, "staged", {})
            else:
                if state is not None:
                    raise ManifestStageError("stage_busy_retry")
                if content is None:
                    raise ManifestStageError("stage_invalid")
                with Directory(project.root / "exports") as target:
                    if target.exists(approved["output_name"]):
                        raise ManifestStageError("stage_destination_conflict")
                stage = dict(
                    name=f"retained-{export_id}-{uuid4().hex}.xlsx",
                    sha256=_sha(content), size=len(content),
                )
                _artifact(stage, export_id)
                _append(db, approved, None, "staging", stage)
            new = _load(db, project, approved)
            if new is None:
                raise ManifestStageError("stage_journal_failed")
            return approved, new
    except (ManifestStageError, intent.ManifestIntentError):
        raise
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError, ExportFileError):
        raise ManifestStageError("stage_journal_failed") from None


def _write_exact(project, state, content):
    stage = state["artifact"]
    if _sha(content) != stage["sha256"] or len(content) != stage["size"]:
        raise ManifestStageError("stage_render_failed")
    try:
        with _store(project, create=True) as location:
            if location.exists(stage["name"]):
                # Never overwrite or adopt an incomplete/corrupt owned stage.
                location.read(stage["name"], digest=stage["sha256"],
                              size=stage["size"])
            else:
                location.write_new(stage["name"], content)
            location.read(stage["name"], digest=stage["sha256"], size=stage["size"])
            location.flush(stage["name"])
    except (FileExistsError, ExportFileError, OSError):
        raise ManifestStageError("stage_artifact_changed") from None


def resume_manifest_stage(project, export_id: str) -> dict:
    """Reconcile a recorded stage after restart; never silently overwrite.

    If a staging receipt exists but no file was written before an interruption,
    render ONLY the exact still-current original revision and compare its
    complete byte digest to the *recorded* SHA-256 before exclusive creation.
    A partial or altered file is never adopted or deleted; a new export ID and
    researcher approval are required. A staged file is never regenerated.
    """
    intent._uuid(export_id)
    approved, state, current, file_state = _read_state(project, export_id)
    if not current:
        raise ManifestStageError("stage_revision_stale")
    if state is None:
        raise ManifestStageError("stage_not_found")
    if state["phase"] == "staged":
        if file_state != "verified":
            raise ManifestStageError("stage_artifact_changed")
        return _view(approved, state, file_state, original_current=True)
    if file_state == "missing":
        content = _render(project, approved)
        _write_exact(project, state, content)
    elif file_state != "verified":
        raise ManifestStageError("stage_artifact_changed")
    _writer(project, export_id, completion=True)
    return inspect_manifest_stage(project, export_id)


def stage_manifest_workbook(project, export_id: str) -> dict:
    """Stage an already researcher-approved workbook; do not publish it."""
    intent._uuid(export_id)
    approved, state, current, _ = _read_state(project, export_id)
    if not current:
        raise ManifestStageError("stage_revision_stale")
    if state is not None:
        return resume_manifest_stage(project, export_id)
    raw = _render(project, approved)
    _, pending = _writer(project, export_id, content=raw)
    _write_exact(project, pending, raw)
    return resume_manifest_stage(project, export_id)
