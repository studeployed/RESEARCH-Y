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
from research_y.projects import (MANIFEST_FILENAME, ProjectFormatError, ProjectVersionError,
                                  _parse_manifest, create_project, open_project)
from research_y.export_files import Directory, ExportFileError
from tools.gui_feasibility.native_folder_selection import (
    NativeFolderError, checked_folder)
from tools.gui_feasibility.recent_projects import RecentProjects, RecentProjectsError


class ProjectFlowError(ValueError):
    """Static code only. Never echo source content, private paths or exceptions."""


class RealProjectFlow:
    def __init__(self, *, selected_root: Path, selected_parent: Path,
                 recent_parent: Path | None = None):
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
        # External folders are transient, host-selected, explicitly confirmed.
        # The audit journal stores directory identity, not the path.
        self._external_candidate = None
        self._external_candidate_identity = None
        self._external_confirmed = None
        self._external_confirmed_identity = None
        self._recent_index = None
        self._recent_items = []
        self._recent_error = None
        if recent_parent is not None:
            try:
                self._recent_index = RecentProjects(recent_parent)
                self._recent_items = self._recent_index.items()
            except RecentProjectsError:
                # Corrupt launcher history never blocks work or silently resets.
                self._recent_error = 'recent_history_unavailable'
        self._public_state = self._build_state()

    def _require_no_unresolved_selection(self):
        if self._closed:
            raise ProjectFlowError('flow_closed')
        if self._pending_export_id is not None:
            raise ProjectFlowError('export_reconciliation_required')

    def _clear_external(self):
        # A file observation is tied to a specific confirmed directory at an
        # instant in time. Never carry success across a destination change.
        self.observation = None
        self._external_candidate = None
        self._external_candidate_identity = None
        self._external_confirmed = None
        self._external_confirmed_identity = None

    @staticmethod
    def _checked_external_identity(path: Path):
        try:
            with Directory(path) as target:
                return target.identity
        except (ExportFileError, OSError, ValueError, TypeError):
            raise ProjectFlowError('external_destination_changed') from None

    def _remember_project(self, project):
        if self._recent_index is None:
            return
        try:
            self._recent_items = self._recent_index.record(project)
            self._recent_error = None
        except RecentProjectsError:
            self._recent_items = []
            self._recent_error = 'recent_history_unavailable'

    def refresh_recents(self):
        """Explicit refresh; never search arbitrary locations on the disk."""
        with self._guard:
            if self._closed:
                raise ProjectFlowError('flow_closed')
            if self._recent_index is None:
                raise ProjectFlowError('recent_history_unavailable')
            try:
                self._recent_items = self._recent_index.items()
                self._recent_error = None
            except RecentProjectsError:
                self._recent_items = []
                self._recent_error = 'recent_history_unavailable'
            return self._publish()

    def open_recent(self, project_id: str):
        """Look up one host-stored ID, then verify directory and real UUID."""
        with self._guard:
            self._require_no_unresolved_selection()
            if self._recent_index is None or self._recent_error:
                raise ProjectFlowError('recent_history_unavailable')
            try:
                entry = self._recent_index.get(project_id)
            except RecentProjectsError as exc:
                raise ProjectFlowError(str(exc)) from None
            try:
                folder = self._validated_host_directory(Path(entry['location']))
                with Directory(folder):
                    manifest_path = folder / MANIFEST_FILENAME
                    if manifest_path.is_symlink():
                        raise ProjectFlowError('recent_project_unavailable')
                    # Critical: open_project may migrate an older supported
                    # database. Compare its canonical manifest UUID first,
                    # so a stale/tampered recent entry cannot mutate a
                    # different project's database or create migration backup.
                    manifest_id, _, _ = _parse_manifest(manifest_path)
                    if str(manifest_id) != entry['project_id']:
                        raise ProjectFlowError('recent_project_identity_mismatch')
                    # Core project validation compares the manifest with the
                    # SQLite identity before it performs any migrations.
                    project = open_project(folder)
            except ProjectFlowError as exc:
                if str(exc) == 'recent_project_identity_mismatch':
                    raise
                raise ProjectFlowError('recent_project_unavailable') from None
            except ProjectVersionError:
                raise ProjectFlowError('unsupported_project_version') from None
            except (ProjectFormatError, OSError, ValueError, TypeError):
                raise ProjectFlowError('recent_project_unavailable') from None
            if str(project.identifier) != entry['project_id']:
                raise ProjectFlowError('recent_project_identity_mismatch')
            self._set_project(project)
            self._root = folder
            self._remember_project(project)
            return self._publish()

    def _require_open(self):
        if self._closed:
            raise ProjectFlowError('flow_closed')
        if self.project is None:
            raise ProjectFlowError('project_not_open')

    def _operation(self, name, **kwargs):
        self._require_open()
        return self._operation_for_project(self.project, name, **kwargs)

    def _operation_for_project(self, project, name, **kwargs):
        """Run a worker against an explicit candidate without switching state."""
        command = ApplicationCommand.for_project(project, name, **kwargs)
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
        # The candidate is not active until its actual read model passes the
        # supervised inspection. Otherwise a failed switch leaves the host
        # pointed at project B while the displayed snapshot still describes A.
        # This also protects freshly created projects: never erase the new
        # folder merely because opening its initial inspection failed.
        inspected = self._operation_for_project(project, 'inspect')
        snapshot = inspected.get('snapshot')
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('runs'), list) or not isinstance(snapshot.get('exports'), list):
            raise ProjectFlowError('invalid_worker_result')
        self.project = project
        self.selected_run_id = None
        self.selected_export_id = None
        self._pending_export_id = None
        self.observation = None
        self.retained_export_report = None
        self._clear_external()
        self.last_result = inspected
        self.snapshot = snapshot
        return self._publish()

    def open_selected(self):
        """The trusted launcher may select a folder OR a project.ryproj file."""
        with self._guard:
            self._require_no_unresolved_selection()
            try:
                project = open_project(self._root)
            except ProjectVersionError:
                raise ProjectFlowError('unsupported_project_version') from None
            except (ProjectFormatError, OSError, ValueError, TypeError):
                raise ProjectFlowError('invalid_project') from None
            self._set_project(project)
            self._remember_project(project)
            return self._publish()

    def create_selected(self, name: str):
        """Create in the current host-selected parent; name alone is browser text."""
        try:
            return self.create_native_parent(self._parent, name)
        except ProjectFlowError as exc:
            if str(exc) in ('native_selection_invalid', 'native_selection_unsafe'):
                raise ProjectFlowError('project_creation_failed') from None
            raise

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
            self._set_project(project)
            self._root = path
            self._remember_project(project)
            return self._publish()

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
            self._set_project(project)
            self._parent = path
            self._root = project.root
            self._remember_project(project)
            return self._publish()

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
            self._clear_external()
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
            self._clear_external()
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

    def offer_external_directory(self, selected: Path):
        """Accept only the trusted native/host folder selection, not browser text.

        Selecting alone is not permission to write. The user must explicitly
        confirm the candidate; no path is written to the project or history.
        """
        with self._guard:
            self._require_no_unresolved_selection()
            self._require_open()
            if self.selected_run_id is None:
                raise ProjectFlowError('run_selection_required')
            if self.selected_export_id is not None:
                row = self._selected_export()
                if row['destination_kind'] != 'external':
                    raise ProjectFlowError('external_destination_not_applicable')
            path = self._validated_host_directory(selected)
            if path == self.project.root or path.is_relative_to(self.project.root):
                raise ProjectFlowError('external_destination_invalid')
            identity = self._checked_external_identity(path)
            self._clear_external()
            self._external_candidate = path
            self._external_candidate_identity = identity
            return self._publish()

    def confirm_external_directory(self):
        """Confirm a pending host-selected folder; browser cannot submit a path."""
        with self._guard:
            self._require_no_unresolved_selection()
            self._require_open()
            if self._external_candidate is None:
                raise ProjectFlowError('external_destination_not_selected')
            path = self._validated_host_directory(self._external_candidate)
            if path == self.project.root or path.is_relative_to(self.project.root):
                raise ProjectFlowError('external_destination_invalid')
            if self._checked_external_identity(path) != self._external_candidate_identity:
                raise ProjectFlowError('external_destination_changed')
            self.observation = None
            self._external_confirmed = path
            self._external_confirmed_identity = self._external_candidate_identity
            self._external_candidate = None
            self._external_candidate_identity = None
            return self._publish()

    def clear_external_directory(self):
        with self._guard:
            self._require_no_unresolved_selection()
            self._require_open()
            self._clear_external()
            return self._publish()

    def _selected_export(self):
        """Reconcile a previously committed ID when the cached inventory lags.

        A worker can commit the preparation receipt but a following inspection
        can fail. Do not strand that request or create a new one merely because
        the cached snapshot predates the commit.
        """
        row = next((row for row in self.snapshot['exports']
                    if row['export_id'] == self.selected_export_id), None)
        if row is None:
            if self._reinspect():
                row = next((item for item in self.snapshot['exports']
                            if item['export_id'] == self.selected_export_id), None)
            if row is None:
                raise ProjectFlowError('export_reconciliation_required')
        if row['run_id'] != self.selected_run_id:
            raise ProjectFlowError('export_run_mismatch')
        return row

    def _export_directory(self, *, required=True):
        if self._external_candidate is not None:
            raise ProjectFlowError('external_destination_confirmation_required')
        if self.selected_export_id is not None:
            kind = self._selected_export()['destination_kind']
            if kind == 'project_exports':
                if self._external_confirmed is not None:
                    raise ProjectFlowError('external_destination_not_applicable')
                return None
            if kind != 'external':
                raise ProjectFlowError('invalid_export_destination')
            if self._external_confirmed is None and required:
                raise ProjectFlowError('external_destination_confirmation_required')
        if self._external_confirmed is not None:
            if (self._checked_external_identity(self._external_confirmed)
                    != self._external_confirmed_identity):
                raise ProjectFlowError('external_destination_changed')
        return None if self._external_confirmed is None else str(self._external_confirmed)

    def prepare(self, filename=None):
        with self._guard:
            self._require_open()
            if self.selected_run_id is None:
                raise ProjectFlowError('run_selection_required')
            directory = self._export_directory()
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
                identity_args = ({} if directory is None else
                                 {'expected_directory_identity': self._external_confirmed_identity})
                result = self._operation('prepare_export', run_id=self.selected_run_id,
                                         export_id=export_id, output_name=filename,
                                         directory=directory, **identity_args)
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
                directory = self._export_directory()
                self._operation('resume_export', export_id=self.selected_export_id,
                                directory=directory)
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
                directory = self._export_directory()
                self._operation('cancel_export', export_id=self.selected_export_id,
                                directory=directory)
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
                # Missing external reconfirmation remains an honest observation
                # of confirmation-required, never audited file success.
                directory = self._export_directory(required=False)
                self.observation = self._operation('observe_export',
                                                    export_id=self.selected_export_id,
                                                    directory=directory)
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
                'export_reconciliation_required': (
                    self._pending_export_id is not None or
                    (self.selected_export_id is not None and data is not None
                     and not any(row['export_id'] == self.selected_export_id
                                 for row in data['exports']))),
                'observation': self.observation,
                'retained_export_report': self.retained_export_report,
                'operation_state': self.operation_state,
                'operation_error': self.operation_error,
                'source_retrieval_verified': False,
                'recent_projects': list(self._recent_items),
                'recent_history_error': self._recent_error,
                'external_destination_candidate': (
                    None if self._external_candidate is None
                    else str(self._external_candidate)),
                'external_destination_confirmed': self._external_confirmed is not None,
                'external_destination_location': (
                    None if self._external_confirmed is None
                    else str(self._external_confirmed)),
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
