"""Trusted local commands for existing services; NOT a browser/path endpoint.

Commands contain transient local paths, never credentials. They are not a
persistent queue. Export identity/durability continues to belong to the existing
append-only workbook journal. This module does not launch searches or a GUI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import UUID

OPERATIONS = frozenset({'inspect', 'prepare_export', 'resume_export', 'cancel_export',
                        'observe_export', 'export_report'})
SERVICE_ERRORS = frozenset({'invalid_identifier', 'invalid_evidence', 'unknown_export',
    'unknown_run', 'unsupported_export_journal', 'project_busy', 'project_unavailable',
    'render_failed', 'storage_failed', 'destination_conflict', 'artifact_changed',
    'destination_required', 'directory_changed', 'journal_failed', 'cancelled',
    'invalid_export', 'concurrent_progress_retry'})


class ApplicationCommandError(ValueError):
    """A static error code, not the original exception or private path."""
    def __init__(self, code: str):
        self.code = code if code in SERVICE_ERRORS | {'invalid_command', 'operation_failed'} else 'operation_failed'
        super().__init__(self.code)


def _uuid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError


def _path(value):
    if type(value) is not str or not value or '\x00' in value:
        raise ValueError
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError


@dataclass(frozen=True, slots=True, repr=False)
class ApplicationCommand:
    operation: str
    project_root: str
    project_id: str
    project_name: str
    project_created_at: str
    run_id: str | None = None
    export_id: str | None = None
    output_name: str | None = None
    directory: str | None = None

    def __post_init__(self):
        try:
            if type(self.operation) is not str or self.operation not in OPERATIONS:
                raise ValueError
            _path(self.project_root); _uuid(self.project_id)
            if type(self.project_name) is not str or not self.project_name or len(self.project_name) > 200:
                raise ValueError
            stamp = datetime.fromisoformat(self.project_created_at)
            if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
                raise ValueError
            if self.run_id is not None:
                _uuid(self.run_id)
            if self.export_id is not None:
                _uuid(self.export_id)
            if self.directory is not None:
                _path(self.directory)
            if self.operation == 'inspect':
                if any(v is not None for v in (self.export_id, self.output_name, self.directory)):
                    raise ValueError
            else:
                if self.export_id is None:
                    raise ValueError
                if self.operation == 'prepare_export':
                    from research_y.export_files import filename
                    if self.run_id is None:
                        raise ValueError
                    filename(self.output_name, workbook=True)
                elif self.run_id is not None or self.output_name is not None:
                    raise ValueError
                if self.operation == 'export_report' and self.directory is not None:
                    raise ValueError
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise ApplicationCommandError('invalid_command') from None

    def __repr__(self):
        return f'ApplicationCommand(operation={self.operation!r})'

    @classmethod
    def for_project(cls, project, operation: str, **kwargs):
        """Host-only constructor after trusted project selection/opening."""
        from research_y.projects import Project
        if not isinstance(project, Project):
            raise ApplicationCommandError('invalid_command')
        return cls(operation, str(project.root), str(project.identifier), project.name,
                   project.created_at_utc, **kwargs)


def execute_command(command: ApplicationCommand) -> dict:
    """Call existing services; never reopen a different project or invent counts.

    Reconstruct the expected Project identity only. Each service validates that
    identity against storage. Inspection does not use the migrating/recovering
    project opener. Explicit project open/recovery remains the launcher's job.
    """
    if type(command) is not ApplicationCommand:
        raise ApplicationCommandError('invalid_command')
    command.__post_init__()  # Revalidate after the trusted process boundary.
    from research_y.projects import Project
    from research_y import application_inspection as inspection
    from research_y import workbook_exports as exports
    project = Project(Path(command.project_root), UUID(command.project_id),
                      command.project_name, command.project_created_at)
    try:
        if command.operation == 'inspect':
            snapshot = inspection.read_application_snapshot(project, selected_run_id=command.run_id)
            return {'snapshot': snapshot.as_dict(), 'location': str(snapshot.location)}
        if command.operation == 'export_report':
            return inspection.read_export_report(project, command.export_id).as_dict()
        if command.operation == 'observe_export':
            result = inspection.observe_export_request(project, command.export_id, directory=command.directory)
        elif command.operation == 'prepare_export':
            result = exports.prepare_workbook_export(project, command.run_id, command.output_name,
                       export_id=command.export_id, directory=command.directory)
        elif command.operation == 'resume_export':
            result = exports.resume_workbook_export(project, command.export_id, directory=command.directory)
        else:
            result = exports.cancel_workbook_export(project, command.export_id, directory=command.directory)
        return asdict(result)
    except (inspection.ApplicationInspectionError, exports.WorkbookExportError) as exc:
        raise ApplicationCommandError(exc.code) from None
    except sqlite3.Error as exc:
        number = getattr(exc, 'sqlite_errorcode', 0)
        busy = isinstance(number, int) and (number & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        raise ApplicationCommandError('project_busy' if busy else 'project_unavailable') from None
    except Exception:
        # Original errors may contain paths, source text or renderer details.
        raise ApplicationCommandError('operation_failed') from None
