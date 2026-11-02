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
from research_y.export_files import Directory
from tools.gui_feasibility.native_folder_selection import (
    NativeFolderError, checked_folder)


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
        # A worker may die after committing the prepared receipt but before replying.
        # Retain the UUID privately until authoritative inspection reconciles it.
        self._pending_export_id = None
        self.operation_state = 'idle'
        self.operation_error = None
        self.last_result = None
        self.observation = None
        self.retained_export_report = None
        self._public_state = self._build_state()

    def _require_no_unresolved_selection(self):
        if self._closed:
            raise ProjectFlowError('flow_closed')
        if self._pending_export_id is not None:
            raise ProjectFlowError('export_reconciliation_required')

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
                # The spawned worker authenticates these fixed service/worker codes.
                # Keep real recovery reasons without exposing raw file errors.
                raise ProjectFlowError(state.error or 'worker_' + state.state)
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
        self._pending_export_id = None
        self.observation = None
        self.retained_export_report = None
        self.last_result = None
        self.snapshot = self._operation('inspect')['snapshot']
        return self._publish()

    def open_selected(self):
        """The existing launcher selected this location, not a browser request."""
        return self.open_native_folder(self._root)

    def create_selected(self, name: str):
        """Create in the current host-selected parent; name alone is browser text."""
        return self.create_native_parent(self._parent, name)

    @staticmethod
    def _validated_host_directory(selected: Path) -> Path:
        # The raw native dialog result is never passed through an HTTP route.
        # Revalidate before a service call: the folder could change after
        # the dialog closed. A Directory handle additionally anchors/locks
        # the project path while its manifest/database is opened.
        if not isinstance(selected, Path):
            raise ProjectFlowError('native_selection_invalid')
        try:
            path = checked_folder((str(selected),))
        except NativeFolderError as exc:
            raise ProjectFlowError(str(exc)) from None
        if path is None:
            raise ProjectFlowError('native_selection_invalid')
        return path

    def open_native_folder(self, selected: Path):
        """Open only an OS/launcher-selected existing folder on the host."""
        with self._guard:
            self._require_no_unresolved_selection()
            path = self._validated_host_directory(selected)
            try:
                with Directory(path):
                    project = open_project(path)
            except ProjectVersionError:
                raise ProjectFlowError('unsupported_project_version') from None
            except (ProjectFormatError, OSError, ValueError, TypeError):
                raise ProjectFlowError('invalid_project') from None
            state = self._set_project(project)
            self._root = path
            return state

    def create_native_parent(self, selected: Path, name: str):
        """Create exclusively in a host-selected parent, never a browser path."""
        with self._guard:
            self._require_no_unresolved_selection()
            path = self._validated_host_directory(selected)
            try:
                with Directory(path):
                    project = create_project(path, name)
            except (OSError, ValueError, TypeError):
                raise ProjectFlowError('project_creation_failed') from None
            state = self._set_project(project)
            self._parent = path
            self._root = project.root
            return state

    def select_run(self, run_id: str):
        with self._guard:
            self._require_open()
            if self._pending_export_id is not None:
                raise ProjectFlowError('export_reconciliation_required')
            if type(run_id) is not str or run_id not in {r['run_id'] for r in self.snapshot['runs']}:
                raise ProjectFlowError('unknown_run')
            report = self._operation('inspect', run_id=run_id)['snapshot']
            if report.get('selected_run_id') != run_id or report.get('report') is None:
                raise ProjectFlowError('invalid_worker_result')
            self.selected_run_id = run_id
            self.selected_export_id = None
            self.observation = None
            self.retained_export_report = None
            self.snapshot = report
            return self._publish()

    def select_export(self, export_id: str):
        with self._guard:
            self._require_open()
            if self._pending_export_id is not None:
                raise ProjectFlowError('export_reconciliation_required')
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
            retained = self._operation('export_report', export_id=export_id)
            if retained.get('run', {}).get('run_id') != self.selected_run_id:
                raise ProjectFlowError('retained_report_run_mismatch')
            self.selected_export_id = export_id
            self.retained_export_report = retained
            self.observation = None
            return self._publish()

    def _reinspect(self):
        """Best-effort inventory after a failed worker; never invent a receipt."""
        try:
            self.snapshot = self._operation('inspect', run_id=self.selected_run_id)['snapshot']
            return True
        except ProjectFlowError:
            return False

    def prepare(self, filename=None):
        with self._guard:
            self._require_open()
            if self.selected_run_id is None:
                raise ProjectFlowError('run_selection_required')
            if filename is None:
                filename = 'strategy-summary-' + self.selected_run_id + '.xlsx'
            if self.selected_export_id is None:
                if self._pending_export_id is None:
                    if any(row['run_id'] == self.selected_run_id and row['filename'] == filename
                           for row in self.snapshot['exports']):
                        raise ProjectFlowError('select_existing_request')
                    self._pending_export_id = str(uuid4())
                export_id = self._pending_export_id
            else:
                export_id = self.selected_export_id
            # A previous verified observation must not survive new work.
            self.observation = None
            self._publish()
            try:
                result = self._operation('prepare_export', run_id=self.selected_run_id,
                                         export_id=export_id, output_name=filename)
                if result.get('export_id') != export_id or result.get('audited_success') is True:
                    raise ProjectFlowError('invalid_preparation')
            except ProjectFlowError:
                # A lost response is NOT proof the receipt failed to commit.
                # Reconcile this exact ID with the authoritative journal first.
                if self._reinspect():
                    if any(row['export_id'] == export_id for row in self.snapshot['exports']):
                        self.selected_export_id = export_id
                    self._pending_export_id = None
                # On inspection failure retain the tentative UUID for a safe retry.
                self._publish()
                raise
            self.selected_export_id = export_id
            self._pending_export_id = None
            try:
                self.snapshot = self._operation('inspect', run_id=self.selected_run_id)['snapshot']
                retained = self._operation('export_report', export_id=export_id)
                if retained.get('run', {}).get('run_id') != self.selected_run_id:
                    raise ProjectFlowError('retained_report_run_mismatch')
                self.retained_export_report = retained
                return self._publish()
            except ProjectFlowError:
                # The preparation receipt is already committed: preserve the ID.
                self._publish()
                raise

    def resume(self):
        with self._guard:
            self._require_open()
            if self.selected_export_id is None:
                raise ProjectFlowError('export_selection_required')
            self.observation = None
            self._publish()
            try:
                self._operation('resume_export', export_id=self.selected_export_id)
                self.snapshot = self._operation('inspect', run_id=self.selected_run_id)['snapshot']
                return self._publish()
            except ProjectFlowError:
                # A failed publish may leave a new durable failure/phase receipt.
                self._reinspect()
                self._publish()
                raise

    def cancel(self):
        with self._guard:
            self._require_open()
            if self.selected_export_id is None:
                raise ProjectFlowError('export_selection_required')
            self.observation = None
            self._publish()
            try:
                self._operation('cancel_export', export_id=self.selected_export_id)
                self.snapshot = self._operation('inspect', run_id=self.selected_run_id)['snapshot']
                return self._publish()
            except ProjectFlowError:
                self._reinspect()
                self._publish()
                raise

    def observe(self):
        with self._guard:
            self._require_open()
            if self.selected_export_id is None:
                raise ProjectFlowError('export_selection_required')
            # A previous file observation is time-specific; never display it as
            # a new verification while an observation is pending or has failed.
            self.observation = None
            self._publish()
            try:
                self.observation = self._operation('observe_export',
                                                    export_id=self.selected_export_id)
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

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
                'export_reconciliation_required': self._pending_export_id is not None,
                'observation': self.observation,
                'retained_export_report': self.retained_export_report,
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
