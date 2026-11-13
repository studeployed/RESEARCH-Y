"""Dispatch local research actions to the trusted project host."""
from research_y.desktop.flow import ProjectFlowError


def perform_action(flow, name, value=None):
    if name == 'study_inspect':
        return flow.inspect_study()
    if name == 'study_suggest':
        return flow.propose_local_study(value)
    if name == 'study_confirm':
        if type(value) is not dict or set(value) != {'dimension','labels','actor','rationale','revision','event_id'}:
            raise ProjectFlowError('invalid_study_review')
        return flow.decide_study(**value)
    if name == 'local_mode':
        return flow.set_local_mode(value)
    if name == 'local_suggest':
        if type(value) is not dict or set(value) != {'group_id', 'term_id'}:
            raise ProjectFlowError('invalid_setup_action')
        return flow.propose_local_terms(**value)
    if name == 'recent_open':
        return flow.open_recent(value)
    if name == 'recent_refresh':
        return flow.refresh_recents()
    if name == 'setup_edit':
        if type(value) is not dict or set(value) != {'action', 'data'}:
            raise ProjectFlowError('invalid_setup_action')
        return flow.edit_setup(value['action'], value['data'])
    if name == 'setup_preview':
        return flow.preview_setup()
    if name == 'setup_approve':
        # An explicit researcher click is the only route
        # to this approval operation. Never during typing
        # or automatically after compiling a preview.
        return flow.approve_setup()
    if name == 'select_run':
        return flow.select_run(value)
    if name == 'preflight_inspect':
        return flow.inspect_preflight()
    if name == 'preflight_offer':
        if type(value) is not dict:
            raise ProjectFlowError('preflight_review_invalid')
        return flow.offer_preflight_review(**value)
    if name == 'preflight_revise':
        return flow.revise_preflight_review()
    if name == 'preflight_record':
        return flow.record_preflight_review()
    if name == 'pubmed_pilot_offer':
        return flow.offer_pubmed_pilot(value)
    if name == 'pubmed_pilot_revise':
        return flow.revise_pubmed_pilot()
    if name == 'pubmed_pilot_confirm':
        # This is the *only* action that may send a count
        # request. A separate frozen-query offer is required.
        return flow.confirm_pubmed_pilot()
    if name == 'pubmed_pilot_reconcile':
        # Read-only journal inspection; NEVER resend.
        return flow.reconcile_pubmed_pilot()
    if name == 'wos_pilot_offer':
        return flow.offer_wos_pilot(value)
    if name == 'wos_pilot_revalidation_offer':
        return flow.offer_wos_pilot(value, revalidate_quota=True)
    if name == 'wos_pilot_revise':
        return flow.revise_wos_pilot()
    if name == 'wos_pilot_confirm':
        # Only a separate confirmed click may send Starter GET.
        return flow.confirm_wos_pilot()
    if name == 'wos_pilot_reconcile':
        # No network; read original UUID's immutable journal.
        return flow.reconcile_wos_pilot()
    if name == 'pilot_history_refresh':
        # Read-only; never reconstruct or resend a pilot.
        return flow.inspect_pilot_history()
    if name == 'pilot_history_older':
        return flow.inspect_pilot_history(before_event_id=value)
    if name == 'pilot_history_detail':
        return flow.inspect_saved_pilot(value)
    if name == 'wos_acquisition_offer':
        return flow.offer_wos_acquisition(value)
    if name == 'wos_acquisition_dismiss':
        return flow.dismiss_wos_acquisition()
    if name == 'wos_acquisition_prepare':
        # No provider request: explicit retention consent only.
        return flow.confirm_wos_acquisition()
    if name == 'wos_acquisition_prepare_reconcile':
        return flow.reconcile_wos_acquisition()
    if name == 'wos_acquisition_read':
        return flow.inspect_stored_wos_acquisition(value)
    if name == 'wos_acquisition_tick_offer':
        return flow.offer_wos_acquisition_tick()
    if name == 'wos_acquisition_revalidate_offer':
        return flow.offer_wos_acquisition_tick(revalidate_quota=True)
    if name == 'wos_acquisition_tick_dismiss':
        return flow.dismiss_wos_acquisition_tick()
    if name == 'wos_acquisition_tick_confirm':
        # Only explicit separate consent authorises HTTPS.
        return flow.confirm_wos_acquisition_tick()
    if name == 'wos_acquisition_tick_reconcile':
        # Read-only checkpoint inspection; NEVER resend.
        return flow.reconcile_wos_acquisition_tick()
    if name == 'wos_verification_offer':
        return flow.offer_wos_verification()
    if name == 'wos_verification_revalidate_offer':
        return flow.offer_wos_verification(revalidate_quota=True)
    if name == 'wos_verification_dismiss':
        return flow.dismiss_wos_verification()
    if name == 'wos_verification_confirm':
        # ONLY a separate explicit click authorises transport.
        # The separate worker starts without blocking the GUI.
        return flow.confirm_wos_verification()
    if name == 'wos_verification_poll':
        # Read-only supervisor + durable original checkpoint.
        return flow.poll_wos_verification()
    if name == 'wos_verification_pause':
        # Explicit cooperative pause, NEVER network initiation.
        return flow.pause_wos_verification()
    if name == 'wos_verification_reconcile':
        # Terminal child evidence AND durable source receipt.
        return flow.reconcile_wos_verification()
    if name == 'pubmed_identifier_read':
        return flow.inspect_stored_pubmed_source(value)
    if name == 'pubmed_identifier_offer':
        if type(value) is not dict or set(value) != {
                'query_id','coverage_start','coverage_end'}:
            raise ProjectFlowError('pubmed_coverage_invalid')
        return flow.offer_pubmed_source(**value)
    if name == 'pubmed_identifier_dismiss':
        return flow.dismiss_pubmed_source()
    if name == 'pubmed_identifier_confirm':
        # Only explicit separate confirmation starts ESearch.
        return flow.confirm_pubmed_source()
    if name == 'pubmed_identifier_poll':
        # No PubMed request; original disk checkpoint only.
        return flow.poll_pubmed_source()
    if name == 'pubmed_identifier_pause':
        return flow.pause_pubmed_source()
    if name == 'pubmed_identifier_reconcile':
        return flow.reconcile_pubmed_source()
    if name == 'pubmed_metadata_read':
        return flow.inspect_stored_pubmed_metadata(value)
    if name == 'pubmed_metadata_offer':
        return flow.offer_pubmed_metadata(value)
    if name == 'pubmed_metadata_dismiss':
        return flow.dismiss_pubmed_metadata()
    if name == 'pubmed_metadata_confirm':
        # Explicit user consent; the ONLY EFetch HTTP path.
        return flow.confirm_pubmed_metadata()
    if name == 'pubmed_metadata_poll':
        # Original durable record counts, no network.
        return flow.poll_pubmed_metadata()
    if name == 'pubmed_metadata_reconcile':
        # Read-only final verification of stopped worker.
        return flow.reconcile_pubmed_metadata()
    if name == 'run_board_refresh':
        # One explicit whole-run inspection. No provider
        # traffic, query execution or background scheduling.
        return flow.inspect_run_execution_board()
    if name == 'run_board_select':
        if type(value) is not dict or set(value) != {
                'query_id','revision'}:
            raise ProjectFlowError('run_board_invalid')
        return flow.choose_run_execution_step(**value)
    if name == 'publication_refresh':
        return flow.inspect_publications()
    if name == 'publication_next':
        if type(value) is not dict or set(value) != {'cursor', 'revision'}:
            raise ProjectFlowError('publication_view_invalid')
        return flow.inspect_publications(
            after_publication_id=value['cursor'], revision=value['revision'])
    if name == 'publication_detail':
        if type(value) is not dict or set(value) != {'publication_id', 'revision'}:
            raise ProjectFlowError('publication_view_invalid')
        return flow.inspect_publication_detail(**value)
    if name == 'publication_materialise_offer':
        # No write. The next CONFIRM is a separate, bounded,
        # deliberately initiated local SQLite transaction.
        return flow.offer_publication_materialisation()
    if name == 'publication_materialise_dismiss':
        return flow.dismiss_publication_materialisation()
    if name == 'publication_materialise_confirm':
        return flow.confirm_publication_materialisation(value)
    if name in ('publication_window_inspect',
                'publication_window_offer',
                'publication_window_dismiss'):
        # Only fixed actions; browser cannot supply a run,
        # consent hash, source IDs, work limit or path.
        if value is not None:
            raise ProjectFlowError('publication_window_invalid')
        if name == 'publication_window_inspect':
            return flow.inspect_publication_window()
        if name == 'publication_window_offer':
            return flow.offer_publication_window()
        return flow.dismiss_publication_window()
    if name == 'publication_window_confirm':
        if type(value) is not str or not value.strip():
            raise ProjectFlowError(
                'publication_window_confirmation_required')
        return flow.confirm_publication_window(value)
    if name == 'candidate_index_inspect':
        # Local source-key cache status only. No writes.
        return flow.inspect_candidate_index()
    if name == 'candidate_index_offer':
        if value not in ('start','advance'):
            raise ProjectFlowError('candidate_index_invalid')
        return flow.offer_candidate_index(value)
    if name == 'candidate_index_dismiss':
        return flow.dismiss_candidate_index()
    if name == 'candidate_index_confirm':
        # Only a separate confirmation click authorises one
        # transaction of at most 128 original source records.
        return flow.confirm_candidate_index(value)
    if name == 'candidate_pairs_inspect':
        # Read-only saved pair checkpoint for selected run.
        return flow.inspect_candidate_pairs()
    if name == 'candidate_pairs_offer':
        if type(value) is not str or value not in ('start','advance'):
            raise ProjectFlowError('candidate_pair_invalid')
        return flow.offer_candidate_pairs(value)
    if name == 'candidate_pairs_dismiss':
        return flow.dismiss_candidate_pairs()
    if name == 'candidate_pairs_confirm':
        # Separate explicit click, one bounded transaction
        # and independent saved-state reconciliation.
        return flow.confirm_candidate_pairs(value)
    if name == 'candidate_queue_refresh':
        # Full project candidate index, original SQLite only.
        return flow.inspect_candidate_queue()
    if name == 'candidate_queue_next':
        if (type(value) is not dict or
                set(value) != {'cursor','revision'} or
                type(value['cursor']) is not list or
                len(value['cursor']) != 2):
            raise ProjectFlowError('candidate_queue_invalid')
        return flow.inspect_candidate_queue(
            cursor=tuple(value['cursor']),
            revision=value['revision'])
    if name in ('candidate_queue_review', 'candidate_queue_cross_review'):
        if (type(value) is not dict or
                set(value) != {'left','right','revision'}):
            raise ProjectFlowError('candidate_queue_invalid')
        return flow.inspect_queue_candidate_pair(**value, cross_run=name == 'candidate_queue_cross_review')
    if name == 'candidate_choose_source':
        return flow.choose_candidate_source(value)
    if name == 'candidate_review_dismiss':
        return flow.dismiss_candidate_review()
    if name == 'candidate_reversal_offer':
        return flow.offer_candidate_reversal(value)
    if name == 'candidate_review_decide':
        if type(value) is not dict or set(value) != {
                'decision', 'move_retrieval_id', 'actor',
                'evidence', 'acknowledged', 'offer_revision'}:
            raise ProjectFlowError('publication_review_invalid')
        return flow.confirm_candidate_decision(**value)
    if name == 'candidate_reversal_confirm':
        if type(value) is not dict or set(value) != {
                'actor', 'evidence'}:
            raise ProjectFlowError('publication_review_invalid')
        return flow.confirm_candidate_reversal(**value)
    if name == 'run_coord_offer':
        return flow.offer_run_coordination()
    if name == 'run_coord_dismiss':
        return flow.dismiss_run_coordination()
    if name == 'run_coord_confirm':
        # Only this separately confirmed click can begin
        # a bounded source-work sequence.
        return flow.confirm_run_coordination()
    if name == 'run_coord_poll':
        # Original source checkpoint reads ONLY.
        return flow.poll_run_coordination()
    if name == 'run_coord_reconcile':
        return flow.reconcile_run_coordination()
    if name == 'select_export':
        return flow.select_export(value)
    if name == 'manifest_preview':
        if type(value) is not dict or set(value) != {'output_name', 'actor'}:
            raise ProjectFlowError('invalid_manifest_request')
        return flow.preview_manifest(**value)
    if name == 'manifest_confirm':
        return flow.confirm_manifest(value)
    if name == 'manifest_dismiss':
        return flow.dismiss_manifest(value)
    if name == 'manifest_reconcile':
        return flow.reconcile_manifest()
    if name in ('manifest_history', 'manifest_older'):
        return flow.manifest_history(older=name == 'manifest_older')
    if name == 'manifest_inspect':
        return flow.inspect_saved_manifest(value)
    if name == 'manifest_save':
        return flow.start_manifest_save(value)
    if name == 'manifest_poll':
        return flow.poll_manifest_save()
    if name == 'manifest_check_file':
        return flow.inspect_manifest_file(value)
    if name == 'prepare':
        return flow.prepare()
    if name == 'prepare_reviewed_master':
        return flow.prepare(reviewed_master=True)
    if name == 'external_confirm':
        return flow.confirm_external_directory()
    if name == 'external_clear':
        return flow.clear_external_directory()
    if name == 'resume':
        return flow.resume()
    if name == 'cancel':
        return flow.cancel()
    if name == 'observe':
        return flow.observe()
    raise ProjectFlowError('unsupported_action')
