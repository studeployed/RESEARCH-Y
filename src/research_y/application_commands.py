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
                        'observe_export', 'export_report', 'admit_strategy',
                        'preflight_read', 'preflight_record',
                        'pubmed_pilot_count', 'pubmed_pilot_read',
                         'wos_pilot_sample', 'wos_pilot_read', 'pilot_history',
                         'wos_acquisition_preview', 'wos_acquisition_prepare',
                         'wos_acquisition_read', 'wos_acquisition_tick'})
SERVICE_ERRORS = frozenset({'invalid_identifier', 'invalid_evidence', 'unknown_export',
    'unknown_run', 'unsupported_export_journal', 'project_busy', 'project_unavailable',
    'render_failed', 'storage_failed', 'destination_conflict', 'artifact_changed',
    'destination_required', 'directory_changed', 'journal_failed', 'cancelled',
    'invalid_export', 'concurrent_progress_retry', 'strategy_invalid',
    'approval_required', 'invalid_request_id', 'admission_conflict',
    'admission_evidence_invalid', 'no_active_terms', 'run_not_pending',
    'plan_unverified', 'review_invalid', 'review_conflict', 'stale_preflight',
    'review_evidence_invalid',
    'pilot_confirmation_required', 'pilot_conflict',
    'pilot_evidence_invalid', 'pilot_plan_invalid', 'pilot_storage_failed',
    'pilot_client_invalid', 'pubmed_profile_invalid', 'wos_profile_invalid',
     'provider_cooldown', 'provider_quota_revalidation_required',
     'provider_worker_active', 'provider_pilot_cooldown',
     'provider_pilot_outcome_unknown', 'pilot_history_cursor_invalid',
     'source_execution_unavailable', 'source_plan_unverified',
     'retention_confirmation_required', 'session_confirmation_required',
     'gui_admission_missing', 'pending_wos_query_required',
     'checkpoint_identity_mismatch', 'strategy_identity_mismatch',
     'invalid_checkpoint_plan', 'checkpoint_write_failed',
     'worker_busy_or_interrupted', 'another_wos_worker_active',
     'local_retention_not_authorized', 'unsupported_query_parameters',
     'query_not_in_approved_compilation', 'unknown_checkpoint',
     'checkpoint_already_exists', 'verification_requires_long_worker'})


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
    # Trusted host confirmation: filesystem identity bound across the worker
    # process boundary. Never supplied by a browser request or stored in a project.
    expected_directory_identity: tuple[int, int] | None = None
    # Only the trusted host's explicit researcher-approved draft uses these
    # fields. Neither IDs nor groups can serve as a browser filesystem path.
    admission_request_id: str | None = None
    admission_theme: str | None = None
    admission_approved_by: str | None = None
    admission_groups: tuple | None = None
    approval_confirmed: bool | None = None
    # Optional pre-execution review, bound to a stored immutable run/plan.
    # These values originate only from the authenticated host GUI.
    review_id: str | None = None
    review_plan_sha256: str | None = None
    review_reviewer_name: str | None = None
    review_reviewer_role: str | None = None
    review_items: dict | None = None
    review_note: str | None = None
    review_known_relevant: tuple | None = None
    # Explicitly confirmed source pilots; contact/key come
    # from trusted Python host configuration, NEVER browser request values.
    # The core command's repr excludes *all* fields and child exceptions
    # cannot echo them. No secrets are persisted by the pilot audit service.
    pilot_id: str | None = None
    pilot_query_id: str | None = None
    pilot_plan_sha256: str | None = None
    pilot_contact_email: str | None = None
    pilot_api_key: str | None = None
    pilot_confirmed: bool | None = None
    # WoS-only explicit quota revalidation, never inferred from an HTTP error.
    pilot_wos_revalidate_quota: bool | None = None
    # Read-only audit cursor; NEVER a browser-supplied SQL expression.
    history_before_event_id: int | None = None
    # Explicit WoS source-acquisition consent. NOT a pilot; up to two HTTPS
    # requests and lawfully permitted source-metadata retention per session.
    acquisition_query_id: str | None = None
    acquisition_plan_sha256: str | None = None
    acquisition_confirmed: bool | None = None
    acquisition_retention_authorized: bool | None = None
    acquisition_revalidate_quota: bool | None = None
    acquisition_api_key: str | None = None

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
            if self.expected_directory_identity is not None:
                identity = self.expected_directory_identity
                if (self.operation != 'prepare_export' or self.directory is None
                        or type(identity) is not tuple or len(identity) != 2
                        or any(type(part) is not int or part < 0 for part in identity)):
                    raise ValueError
            admission_fields = (self.admission_request_id, self.admission_theme,
                                self.admission_approved_by, self.admission_groups,
                                self.approval_confirmed)
            review_fields = (self.review_id, self.review_plan_sha256,
                             self.review_reviewer_name, self.review_reviewer_role,
                             self.review_items, self.review_note,
                             self.review_known_relevant)
            pilot_fields = (self.pilot_id, self.pilot_query_id,
                            self.pilot_plan_sha256, self.pilot_contact_email,
                            self.pilot_api_key, self.pilot_confirmed,
                             self.pilot_wos_revalidate_quota)
            acquisition_fields = (
                self.acquisition_query_id, self.acquisition_plan_sha256,
                self.acquisition_confirmed,
                self.acquisition_retention_authorized,
                self.acquisition_revalidate_quota, self.acquisition_api_key,
            )
            if self.operation in ('pubmed_pilot_count', 'pubmed_pilot_read',
                                  'wos_pilot_sample', 'wos_pilot_read'):
                if any(v is not None for v in
                       (self.export_id, self.output_name, self.directory,
                        self.expected_directory_identity)):
                    raise ValueError
                _uuid(self.pilot_id)
                if self.operation in ('pubmed_pilot_read', 'wos_pilot_read'):
                    if self.run_id is not None or any(
                            v is not None for v in pilot_fields[1:]):
                        raise ValueError
                else:
                    _uuid(self.run_id)
                    _uuid(self.pilot_query_id)
                    digest = self.pilot_plan_sha256
                    if (type(digest) is not str or len(digest) != 64 or
                            any(c not in '0123456789abcdef' for c in digest) or
                            self.pilot_confirmed is not True):
                        raise ValueError
                    if self.operation == 'wos_pilot_sample':
                        if (self.pilot_contact_email is not None or
                                type(self.pilot_wos_revalidate_quota) is not bool):
                            raise ValueError
                        from research_y.wos_starter import WoSStarterError
                        from research_y.wos_starter_client import WoSStarterClient
                        try:
                            WoSStarterClient(api_key=self.pilot_api_key,
                                             request_budget=1)
                        except WoSStarterError:
                            raise ValueError from None
                    else:
                        if self.pilot_wos_revalidate_quota is not None:
                            raise ValueError
                        from research_y.pubmed_probe import PubMedESearchProbeClient
                        if (type(self.pilot_contact_email) is not str or
                                len(self.pilot_contact_email) > 254 or
                                not self.pilot_contact_email.isascii() or
                                any(ord(c) < 33 or ord(c) > 126
                                    for c in self.pilot_contact_email) or
                                (self.pilot_api_key is not None and
                                 (type(self.pilot_api_key) is not str or
                                  not 1 <= len(self.pilot_api_key) <= 4096 or
                                  not self.pilot_api_key.isascii() or
                                  any(ord(c) < 33 or ord(c) > 126
                                      for c in self.pilot_api_key)))):
                            raise ValueError
                        PubMedESearchProbeClient(
                            email=self.pilot_contact_email,
                            api_key=self.pilot_api_key)
            elif self.operation in (
                    'wos_acquisition_preview', 'wos_acquisition_prepare', 'wos_acquisition_read',
                    'wos_acquisition_tick'):
                if any(v is not None for v in (
                        self.export_id, self.output_name, self.directory,
                        self.expected_directory_identity)):
                    raise ValueError
                _uuid(self.run_id)
                _uuid(self.acquisition_query_id)
                if self.operation in ('wos_acquisition_read','wos_acquisition_preview'):
                    if any(v is not None for v in acquisition_fields[1:]):
                        raise ValueError
                elif self.operation == 'wos_acquisition_prepare':
                    digest = self.acquisition_plan_sha256
                    if (type(digest) is not str or len(digest) != 64 or
                            any(c not in '0123456789abcdef' for c in digest) or
                            self.acquisition_confirmed is not True or
                            self.acquisition_retention_authorized is not True or
                            self.acquisition_api_key is not None or
                            self.acquisition_revalidate_quota is not None):
                        raise ValueError
                else:
                    if (self.acquisition_plan_sha256 is not None or
                            self.acquisition_confirmed is not True or
                            self.acquisition_retention_authorized is not None or
                            type(self.acquisition_revalidate_quota) is not bool):
                        raise ValueError
                    from research_y.wos_starter_client import WoSStarterClient
                    from research_y.wos_starter import WoSStarterError
                    try:
                        WoSStarterClient(api_key=self.acquisition_api_key,
                                         request_budget=3, timeout=10)
                    except WoSStarterError:
                        raise ValueError from None
            elif self.operation == 'pilot_history':
                if any(v is not None for v in
                       (self.run_id, self.export_id, self.output_name,
                        self.directory, self.expected_directory_identity)):
                    raise ValueError
                value = self.history_before_event_id
                if value is not None and (
                        type(value) is not int or not 1 <= value <= 2**63 - 1):
                    raise ValueError
            elif self.operation in ('preflight_read', 'preflight_record'):
                if (self.run_id is None or any(v is not None for v in
                    (self.export_id, self.output_name, self.directory,
                     self.expected_directory_identity))):
                    raise ValueError
                if self.operation == 'preflight_read':
                    # The host may request one immutable receipt by UUID to
                    # reconcile it after another review has been appended.
                    if self.review_id is not None:
                        _uuid(self.review_id)
                    if any(v is not None for v in review_fields[1:]):
                        raise ValueError
                else:
                    from research_y.preflight_review import _review_payload
                    _review_payload(
                        self.review_id, self.run_id, self.review_plan_sha256,
                        reviewer_name=self.review_reviewer_name,
                        reviewer_role=self.review_reviewer_role,
                        press_items=self.review_items,
                        review_note=self.review_note,
                        known_relevant=self.review_known_relevant,
                    )
            elif self.operation == 'admit_strategy':
                if any(v is not None for v in
                       (self.run_id, self.export_id, self.output_name, self.directory,
                        self.expected_directory_identity)):
                    raise ValueError
                _uuid(self.admission_request_id)
                if (self.approval_confirmed is not True
                        or type(self.admission_theme) is not str
                        or type(self.admission_approved_by) is not str
                        or type(self.admission_groups) is not tuple
                        or not self.admission_groups):
                    raise ValueError
                # Reject malformed drafts before they cross the process
                # boundary. Storage and the compiler verify again in child.
                from research_y.storage import _groups_snapshot
                from research_y.query_compiler import compile_both
                frozen = dict(format_version=1, logic='OR',
                              theme=self.admission_theme,
                              approved_by=self.admission_approved_by,
                              groups=_groups_snapshot(self.admission_groups))
                compile_both(frozen)
            elif self.operation == 'inspect':
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
            if self.operation not in ('wos_acquisition_preview', 'wos_acquisition_prepare', 'wos_acquisition_read',
                                       'wos_acquisition_tick') and any(
                    value is not None for value in acquisition_fields):
                raise ValueError
            if self.operation != 'pilot_history' and self.history_before_event_id is not None:
                raise ValueError
            if self.operation != 'admit_strategy' and any(
                    value is not None for value in admission_fields):
                raise ValueError
            if self.operation not in ('preflight_read', 'preflight_record') and any(
                    value is not None for value in review_fields):
                raise ValueError
            if self.operation not in ('pubmed_pilot_count', 'pubmed_pilot_read',
                                       'wos_pilot_sample', 'wos_pilot_read') and any(
                    value is not None for value in pilot_fields):
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
        if command.operation in (
                'wos_acquisition_preview', 'wos_acquisition_prepare', 'wos_acquisition_read',
                'wos_acquisition_tick'):
            from research_y import wos_acquisition_gui as acquisition
            try:
                if command.operation == 'wos_acquisition_preview':
                    return acquisition.preview_wos_acquisition(
                        project,run_id=command.run_id,
                        query_id=command.acquisition_query_id)
                if command.operation == 'wos_acquisition_read':
                    return acquisition.inspect_wos_acquisition(
                        project, run_id=command.run_id,
                        query_id=command.acquisition_query_id)
                if command.operation == 'wos_acquisition_prepare':
                    return acquisition.prepare_wos_acquisition(
                        project, run_id=command.run_id,
                        query_id=command.acquisition_query_id,
                        expected_plan_sha256=command.acquisition_plan_sha256,
                        confirmed=command.acquisition_confirmed,
                        retention_authorized=command.acquisition_retention_authorized)
                from research_y.wos_starter_client import WoSStarterClient
                client = WoSStarterClient(
                    api_key=command.acquisition_api_key,
                    request_budget=3, timeout=10)
                return acquisition.run_wos_acquisition_session(
                    project, run_id=command.run_id,
                    query_id=command.acquisition_query_id,
                    confirmed=command.acquisition_confirmed,
                    revalidate_quota=command.acquisition_revalidate_quota,
                    client=client)
            except acquisition.WoSAcquisitionError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation == 'pilot_history':
            from research_y.pilot_history import read_pilot_history, PilotHistoryError
            try:
                return read_pilot_history(
                    project, before_event_id=command.history_before_event_id)
            except PilotHistoryError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation in ('pubmed_pilot_count', 'pubmed_pilot_read'):
            from research_y import pubmed_pilot as pilot
            try:
                if command.operation == 'pubmed_pilot_read':
                    return {'pilot': pilot.read_pubmed_pilot(
                        project, command.pilot_id),
                        'source_retrieval_verified': False}
                from research_y.pubmed_probe import PubMedESearchProbeClient
                client = PubMedESearchProbeClient(
                    email=command.pilot_contact_email,
                    api_key=command.pilot_api_key)
                return pilot.probe_pubmed_count_once(
                    project, pilot_id=command.pilot_id,
                    run_id=command.run_id, query_id=command.pilot_query_id,
                    expected_plan_sha256=command.pilot_plan_sha256,
                    confirmed=command.pilot_confirmed, client=client)
            except pilot.PubMedPilotError as exc:
                raise ApplicationCommandError(exc.code) from None
            except ValueError:
                raise ApplicationCommandError('pubmed_profile_invalid') from None
        if command.operation in ('wos_pilot_sample', 'wos_pilot_read'):
            from research_y import wos_starter_pilot as pilot
            try:
                if command.operation == 'wos_pilot_read':
                    return {'pilot': pilot.read_wos_pilot(
                        project, command.pilot_id),
                        'source_retrieval_verified': False}
                from research_y.wos_starter_client import WoSStarterClient
                client = WoSStarterClient(api_key=command.pilot_api_key,
                                          request_budget=1)
                return pilot.probe_wos_starter_once(
                    project, pilot_id=command.pilot_id,
                    run_id=command.run_id, query_id=command.pilot_query_id,
                    expected_plan_sha256=command.pilot_plan_sha256,
                    confirmed=command.pilot_confirmed, client=client,
                    revalidate_quota=command.pilot_wos_revalidate_quota)
            except pilot.WoSPilotError as exc:
                raise ApplicationCommandError(exc.code) from None
            except ValueError:
                raise ApplicationCommandError('wos_profile_invalid') from None
        if command.operation in ('preflight_read', 'preflight_record'):
            from research_y import preflight_review as preflight
            try:
                if command.operation == 'preflight_read':
                    lookup = ({} if command.review_id is None else
                              {'review_id': command.review_id})
                    return preflight.read_preflight(project, command.run_id, **lookup)
                return preflight.record_preflight_review(
                    project, run_id=command.run_id,
                    review_id=command.review_id,
                    expected_plan_sha256=command.review_plan_sha256,
                    reviewer_name=command.review_reviewer_name,
                    reviewer_role=command.review_reviewer_role,
                    press_items=command.review_items,
                    review_note=command.review_note,
                    known_relevant=command.review_known_relevant)
            except preflight.PreflightError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation == 'admit_strategy':
            from research_y import strategy_admission as admission
            try:
                result = admission.commit_approved_strategy(
                    project, request_id=command.admission_request_id,
                    theme=command.admission_theme,
                    approved_by=command.admission_approved_by,
                    groups=command.admission_groups,
                    approval_confirmed=command.approval_confirmed)
            except admission.StrategyAdmissionError as exc:
                raise ApplicationCommandError(str(exc)) from None
            except (ValueError, TypeError):
                raise ApplicationCommandError('strategy_invalid') from None
            return dict(asdict(result), source_retrieval_verified=False)
        if command.operation == 'export_report':
            return inspection.read_export_report(project, command.export_id).as_dict()
        if command.operation == 'observe_export':
            result = inspection.observe_export_request(project, command.export_id, directory=command.directory)
        elif command.operation == 'prepare_export':
            identity_args = ({} if command.expected_directory_identity is None else
                             {'expected_directory_identity': command.expected_directory_identity})
            result = exports.prepare_workbook_export(project, command.run_id, command.output_name,
                       export_id=command.export_id, directory=command.directory, **identity_args)
        elif command.operation == 'resume_export':
            result = exports.resume_workbook_export(project, command.export_id, directory=command.directory)
        else:
            result = exports.cancel_workbook_export(project, command.export_id, directory=command.directory)
        return asdict(result)
    except ApplicationCommandError:
        raise
    except (inspection.ApplicationInspectionError, exports.WorkbookExportError) as exc:
        raise ApplicationCommandError(exc.code) from None
    except sqlite3.Error as exc:
        number = getattr(exc, 'sqlite_errorcode', 0)
        busy = isinstance(number, int) and (number & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        raise ApplicationCommandError('project_busy' if busy else 'project_unavailable') from None
    except Exception:
        # Original errors may contain paths, source text or renderer details.
        raise ApplicationCommandError('operation_failed') from None
