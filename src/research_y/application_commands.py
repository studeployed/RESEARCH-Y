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

OPERATIONS = frozenset({'inspect', 'run_board', 'run_coord_preview', 'run_coord_run',
                        'publication_page', 'publication_detail',
                        'publication_materialisation_preview', 'publication_materialisation_confirm',
                        'candidate_review_preview', 'candidate_review_decide',
                        'candidate_reversal_preview', 'candidate_reversal_confirm',
                        'prepare_export', 'resume_export', 'cancel_export',
                        'observe_export', 'export_report', 'admit_strategy',
                        'preflight_read', 'preflight_record',
                        'pubmed_pilot_count', 'pubmed_pilot_read',
                         'wos_pilot_sample', 'wos_pilot_read', 'pilot_history',
                         'wos_acquisition_preview', 'wos_acquisition_prepare',
                         'wos_acquisition_read', 'wos_acquisition_tick',
                         'wos_acquisition_verify_plan', 'wos_acquisition_verify',
                         'wos_acquisition_pause', 'pubmed_identifier_preview',
                         'pubmed_identifier_read', 'pubmed_identifier_run',
                         'pubmed_identifier_pause', 'pubmed_metadata_read',
                         'pubmed_metadata_preview', 'pubmed_metadata_run'})
SERVICE_ERRORS = frozenset({'publication_review_unavailable', 'publication_review_invalid',
    'publication_review_stale', 'publication_review_wrong_run',
    'publication_review_no_reversal', 'publication_review_confirmation_required',
    'publication_view_unavailable', 'publication_view_invalid',
    'publication_view_stale', 'publication_view_not_in_run',
    'publication_materialisation_unavailable', 'publication_materialisation_stale',
    'publication_materialisation_no_work', 'run_board_unavailable', 'run_board_invalid',
    'run_coordination_unavailable', 'run_coordination_stale',
    'run_coordination_invalid', 'run_coordination_confirmation_required',
    'run_coordination_credentials_required', 'run_coordination_no_work',
    'run_board_unknown_run', 'run_board_stale', 'invalid_identifier', 'invalid_evidence', 'unknown_export',
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
     'checkpoint_already_exists', 'verification_requires_long_worker',
     'verification_not_ready', 'verification_budget_exceeded',
     'verification_plan_changed', 'verification_worker_recovery_required',
     'verification_worker_not_running',
     'pubmed_plan_unverified', 'pubmed_checkpoint_invalid',
     'pubmed_contact_required', 'pubmed_session_confirmation_required',
     'pubmed_identifier_budget_invalid', 'pubmed_coverage_invalid',
     'pubmed_coverage_changed', 'pubmed_provider_incomplete',
     'pubmed_worker_recovery_required', 'pubmed_source_unavailable',
     'pubmed_query_not_ready', 'pubmed_checkpoint_not_ready',
     'pubmed_verification_exceeds_budget',
     'pubmed_worker_not_running',
     'pubmed_metadata_evidence_invalid', 'pubmed_metadata_not_ready',
     'pubmed_metadata_already_acquired', 'pubmed_metadata_plan_changed',
     'pubmed_metadata_confirmation_required', 'pubmed_metadata_unavailable'})


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
    # Explicit WoS source-acquisition consent. NOT a pilot; up to three HTTPS
    # requests and lawfully permitted source-metadata retention per session.
    acquisition_query_id: str | None = None
    acquisition_plan_sha256: str | None = None
    acquisition_confirmed: bool | None = None
    acquisition_retention_authorized: bool | None = None
    acquisition_revalidate_quota: bool | None = None
    acquisition_api_key: str | None = None
    # Frozen long-verification request count; derived by core from committed
    # source pages, never provided as an arbitrary browser-side budget.
    verification_expected_requests: int | None = None
    # PubMed ESearch identifier retrieval; host-supplied contact/key only.
    # Dates specify an explicitly reviewed administrative Create Date window
    # for partitioning >10,000 IDs, never a hidden conceptual date exclusion.
    pubmed_source_query_id: str | None = None
    pubmed_source_plan_sha256: str | None = None
    pubmed_coverage_start: str | None = None
    pubmed_coverage_end: str | None = None
    pubmed_source_confirmed: bool | None = None
    pubmed_source_contact_email: str | None = None
    pubmed_source_api_key: str | None = None
    # Run-wide explicit one-session coordination. Host-only fields, never
    # populated from untrusted browser form values.
    coord_plan_sha256: str | None = None
    coord_tasks: tuple | None = None
    coord_confirmed: bool | None = None
    coord_wos_key: str | None = None
    coord_pubmed_email: str | None = None
    coord_pubmed_key: str | None = None
    # Local publication browsing and explicit provisional-identity preparation.
    # No metadata, SQL expression, source content or project path is accepted
    # from the browser through these fields.
    publication_view_cursor: str | None = None
    publication_view_id: str | None = None
    publication_view_revision: str | None = None
    publication_actor: str | None = None
    publication_confirmed: bool | None = None
    # Exact candidate-review identities/tokens. Browser selection is checked
    # again against a currently displayed, trusted-host page/detail.
    candidate_left_id: str | None = None
    candidate_right_id: str | None = None
    candidate_retrieval_id: str | None = None
    candidate_run_revision: str | None = None
    candidate_revision: str | None = None
    candidate_decision: str | None = None
    candidate_move_id: str | None = None
    candidate_actor: str | None = None
    candidate_evidence: str | None = None
    candidate_confirmed: bool | None = None
    candidate_warnings_acknowledged: bool | None = None

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
            pubmed_source_fields = (
                self.pubmed_source_query_id, self.pubmed_source_plan_sha256,
                self.pubmed_coverage_start, self.pubmed_coverage_end,
                self.pubmed_source_confirmed, self.pubmed_source_contact_email,
                self.pubmed_source_api_key,
            )
            coordination_fields = (
                self.coord_plan_sha256, self.coord_tasks,
                self.coord_confirmed, self.coord_wos_key,
                self.coord_pubmed_email, self.coord_pubmed_key)
            publication_fields = (
                self.publication_view_cursor, self.publication_view_id,
                self.publication_view_revision, self.publication_actor,
                self.publication_confirmed)
            candidate_fields = (
                self.candidate_left_id, self.candidate_right_id,
                self.candidate_retrieval_id, self.candidate_run_revision,
                self.candidate_revision, self.candidate_decision,
                self.candidate_move_id, self.candidate_actor,
                self.candidate_evidence, self.candidate_confirmed,
                self.candidate_warnings_acknowledged)
            candidate_ops = (
                'candidate_review_preview', 'candidate_review_decide',
                'candidate_reversal_preview', 'candidate_reversal_confirm')
            if self.operation in candidate_ops:
                if (self.run_id is None or any(v is not None for v in (
                        self.export_id, self.output_name, self.directory,
                        self.expected_directory_identity)) or
                        any(v is not None for v in publication_fields)):
                    raise ValueError
                digest = self.candidate_run_revision
                if (type(digest) is not str or len(digest) != 64 or
                        any(ch not in '0123456789abcdef' for ch in digest)):
                    raise ValueError
                if self.operation in ('candidate_review_preview', 'candidate_review_decide'):
                    _uuid(self.candidate_left_id); _uuid(self.candidate_right_id)
                    if (self.candidate_left_id == self.candidate_right_id or
                            self.candidate_retrieval_id is not None):
                        raise ValueError
                else:
                    _uuid(self.candidate_retrieval_id)
                    if self.candidate_left_id is not None or self.candidate_right_id is not None:
                        raise ValueError
                if self.operation in ('candidate_review_preview', 'candidate_reversal_preview'):
                    if any(v is not None for v in (
                            self.candidate_revision, self.candidate_decision,
                            self.candidate_move_id, self.candidate_actor,
                            self.candidate_evidence, self.candidate_confirmed,
                            self.candidate_warnings_acknowledged)):
                        raise ValueError
                else:
                    digest = self.candidate_revision
                    if (type(digest) is not str or len(digest) != 64 or
                            any(ch not in '0123456789abcdef' for ch in digest) or
                            self.candidate_confirmed is not True):
                        raise ValueError
                    from research_y.publication_identity import _text
                    _text(self.candidate_actor, 200)
                    _text(self.candidate_evidence)
                    if self.operation == 'candidate_review_decide':
                        if (self.candidate_decision not in ('confirmed_match', 'rejected_match')
                                or self.candidate_warnings_acknowledged is not True or
                                (self.candidate_decision == 'confirmed_match'
                                 and self.candidate_move_id not in
                                 (self.candidate_left_id, self.candidate_right_id)) or
                                (self.candidate_decision == 'rejected_match'
                                 and self.candidate_move_id is not None)):
                            raise ValueError
                    elif (self.candidate_decision is not None or
                          self.candidate_move_id is not None or
                          self.candidate_warnings_acknowledged is not None):
                        raise ValueError
            if self.operation in ('publication_page', 'publication_detail',
                    'publication_materialisation_preview', 'publication_materialisation_confirm'):
                if (self.run_id is None or self.export_id is not None or
                        self.output_name is not None or self.directory is not None or
                        self.expected_directory_identity is not None):
                    raise ValueError
                if self.operation == 'publication_page':
                    if self.publication_view_cursor is not None:
                        _uuid(self.publication_view_cursor)
                        if self.publication_view_revision is None:
                            raise ValueError
                    if any(v is not None for v in (
                            self.publication_view_id, self.publication_actor,
                            self.publication_confirmed)):
                        raise ValueError
                    digest = self.publication_view_revision
                    if digest is not None and (type(digest) is not str or
                            len(digest) != 64 or
                            any(c not in '0123456789abcdef' for c in digest)):
                        raise ValueError
                elif self.operation == 'publication_detail':
                    _uuid(self.publication_view_id)
                    if (self.publication_view_cursor is not None or
                            self.publication_actor is not None or
                            self.publication_confirmed is not None):
                        raise ValueError
                    digest = self.publication_view_revision
                    if (type(digest) is not str or len(digest) != 64 or
                            any(c not in '0123456789abcdef' for c in digest)):
                        raise ValueError
                elif self.operation == 'publication_materialisation_preview':
                    if any(v is not None for v in publication_fields):
                        raise ValueError
                else:
                    if (self.publication_view_cursor is not None or
                            self.publication_view_id is not None or
                            self.publication_confirmed is not True):
                        raise ValueError
                    digest = self.publication_view_revision
                    if (type(digest) is not str or len(digest) != 64 or
                            any(c not in '0123456789abcdef' for c in digest)):
                        raise ValueError
                    from research_y.publication_identity import _text
                    _text(self.publication_actor, 200)
            if self.operation in ('run_coord_preview', 'run_coord_run'):
                if (self.run_id is None or any(v is not None for v in (
                        self.export_id, self.output_name, self.directory,
                        self.expected_directory_identity))):
                    raise ValueError
                _uuid(self.run_id)
                if self.operation == 'run_coord_preview':
                    if any(v is not None for v in coordination_fields):
                        raise ValueError
                else:
                    digest = self.coord_plan_sha256
                    if (type(digest) is not str or len(digest) != 64 or
                            any(c not in '0123456789abcdef' for c in digest) or
                            self.coord_confirmed is not True or
                            type(self.coord_tasks) is not tuple or
                            not 1 <= len(self.coord_tasks) <= 2):
                        raise ValueError
                    from research_y.run_source_coordinator import ELIGIBLE_ACTIONS
                    keys = {'query_id', 'source_name', 'group_id',
                            'exact_query', 'action', 'preflight_sha256',
                            'max_requests', 'coverage_start', 'coverage_end',
                            'records_to_fetch'}
                    for task in self.coord_tasks:
                        if (type(task) is not dict or
                                set(task) - keys or
                                task.get('action') not in ELIGIBLE_ACTIONS or
                                type(task.get('max_requests')) is not int or
                                not 1 <= task['max_requests'] <= 512 or
                                type(task.get('exact_query')) is not str or
                                not 1 <= len(task['exact_query']) <= 8192 or
                                type(task.get('preflight_sha256')) is not str or
                                len(task['preflight_sha256']) != 64 or
                                any(c not in '0123456789abcdef'
                                    for c in task['preflight_sha256'])):
                            raise ValueError
                        _uuid(task.get('query_id'))
                        if (type(task.get('group_id')) is not str or
                                not 1 <= len(task['group_id']) <= 200 or
                                task.get('source_name') not in ('pubmed','wos')):
                            raise ValueError
                    if self.coord_wos_key is not None:
                        from research_y.wos_starter_client import WoSStarterClient
                        from research_y.wos_starter import WoSStarterError
                        try:
                            WoSStarterClient(api_key=self.coord_wos_key,
                                             request_budget=3,timeout=10)
                        except WoSStarterError:
                            raise ValueError from None
                    if self.coord_pubmed_email is not None:
                        if (type(self.coord_pubmed_email) is not str or
                                not self.coord_pubmed_email.isascii() or
                                not 1 <= len(self.coord_pubmed_email) <= 254 or
                                (self.coord_pubmed_key is not None and
                                 (type(self.coord_pubmed_key) is not str or
                                  not self.coord_pubmed_key.isascii() or
                                  not 1 <= len(self.coord_pubmed_key) <= 4096 or
                                  any(ord(char) < 33 or ord(char) > 126
                                      for char in self.coord_pubmed_key)))):
                            raise ValueError
                        from research_y.pubmed_probe import PubMedESearchProbeClient
                        PubMedESearchProbeClient(email=self.coord_pubmed_email,
                            api_key=self.coord_pubmed_key,timeout=15)
                    elif self.coord_pubmed_key is not None:
                        raise ValueError
            if self.operation in ('pubmed_identifier_preview',
                                  'pubmed_identifier_read',
                                  'pubmed_identifier_run', 'pubmed_identifier_pause',
                                  'pubmed_metadata_read', 'pubmed_metadata_preview',
                                  'pubmed_metadata_run'):
                if any(v is not None for v in (
                        self.export_id, self.output_name, self.directory,
                        self.expected_directory_identity)):
                    raise ValueError
                _uuid(self.run_id)
                _uuid(self.pubmed_source_query_id)
                if self.operation in ('pubmed_identifier_preview',
                                      'pubmed_identifier_read', 'pubmed_identifier_pause',
                                      'pubmed_metadata_read', 'pubmed_metadata_preview'):
                    if any(v is not None for v in pubmed_source_fields[1:]):
                        raise ValueError
                else:
                    from research_y.pubmed_source_gui import _sha, _window
                    _sha(self.pubmed_source_plan_sha256)
                    if self.operation == 'pubmed_identifier_run':
                        _window(self.pubmed_coverage_start, self.pubmed_coverage_end)
                    elif self.pubmed_coverage_start is not None or self.pubmed_coverage_end is not None:
                        raise ValueError
                    if (self.pubmed_source_confirmed is not True or
                            type(self.pubmed_source_contact_email) is not str or
                            len(self.pubmed_source_contact_email) > 254 or
                            not self.pubmed_source_contact_email.isascii() or
                            (self.pubmed_source_api_key is not None and
                             (type(self.pubmed_source_api_key) is not str or
                              not 1 <= len(self.pubmed_source_api_key) <= 4096 or
                              not self.pubmed_source_api_key.isascii() or
                              any(ord(c) < 33 or ord(c) > 126
                                  for c in self.pubmed_source_api_key)))):
                        raise ValueError
                    from research_y.pubmed_probe import PubMedESearchProbeClient
                    PubMedESearchProbeClient(
                        email=self.pubmed_source_contact_email,
                        api_key=self.pubmed_source_api_key,timeout=15)
            elif self.operation in ('pubmed_pilot_count', 'pubmed_pilot_read',
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
                    'wos_acquisition_tick', 'wos_acquisition_verify_plan',
                    'wos_acquisition_verify', 'wos_acquisition_pause'):
                if any(v is not None for v in (
                        self.export_id, self.output_name, self.directory,
                        self.expected_directory_identity)):
                    raise ValueError
                _uuid(self.run_id)
                _uuid(self.acquisition_query_id)
                if self.operation in ('wos_acquisition_read','wos_acquisition_preview',
                                      'wos_acquisition_verify_plan','wos_acquisition_pause'):
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
                elif self.operation == 'wos_acquisition_tick':
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
                else:
                    from research_y.wos_acquisition_gui import MAX_VERIFY_REQUESTS
                    if (self.operation != 'wos_acquisition_verify' or
                            self.acquisition_retention_authorized is not None or
                            self.acquisition_confirmed is not True or
                            type(self.acquisition_revalidate_quota) is not bool or
                            type(self.acquisition_plan_sha256) is not str or
                            len(self.acquisition_plan_sha256) != 64 or
                            any(c not in '0123456789abcdef'
                                for c in self.acquisition_plan_sha256) or
                            type(self.verification_expected_requests) is not int or
                            not 3 <= self.verification_expected_requests <=
                                MAX_VERIFY_REQUESTS):
                        raise ValueError
                    from research_y.wos_starter_client import WoSStarterClient
                    from research_y.wos_starter import WoSStarterError
                    try:
                        WoSStarterClient(api_key=self.acquisition_api_key,
                                         request_budget=MAX_VERIFY_REQUESTS,
                                         timeout=10)
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
            elif self.operation in candidate_ops:
                pass  # All source IDs and evidence-bound decisions validated above.
            elif self.operation in ('publication_page', 'publication_detail',
                    'publication_materialisation_preview', 'publication_materialisation_confirm'):
                pass  # Validated above; no provider request or export authority.
            elif self.operation in ('run_coord_preview','run_coord_run'):
                pass  # Validated above; not an export operation.
            elif self.operation == 'run_board':
                if (self.run_id is None or any(v is not None for v in
                        (self.export_id, self.output_name, self.directory,
                         self.expected_directory_identity))):
                    raise ValueError
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
            if self.operation not in candidate_ops and any(v is not None for v in candidate_fields):
                raise ValueError
            if self.operation not in ('publication_page', 'publication_detail',
                    'publication_materialisation_preview', 'publication_materialisation_confirm') and any(
                    value is not None for value in publication_fields):
                raise ValueError
            if self.operation not in ('run_coord_preview','run_coord_run') and any(
                    v is not None for v in coordination_fields):
                raise ValueError
            if self.operation not in ('pubmed_identifier_preview',
                                        'pubmed_identifier_read',
                                        'pubmed_identifier_run',
                                        'pubmed_identifier_pause',
                                        'pubmed_metadata_read', 'pubmed_metadata_preview',
                                        'pubmed_metadata_run') and any(
                    v is not None for v in pubmed_source_fields):
                raise ValueError
            if self.operation != 'wos_acquisition_verify' and self.verification_expected_requests is not None:
                raise ValueError
            if self.operation not in ('wos_acquisition_preview', 'wos_acquisition_prepare', 'wos_acquisition_read',
                                       'wos_acquisition_tick', 'wos_acquisition_verify_plan',
                                       'wos_acquisition_verify','wos_acquisition_pause') and any(
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
        if command.operation in (
                'candidate_review_preview', 'candidate_review_decide',
                'candidate_reversal_preview', 'candidate_reversal_confirm'):
            from research_y import publication_review_gui as candidate
            try:
                if command.operation == 'candidate_review_preview':
                    return candidate.preview_candidate_review(
                        project, command.run_id, command.candidate_left_id,
                        command.candidate_right_id,
                        run_revision=command.candidate_run_revision)
                if command.operation == 'candidate_review_decide':
                    return candidate.record_candidate_review(
                        project, command.run_id, command.candidate_left_id,
                        command.candidate_right_id,
                        run_revision=command.candidate_run_revision,
                        expected_revision=command.candidate_revision,
                        decision=command.candidate_decision,
                        move_retrieval_id=command.candidate_move_id,
                        actor=command.candidate_actor,
                        evidence=command.candidate_evidence,
                        warnings_acknowledged=command.candidate_warnings_acknowledged,
                        confirmed=command.candidate_confirmed)
                if command.operation == 'candidate_reversal_preview':
                    return candidate.preview_candidate_reversal(
                        project, command.run_id, command.candidate_retrieval_id,
                        run_revision=command.candidate_run_revision)
                return candidate.confirm_candidate_reversal(
                    project, command.run_id, command.candidate_retrieval_id,
                    run_revision=command.candidate_run_revision,
                    expected_revision=command.candidate_revision,
                    actor=command.candidate_actor, evidence=command.candidate_evidence,
                    confirmed=command.candidate_confirmed)
            except candidate.PublicationReviewError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation in ('publication_page', 'publication_detail'):
            from research_y.publication_results import (
                read_publication_page, read_publication_detail, PublicationViewError)
            try:
                if command.operation == 'publication_page':
                    return read_publication_page(
                        project, command.run_id,
                        after_publication_id=command.publication_view_cursor,
                        expected_revision=command.publication_view_revision)
                return read_publication_detail(
                    project, command.run_id, command.publication_view_id,
                    expected_revision=command.publication_view_revision)
            except PublicationViewError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation in ('publication_materialisation_preview',
                                 'publication_materialisation_confirm'):
            from research_y.publication_run_materialisation import (
                preview_run_materialisation, materialise_run_batch, MaterialisationConflict)
            try:
                if command.operation == 'publication_materialisation_preview':
                    return preview_run_materialisation(project, command.run_id)
                return materialise_run_batch(
                    project, command.run_id,
                    expected_revision=command.publication_view_revision,
                    actor=command.publication_actor,
                    confirmed=command.publication_confirmed)
            except MaterialisationConflict:
                raise ApplicationCommandError('publication_materialisation_stale') from None
            except ValueError:
                raise ApplicationCommandError('publication_materialisation_no_work') from None
            except Exception:
                raise ApplicationCommandError('publication_materialisation_unavailable') from None
        if command.operation in ('run_coord_preview', 'run_coord_run'):
            from research_y import run_source_coordinator as coordinator
            try:
                if command.operation == 'run_coord_preview':
                    return coordinator.preview_run_coordination(
                        project,run_id=command.run_id)
                return coordinator.run_coordinated_source_session(
                    project,run_id=command.run_id,
                    expected_plan_sha256=command.coord_plan_sha256,
                    tasks=command.coord_tasks,
                    confirmed=command.coord_confirmed,
                    wos_key=command.coord_wos_key,
                    pubmed_email=command.coord_pubmed_email,
                    pubmed_key=command.coord_pubmed_key)
            except coordinator.RunCoordinationError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation == 'run_board':
            from research_y.run_execution_board import (
                read_run_execution_board, ExecutionBoardError)
            try:
                return read_run_execution_board(project, command.run_id)
            except ExecutionBoardError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation == 'inspect':
            snapshot = inspection.read_application_snapshot(project, selected_run_id=command.run_id)
            return {'snapshot': snapshot.as_dict(), 'location': str(snapshot.location)}
        if command.operation in (
                'wos_acquisition_preview', 'wos_acquisition_prepare', 'wos_acquisition_read',
                'wos_acquisition_tick', 'wos_acquisition_verify_plan',
                'wos_acquisition_verify','wos_acquisition_pause'):
            from research_y import wos_acquisition_gui as acquisition
            try:
                if command.operation == 'wos_acquisition_pause':
                    return acquisition.pause_wos_verification_session(
                        project,run_id=command.run_id,
                        query_id=command.acquisition_query_id)
                if command.operation == 'wos_acquisition_verify_plan':
                    return acquisition.preview_wos_verification(
                        project,run_id=command.run_id,
                        query_id=command.acquisition_query_id)
                if command.operation == 'wos_acquisition_verify':
                    from research_y.wos_starter_client import WoSStarterClient
                    from research_y.wos_acquisition_gui import MAX_VERIFY_REQUESTS
                    client = WoSStarterClient(api_key=command.acquisition_api_key,
                                               request_budget=MAX_VERIFY_REQUESTS,timeout=10)
                    return acquisition.run_wos_verification_session(
                        project,run_id=command.run_id,
                        query_id=command.acquisition_query_id,
                        expected_plan_sha256=command.acquisition_plan_sha256,
                        expected_requests=command.verification_expected_requests,
                        confirmed=command.acquisition_confirmed,
                        revalidate_quota=command.acquisition_revalidate_quota,
                        client=client)
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
        if command.operation in ('pubmed_metadata_read',
                                 'pubmed_metadata_preview',
                                 'pubmed_metadata_run'):
            from research_y import pubmed_metadata_gui as metadata
            try:
                if command.operation == 'pubmed_metadata_read':
                    return metadata.inspect_pubmed_metadata(
                        project, run_id=command.run_id,
                        query_id=command.pubmed_source_query_id)
                if command.operation == 'pubmed_metadata_preview':
                    return metadata.preview_pubmed_metadata(
                        project, run_id=command.run_id,
                        query_id=command.pubmed_source_query_id)
                from research_y.pubmed_probe import PubMedESearchProbeClient
                from research_y.pubmed_metadata import PubMedEFetchClient
                esearch = PubMedESearchProbeClient(
                    email=command.pubmed_source_contact_email,
                    api_key=command.pubmed_source_api_key, timeout=15)
                return metadata.run_pubmed_metadata_session(
                    project, run_id=command.run_id,
                    query_id=command.pubmed_source_query_id,
                    expected_plan_sha256=command.pubmed_source_plan_sha256,
                    confirmed=command.pubmed_source_confirmed,
                    client=PubMedEFetchClient(esearch))
            except metadata.PubMedMetadataGUIError as exc:
                raise ApplicationCommandError(exc.code) from None
        if command.operation in ('pubmed_identifier_preview',
                                 'pubmed_identifier_read',
                                 'pubmed_identifier_run', 'pubmed_identifier_pause'):
            from research_y import pubmed_source_gui as source
            try:
                if command.operation == 'pubmed_identifier_pause':
                    return source.pause_pubmed_source_session(
                        project,run_id=command.run_id,
                        query_id=command.pubmed_source_query_id)
                if command.operation == 'pubmed_identifier_read':
                    return source.inspect_pubmed_source(
                        project,run_id=command.run_id,
                        query_id=command.pubmed_source_query_id)
                if command.operation == 'pubmed_identifier_preview':
                    return source.preview_pubmed_source(
                        project,run_id=command.run_id,
                        query_id=command.pubmed_source_query_id)
                from research_y.pubmed_probe import PubMedESearchProbeClient
                client = PubMedESearchProbeClient(
                    email=command.pubmed_source_contact_email,
                    api_key=command.pubmed_source_api_key,timeout=15)
                return source.run_pubmed_source_session(
                    project,run_id=command.run_id,
                    query_id=command.pubmed_source_query_id,
                    expected_plan_sha256=command.pubmed_source_plan_sha256,
                    coverage_start=command.pubmed_coverage_start,
                    coverage_end=command.pubmed_coverage_end,
                    confirmed=command.pubmed_source_confirmed,client=client)
            except source.PubMedSourceError as exc:
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
