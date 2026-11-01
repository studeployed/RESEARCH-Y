"""Audited strategy-workbook publication with explicit crash recovery.

Database commits and filesystem publication are separate operations. A durable
publishing intent precedes the no-overwrite link; only a committed published
receipt plus a matching observed artifact constitutes audited success. Exact
retries retain the original captured report. No research row/status is updated.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from research_y.export_files import Directory, ExportFileError, MAX_ARTIFACT_BYTES, filename, project_guard
from research_y.strategy_report import StrategyReport, canonical, decode, digest

if TYPE_CHECKING:
    from research_y.projects import Project

EVENT = 'workbook_export_v1'
METHOD = 'audited-workbook-publication/1'
STORE = '.researchy-exports'
ERRORS = frozenset({'render_failed', 'storage_failed', 'destination_conflict', 'artifact_changed',
                    'destination_required', 'directory_changed', 'journal_failed', 'cancelled',
                    'unknown_export', 'invalid_export', 'concurrent_progress_retry'})


class WorkbookExportError(ValueError):
    """Static diagnostic; export_id locates durable progress without leaking paths."""
    def __init__(self, code: str, export_id: str):
        self.code, self.export_id = code, export_id
        super().__init__(f'{code}: export {export_id}')


@dataclass(frozen=True, slots=True)
class WorkbookExport:
    export_id: str
    state: str
    filename: str
    destination_kind: str
    report_sha256: str
    artifact_sha256: str | None
    last_event_id: int
    last_error: str | None
    audited_success: bool = False
    report_status: str = 'incomplete'
    source_retrieval_verified: bool = False


def _uuid(value: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Canonical export or run identifier required')
    return value


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


@contextmanager
def _transaction(project, *, write=True):
    # Preserve the existing project identity, crash recovery and migration checks.
    from research_y.projects import _validated_project_connection, _parse_manifest
    with project_guard(project):
        if _parse_manifest(project.manifest_path) != (project.identifier, project.name, project.created_at_utc):
            raise ExportFileError('Project manifest identity changed')
        with _validated_project_connection(project) as db:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ExportFileError('Broken project evidence references')
            yield db


def _capture(db, project, run_id):
    from research_y.strategy_report import _capture as capture
    return capture(db, project, run_id, _now())


def _renderer():
    from research_y.strategy_workbook import RENDER_METHOD, render_strategy_workbook
    return RENDER_METHOD, render_strategy_workbook


def _selection(project, directory):
    chosen = project.root / 'exports' if directory is None else Path(directory)
    with Directory(chosen) as target:
        if chosen == project.root / 'exports':
            return {'kind': 'project_exports'}
        if chosen.is_relative_to(project.root):
            raise ExportFileError('Use the project exports directory or an external directory')
        return {'kind': 'external', 'directory_identity': list(target.identity)}


@contextmanager
def _target(project, selection, directory):
    if selection['kind'] == 'project_exports':
        path = project.root / 'exports'
        if directory is not None and Path(directory) != path:
            raise ExportFileError('An export cannot be silently retargeted')
    else:
        if directory is None:
            raise WorkbookExportError('destination_required', '')
        path = Path(directory)
    with Directory(path) as target:
        if selection['kind'] == 'external' and list(target.identity) != selection['directory_identity']:
            raise WorkbookExportError('directory_changed', '')
        yield target


@contextmanager
def _store(project, *, create=False):
    with Directory(project.root / 'exports') as exports:
        if create:
            exports.mkdir(STORE)
        with Directory(project.root / 'exports' / STORE) as store:
            yield store


def _append(db, export_id, previous, action, data):
    body = dict(version=1, method=METHOD, export_id=export_id, at_utc=_now(), action=action, data=data,
                previous_event_id=previous['event_id'] if previous else None,
                previous_sha256=previous['event_sha256'] if previous else None)
    body['sha256'] = digest(canonical(body))
    db.execute('INSERT INTO audit_events(occurred_at_utc,event_type,details_json) VALUES(?,?,?)',
               (body['at_utc'], f'{EVENT}:{export_id}', canonical(body)))


def _load(db, project, export_id):
    state = None
    for event_id, raw in db.execute('SELECT event_id,details_json FROM audit_events WHERE event_type=? ORDER BY event_id', (f'{EVENT}:{export_id}',)):
        body = decode(raw)
        if body.get('export_id') != export_id:
            raise WorkbookExportError('invalid_export', export_id)
        try:
            claimed = body.pop('sha256')
            if (set(body) != {'version','method','export_id','at_utc','action','data',
                             'previous_event_id','previous_sha256'}
                    or body['version'] != 1 or type(body['version']) is not int
                    or body['method'] != METHOD or not _hash(claimed) or digest(canonical(body)) != claimed
                    or body['previous_event_id'] != (state['event_id'] if state else None)
                    or body['previous_sha256'] != (state['event_sha256'] if state else None)):
                raise ValueError
            timestamp = datetime.fromisoformat(body['at_utc'])
            if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
                raise ValueError
            action, data = body['action'], body['data']
            if not isinstance(data, dict):
                raise ValueError
            if action == 'prepared':
                if state is not None or set(data) != {'run_id','filename','destination','report_json','report_sha256','renderer'}:
                    raise ValueError
                report = StrategyReport(data['report_json'])
                meta = report.as_dict()
                _uuid(data['run_id'])
                filename(data['filename'], workbook=True)
                if (report.sha256 != data['report_sha256'] or meta['project']['project_id'] != str(project.identifier)
                        or meta['run']['run_id'] != data['run_id'] or not isinstance(data['renderer'], str)):
                    raise ValueError
                run = db.execute('SELECT strategy_version_id FROM search_runs WHERE run_id=?', (data['run_id'],)).fetchone()
                if run != (meta['run']['strategy_version_id'],):
                    raise ValueError
                selection = data['destination']
                if selection != {'kind':'project_exports'}:
                    if (set(selection) != {'kind','directory_identity'} or selection['kind'] != 'external'
                            or not isinstance(selection['directory_identity'], list) or len(selection['directory_identity']) != 2
                            or any(type(i) is not int or i < 0 for i in selection['directory_identity'])):
                        raise ValueError
                state = dict(data, state='prepared', stage=None, publication=None, last_error=None)
            elif state is None:
                raise ValueError
            elif action == 'staging':
                if (state['state'] not in ('prepared','staging') or set(data) != {'name','sha256','size'}
                        or not re.fullmatch(r'retained-' + re.escape(export_id) + r'-[0-9a-f]{32}\.xlsx', data['name'])
                        or not _hash(data['sha256']) or type(data['size']) is not int
                        or not 0 < data['size'] <= MAX_ARTIFACT_BYTES):
                    raise ValueError
                state.update(state='staging', stage=data, last_error=None)
            elif action == 'staged':
                if state['state'] != 'staging' or data:
                    raise ValueError
                state.update(state='staged', last_error=None)
            elif action == 'publishing':
                if (state['state'] not in ('staged','publishing') or set(data) != {'name'}
                        or not re.fullmatch(r'\.researchy-' + re.escape(export_id) + r'-[0-9a-f]{32}\.part', data['name'])):
                    raise ValueError
                state.update(state='publishing', publication=data, last_error=None)
            elif action == 'published':
                if state['state'] != 'publishing' or data:
                    raise ValueError
                state.update(state='published', last_error=None)
            elif action == 'cancelled':
                if state['state'] not in ('prepared','staging','staged','publishing') or data:
                    raise ValueError
                state.update(state='cancelled', last_error=None)
            elif action == 'failure':
                if set(data) != {'code'} or data['code'] not in ERRORS or state['state'] == 'cancelled':
                    raise ValueError
                state['last_error'] = data['code']
            else:
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise WorkbookExportError('invalid_export', export_id) from None
        state.update(event_id=event_id, event_sha256=claimed, export_id=export_id)
    return state


def _view(state, *, verified=False):
    return WorkbookExport(state['export_id'], state['state'], state['filename'], state['destination']['kind'],
                          state['report_sha256'], state['stage']['sha256'] if state['stage'] else None,
                          state['event_id'], state['last_error'], verified)


def _required(db, project, export_id):
    state = _load(db, project, export_id)
    if state is None:
        raise WorkbookExportError('unknown_export', export_id)
    return state


def _failure(project, export_id, code):
    # If the journal itself failed, the last committed phase remains authoritative.
    try:
        with _transaction(project) as db:
            state = _load(db, project, export_id)
            if state is not None and state['state'] != 'cancelled':
                _append(db, export_id, state, 'failure', {'code': code})
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass


def prepare_workbook_export(project: Project, run_id: str, output_name: str, *,
                            export_id: str, directory: Path | str | None = None) -> WorkbookExport:
    """Capture and journal once. Supply the same export_id to retry this request.

    The default destination is project-relative exports/. An external destination
    must exist and be supplied again when resuming; its absolute path is not stored.
    """
    _uuid(export_id)
    _uuid(run_id)
    filename(output_name, workbook=True)
    try:
        selection = _selection(project, directory)
        with _transaction(project) as db:
            prior = _load(db, project, export_id)
            if prior is not None:
                if (prior['run_id'], prior['filename'], prior['destination']) != (run_id, output_name, selection):
                    raise WorkbookExportError('invalid_export', export_id)
                return _view(prior)  # Never recapture newer research evidence on retry.
            with _target(project, selection, directory) as target:
                if target.exists(output_name):
                    raise WorkbookExportError('destination_conflict', export_id)
            report = _capture(db, project, run_id)
            renderer, _ = _renderer()
            _append(db, export_id, None, 'prepared', dict(run_id=run_id, filename=output_name,
                destination=selection, report_json=report.payload_json, report_sha256=report.sha256, renderer=renderer))
            state = _required(db, project, export_id)
        return _view(state)  # Return only after the prepared receipt commits.
    except WorkbookExportError as exc:
        raise WorkbookExportError(exc.code, export_id) from None
    except sqlite3.Error:
        raise WorkbookExportError('journal_failed', export_id) from None
    except (OSError, ValueError, TypeError):
        raise WorkbookExportError('invalid_export', export_id) from None


def _read_artifact(store, state):
    stage = state['stage']
    return store.read(stage['name'], digest=stage['sha256'], size=stage['size'])


def _new_stage(db, export_id, state, content):
    if type(content) is not bytes or not 0 < len(content) <= MAX_ARTIFACT_BYTES:
        raise WorkbookExportError('render_failed', export_id)
    stage = dict(name=f'retained-{export_id}-{uuid4().hex}.xlsx', sha256=digest(content), size=len(content))
    _append(db, export_id, state, 'staging', stage)
    return content


def _render(state):
    method, render = _renderer()
    if method != state['renderer']:
        raise WorkbookExportError('render_failed', state['export_id'])
    try:
        return render(StrategyReport(state['report_json']))
    except (ValueError, TypeError, OSError, ImportError, RuntimeError):
        raise WorkbookExportError('render_failed', state['export_id']) from None


def _step(project, export_id, directory, cached):
    """One serialized transition. File side effects may outlive a rolled-back receipt."""
    with _transaction(project) as db:
        state = _required(db, project, export_id)
        phase = state['state']
        if phase == 'cancelled':
            raise WorkbookExportError('cancelled', export_id)
        if phase == 'prepared':
            cached = _new_stage(db, export_id, state, _render(state))
        elif phase == 'staging':
            with _store(project, create=True) as store:
                stage = state['stage']
                valid = False
                if store.exists(stage['name']):
                    try:
                        _read_artifact(store, state)
                        valid = True
                    except (ExportFileError, OSError):
                        pass  # Retain the failed generation; never overwrite or delete it.
                if valid:
                    store.flush(stage['name'])
                    _append(db, export_id, state, 'staged', {})
                elif not store.exists(stage['name']) and cached is not None and digest(cached) == stage['sha256']:
                    store.write_new(stage['name'], cached)
                    _read_artifact(store, state)
                    _append(db, export_id, state, 'staged', {})
                else:
                    # A crash before successful staging may require new rendered bytes,
                    # but always from the retained immutable report, never a new capture.
                    cached = _new_stage(db, export_id, state, _render(state))
        elif phase == 'staged':
            with _store(project) as store, _target(project, state['destination'], directory) as target:
                _read_artifact(store, state)
                if target.exists(state['filename']):
                    raise WorkbookExportError('destination_conflict', export_id)
                _append(db, export_id, state, 'publishing', {'name': f'.researchy-{export_id}-{uuid4().hex}.part'})
        else:  # publishing or published
            with _store(project) as store, _target(project, state['destination'], directory) as target:
                artifact = _read_artifact(store, state)  # Retained artifact is independent of the exported copy.
                stage, copy = state['stage'], state['publication']['name']
                if phase == 'published':
                    target.read(state['filename'], digest=stage['sha256'], size=stage['size'])
                    return _view(state, verified=True), None
                if target.exists(state['filename']):
                    if not target.exists(copy) or not target.same_file(copy, state['filename']):
                        raise WorkbookExportError('destination_conflict', export_id)
                    target.read(state['filename'], digest=stage['sha256'], size=stage['size'])
                    target.flush(copy)
                    _append(db, export_id, state, 'published', {})
                else:
                    if target.exists(copy):
                        try:
                            target.read(copy, digest=stage['sha256'], size=stage['size'])
                        except (ExportFileError, OSError):
                            _append(db, export_id, state, 'publishing', {'name': f'.researchy-{export_id}-{uuid4().hex}.part'})
                            return None, None
                    else:
                        target.write_new(copy, artifact)
                    target.read(copy, digest=stage['sha256'], size=stage['size'])
                    target.flush(copy)
                    target.publish_link(copy, state['filename'])
                    target.read(state['filename'], digest=stage['sha256'], size=stage['size'])
                    target.flush(copy)
                    _append(db, export_id, state, 'published', {})
    # No success response is returned before the final receipt commits.
    return None, cached


def resume_workbook_export(project: Project, export_id: str, *,
                           directory: Path | str | None = None) -> WorkbookExport:
    """Resume retained evidence; refuse unsupported linking instead of replacing files."""
    _uuid(export_id)
    cached = None
    try:
        for _ in range(12):  # Bounded progress in the face of competing invocations.
            result, cached = _step(project, export_id, directory, cached)
            if result is not None:
                return result
        raise WorkbookExportError('concurrent_progress_retry', export_id)
    except WorkbookExportError as exc:
        code = exc.code
    except FileExistsError:
        code = 'destination_conflict'
    except ExportFileError:
        code = 'artifact_changed'
    except sqlite3.Error:
        code = 'journal_failed'
    except OSError:
        code = 'storage_failed'
    except (ValueError, TypeError, KeyError):
        code = 'invalid_export'
    _failure(project, export_id, code)
    raise WorkbookExportError(code, export_id) from None


def _inspect_workbook_export(project: Project, export_id: str, *,
                            directory: Path | str | None = None) -> WorkbookExport:
    """Inspect recorded state; verify both retained and final bytes before success."""
    _uuid(export_id)
    with _transaction(project, write=False) as db:
        state = _required(db, project, export_id)
        if state['state'] == 'published':
            with _store(project) as store, _target(project, state['destination'], directory) as target:
                _read_artifact(store, state)
                target.read(state['filename'], digest=state['stage']['sha256'], size=state['stage']['size'])
            return _view(state, verified=True)
        return _view(state)


def _cancel_workbook_export(project: Project, export_id: str, *,
                           directory: Path | str | None = None) -> WorkbookExport:
    """Append cancellation without deleting stages or already-visible artifacts."""
    _uuid(export_id)
    with _transaction(project) as db:
        state = _required(db, project, export_id)
        if state['state'] == 'published':
            raise WorkbookExportError('invalid_export', export_id)
        if state['state'] == 'cancelled':
            return _view(state)
        if state['state'] == 'publishing':
            with _target(project, state['destination'], directory) as target:
                if target.exists(state['filename']):
                    raise WorkbookExportError('destination_conflict', export_id)
        _append(db, export_id, state, 'cancelled', {})
        result = _view(_required(db, project, export_id))
    return result


def _observe_or_cancel(operation, project, export_id, directory):
    _uuid(export_id)
    try:
        return operation(project, export_id, directory=directory)
    except WorkbookExportError as exc:
        code = exc.code
    except ExportFileError:
        code = 'artifact_changed'
    except sqlite3.Error:
        code = 'journal_failed'
    except OSError:
        code = 'storage_failed'
    except (ValueError, TypeError, KeyError):
        code = 'invalid_export'
    raise WorkbookExportError(code, export_id) from None


def inspect_workbook_export(project: Project, export_id: str, *,
                            directory: Path | str | None = None) -> WorkbookExport:
    """No audit writes; an old success receipt alone is not current file verification."""
    return _observe_or_cancel(_inspect_workbook_export, project, export_id, directory)


def cancel_workbook_export(project: Project, export_id: str, *,
                           directory: Path | str | None = None) -> WorkbookExport:
    """Cancel uncompleted work, with no destructive file cleanup."""
    return _observe_or_cancel(_cancel_workbook_export, project, export_id, directory)
