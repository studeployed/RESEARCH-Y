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
from research_y.application_worker import ApplicationWorker, ApplicationWorkerError
from research_y.projects import (MANIFEST_FILENAME, ProjectFormatError, ProjectVersionError,
                                  _parse_manifest, create_project, open_project)
from research_y.export_files import Directory, ExportFileError
from tools.gui_feasibility.native_folder_selection import (
    NativeFolderError, checked_folder)
from tools.gui_feasibility.recent_projects import RecentProjects, RecentProjectsError
from tools.gui_feasibility.pubmed_host_profile import PubMedHostProfile
from tools.gui_feasibility.wos_host_profile import WoSHostProfile
from tools.gui_feasibility.strategy_setup import StrategyDraft, DraftError
from research_y.preflight_review import (
    PreflightError, _review_payload, PRESS_ITEMS, read_preflight,
)
from research_y.query_compiler import QueryCompilationError


class ProjectFlowError(ValueError):
    """Static code only. Never echo source content, private paths or exceptions."""


class RealProjectFlow:
    def __init__(self, *, selected_root: Path, selected_parent: Path,
                 recent_parent: Path | None = None,
                 pubmed_profile: PubMedHostProfile | None = None,
                  wos_profile: WoSHostProfile | None = None):
        self._root = Path(selected_root)
        self._parent = Path(selected_parent)
        if not self._root.is_absolute() or not self._parent.is_absolute():
            raise ProjectFlowError('trusted_selection_required')
        if pubmed_profile is not None and type(pubmed_profile) is not PubMedHostProfile:
            raise ProjectFlowError('pubmed_profile_invalid')
        if wos_profile is not None and type(wos_profile) is not WoSHostProfile:
            raise ProjectFlowError('wos_profile_invalid')
        self._pubmed_profile = pubmed_profile
        self._wos_profile = wos_profile
        self._guard = threading.RLock()
        self._worker = ApplicationWorker()
        # Separate supervised process: verification may run longer than
        # ordinary 35-second inspection operations. Durable checkpoint
        # progress remains readable via the independent ordinary worker.
        self._verify_worker = ApplicationWorker()
        # PubMed ESearch may need long, separately supervised partition work.
        # Read-only progress remains possible through the ordinary worker.
        self._pubmed_source_worker = ApplicationWorker()
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
        self._setup = StrategyDraft()
        # Stable until the authoritative run inventory confirms a commit.
        # On worker interruption, every retry carries the same exact snapshot.
        self._pending_admission_id = None
        self._pending_admission_payload = None
        self._last_strategy_admission = None
        self._preflight = None
        self._review_candidate = None
        self._pending_review = None
        self._pilot_candidate = None
        self._pending_pilot = None
        self._last_pilot = None
        self._wos_pilot_candidate = None
        self._pending_wos_pilot = None
        self._last_wos_pilot = None
        self._wos_acquisition_offer = None
        self._wos_acquisition_prepare_pending = None
        self._wos_acquisition = None
        self._wos_acquisition_tick_offer = None
        self._wos_acquisition_tick_pending = None
        self._verify_operation_id = None
        self._verify_offer = None
        self._verify_pending = None
        self._verify_worker_state = 'idle'
        self._verify_error = None
        self._verify_last_outcome = None
        self._pubmed_source_offer = None
        self._pubmed_source_pending = None
        self._pubmed_source_operation_id = None
        self._pubmed_source = None
        self._pubmed_source_worker_state = 'idle'
        self._pubmed_source_worker_error = None
        self._pubmed_source_last_outcome = None
        self._pilot_history = None
        self._pilot_history_error = None
        self._saved_pilot_detail = None
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

    def _require_no_unresolved_selection(self, *, for_external_choice=False):
        if self._closed:
            raise ProjectFlowError('flow_closed')
        if self._pending_admission_id is not None:
            raise ProjectFlowError('strategy_reconciliation_required')
        if self._pending_review is not None:
            raise ProjectFlowError('preflight_reconciliation_required')
        if self._pending_pilot is not None or self._pending_wos_pilot is not None:
            raise ProjectFlowError('pilot_reconciliation_required')
        if (self._wos_acquisition_prepare_pending is not None or
                self._wos_acquisition_tick_pending is not None):
            raise ProjectFlowError('acquisition_reconciliation_required')
        if self._verify_pending is not None:
            raise ProjectFlowError('verification_reconciliation_required')
        if self._pubmed_source_pending is not None:
            raise ProjectFlowError('pubmed_source_reconciliation_required')
        if self._pending_export_id is not None:
            if not for_external_choice:
                raise ProjectFlowError('export_reconciliation_required')
            # A host-side folder change cannot silently retarget a committed
            # request. First consult the journal for the original pending UUID.
            # Only the no-receipt case may change folder using that *same* ID.
            self._reconcile_pending_before_destination()

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
        self._setup = StrategyDraft()
        self._pending_admission_id = None
        self._pending_admission_payload = None
        self._last_strategy_admission = None
        self._preflight = None
        self._review_candidate = None
        self._pending_review = None
        self._pilot_candidate = None
        self._pending_pilot = None
        self._last_pilot = None
        self._wos_pilot_candidate = None
        self._pending_wos_pilot = None
        self._last_wos_pilot = None
        self._wos_acquisition_offer = None
        self._wos_acquisition_prepare_pending = None
        self._wos_acquisition = None
        self._wos_acquisition_tick_offer = None
        self._wos_acquisition_tick_pending = None
        self._verify_operation_id = None
        self._verify_offer = None
        self._verify_pending = None
        self._verify_worker_state = 'idle'
        self._verify_error = None
        self._verify_last_outcome = None
        self._pubmed_source_offer = None
        self._pubmed_source_pending = None
        self._pubmed_source_operation_id = None
        self._pubmed_source = None
        self._pubmed_source_worker_state = 'idle'
        self._pubmed_source_worker_error = None
        self._pubmed_source_last_outcome = None
        self._pilot_history = None
        self._pilot_history_error = None
        self._saved_pilot_detail = None
        self._clear_external()
        self.last_result = inspected
        self.snapshot = snapshot
        # A source pilot may have been journalled by an earlier GUI session.
        # Read its current receipt history without touching either provider.
        # If history is damaged, preserve access to the project/workbooks but
        # show an explicit warning instead of assuming it contains no pilots.
        try:
            self.inspect_pilot_history()
        except ProjectFlowError:
            self._pilot_history = None
            self._pilot_history_error = 'pilot_history_unavailable'
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
            self._require_no_unresolved_selection()
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
            self._preflight = None
            self._review_candidate = None
            self._pilot_candidate = None
            self._last_pilot = None
            self._wos_pilot_candidate = None
            self._last_wos_pilot = None
            self._wos_acquisition_offer = None
            self._wos_acquisition = None
            self._wos_acquisition_tick_offer = None
            self._verify_offer = None
            self._verify_last_outcome = None
            self._pubmed_source_offer = None
            self._pubmed_source = None
            self._pubmed_source_last_outcome = None
            self.snapshot = report
            return self._publish()

    def select_export(self, export_id: str):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
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

    # Research Setup draft controls. The only persistence boundary is the
    # explicit Confirm approval action below. There is no network action here.
    _SETUP_ACTIONS = {
        'heading': 'update_heading',
        'revise_preview': 'revise_preview',
        'add_group': 'add_group',
        'rename_group': 'rename_group',
        'remove_group': 'remove_group',
        'move_group': 'move_group',
        'add_term': 'add_term',
        'edit_term': 'edit_term',
        'remove_term': 'remove_term',
        'move_term': 'move_term',
    }

    def edit_setup(self, action: str, data: dict):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if (type(action) is not str or action not in self._SETUP_ACTIONS
                    or type(data) is not dict):
                raise ProjectFlowError('invalid_setup_action')
            try:
                method = getattr(self._setup, self._SETUP_ACTIONS[action])
                method(**data)
            except (DraftError, ValueError, TypeError):
                raise ProjectFlowError('invalid_setup_input') from None
            self._last_strategy_admission = None
            return self._publish()

    def preview_setup(self):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            try:
                self._setup.preview()
            except (DraftError, QueryCompilationError, ValueError, TypeError):
                raise ProjectFlowError('strategy_preview_invalid') from None
            return self._publish()

    def approve_setup(self):
        """Only the explicit user-facing approval click invokes this method.

        A lost worker reply retains the original approved terms and request ID;
        the next click replays *exactly* those, without double-approving.
        """
        with self._guard:
            self._require_open()
            if self._pending_export_id is not None:
                raise ProjectFlowError('export_reconciliation_required')
            if self._pending_review is not None:
                raise ProjectFlowError('preflight_reconciliation_required')
            if self._pending_pilot is not None or self._pending_wos_pilot is not None:
                raise ProjectFlowError('pilot_reconciliation_required')
            if (self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None):
                raise ProjectFlowError('acquisition_reconciliation_required')
            if self._verify_pending is not None:
                raise ProjectFlowError('verification_reconciliation_required')
            if self._pubmed_source_pending is not None:
                raise ProjectFlowError('pubmed_source_reconciliation_required')
            if self._pending_admission_id is None:
                if self._setup.preview_data is None:
                    raise ProjectFlowError('strategy_preview_required')
                self._pending_admission_id = str(uuid4())
                self._pending_admission_payload = dict(
                    admission_theme=self._setup.theme,
                    admission_approved_by=self._setup.approved_by,
                    admission_groups=self._setup.approved_groups(),
                    approval_confirmed=True,
                )
            request_id = self._pending_admission_id
            payload = self._pending_admission_payload
            self._publish()
            try:
                result = self._operation('admit_strategy',
                    admission_request_id=request_id, **payload)
                if (result.get('request_id') != request_id
                        or result.get('query_count', 0) < 2
                        or result.get('source_retrieval_verified') is not False):
                    raise ProjectFlowError('invalid_admission_receipt')
                # Inspection is authoritative; a successful-looking worker
                # response alone does not clear an uncertain mutation.
                inspected = self._operation(
                    'inspect', run_id=self.selected_run_id)['snapshot']
                # A new approval may be created while viewing an older run.
                # Keep that old selection/report/export coherent; the new run
                # is available separately, never automatically selected.
                if (not isinstance(inspected, dict)
                        or inspected.get('selected_run_id') != self.selected_run_id
                        or not any(row['run_id'] == result['run_id']
                                   and row['strategy_version_id'] ==
                                       result['strategy_version_id']
                                   for row in inspected.get('runs', []))):
                    raise ProjectFlowError('admission_reconciliation_required')
                self.snapshot = inspected
                self._last_strategy_admission = {
                    'strategy_version_id': result['strategy_version_id'],
                    'version_number': result['version_number'],
                    'run_id': result['run_id'],
                    'query_count': result['query_count'],
                    'source_retrieval_verified': False,
                }
                self._pending_admission_id = None
                self._pending_admission_payload = None
                self._setup = StrategyDraft()
                # No implicit run selection or source execution.
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

    def inspect_preflight(self):
        """Explicit worker read of one frozen run, not an execution trigger."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self.selected_run_id is None:
                raise ProjectFlowError('run_selection_required')
            result = self._operation('preflight_read', run_id=self.selected_run_id)
            if (result.get('run_id') != self.selected_run_id
                    or result.get('source_retrieval_verified') is not False
                    or result.get('execution_authorized') is not False):
                raise ProjectFlowError('invalid_worker_result')
            self._preflight = result
            self._review_candidate = None
            # A pilot confirmation always has to show the current plan, not
            # silently retain an old candidate after reinspection.
            self._pilot_candidate = None
            self._wos_pilot_candidate = None
            return self._publish()

    def offer_preflight_review(self, *, reviewer_name, reviewer_role,
                               press_items, review_note='', known_relevant=()):
        """Host owns a previewed, immutable candidate; offering is not a write."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self.selected_run_id is None or self._preflight is None:
                raise ProjectFlowError('preflight_inspection_required')
            try:
                review_id = str(uuid4())
                candidate = _review_payload(
                    review_id, self.selected_run_id, self._preflight['plan_sha256'],
                    reviewer_name=reviewer_name, reviewer_role=reviewer_role,
                    press_items=press_items, review_note=review_note,
                    known_relevant=known_relevant)
            except PreflightError:
                raise ProjectFlowError('preflight_review_invalid') from None
            self._review_candidate = candidate
            return self._publish()

    def revise_preflight_review(self):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            self._review_candidate = None
            return self._publish()

    def record_preflight_review(self):
        """Confirm the displayed candidate; retain exact ID and data on failure."""
        with self._guard:
            self._require_open()
            if (self._pending_admission_id is not None or
                    self._pending_export_id is not None or
                    self._pending_pilot is not None or
                    self._pending_wos_pilot is not None or
                    self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None or
                    self._verify_pending is not None or
                    self._pubmed_source_pending is not None):
                raise ProjectFlowError('operation_reconciliation_required')
            if self._pending_review is None:
                if self._review_candidate is None or self._preflight is None:
                    raise ProjectFlowError('preflight_confirmation_required')
                self._pending_review = dict(self._review_candidate)
            candidate = self._pending_review
            self._publish()
            try:
                reply = self._operation(
                    'preflight_record', run_id=candidate['run_id'],
                    review_id=candidate['review_id'],
                    review_plan_sha256=candidate['plan_sha256'],
                    review_reviewer_name=candidate['reviewer_name'],
                    review_reviewer_role=candidate['reviewer_role'],
                    review_items=dict(candidate['press_items']),
                    review_note=candidate['review_note'],
                    review_known_relevant=tuple(candidate['known_relevant']))
                if (reply.get('review_id') != candidate['review_id']
                        or reply.get('plan_sha256') != candidate['plan_sha256']
                        or reply.get('execution_authorized') is not False):
                    raise ProjectFlowError('invalid_review_receipt')
                verified = self._operation(
                    'preflight_read', run_id=candidate['run_id'],
                    review_id=candidate['review_id'])
                receipt = verified.get('requested_review')
                # A different reviewer may have appended a newer receipt
                # between this commit and inspection. Verify our *original*
                # immutable UUID and every submitted field instead of wrongly
                # requiring it to remain the latest journal entry.
                if (verified.get('plan_sha256') != candidate['plan_sha256']
                        or not isinstance(receipt, dict)
                        or any(receipt.get(key) != value
                               for key, value in candidate.items())
                        or receipt.get('execution_authorized') is not False):
                    raise ProjectFlowError('preflight_reconciliation_required')
                self._preflight = verified
                self._review_candidate = None
                self._pending_review = None
                return self._publish()
            except ProjectFlowError:
                # A lost reply could follow a durable audit insert. Preserve
                # original content and idempotency key until authoritative read.
                self._publish()
                raise

    def offer_pubmed_pilot(self, query_id: str):
        """Display one stored exact PubMed query without contacting NCBI.

        The query ID comes from an authenticated GUI control but is verified
        against the current storage-backed preflight and selected run. No
        browser-selected arbitrary term or contact/key is accepted.
        """
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self._pubmed_profile is None:
                raise ProjectFlowError('pubmed_profile_unavailable')
            if self.selected_run_id is None or self._preflight is None:
                raise ProjectFlowError('preflight_inspection_required')
            if type(query_id) is not str:
                raise ProjectFlowError('unknown_pubmed_query')
            verified = self._operation('preflight_read',
                                       run_id=self.selected_run_id)
            if (verified.get('plan_sha256') != self._preflight.get('plan_sha256')
                    or verified.get('run_id') != self.selected_run_id
                    or verified.get('source_retrieval_verified') is not False
                    or verified.get('execution_authorized') is not False):
                raise ProjectFlowError('stale_preflight')
            matches = [q for source in verified.get('sources', [])
                       if source.get('source_name') == 'pubmed'
                       for q in source.get('queries', [])
                       if q.get('query_id') == query_id and
                       q.get('status') == 'pending']
            if len(matches) != 1 or type(matches[0].get('exact_query')) is not str:
                raise ProjectFlowError('unknown_pubmed_query')
            candidate = dict(
                pilot_id=str(uuid4()), run_id=self.selected_run_id,
                query_id=query_id, group_id=matches[0]['group_id'],
                plan_sha256=verified['plan_sha256'],
                exact_query=matches[0]['exact_query'],
            )
            self._preflight = verified
            self._pilot_candidate = candidate
            self._wos_pilot_candidate = None
            return self._publish()

    def revise_pubmed_pilot(self):
        """Dismissing an unconfirmed pilot never creates a source request."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            self._pilot_candidate = None
            return self._publish()

    def confirm_pubmed_pilot(self):
        """The separate confirmation is the *only* network-capable GUI action.

        Any uncertain worker result locks the UUID. Reconciliation below is
        read-only and never resubmits a count request or invents a zero count.
        """
        with self._guard:
            self._require_open()
            if self._pending_pilot is not None or self._pending_wos_pilot is not None:
                raise ProjectFlowError('pilot_reconciliation_required')
            if (self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None):
                raise ProjectFlowError('acquisition_reconciliation_required')
            if self._verify_pending is not None:
                raise ProjectFlowError('verification_reconciliation_required')
            if self._pubmed_source_pending is not None:
                raise ProjectFlowError('pubmed_source_reconciliation_required')
            if (self._pending_admission_id is not None or
                    self._pending_review is not None or
                    self._pending_export_id is not None):
                raise ProjectFlowError('operation_reconciliation_required')
            if self._pubmed_profile is None:
                raise ProjectFlowError('pubmed_profile_unavailable')
            candidate = self._pilot_candidate
            if (not isinstance(candidate, dict) or
                    candidate.get('run_id') != self.selected_run_id):
                raise ProjectFlowError('pilot_confirmation_required')
            self._pending_pilot = dict(candidate)
            self._publish()
            try:
                reply = self._operation('pubmed_pilot_count',
                    run_id=candidate['run_id'], pilot_id=candidate['pilot_id'],
                    pilot_query_id=candidate['query_id'],
                    pilot_plan_sha256=candidate['plan_sha256'],
                    pilot_contact_email=self._pubmed_profile.contact_email,
                    pilot_api_key=self._pubmed_profile.api_key,
                    pilot_confirmed=True)
                if (reply.get('pilot_id') != candidate['pilot_id'] or
                        reply.get('run_id') != candidate['run_id'] or
                        reply.get('query_id') != candidate['query_id'] or
                        reply.get('plan_sha256') != candidate['plan_sha256'] or
                        reply.get('source_retrieval_verified') is not False or
                        reply.get('execution_authorized') is not False):
                    raise ProjectFlowError('pilot_receipt_invalid')
            except ProjectFlowError:
                # A request receipt may have committed before a worker error.
                # Do not call the count operation again on this attempt.
                self._publish()
                raise
            return self.reconcile_pubmed_pilot()

    def reconcile_pubmed_pilot(self):
        """Read original attempt by UUID; NEVER submit a second provider call."""
        with self._guard:
            self._require_open()
            candidate = self._pending_pilot
            if candidate is None:
                raise ProjectFlowError('pilot_reconciliation_not_required')
            try:
                response = self._operation('pubmed_pilot_read',
                                           pilot_id=candidate['pilot_id'])
                if (response.get('source_retrieval_verified') is not False
                        or 'pilot' not in response):
                    raise ProjectFlowError('pilot_receipt_invalid')
                observed = response['pilot']
                if observed is None:
                    # The supervised worker is terminal; a missing durable
                    # request receipt means no network request could occur.
                    # Permit a NEW explicitly confirmed attempt, never an
                    # automatic retry of the old UUID.
                    self._last_pilot = dict(
                        pilot_id=candidate['pilot_id'],
                        run_id=candidate['run_id'],
                        query_id=candidate['query_id'],
                        status='not_recorded', reported_matches=None,
                        source_retrieval_verified=False,
                        execution_authorized=False, search_completed=False)
                else:
                    if (type(observed) is not dict or
                            any(observed.get(key) != candidate[key]
                                for key in ('pilot_id','run_id','query_id',
                                            'plan_sha256','exact_query')) or
                            observed.get('source_retrieval_verified') is not False
                            or observed.get('execution_authorized') is not False
                            or observed.get('search_completed') is not False
                            or observed.get('retrieval_verified') is not False
                            or observed.get('count_only') is not True
                            or observed.get('automatically_retryable') is not False):
                        raise ProjectFlowError('pilot_receipt_invalid')
                    self._last_pilot = observed
                self._pending_pilot = None
                self._pilot_candidate = None
                return self._publish()
            except ProjectFlowError:
                # Read failures remain uncertain. Retain the original ID and
                # prevent project/run changes until the read succeeds.
                self._publish()
                raise

    def offer_wos_pilot(self, query_id: str, *, revalidate_quota=False):
        """Preview a current, source-backed Starter Topic query without network."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self._wos_profile is None:
                raise ProjectFlowError('wos_profile_unavailable')
            if type(revalidate_quota) is not bool:
                raise ProjectFlowError('pilot_confirmation_required')
            if self.selected_run_id is None or self._preflight is None:
                raise ProjectFlowError('preflight_inspection_required')
            if type(query_id) is not str:
                raise ProjectFlowError('unknown_wos_query')
            verified = self._operation('preflight_read',
                                       run_id=self.selected_run_id)
            if (verified.get('plan_sha256') != self._preflight.get('plan_sha256')
                    or verified.get('run_id') != self.selected_run_id
                    or verified.get('source_retrieval_verified') is not False
                    or verified.get('execution_authorized') is not False):
                raise ProjectFlowError('stale_preflight')
            matches = [q for source in verified.get('sources', [])
                       if source.get('source_name') == 'wos'
                       for q in source.get('queries', [])
                       if q.get('query_id') == query_id and
                       q.get('status') == 'pending']
            if len(matches) != 1 or type(matches[0].get('exact_query')) is not str:
                raise ProjectFlowError('unknown_wos_query')
            candidate = dict(
                pilot_id=str(uuid4()), run_id=self.selected_run_id,
                query_id=query_id, group_id=matches[0]['group_id'],
                plan_sha256=verified['plan_sha256'],
                exact_query=matches[0]['exact_query'],
                revalidate_quota=revalidate_quota,
            )
            self._preflight = verified
            self._wos_pilot_candidate = candidate
            self._pilot_candidate = None
            return self._publish()

    def revise_wos_pilot(self):
        """Cancel an unsent offer without reserving or consuming any quota."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            self._wos_pilot_candidate = None
            return self._publish()

    def confirm_wos_pilot(self):
        """The ONLY network-capable Starter GUI action.

        Preserve one UUID until inspecting its immutable receipt, even when
        the worker response is lost or the service rejects the attempt.
        """
        with self._guard:
            self._require_open()
            if self._pending_pilot is not None or self._pending_wos_pilot is not None:
                raise ProjectFlowError('pilot_reconciliation_required')
            if (self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None):
                raise ProjectFlowError('acquisition_reconciliation_required')
            if self._verify_pending is not None:
                raise ProjectFlowError('verification_reconciliation_required')
            if self._pubmed_source_pending is not None:
                raise ProjectFlowError('pubmed_source_reconciliation_required')
            if (self._pending_admission_id is not None or
                    self._pending_review is not None or
                    self._pending_export_id is not None):
                raise ProjectFlowError('operation_reconciliation_required')
            if self._wos_profile is None:
                raise ProjectFlowError('wos_profile_unavailable')
            candidate = self._wos_pilot_candidate
            if (not isinstance(candidate, dict) or
                    candidate.get('run_id') != self.selected_run_id):
                raise ProjectFlowError('pilot_confirmation_required')
            self._pending_wos_pilot = dict(candidate)
            self._publish()
            try:
                reply = self._operation('wos_pilot_sample',
                    run_id=candidate['run_id'], pilot_id=candidate['pilot_id'],
                    pilot_query_id=candidate['query_id'],
                    pilot_plan_sha256=candidate['plan_sha256'],
                    pilot_api_key=self._wos_profile.api_key,
                    pilot_confirmed=True,
                    pilot_wos_revalidate_quota=candidate['revalidate_quota'])
                if (any(reply.get(key) != candidate[key] for key in
                        ('pilot_id','run_id','query_id','plan_sha256',
                         'exact_query','revalidate_quota')) or
                        reply.get('source') != 'wos' or
                        reply.get('sample_only') is not True or
                        reply.get('count_only') is not False or
                        reply.get('bibliographic_records_persisted') != 0 or
                        reply.get('source_retrieval_verified') is not False or
                        reply.get('execution_authorized') is not False):
                    raise ProjectFlowError('pilot_receipt_invalid')
            except ProjectFlowError:
                self._publish()
                raise
            return self.reconcile_wos_pilot()

    def reconcile_wos_pilot(self):
        """Read-only original attempt inspection; never repeat a Starter GET."""
        with self._guard:
            self._require_open()
            candidate = self._pending_wos_pilot
            if candidate is None:
                raise ProjectFlowError('pilot_reconciliation_not_required')
            try:
                response = self._operation('wos_pilot_read',
                                           pilot_id=candidate['pilot_id'])
                if (response.get('source_retrieval_verified') is not False
                        or 'pilot' not in response):
                    raise ProjectFlowError('pilot_receipt_invalid')
                observed = response['pilot']
                if observed is None:
                    self._last_wos_pilot = dict(
                        pilot_id=candidate['pilot_id'],
                        run_id=candidate['run_id'],
                        query_id=candidate['query_id'],
                        revalidate_quota=candidate['revalidate_quota'],
                        status='not_recorded', reported_matches=None,
                        source_retrieval_verified=False,
                        execution_authorized=False, search_completed=False)
                else:
                    if (type(observed) is not dict or
                            any(observed.get(key) != candidate[key] for key in
                                ('pilot_id','run_id','query_id','plan_sha256',
                                 'exact_query','revalidate_quota')) or
                            observed.get('source') != 'wos' or
                            observed.get('sample_only') is not True or
                            observed.get('count_only') is not False or
                            observed.get('bibliographic_records_persisted') != 0 or
                            observed.get('source_retrieval_verified') is not False or
                            observed.get('execution_authorized') is not False or
                            observed.get('search_completed') is not False or
                            observed.get('retrieval_verified') is not False or
                            observed.get('automatically_retryable') is not False):
                        raise ProjectFlowError('pilot_receipt_invalid')
                    self._last_wos_pilot = observed
                self._pending_wos_pilot = None
                self._wos_pilot_candidate = None
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

    # Explicit durable WoS retrieval, distinct from transient sample pilots.
    def offer_wos_acquisition(self, query_id: str):
        """Preview an untouched source even after another group has progressed.

        The worker reconstructs the original complete broad-OR frozen plan
        without treating mutable sibling counts/statuses as preflight results.
        It checks that this particular query is still pending.
        """
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self._wos_profile is None:
                raise ProjectFlowError('wos_profile_unavailable')
            if self.selected_run_id is None or self.snapshot is None:
                raise ProjectFlowError('run_selection_required')
            allowed = {q['query_id'] for q in self.snapshot['report']['queries']
                       if q['source_name']=='wos' and q['status']=='pending'}
            if type(query_id) is not str or query_id not in allowed:
                raise ProjectFlowError('unknown_wos_query')
            verified = self._operation(
                'wos_acquisition_preview',run_id=self.selected_run_id,
                acquisition_query_id=query_id)
            if (verified.get('run_id') != self.selected_run_id or
                    verified.get('query_id') != query_id or
                    verified.get('source_retrieval_verified') is not False or
                    verified.get('no_network_requests') is not True):
                raise ProjectFlowError('source_plan_unverified')
            if (self._preflight is not None and
                    verified.get('plan_sha256') != self._preflight.get('plan_sha256')):
                raise ProjectFlowError('stale_preflight')
            if verified.get('checkpoint_exists') is True:
                # The query may still say pending even though a different
                # CLI/manual workflow already created a durable checkpoint.
                # Inspect it as historical read-only evidence rather than
                # mistakenly entering an unfinishable GUI-retention offer.
                existing = self._operation('wos_acquisition_read',
                    run_id=self.selected_run_id,
                    acquisition_query_id=query_id)
                if (existing.get('run_id') != self.selected_run_id or
                        existing.get('query_id') != query_id or
                        existing.get('exact_query') != verified['exact_query'] or
                        existing.get('no_network_requests') is not True or
                        existing.get('source_retrieval_verified') is not False):
                    raise ProjectFlowError('acquisition_receipt_invalid')
                self._wos_acquisition = existing
                self._wos_acquisition_offer = None
                self._wos_acquisition_tick_offer = None
                return self._publish()
            if verified.get('checkpoint_exists') is not False:
                raise ProjectFlowError('source_plan_unverified')
            self._wos_acquisition_offer = dict(
                run_id=self.selected_run_id,query_id=query_id,
                group_id=verified['group_id'],
                exact_query=verified['exact_query'],
                plan_sha256=verified['plan_sha256'])
            self._wos_pilot_candidate = None
            self._pilot_candidate = None
            return self._publish()

    def dismiss_wos_acquisition(self):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            self._wos_acquisition_offer = None
            return self._publish()

    def confirm_wos_acquisition(self):
        """Commit retention consent without sending ANY provider request."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self._wos_acquisition_offer is None:
                raise ProjectFlowError('retention_confirmation_required')
            candidate = dict(self._wos_acquisition_offer)
            self._wos_acquisition_prepare_pending = candidate
            self._publish()
            try:
                reply = self._operation('wos_acquisition_prepare',
                    run_id=candidate['run_id'],
                    acquisition_query_id=candidate['query_id'],
                    acquisition_plan_sha256=candidate['plan_sha256'],
                    acquisition_confirmed=True,
                    acquisition_retention_authorized=True)
                if (reply.get('run_id') != candidate['run_id'] or
                        reply.get('query_id') != candidate['query_id'] or
                        reply.get('exact_query') != candidate['exact_query'] or
                        reply.get('preflight_sha256') != candidate['plan_sha256'] or
                        reply.get('approved_gui_retention') is not True or
                        reply.get('no_network_requests') is not True or
                        reply.get('source_retrieval_verified') is not False):
                    raise ProjectFlowError('acquisition_receipt_invalid')
            except ProjectFlowError:
                self._publish()
                raise
            return self.reconcile_wos_acquisition()

    def reconcile_wos_acquisition(self):
        """Read original stored query plan, NEVER repeat the consent write."""
        with self._guard:
            self._require_open()
            candidate = self._wos_acquisition_prepare_pending
            if candidate is None:
                raise ProjectFlowError('acquisition_reconciliation_not_required')
            try:
                response = self._operation('wos_acquisition_read',
                    run_id=candidate['run_id'],
                    acquisition_query_id=candidate['query_id'])
                if (response.get('run_id') != candidate['run_id'] or
                        response.get('query_id') != candidate['query_id'] or
                        response.get('exact_query') != candidate['exact_query'] or
                        response.get('no_network_requests') is not True or
                        response.get('source_retrieval_verified') is not False):
                    raise ProjectFlowError('acquisition_receipt_invalid')
                if (response.get('approved_gui_retention') is False and
                        response.get('preflight_sha256') is None):
                    # A competing CLI/manual checkpoint may have appeared
                    # after the offline GUI preview. The original immutable
                    # ledger is now view-only, not GUI-authorised. This
                    # safe conflict disposition clears the stale pending UI
                    # state without creating another job or sending HTTP.
                    self._wos_acquisition = response
                    self._wos_acquisition_prepare_pending = None
                    self._wos_acquisition_offer = None
                    return self._publish()
                if (response.get('approved_gui_retention') is not True or
                        response.get('preflight_sha256') != candidate['plan_sha256']):
                    raise ProjectFlowError('acquisition_receipt_invalid')
                self._wos_acquisition = response
                self._wos_acquisition_prepare_pending = None
                self._wos_acquisition_offer = None
                return self._publish()
            except ProjectFlowError as exc:
                if str(exc) == 'unknown_checkpoint':
                    # No durable plan exists, and preparing never sends HTTP.
                    # A fresh explicit consent may prepare a new checkpoint.
                    self._wos_acquisition_prepare_pending = None
                    self._wos_acquisition_offer = None
                    self._wos_acquisition = None
                    return self._publish()
                self._publish()
                raise

    def inspect_stored_wos_acquisition(self, query_id: str):
        """Read an existing checkpoint after restarting GUI or selecting a run."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self.selected_run_id is None or type(query_id) is not str:
                raise ProjectFlowError('run_selection_required')
            allowed = {q['query_id'] for q in self.snapshot['report']['queries']
                       if q['source_name'] == 'wos'}
            if query_id not in allowed:
                raise ProjectFlowError('unknown_wos_query')
            read = self._operation('wos_acquisition_read',
                run_id=self.selected_run_id, acquisition_query_id=query_id)
            if (read.get('run_id') != self.selected_run_id or
                    read.get('query_id') != query_id or
                    read.get('no_network_requests') is not True or
                    read.get('source_retrieval_verified') is not False):
                raise ProjectFlowError('acquisition_receipt_invalid')
            self._wos_acquisition = read
            self._wos_acquisition_offer = None
            self._wos_acquisition_tick_offer = None
            return self._publish()

    def offer_wos_acquisition_tick(self, *, revalidate_quota=False):
        """Preview the maximum two provider requests; clicking does not send."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self._wos_profile is None:
                raise ProjectFlowError('wos_profile_unavailable')
            if type(revalidate_quota) is not bool:
                raise ProjectFlowError('session_confirmation_required')
            state = self._wos_acquisition
            if (not isinstance(state, dict) or
                    state['run_id'] != self.selected_run_id):
                raise ProjectFlowError('acquisition_selection_required')
            verified = self._operation('wos_acquisition_read',
                run_id=state['run_id'],
                acquisition_query_id=state['query_id'])
            if (verified.get('approved_gui_retention') is not True or
                    verified.get('preflight_sha256') != state['preflight_sha256'] or
                    verified.get('source_retrieval_verified') is not False):
                raise ProjectFlowError('gui_admission_missing')
            job = verified['checkpoint']
            if job['worker_active'] is True or job['requests_unknown'] > 0:
                raise ProjectFlowError('acquisition_worker_recovery_required')
            if job['enumeration_reconciled'] is True or job['status'] == 'cancelled':
                raise ProjectFlowError('acquisition_already_terminal')
            if (job['pages_expected'] is not None and job['pages_expected'] > 1
                    and job['stage'] in ('verify','final')):
                raise ProjectFlowError('verification_requires_long_worker')
            self._wos_acquisition = verified
            self._verify_offer = None
            self._wos_acquisition_tick_offer = dict(
                run_id=verified['run_id'], query_id=verified['query_id'],
                preflight_sha256=verified['preflight_sha256'],
                revalidate_quota=revalidate_quota)
            return self._publish()

    def dismiss_wos_acquisition_tick(self):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            self._wos_acquisition_tick_offer = None
            return self._publish()

    def confirm_wos_acquisition_tick(self):
        """Single-use explicit provider session, not a background loop."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            candidate = self._wos_acquisition_tick_offer
            if candidate is None or candidate['run_id'] != self.selected_run_id:
                raise ProjectFlowError('session_confirmation_required')
            self._wos_acquisition_tick_pending = dict(candidate)
            self._wos_acquisition_tick_offer = None  # Double click cannot re-authorise.
            self._publish()
            try:
                reply = self._operation('wos_acquisition_tick',
                    run_id=candidate['run_id'],
                    acquisition_query_id=candidate['query_id'],
                    acquisition_confirmed=True,
                    acquisition_revalidate_quota=candidate['revalidate_quota'],
                    acquisition_api_key=self._wos_profile.api_key)
                if (reply.get('run_id') != candidate['run_id'] or
                        reply.get('query_id') != candidate['query_id'] or
                        reply.get('preflight_sha256') != candidate['preflight_sha256'] or
                        reply.get('source_retrieval_verified') is not False or
                        reply.get('max_next_session_requests') != 3):
                    raise ProjectFlowError('acquisition_receipt_invalid')
            except ProjectFlowError:
                self._publish()
                raise
            return self.reconcile_wos_acquisition_tick()

    def reconcile_wos_acquisition_tick(self):
        """Inspect original durable progress; never resend an unknown request."""
        with self._guard:
            self._require_open()
            candidate = self._wos_acquisition_tick_pending
            if candidate is None:
                raise ProjectFlowError('acquisition_reconciliation_not_required')
            try:
                read = self._operation('wos_acquisition_read',
                    run_id=candidate['run_id'],
                    acquisition_query_id=candidate['query_id'])
                if (read.get('run_id') != candidate['run_id'] or
                        read.get('query_id') != candidate['query_id'] or
                        read.get('preflight_sha256') != candidate['preflight_sha256'] or
                        read.get('approved_gui_retention') is not True or
                        read.get('source_retrieval_verified') is not False or
                        read.get('no_network_requests') is not True):
                    raise ProjectFlowError('acquisition_receipt_invalid')
                self._wos_acquisition = read
                if read['checkpoint']['worker_active']:
                    raise ProjectFlowError('acquisition_worker_recovery_required')
                self.snapshot = self._operation('inspect',
                                                run_id=self.selected_run_id)['snapshot']
                self._preflight = None  # Pending pre-run plan is now obsolete.
                self._pilot_candidate = None
                self._wos_pilot_candidate = None
                self._wos_acquisition_tick_pending = None
                return self._publish()
            except ProjectFlowError:
                # A killed worker may still have a durable reservation.
                # Keep the original pending state; only inspect, never retry.
                self._publish()
                raise

    def offer_wos_verification(self, *, revalidate_quota=False):
        """Read exact verification workload; no provider requests or keys."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self._wos_profile is None:
                raise ProjectFlowError('wos_profile_unavailable')
            if type(revalidate_quota) is not bool:
                raise ProjectFlowError('session_confirmation_required')
            source = self._wos_acquisition
            if (type(source) is not dict or
                    source.get('run_id') != self.selected_run_id or
                    source.get('approved_gui_retention') is not True):
                raise ProjectFlowError('acquisition_selection_required')
            preview = self._operation('wos_acquisition_verify_plan',
                run_id=source['run_id'],acquisition_query_id=source['query_id'])
            if (preview.get('run_id') != self.selected_run_id or
                    preview.get('query_id') != source['query_id'] or
                    preview.get('preflight_sha256') != source['preflight_sha256'] or
                    preview.get('exact_query') != source['exact_query'] or
                    preview.get('source_retrieval_verified') is not False or
                    preview.get('no_network_requests') is not True or
                    preview.get('whole_search_verified') is not False or
                    type(preview.get('pages_to_verify')) is not int or
                    type(preview.get('expected_requests')) is not int or
                    preview['expected_requests'] != preview['pages_to_verify'] + 2 or
                    not 3 <= preview['expected_requests'] <= 512):
                raise ProjectFlowError('verification_plan_invalid')
            self._verify_offer = dict(preview, revalidate_quota=revalidate_quota)
            self._wos_acquisition_tick_offer = None
            self._pilot_candidate = None
            self._wos_pilot_candidate = None
            return self._publish()

    def dismiss_wos_verification(self):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            self._verify_offer = None
            return self._publish()

    def confirm_wos_verification(self):
        """Spawn ONE approved long session; return immediately to the GUI."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            offer = self._verify_offer
            if (self._wos_profile is None or offer is None or
                    offer.get('run_id') != self.selected_run_id):
                raise ProjectFlowError('session_confirmation_required')
            # Never authorise a stale query/page count after user review.
            fresh = self._operation('wos_acquisition_verify_plan',
                run_id=offer['run_id'],
                acquisition_query_id=offer['query_id'])
            if any(fresh.get(key) != offer.get(key) for key in
                    ('run_id', 'query_id', 'exact_query', 'preflight_sha256',
                     'pages_to_verify', 'expected_requests')):
                raise ProjectFlowError('verification_plan_changed')
            cmd = ApplicationCommand.for_project(
                self.project, 'wos_acquisition_verify',
                run_id=offer['run_id'],
                acquisition_query_id=offer['query_id'],
                acquisition_plan_sha256=offer['preflight_sha256'],
                acquisition_confirmed=True,
                acquisition_revalidate_quota=offer['revalidate_quota'],
                acquisition_api_key=self._wos_profile.api_key,
                verification_expected_requests=offer['expected_requests'])
            try:
                operation_id = self._verify_worker.submit(cmd)
            except ApplicationWorkerError as exc:
                raise ProjectFlowError(exc.code) from None
            self._verify_pending = dict(offer)
            self._verify_operation_id = operation_id
            self._verify_offer = None
            self._verify_worker_state = 'running'
            self._verify_error = None
            self._verify_last_outcome = None
            return self._publish()

    def poll_wos_verification(self):
        """Nonblocking supervisor status plus independent durable progress read.

        A running response is never treated as completed source retrieval.
        """
        with self._guard:
            self._require_open()
            if self._verify_pending is None or self._verify_operation_id is None:
                raise ProjectFlowError('verification_reconciliation_not_required')
            try:
                status = self._verify_worker.poll(self._verify_operation_id)
            except ApplicationWorkerError as exc:
                raise ProjectFlowError(exc.code) from None
            self._verify_worker_state = status.state
            self._verify_error = status.error
            pending = self._verify_pending
            try:
                read = self._operation('wos_acquisition_read',
                    run_id=pending['run_id'],
                    acquisition_query_id=pending['query_id'])
                if (read.get('run_id') != pending['run_id'] or
                        read.get('query_id') != pending['query_id'] or
                        read.get('preflight_sha256') != pending['preflight_sha256'] or
                        read.get('approved_gui_retention') is not True or
                        read.get('no_network_requests') is not True or
                        read.get('source_retrieval_verified') is not False):
                    raise ProjectFlowError('verification_receipt_invalid')
                self._wos_acquisition = read
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

    def pause_wos_verification(self):
        """Request a durable cooperative pause; the owner may still be active."""
        with self._guard:
            self._require_open()
            if self._verify_pending is None or self._verify_operation_id is None:
                raise ProjectFlowError('verification_reconciliation_not_required')
            status = self._verify_worker.poll(self._verify_operation_id)
            if status.state != 'running':
                raise ProjectFlowError('verification_worker_not_running')
            pending = self._verify_pending
            read = self._operation('wos_acquisition_pause',
                run_id=pending['run_id'],
                acquisition_query_id=pending['query_id'])
            if (read.get('run_id') != pending['run_id'] or
                    read.get('query_id') != pending['query_id'] or
                    read.get('approved_gui_retention') is not True or
                    read.get('source_retrieval_verified') is not False):
                raise ProjectFlowError('verification_receipt_invalid')
            self._wos_acquisition = read
            return self._publish()

    def reconcile_wos_verification(self):
        """Verify stopped supervised process AND original checkpoint evidence.

        A lost result, active ownership or unknown HTTP attempt never releases
        the GUI lock or causes an implicit retry.
        """
        with self._guard:
            self._require_open()
            pending = self._verify_pending
            if pending is None or self._verify_operation_id is None:
                raise ProjectFlowError('verification_reconciliation_not_required')
            try:
                status = self._verify_worker.poll(self._verify_operation_id)
            except ApplicationWorkerError as exc:
                raise ProjectFlowError(exc.code) from None
            if status.state == 'running':
                raise ProjectFlowError('verification_worker_still_running')
            self._verify_worker_state = status.state
            self._verify_error = status.error
            try:
                read = self._operation('wos_acquisition_read',
                    run_id=pending['run_id'],
                    acquisition_query_id=pending['query_id'])
                if (read.get('run_id') != pending['run_id'] or
                        read.get('query_id') != pending['query_id'] or
                        read.get('preflight_sha256') != pending['preflight_sha256'] or
                        read.get('approved_gui_retention') is not True or
                        read.get('no_network_requests') is not True or
                        read.get('source_retrieval_verified') is not False):
                    raise ProjectFlowError('verification_receipt_invalid')
                job = read['checkpoint']
                if job['worker_active'] is True or job['requests_unknown'] != 0:
                    raise ProjectFlowError('verification_worker_recovery_required')
                if status.state == 'returned':
                    receipt = status.result()
                    if (type(receipt) is not dict or
                            receipt.get('run_id') != pending['run_id'] or
                            receipt.get('query_id') != pending['query_id'] or
                            receipt.get('preflight_sha256') != pending['preflight_sha256'] or
                            receipt.get('expected_requests') != pending['expected_requests'] or
                            receipt.get('whole_search_verified') is not False or
                            receipt.get('source_retrieval_verified') is not False or
                            receipt.get('provider_snapshot_guaranteed') is not False or
                            receipt.get('actual_checkpoint') != job or
                            receipt.get('enumeration_reconciled') != job['enumeration_reconciled'] or
                            type(receipt.get('session_requests_made')) is not int or
                            not 0 <= receipt['session_requests_made'] <= pending['expected_requests']):
                        raise ProjectFlowError('verification_receipt_invalid')
                    spent = receipt['session_requests_made']
                elif status.state in ('failed', 'interrupted'):
                    spent = None
                else:
                    raise ProjectFlowError('verification_receipt_invalid')
                self._wos_acquisition = read
                self.snapshot = self._operation(
                    'inspect',run_id=self.selected_run_id)['snapshot']
                self._preflight = None
                self._pilot_candidate = None
                self._wos_pilot_candidate = None
                self._verify_last_outcome = dict(
                    worker_state=status.state, worker_error=status.error,
                    run_id=pending['run_id'], query_id=pending['query_id'],
                    requests_made=spent,
                    enumeration_reconciled=job['enumeration_reconciled'],
                    durable_source_status=job['status'],
                    whole_search_verified=False,
                    source_retrieval_verified=False)
                self._verify_pending = None
                self._verify_operation_id = None
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

    # PubMed source identifier collection, distinct from count-only pilots.
    def inspect_stored_pubmed_source(self, query_id: str):
        """Read original identifier checkpoint, even without an API profile."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self.selected_run_id is None or type(query_id) is not str:
                raise ProjectFlowError('run_selection_required')
            allowed = {q['query_id'] for q in self.snapshot['report']['queries']
                       if q['source_name']=='pubmed'}
            if query_id not in allowed:
                raise ProjectFlowError('unknown_pubmed_query')
            read = self._operation('pubmed_identifier_read',
                run_id=self.selected_run_id,pubmed_source_query_id=query_id)
            if (read.get('run_id') != self.selected_run_id or
                    read.get('query_id') != query_id or
                    read.get('no_network_requests') is not True or
                    read.get('source_retrieval_verified') is not False or
                    read.get('metadata_complete') is not False):
                raise ProjectFlowError('pubmed_receipt_invalid')
            self._pubmed_source = read
            self._pubmed_source_offer = None
            return self._publish()

    def offer_pubmed_source(self, query_id: str, *,
                            coverage_start: str, coverage_end: str):
        """Exact frozen OR source and explicitly selected partition coverage."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            if self._pubmed_profile is None:
                raise ProjectFlowError('pubmed_profile_unavailable')
            if self.selected_run_id is None or type(query_id) is not str:
                raise ProjectFlowError('run_selection_required')
            from research_y.pubmed_source_gui import _window
            try:
                _window(coverage_start,coverage_end)
            except ValueError:
                raise ProjectFlowError('pubmed_coverage_invalid') from None
            allowed = {q['query_id'] for q in self.snapshot['report']['queries']
                       if q['source_name']=='pubmed'}
            if query_id not in allowed:
                raise ProjectFlowError('unknown_pubmed_query')
            preview = self._operation('pubmed_identifier_preview',
                run_id=self.selected_run_id,pubmed_source_query_id=query_id)
            if (preview.get('run_id') != self.selected_run_id or
                    preview.get('query_id') != query_id or
                    preview.get('source_retrieval_verified') is not False or
                    preview.get('no_network_requests') is not True or
                    preview.get('whole_search_verified') is not False or
                    preview.get('max_session_requests') != 128 or
                    preview.get('page_size') != 200 or
                    preview.get('max_partition_count_probes') != 100):
                raise ProjectFlowError('pubmed_plan_unverified')
            saved = preview['checkpoint']
            if (saved is not None and
                    saved['status']=='identifiers_reconciled_metadata_pending'):
                raise ProjectFlowError('pubmed_query_not_ready')
            if (saved is not None and saved.get('coverage') is not None and
                    saved['coverage'] != {'start':coverage_start,'end':coverage_end}):
                raise ProjectFlowError('pubmed_coverage_changed')
            self._pubmed_source_offer = dict(
                run_id=self.selected_run_id,query_id=query_id,
                exact_query=preview['exact_query'],
                group_id=preview['group_id'],plan_sha256=preview['plan_sha256'],
                coverage_start=coverage_start,coverage_end=coverage_end,
                checkpoint=saved,max_session_requests=128)
            self._pilot_candidate = None
            self._wos_pilot_candidate = None
            self._wos_acquisition_offer = None
            self._wos_acquisition_tick_offer = None
            return self._publish()

    def dismiss_pubmed_source(self):
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            self._pubmed_source_offer = None
            return self._publish()

    def confirm_pubmed_source(self):
        """One explicit bounded ESearch session; return without blocking UI."""
        with self._guard:
            self._require_open()
            self._require_no_unresolved_selection()
            candidate = self._pubmed_source_offer
            if self._pubmed_profile is None or candidate is None:
                raise ProjectFlowError('pubmed_session_confirmation_required')
            if candidate['run_id'] != self.selected_run_id:
                raise ProjectFlowError('pubmed_plan_unverified')
            fresh = self._operation('pubmed_identifier_preview',
                run_id=candidate['run_id'],pubmed_source_query_id=candidate['query_id'])
            if (fresh.get('run_id') != candidate['run_id'] or
                    fresh.get('query_id') != candidate['query_id'] or
                    fresh.get('plan_sha256') != candidate['plan_sha256'] or
                    fresh.get('exact_query') != candidate['exact_query'] or
                    fresh.get('checkpoint') != candidate['checkpoint'] or
                    fresh.get('source_retrieval_verified') is not False or
                    fresh.get('no_network_requests') is not True):
                raise ProjectFlowError('pubmed_plan_unverified')
            command = ApplicationCommand.for_project(
                self.project,'pubmed_identifier_run',
                run_id=candidate['run_id'],
                pubmed_source_query_id=candidate['query_id'],
                pubmed_source_plan_sha256=candidate['plan_sha256'],
                pubmed_coverage_start=candidate['coverage_start'],
                pubmed_coverage_end=candidate['coverage_end'],
                pubmed_source_confirmed=True,
                pubmed_source_contact_email=self._pubmed_profile.contact_email,
                pubmed_source_api_key=self._pubmed_profile.api_key)
            try:
                operation_id = self._pubmed_source_worker.submit(command)
            except ApplicationWorkerError as exc:
                raise ProjectFlowError(exc.code) from None
            self._pubmed_source_pending = dict(candidate)
            self._pubmed_source_operation_id = operation_id
            self._pubmed_source_offer = None
            self._pubmed_source_worker_state = 'running'
            self._pubmed_source_worker_error = None
            self._pubmed_source_last_outcome = None
            return self._publish()

    def poll_pubmed_source(self):
        """Passive checkpoint read during retrieval; never calls PubMed."""
        with self._guard:
            self._require_open()
            pending = self._pubmed_source_pending
            if pending is None or self._pubmed_source_operation_id is None:
                raise ProjectFlowError('pubmed_source_reconciliation_not_required')
            try:
                status = self._pubmed_source_worker.poll(
                    self._pubmed_source_operation_id)
            except ApplicationWorkerError as exc:
                raise ProjectFlowError(exc.code) from None
            self._pubmed_source_worker_state = status.state
            self._pubmed_source_worker_error = status.error
            try:
                read = self._operation('pubmed_identifier_read',
                    run_id=pending['run_id'],
                    pubmed_source_query_id=pending['query_id'])
                if (read.get('run_id') != pending['run_id'] or
                        read.get('query_id') != pending['query_id'] or
                        read.get('exact_query') != pending['exact_query'] or
                        read.get('source_retrieval_verified') is not False or
                        read.get('whole_search_verified') is not False or
                        read.get('no_network_requests') is not True):
                    raise ProjectFlowError('pubmed_receipt_invalid')
                self._pubmed_source = read
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

    def pause_pubmed_source(self):
        """Request cooperative checkpoint pause, not worker termination."""
        with self._guard:
            self._require_open()
            pending = self._pubmed_source_pending
            if pending is None:
                raise ProjectFlowError('pubmed_source_reconciliation_not_required')
            status = self._pubmed_source_worker.poll(
                self._pubmed_source_operation_id)
            if status.state != 'running':
                raise ProjectFlowError('pubmed_worker_not_running')
            read = self._operation('pubmed_identifier_pause',
                run_id=pending['run_id'],
                pubmed_source_query_id=pending['query_id'])
            if (read.get('run_id') != pending['run_id'] or
                    read.get('query_id') != pending['query_id'] or
                    read.get('source_retrieval_verified') is not False or
                    read.get('no_network_requests') is not True):
                raise ProjectFlowError('pubmed_receipt_invalid')
            self._pubmed_source = read
            return self._publish()

    def reconcile_pubmed_source(self):
        """Require terminal child and compare its result to durable source data."""
        with self._guard:
            self._require_open()
            pending = self._pubmed_source_pending
            if pending is None or self._pubmed_source_operation_id is None:
                raise ProjectFlowError('pubmed_source_reconciliation_not_required')
            try:
                status = self._pubmed_source_worker.poll(
                    self._pubmed_source_operation_id)
            except ApplicationWorkerError as exc:
                raise ProjectFlowError(exc.code) from None
            if status.state == 'running':
                raise ProjectFlowError('pubmed_worker_still_running')
            self._pubmed_source_worker_state = status.state
            self._pubmed_source_worker_error = status.error
            try:
                read = self._operation('pubmed_identifier_read',
                    run_id=pending['run_id'],
                    pubmed_source_query_id=pending['query_id'])
                if (read.get('run_id') != pending['run_id'] or
                        read.get('query_id') != pending['query_id'] or
                        read.get('exact_query') != pending['exact_query'] or
                        read.get('source_retrieval_verified') is not False or
                        read.get('metadata_complete') is not False or
                        read.get('no_network_requests') is not True):
                    raise ProjectFlowError('pubmed_receipt_invalid')
                if status.state=='returned':
                    receipt=status.result()
                    if (type(receipt) is not dict or
                            receipt.get('run_id')!=pending['run_id'] or
                            receipt.get('query_id')!=pending['query_id'] or
                            receipt.get('plan_sha256')!=pending['plan_sha256'] or
                            receipt.get('source_retrieval_verified') is not False or
                            receipt.get('whole_search_verified') is not False or
                            receipt.get('metadata_complete') is not False or
                            receipt.get('checkpoint')!=read['checkpoint'] or
                            type(receipt.get('session_requests_reserved')) is not int or
                            not 0 <= receipt['session_requests_reserved'] <= 128):
                        raise ProjectFlowError('pubmed_receipt_invalid')
                    attempts = receipt['session_requests_reserved']
                elif status.state in ('interrupted','failed'):
                    attempts = None  # Do NOT claim unknown HTTP attempts were zero.
                else:
                    raise ProjectFlowError('pubmed_receipt_invalid')
                self._pubmed_source = read
                self.snapshot = self._operation(
                    'inspect',run_id=self.selected_run_id)['snapshot']
                self._preflight = None
                self._pubmed_source_last_outcome = dict(
                    run_id=pending['run_id'],query_id=pending['query_id'],
                    worker_state=status.state,worker_error=status.error,
                    requests_reserved=attempts,
                    durable_checkpoint=read['checkpoint'],
                    source_retrieval_verified=False,
                    whole_search_verified=False,metadata_complete=False)
                self._pubmed_source_pending = None
                self._pubmed_source_operation_id = None
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

    def inspect_pilot_history(self, *, before_event_id=None):
        """Read a page of prior project-wide pilot requests, no source network."""
        with self._guard:
            self._require_open()
            if before_event_id is not None:
                if (self._pilot_history is None or
                        self._pilot_history.get('next_before_event_id') != before_event_id):
                    raise ProjectFlowError('pilot_history_cursor_invalid')
            self._saved_pilot_detail = None
            try:
                history = self._operation(
                    'pilot_history', history_before_event_id=before_event_id)
                if (type(history) is not dict or
                        type(history.get('entries')) is not list or
                        type(history.get('request_events_total')) is not int or
                        history.get('no_network_requests') is not True or
                        history.get('source_retrieval_verified') is not False or
                        history.get('search_completed') is not False or
                        history.get('execution_authorized') is not False):
                    raise ProjectFlowError('pilot_history_unavailable')
                for record in history['entries']:
                    if (type(record) is not dict or
                            record.get('source') not in ('pubmed','wos') or
                            type(record.get('pilot_id')) is not str or
                            type(record.get('run_id')) is not str or
                            type(record.get('query_id')) is not str or
                            record.get('source_retrieval_verified') is not False or
                            record.get('execution_authorized') is not False or
                            record.get('search_completed') is not False):
                        raise ProjectFlowError('pilot_history_unavailable')
                self._pilot_history = history
                self._pilot_history_error = None
                return self._publish()
            except ProjectFlowError:
                self._pilot_history_error = 'pilot_history_unavailable'
                self._publish()
                raise

    def inspect_saved_pilot(self, pilot_id: str):
        """Explicit historical detail read; ID must belong to visible page."""
        with self._guard:
            self._require_open()
            history = self._pilot_history
            if (history is None or self._pilot_history_error is not None or
                    type(pilot_id) is not str):
                raise ProjectFlowError('pilot_history_unavailable')
            matched = [x for x in history['entries']
                       if x['pilot_id'] == pilot_id]
            if len(matched) != 1:
                raise ProjectFlowError('unknown_pilot')
            row = matched[0]
            operation = ('pubmed_pilot_read' if row['source'] == 'pubmed'
                         else 'wos_pilot_read')
            self._saved_pilot_detail = None
            self._publish()
            try:
                response = self._operation(operation, pilot_id=pilot_id)
                detail = response.get('pilot')
                if (response.get('source_retrieval_verified') is not False or
                        type(detail) is not dict or
                        any(detail.get(k) != row[k] for k in
                            ('pilot_id','run_id','query_id',
                             'status','reported_matches','requested_at_utc')) or
                        detail.get('source_retrieval_verified') is not False or
                        detail.get('retrieval_verified') is not False or
                        detail.get('search_completed') is not False or
                        detail.get('execution_authorized') is not False or
                        detail.get('automatically_retryable') is not False or
                        detail.get('count_only') is not row['count_only']):
                    raise ProjectFlowError('pilot_history_stale')
                if row['source'] == 'wos' and (
                        detail.get('source') != 'wos' or
                        detail.get('sample_only') is not True or
                        detail.get('bibliographic_records_persisted') != 0):
                    raise ProjectFlowError('pilot_history_stale')
                self._saved_pilot_detail = detail
                return self._publish()
            except ProjectFlowError:
                self._publish()
                raise

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
            self._require_no_unresolved_selection(for_external_choice=True)
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
            self._require_no_unresolved_selection(for_external_choice=True)
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
            self._require_no_unresolved_selection(for_external_choice=True)
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

    def _reconcile_pending_before_destination(self):
        """Resolve the original tentative UUID without requiring its folder.

        If the worker committed a receipt but its response and reinspection
        failed, the originally confirmed external folder may no longer exist.
        The research journal, not that path, determines whether this UUID was
        retained. Only a completed inspection can release the pending guard.
        """
        if self._pending_export_id is None:
            return
        pending_id = self._pending_export_id
        if not self._reinspect():
            self._publish()
            raise ProjectFlowError('export_reconciliation_required')
        row = next((item for item in self.snapshot['exports']
                    if item['export_id'] == pending_id), None)
        if row is not None:
            if row['run_id'] != self.selected_run_id:
                raise ProjectFlowError('export_run_mismatch')
            self.selected_export_id = pending_id
            self._pending_export_id = None
        # A definitive *absence* of a preparation receipt does not authorise
        # minting a new UUID on retry. Retain the tentative original UUID.
        # This also permits explicitly selected new folders, but only after
        # the journal has again shown no receipt for that UUID.
        self._publish()

    def prepare(self, filename=None):
        with self._guard:
            self._require_open()
            if self.selected_run_id is None:
                raise ProjectFlowError('run_selection_required')
            if self._pending_admission_id is not None:
                raise ProjectFlowError('strategy_reconciliation_required')
            if self._pending_review is not None:
                raise ProjectFlowError('preflight_reconciliation_required')
            if self._pending_pilot is not None or self._pending_wos_pilot is not None:
                raise ProjectFlowError('pilot_reconciliation_required')
            if (self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None):
                raise ProjectFlowError('acquisition_reconciliation_required')
            if self._verify_pending is not None:
                raise ProjectFlowError('verification_reconciliation_required')
            if self._pubmed_source_pending is not None:
                raise ProjectFlowError('pubmed_source_reconciliation_required')
            self._reconcile_pending_before_destination()
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
            if self._pending_pilot is not None or self._pending_wos_pilot is not None:
                raise ProjectFlowError('pilot_reconciliation_required')
            if (self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None):
                raise ProjectFlowError('acquisition_reconciliation_required')
            if self._verify_pending is not None:
                raise ProjectFlowError('verification_reconciliation_required')
            if self._pubmed_source_pending is not None:
                raise ProjectFlowError('pubmed_source_reconciliation_required')
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
            if self._pending_pilot is not None or self._pending_wos_pilot is not None:
                raise ProjectFlowError('pilot_reconciliation_required')
            if (self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None):
                raise ProjectFlowError('acquisition_reconciliation_required')
            if self._verify_pending is not None:
                raise ProjectFlowError('verification_reconciliation_required')
            if self._pubmed_source_pending is not None:
                raise ProjectFlowError('pubmed_source_reconciliation_required')
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
            if self._pending_pilot is not None or self._pending_wos_pilot is not None:
                raise ProjectFlowError('pilot_reconciliation_required')
            if (self._wos_acquisition_prepare_pending is not None or
                    self._wos_acquisition_tick_pending is not None):
                raise ProjectFlowError('acquisition_reconciliation_required')
            if self._verify_pending is not None:
                raise ProjectFlowError('verification_reconciliation_required')
            if self._pubmed_source_pending is not None:
                raise ProjectFlowError('pubmed_source_reconciliation_required')
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
                'strategy_draft': self._setup.state(),
                'strategy_reconciliation_required': self._pending_admission_id is not None,
                'last_strategy_admission': self._last_strategy_admission,
                'preflight_report': self._preflight,
                'preflight_candidate': self._review_candidate,
                'preflight_review_reconciliation_required': self._pending_review is not None,
                'pubmed_profile_configured': self._pubmed_profile is not None,
                'pubmed_pilot_candidate': self._pilot_candidate,
                'pubmed_pilot_reconciliation_required': self._pending_pilot is not None,
                'last_pubmed_pilot': self._last_pilot,
                'wos_profile_configured': self._wos_profile is not None,
                'wos_pilot_candidate': self._wos_pilot_candidate,
                'wos_pilot_reconciliation_required': self._pending_wos_pilot is not None,
                'last_wos_pilot': self._last_wos_pilot,
                'wos_acquisition_offer': self._wos_acquisition_offer,
                'wos_acquisition_prepare_pending': self._wos_acquisition_prepare_pending is not None,
                'wos_acquisition': self._wos_acquisition,
                'wos_acquisition_tick_offer': self._wos_acquisition_tick_offer,
                'wos_acquisition_tick_pending': self._wos_acquisition_tick_pending is not None,
                'wos_verification_offer': self._verify_offer,
                'wos_verification_pending': self._verify_pending is not None,
                'wos_verification_worker_state': self._verify_worker_state,
                'wos_verification_worker_error': self._verify_error,
                'wos_verification_last_outcome': self._verify_last_outcome,
                'pubmed_source_offer': self._pubmed_source_offer,
                'pubmed_source_pending': self._pubmed_source_pending is not None,
                'pubmed_source_worker_state': self._pubmed_source_worker_state,
                'pubmed_source_worker_error': self._pubmed_source_worker_error,
                'pubmed_source': self._pubmed_source,
                'pubmed_source_last_outcome': self._pubmed_source_last_outcome,
                'pilot_history': self._pilot_history,
                'pilot_history_error': self._pilot_history_error,
                'saved_pilot_detail': self._saved_pilot_detail,
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
                # Shutdown cannot fabricate completion or automatically clear
                # a durable provider reservation; recovery requires inspection.
                try:
                    try:
                        self._pubmed_source_worker.close(grace_seconds=0, kill_seconds=2)
                    finally:
                        self._verify_worker.close(grace_seconds=0, kill_seconds=2)
                finally:
                    self._worker.close(grace_seconds=0, kill_seconds=2)
