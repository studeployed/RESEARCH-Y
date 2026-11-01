"""Read models for the future local application; no server, workers or writes.

Inventory is journal evidence, not live-worker detection or file verification.
Explicit observation checks files without completing an interrupted export.
All project/run/export reads in a snapshot share one validated read transaction.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING, Iterator
from uuid import UUID

from research_y import workbook_exports as exports
from research_y.export_files import ExportFileError, project_guard
from research_y.strategy_report import StrategyReport, canonical, decode

if TYPE_CHECKING:
    from research_y.projects import Project

METHOD = 'application-inspection/1'
# Exact prefix comparison, not SQL LIKE (whose underscores are wildcards).
JOURNAL_PREFIX = 'workbook_export_'


class ApplicationInspectionError(ValueError):
    """Static presentation-safe diagnostic; never echo database/source/path errors."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ApplicationInspectionError('invalid_identifier') from None
    return value


def _stamp(value: str) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        stamp = datetime.fromisoformat(value)
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ApplicationInspectionError('invalid_evidence') from None
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


@contextmanager
def _read(project: Project) -> Iterator[sqlite3.Connection]:
    # Use the existing read-only identity/schema/foreign-key checks, not the
    # ordinary opener which can migrate/recover. Preserve PR #40 path guards.
    from research_y.result_counts import _read_connection
    try:
        with project_guard(project), _read_connection(project) as db:
            yield db
    except ApplicationInspectionError:
        raise
    except sqlite3.Error as exc:
        number = getattr(exc, 'sqlite_errorcode', 0)
        code = 'project_busy' if isinstance(number, int) and (number & 255) in (
            sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else 'project_unavailable'
        raise ApplicationInspectionError(code) from None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise ApplicationInspectionError('invalid_evidence') from None


@dataclass(frozen=True, slots=True)
class ExportRequest:
    export_id: str
    run_id: str
    filename: str
    destination_kind: str
    recorded_state: str
    last_error: str | None
    report_sha256: str
    artifact_sha256: str | None
    first_event_id: int
    last_event_id: int
    created_at_utc: str
    updated_at_utc: str
    # These deliberately never become true just from an inventory receipt.
    audited_success: bool = False
    files_checked: bool = False
    worker_status: str = 'unknown'
    report_status: str = 'incomplete'
    source_retrieval_verified: bool = False


@dataclass(frozen=True, slots=True)
class ExportObservation:
    request: ExportRequest
    outcome: str
    observed_at_utc: str
    audited_success: bool = False
    # Verification is a time-specific observation, not ongoing monitoring.
    source_retrieval_verified: bool = False


@dataclass(frozen=True, slots=True)
class ApplicationSnapshot:
    """Canonical immutable payload; local location is transient display context."""
    payload_json: str
    location: Path

    def as_dict(self) -> dict:
        return decode(self.payload_json)  # Fresh copy; callers cannot mutate it.


def _entry(db, project, export_id: str, bounds=None) -> tuple[ExportRequest, dict]:
    # Reuse the production validator: identities, report hash, predecessor hash,
    # supported method and state transitions must all pass before presentation.
    state = exports._load(db, project, export_id)
    if state is None:
        raise ApplicationInspectionError('unknown_export')
    if bounds is None:
        bounds = db.execute(
            'SELECT event_id,occurred_at_utc FROM audit_events '
            'WHERE event_type=? ORDER BY event_id',
            (f'{exports.EVENT}:{export_id}',)).fetchall()
    if not bounds or bounds[-1][0] != state['event_id']:
        raise ApplicationInspectionError('invalid_evidence')
    # Timestamp columns are part of the index being shown. Compare to validated
    # receipt bodies, rather than trusting a second, contradictory timestamp.
    for event_id, stamp in bounds:
        _stamp(stamp)
        raw = db.execute('SELECT details_json FROM audit_events WHERE event_id=?',
                         (event_id,)).fetchone()
        if raw is None or decode(raw[0]).get('at_utc') != stamp:
            raise ApplicationInspectionError('invalid_evidence')
    stage = state['stage']
    return ExportRequest(export_id, state['run_id'], state['filename'],
        state['destination']['kind'], state['state'], state['last_error'],
        state['report_sha256'], stage['sha256'] if stage else None,
        bounds[0][0], bounds[-1][0], bounds[0][1], bounds[-1][1]), state


def _inventory(db, project) -> tuple[ExportRequest, ...]:
    grouped = {}
    for event_id, stamp, event_type in db.execute(
            'SELECT event_id,occurred_at_utc,event_type FROM audit_events '
            'WHERE substr(event_type,1,?)=? ORDER BY event_id',
            (len(JOURNAL_PREFIX), JOURNAL_PREFIX)):
        prefix = exports.EVENT + ':'
        if not event_type.startswith(prefix):
            raise ApplicationInspectionError('unsupported_export_journal')
        export_id = _uuid(event_type[len(prefix):])
        grouped.setdefault(export_id, []).append((event_id, stamp))
    # Stable latest-event ordering, not filesystem names or modification times.
    result = [_entry(db, project, key, bounds)[0] for key, bounds in grouped.items()]
    return tuple(sorted(result, key=lambda r: r.last_event_id, reverse=True))


def list_export_requests(project: Project) -> tuple[ExportRequest, ...]:
    """List every validated request, including cancelled and unfinished requests.

    No workbook bytes are read and no export is resumed, migrated or repaired.
    A corrupt/unsupported journal fails explicitly; it is never an empty list.
    """
    with _read(project) as db:
        return _inventory(db, project)


def read_export_report(project: Project, export_id: str) -> StrategyReport:
    """Read the retained report, never recapture the current research state."""
    _uuid(export_id)
    with _read(project) as db:
        _, state = _entry(db, project, export_id)
        return StrategyReport(state['report_json'])


def _observe_files(project, state, directory) -> str:
    phase = state['state']
    if phase == 'cancelled':
        return 'recorded_cancelled'
    if state['stage'] is None:
        return 'not_yet_staged'
    try:
        with exports._store(project) as store:
            exports._read_artifact(store, state)
    except FileNotFoundError:
        return 'retained_artifact_missing'
    except ExportFileError:
        return 'retained_artifact_changed'
    except OSError:
        return 'storage_unavailable'
    if phase == 'staging':
        # A complete file still needs the staged receipt; observation never
        # flushes, advances a receipt, or asserts that a worker has stopped.
        return 'staging_receipt_required'
    try:
        with exports._target(project, state['destination'], directory) as target:
            present = target.exists(state['filename'])
            if phase == 'staged':
                return 'destination_conflict' if present else 'ready_to_publish'
            if not present:
                return 'published_file_missing' if phase == 'published' else 'publication_pending'
            if phase == 'publishing':
                copy = state['publication']['name']
                if not target.exists(copy) or not target.same_file(copy, state['filename']):
                    return 'destination_conflict'
            target.read(state['filename'], digest=state['stage']['sha256'], size=state['stage']['size'])
            return 'published_verified' if phase == 'published' else 'published_receipt_missing'
    except exports.WorkbookExportError as exc:
        if exc.code == 'destination_required':
            return 'destination_confirmation_required'
        if exc.code == 'directory_changed':
            return 'destination_directory_changed'
        raise
    except ExportFileError:
        return 'destination_changed'
    except OSError:
        return 'destination_unavailable'


def observe_export_request(project: Project, export_id: str, *,
                           directory: Path | str | None = None) -> ExportObservation:
    """Observe current artifacts without writing any file or audit receipt.

    External directories come only from a trusted local selection. This is not
    a browser endpoint and does not authorise accepting paths from web clients.
    Journal and filesystem are not one atomic snapshot; result is as observed.
    """
    _uuid(export_id)
    with _read(project) as db:
        request, state = _entry(db, project, export_id)
        outcome = _observe_files(project, state, directory)
        return ExportObservation(request, outcome, _now(), outcome == 'published_verified')


def _runs(db):
    from research_y.schema import RUN_STATUSES
    from research_y.strategy_report import _strategy
    result = []
    # Do not invent a run-name column: source schema stores identity/date/version.
    for row in db.execute(
            'SELECT r.run_id,r.strategy_version_id,r.created_at_utc,r.status,'
            'r.completed_at_utc,v.version_number,v.approved_at_utc,v.snapshot_json '
            'FROM search_runs r LEFT JOIN strategy_versions v '
            'ON r.strategy_version_id=v.strategy_version_id '
            'ORDER BY r.created_at_utc DESC,r.run_id'):
        rid, sid, created, status, completed, version, approved, raw = row
        _uuid(rid); _uuid(sid); _stamp(created); _stamp(approved)
        if completed is not None:
            _stamp(completed)
        if status not in RUN_STATUSES or type(version) is not int or version < 1:
            raise ApplicationInspectionError('invalid_evidence')
        strategy = decode(raw)
        groups = db.execute('SELECT group_id,label,group_order FROM strategy_groups '
                            'WHERE strategy_version_id=? ORDER BY group_order,group_id', (sid,)).fetchall()
        _strategy(strategy, groups)
        result.append(dict(run_id=rid, strategy_version_id=sid, version_number=version,
            created_at_utc=created, completed_at_utc=completed, stored_status=status,
            strategy_theme=strategy['theme'], source_retrieval_verified=False))
    return result


def read_application_snapshot(project: Project, *, selected_run_id: str | None = None) -> ApplicationSnapshot:
    """Project/run/export catalogue plus optional full-run report on ONE snapshot.

    No implicit latest-run selection, filters, progress estimate or source calls.
    Rendering text safely remains the responsibility of the future interface.
    """
    if selected_run_id is not None:
        _uuid(selected_run_id)
    from research_y.strategy_report import _capture
    with _read(project) as db:
        runs = _runs(db)
        if selected_run_id is not None and selected_run_id not in {r['run_id'] for r in runs}:
            raise ApplicationInspectionError('unknown_run')
        setup = db.execute('SELECT theme,objectives FROM project_metadata WHERE singleton_id=1').fetchone()
        if setup is None or any(not isinstance(s, str) for s in setup):
            raise ApplicationInspectionError('invalid_evidence')
        inventory = _inventory(db, project)
        captured = _now()
        report = _capture(db, project, selected_run_id, captured) if selected_run_id is not None else None
        audit = db.execute('SELECT event_id,occurred_at_utc FROM audit_events ORDER BY event_id DESC LIMIT 1').fetchone()
        if audit is not None:
            _stamp(audit[1])
        payload = dict(method=METHOD, captured_at_utc=captured,
            project=dict(project_id=str(project.identifier), name=project.name,
                         theme=setup[0], objectives=setup[1]),
            runs=runs, selected_run_id=selected_run_id,
            report=report.as_dict() if report is not None else None,
            exports=[asdict(entry) for entry in inventory],
            last_recorded_audit_event={'event_id': audit[0], 'occurred_at_utc': audit[1]} if audit else None,
            last_successful_source_checkpoint=None, checkpoint_verification='not_performed',
            source_retrieval_verified=False, gui_implemented=False,
            warnings=['read_model_not_source_acceptance', 'export_inventory_not_file_verification',
                      'recorded_phase_not_live_worker_status', 'last_audit_event_is_not_a_source_checkpoint'])
        return ApplicationSnapshot(canonical(payload), project.root)
