"""Trusted-host adapter for the approved isolated *real project* GUI experiment.

No browser path, project ID, run ID, or export ID is accepted by this class's
host-only selection boundary. Existing RESEARCH-Y services remain authoritative.
This experimental module does not add a production GUI dependency.
"""
from __future__ import annotations

from pathlib import Path
import threading
import time
from uuid import uuid4

from research_y.application_commands import ApplicationCommand
from research_y.application_worker import ApplicationWorker
from research_y.projects import (ProjectFormatError, ProjectVersionError,
                                  create_project, open_project)


class ProjectFlowError(ValueError):
    """Static code only. Never echo source content, private paths or exceptions."""


class RealProjectFlow:
    def __init__(self, *, selected_root: Path, selected_parent: Path):
        self._root = Path(selected_root)
        self._parent = Path(selected_parent)
        if not self._root.is_absolute() or not self._parent.is_absolute():
            raise ProjectFlowError('trusted_selection_required')
        self._guard = threading.RLock()
        self._worker = ApplicationWorker()
        self._closed = False
        self.project = None
        self.snapshot = None
        self.selected_run_id = None
        self.selected_export_id = None
        self.operation_state = 'idle'
        self.operation_error = None
        self.last_result = None
        self.observation = None
        self._public_state = self._build_state()

    def _require_open(self):
        if self._closed:
            raise ProjectFlowError('flow_closed')
        if self.project is None:
            raise ProjectFlowError('project_not_open')

    def _operation(self, name, **kwargs):
        self._require_open()
        command = ApplicationCommand.for_project(self.project, name, **kwargs)
        try:
            operation_id = self._worker.submit(command)
            deadline = time.monotonic() + 35
            while True:
                state = self._worker.poll(operation_id)
                if state.state != 'running':
                    break
                if time.monotonic() >= deadline:
                    raise ProjectFlowError('worker_timeout')
                time.sleep(.025)
            self.operation_state = state.state
            self.operation_error = state.error
            if state.state != 'returned':
                raise ProjectFlowError('worker_' + state.state)
            result = state.result()
            if not isinstance(result, dict):
                raise ProjectFlowError('invalid_worker_result')
            self.last_result = result
            return result
        except ProjectFlowError:
            raise
        except Exception:
            self.operation_state = 'failed'
            self.operation_error = 'worker_unavailable'
            raise ProjectFlowError('worker_unavailable') from None

    def _set_project(self, project):
        self.project = project
        self.selected_run_id = None
        self.selected_export_id = None
        self.observation = None
        self.last_result = None
        self.snapshot = self._operation('inspect')['snapshot']
        return self._publish()

    def open_selected(self):
        """The host, never a browser request, selected this exact project location."""
        with self._guard:
            if self._closed:
                raise ProjectFlowError('flow_closed')
            try:
                project = open_project(self._root)
            except ProjectVersionError:
                raise ProjectFlowError('unsupported_project_version') from None
            except (ProjectFormatError, OSError, ValueError):
                raise ProjectFlowError('invalid_project') from None
            return self._set_project(project)

    def create_selected(self, name: str):
        """Create in a host-selected parent folder; the core owns path safety."""
        with self._guard:
            if self._closed:
                raise ProjectFlowError('flow_closed')
            try:
                project = create_project(self._parent, name)
            except (OSError, ValueError, TypeError):
                raise ProjectFlowError('project_creation_failed') from None
            return self._set_project(project)

    def select_run(self, run_id: str):
        with self._guard:
            self._require_open()
            if type(run_id) is not str or run_id not in {r['run_id'] for r in self.snapshot['runs']}:
                raise ProjectFlowError('unknown_run')
            report = self._operation('inspect', run_id=run_id)['snapshot']
            if report.get('selected_run_id') != run_id or report.get('report') is None:
                raise ProjectFlowError('invalid_worker_result')
            self.selected_run_id = run_id
            self.selected_export_id = None
            self.observation = None
            self.snapshot = report
            return self._publish()

    def select_export(self, export_id: str):
        with self._guard:
            self._require_open()
            if type(export_id) is not str:
                raise ProjectFlowError('unknown_export')
            row = next((item for item in self.snapshot['exports']
                        if item['export_id'] == export_id), None)
            if row is None:
                raise ProjectFlowError('unknown_export')
            # An export belongs to one immutable run. Never display run B's
            # report while operating on run A's saved workbook.
            if self.selected_run_id is None or row['run_id'] != self.selected_run_id:
                raise ProjectFlowError('export_run_mismatch')
            self.selected_export_id = export_id
            self.observation = None
            return self._publish()

    def prepare(self, filename='strategy-summary.xlsx'):
        with self._guard:
            self._require_open()
            if self.selected_run_id is None:
                raise ProjectFlowError('run_selection_required')
            if self.selected_export_id is None:
                if any(row['run_id'] == self.selected_run_id and row['filename'] == filename
                       for row in self.snapshot['exports']):
                    raise ProjectFlowError('select_existing_request')
                self.selected_export_id = str(uuid4())
            result = self._operation('prepare_export', run_id=self.selected_run_id,
                                     export_id=self.selected_export_id, output_name=filename)
            if result.get('export_id') != self.selected_export_id or result.get('audited_success') is True:
                raise ProjectFlowError('invalid_preparation')
            self.snapshot = self._operation('inspect', run_id=self.selected_run_id)['snapshot']
            return self._publish()

    def resume(self):
        with self._guard:
            self._require_open()
            if self.selected_export_id is None:
                raise ProjectFlowError('export_selection_required')
            self._operation('resume_export', export_id=self.selected_export_id)
            self.snapshot = self._operation('inspect', run_id=self.selected_run_id)['snapshot']
            return self._publish()

    def observe(self):
        with self._guard:
            self._require_open()
            if self.selected_export_id is None:
                raise ProjectFlowError('export_selection_required')
            result = self._operation('observe_export', export_id=self.selected_export_id)
            self.observation = result
            return self._publish()

    def _build_state(self):
        data = self.snapshot
        return {
                'project': None if self.project is None else {
                    'project_id': str(self.project.identifier), 'name': self.project.name,
                    'location': str(self.project.root)},
                'runs': [] if data is None else data['runs'],
                'selected_run_id': self.selected_run_id,
                'report': None if data is None else data['report'],
                'exports': [] if data is None else data['exports'],
                'selected_export_id': self.selected_export_id,
                'observation': self.observation,
                'operation_state': self.operation_state,
                'operation_error': self.operation_error,
                'source_retrieval_verified': False,
                'gui_acceptance': False,
                'production_adoption_approved': False,
            }

    def _publish(self):
        # Publish a complete immutable-by-convention read-model reference only
        # after each bounded operation. Never hold the work lock on a GUI read.
        self._public_state = self._build_state()
        return self.state()

    def state(self):
        # No RLock acquisition on the interface/event-loop thread while a
        # worker is still running. Snapshots are replaced, never mutated.
        return dict(self._public_state)

    def close(self):
        with self._guard:
            if not self._closed:
                self._closed = True
                self._worker.close(grace_seconds=0, kill_seconds=2)
