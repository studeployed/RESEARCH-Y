"""Render project controls using the current trusted-host snapshot."""
from datetime import date

from research_y.desktop.manifest_consent import render_manifest_consent
from research_y.desktop.study_panel import render_study_panel, render_study_queue


def render_project_panel(ui, flow, act, *, native, error, study_edits=None):
    state = flow.state()
    project = state['project']
    if project is not None:
        ui.label('INCOMPLETE — no source retrieval is verified.').props('data-testid=incomplete')
    ui.label('Recent Projects (explicit selection; locations verified on open).').props(
        'data-testid=recent-heading')
    if state['recent_history_error']:
        ui.label('Recent project history is unavailable; select a folder to open.').props(
            'data-testid=recent-history-error')
    elif not state['recent_projects']:
        ui.label('No recent projects recorded.').props('data-testid=recent-empty')
    else:
        for entry in state['recent_projects']:
            project_id = entry['project_id']
            ui.button('Open recent: ' + entry['name'] + ' — ' + entry['location'],
                      on_click=lambda project_id=project_id: act(
                          'recent_open', project_id)).props('data-testid=open-recent')
    ui.button('Refresh recent projects',
              on_click=lambda: act('recent_refresh')).props(
                  'data-testid=refresh-recents')
    if project is None:
        ui.label('No project open. A host-selected location is required.')
    else:
        ui.label('Project: ' + project['name']).props('data-testid=project-name')
        ui.label('Location: ' + project['location']).props('data-testid=project-location')
        ui.separator()
        ui.label('Saved source-pilot audit history — read-only, including '
                 'earlier sessions and runs. Not verified source retrieval.').props(
                     'data-testid=pilot-history-heading')
        ui.button('Refresh saved pilot history (no network)',
                  on_click=lambda: act('pilot_history_refresh')).props(
                      'data-testid=pilot-history-refresh')
        history = state['pilot_history']
        if state['pilot_history_error'] is not None:
            ui.label('Pilot audit could NOT be verified. Historical '
                     'attempts may exist; do not assume zero prior '
                     'requests. No provider call was made.').props(
                         'data-testid=pilot-history-error')
        elif history is None:
            ui.label('Pilot history not yet inspected; previous attempts '
                     'may exist.').props('data-testid=pilot-history-unread')
        else:
            ui.label('Total saved request EVENTS (not publication '
                     'matches): ' + str(history['request_events_total']) +
                     '; newest ' + str(len(history['entries'])) +
                     ' on this page.').props('data-testid=pilot-history-total')
            if not history['entries']:
                ui.label('No pilot requests on this page.').props(
                    'data-testid=pilot-history-empty')
            for row in history['entries']:
                ui.label(
                    row['source'] + ' • ' + row['requested_at_utc'] +
                    ' • run ' + row['run_id'] + ' • status ' + row['status'] +
                    ' • provisional matches ' +
                    ('UNKNOWN' if row['reported_matches'] is None
                     else str(row['reported_matches']))).props(
                         'data-testid=pilot-history-entry')
                if row['status']=='requested_indeterminate':
                    ui.label('OUTCOME UNKNOWN: request may have reached '
                             'the provider. Do NOT automatically retry. '
                             'Starter quota may remain blocked until '
                             'separately authorised recovery.').props(
                                 'data-testid=pilot-history-indeterminate')
                pid = row['pilot_id']
                ui.button('Inspect original saved receipt ' + pid,
                          on_click=lambda pid=pid: act(
                              'pilot_history_detail', pid)).props(
                                  'data-testid=pilot-history-detail')
            if history['next_before_event_id'] is not None:
                older = history['next_before_event_id']
                ui.label('Older requests not displayed on this page; '
                         'absence of an entry here is not proof that '
                         'a prior attempt never occurred.')
                ui.button('Inspect older pilot requests (no network)',
                          on_click=lambda older=older: act(
                              'pilot_history_older', older)).props(
                                  'data-testid=pilot-history-older')
            detail = state['saved_pilot_detail']
            if detail is not None:
                ui.label('Selected ORIGINAL audited receipt: ' +
                         detail['pilot_id'] + ' — ' + detail['status']).props(
                             'data-testid=pilot-history-selected')
                ui.label('Original exact source query: ' +
                         detail['exact_query']).props(
                             'data-testid=pilot-history-query')
                ui.label('Pilot-only reported matches: ' +
                         ('UNKNOWN' if detail['reported_matches'] is None
                          else str(detail['reported_matches'])) +
                         '; search execution remains unverified.').props(
                             'data-testid=pilot-history-provisional')
                if detail.get('accepted_translation') is not None:
                    ui.label('Source translation: ' +
                             detail['accepted_translation'])
                if detail.get('quota_status') is not None:
                    ui.label('Observed provider quota status: ' +
                             detail['quota_status'])
        # The source text enters only NiceGUI text widgets, not HTML.
        # All draft edits are host-memory mutations. A new preview is
        # mandatory after any edit, before the separate approval click.
        draft = state['strategy_draft']
        local_on = state.get('local_assistant_enabled', False)
        cloud_on = state.get('cloud_enabled', False)
        ui.label('Assistant mode: ' + ('Optional cloud AI' if cloud_on else 'Local Qwen3-1.7B' if local_on else 'No AI'))
        if local_on or cloud_on:
            ui.button('Use no AI', on_click=lambda: act('local_mode', False))
        if state.get('local_assistant_installed') and not local_on:
            ui.button('Use local AI', on_click=lambda: act('local_mode', True))
        if state.get('cloud_configured') and not cloud_on:
            ui.button('Choose optional cloud AI', on_click=lambda: act('cloud_mode'))
        if state.get('cloud_offer'):
            offer = state['cloud_offer']
            ui.label(offer['provider'] + ' · ' + offer['model'] + ' · ' + offer['cost_notice'])
            ui.label('Exact data to send')
            ui.label(offer['payload'])
            ui.button('Authorize and send this request', on_click=lambda rev=offer['revision']: act('cloud_confirm',rev))
        ui.separator()
        ui.label('Research Setup — draft only until explicitly approved').props(
            'data-testid=setup-heading')
        ui.label('OR between all enabled terms AND NO hidden restrictions; '
                 'the group union is also OR. No provider has been queried.').props(
                     'data-testid=setup-broad-or')
        if state['strategy_reconciliation_required']:
            ui.label('Approval outcome uncertain — retry the original request '
                     'unchanged to reconcile the saved run and query plans.').props(
                         'data-testid=setup-recovery')
            ui.button('Retry original strategy approval',
                      on_click=lambda: act('setup_approve')).props(
                          'data-testid=setup-approval-retry')
        else:
            if draft['preview'] is None:
                theme_input = ui.input('Research theme', value=draft['theme']).props(
                    'data-testid=setup-theme')
                approver_input = ui.input('Researcher approving', value=draft['approved_by']).props(
                    'data-testid=setup-approver')
                ui.button('Save research heading',
                          on_click=lambda: act('setup_edit', dict(
                              action='heading', data=dict(
                                  theme=theme_input.value,
                                  approved_by=approver_input.value)))).props(
                                      'data-testid=setup-save-heading')
                new_group = ui.input('New concept group name').props('data-testid=setup-group-input')
                ui.button('Add concept group', on_click=lambda: act('setup_edit', dict(
                    action='add_group', data=dict(label=new_group.value)))).props(
                        'data-testid=setup-add-group')
                for group in draft['groups']:
                    gid = group['group_id']
                    with ui.card():
                        label_input = ui.input('Group name', value=group['label'])
                        ui.button('Rename group', on_click=lambda gid=gid, box=label_input:
                                  act('setup_edit', dict(
                                      action='rename_group',
                                      data=dict(group_id=gid, label=box.value)))).props(
                                          'data-testid=setup-rename-group')
                        ui.button('Move group up', on_click=lambda gid=gid:
                                  act('setup_edit', dict(action='move_group',
                                      data=dict(group_id=gid, direction=-1))))
                        ui.button('Move group down', on_click=lambda gid=gid:
                                  act('setup_edit', dict(action='move_group',
                                      data=dict(group_id=gid, direction=1))))
                        ui.button('Remove group', on_click=lambda gid=gid:
                                  act('setup_edit', dict(action='remove_group',
                                      data=dict(group_id=gid)))).props('data-testid=setup-remove-group')
                        new_term = ui.input('New atomic term (single literal)')
                        ui.button('Add researcher term', on_click=lambda gid=gid, box=new_term:
                                  act('setup_edit', dict(action='add_term',
                                      data=dict(group_id=gid, text=box.value)))).props(
                                          'data-testid=setup-add-term')
                        for term in group['terms']:
                            tid = term['term_id']
                            with ui.card():
                                term_input = ui.input('Atomic term', value=term['text'])
                                if term['enabled']:
                                    if cloud_on:
                                        ui.button('Preview cloud term request', on_click=lambda gid=gid, tid=tid:
                                                  act('cloud_offer', dict(group_id=gid,term_id=tid)))
                                    if state.get('local_assistant_enabled'):
                                        ui.button('Ask local AI for terms', on_click=lambda gid=gid, tid=tid:
                                                  act('local_suggest', dict(group_id=gid, term_id=tid)))
                                    ui.button('Suggest term variants', on_click=lambda gid=gid, tid=tid:
                                              act('setup_edit', dict(action='suggest_variants',
                                                  data=dict(group_id=gid, term_id=tid))))
                                for offer in draft['suggestions']:
                                    if offer['source_term_id'] != tid or offer['status'] != 'pending':
                                        continue
                                    sid = offer['suggestion_id']
                                    ui.label(offer['reason'])
                                    wording = ui.input('Proposed variant', value=offer['text'])
                                    ui.button('Accept wording', on_click=lambda sid=sid, box=wording:
                                              act('setup_edit', dict(action='review_variant',
                                                  data=dict(suggestion_id=sid, decision='accept', text=box.value))))
                                    ui.button('Reject variant', on_click=lambda sid=sid:
                                              act('setup_edit', dict(action='review_variant',
                                                  data=dict(suggestion_id=sid, decision='reject'))))
                                origin_input = ui.select(
                                    {'researcher': 'Researcher', 'deterministic': 'Deterministic',
                                     'ai': 'AI-assisted (requires rationale)'},
                                    value=term['origin'], label='Term provenance')
                                rationale_input = ui.input(
                                    'Origin rationale / notes', value=term['rationale'])
                                enabled_input = ui.checkbox('Include term in OR union',
                                                            value=term['enabled'])
                                ui.button('Save term changes', on_click=lambda
                                          gid=gid, tid=tid, box=term_input,
                                          origin=origin_input, note=rationale_input,
                                          enabled=enabled_input:
                                          act('setup_edit', dict(action='edit_term',
                                              data=dict(group_id=gid, term_id=tid,
                                                        text=box.value, origin=origin.value,
                                                        rationale=note.value,
                                                        enabled=enabled.value)))).props(
                                                            'data-testid=setup-save-term')
                                ui.button('Move term up', on_click=lambda gid=gid, tid=tid:
                                          act('setup_edit', dict(action='move_term',
                                              data=dict(group_id=gid, term_id=tid,
                                                        direction=-1))))
                                ui.button('Move term down', on_click=lambda gid=gid, tid=tid:
                                          act('setup_edit', dict(action='move_term',
                                              data=dict(group_id=gid, term_id=tid,
                                                        direction=1))))
                                ui.button('Remove term', on_click=lambda gid=gid, tid=tid:
                                          act('setup_edit', dict(action='remove_term',
                                              data=dict(group_id=gid, term_id=tid)))).props(
                                                  'data-testid=setup-remove-term')
                ui.button('Preview exact broad-OR source queries',
                          on_click=lambda: act('setup_preview')).props(
                              'data-testid=setup-preview')
            else:
                ui.label('Exact-query preview is locked. To change any field, '
                         'choose Revise draft and preview again.').props(
                             'data-testid=setup-preview-locked')
                ui.button('Revise draft before approval',
                          on_click=lambda: act('setup_edit', dict(
                              action='revise_preview', data={}))).props(
                                  'data-testid=setup-revise')
                preview = draft['preview']
                if preview is not None:
                    ui.label('Strategy preview — NOT EXECUTED').props(
                        'data-testid=setup-preview-active')
                    ui.label('Concept groups: ' + str(preview['group_count']) +
                             '; enabled terms: ' + str(preview['active_term_count']))
                    ui.label('Filters/limits: ' + preview['limitations'])
                    for source in preview['sources']:
                        ui.label('Source: ' + source['name'] + ' — ' +
                                 source['coverage']).props('data-testid=setup-source-coverage')
                        ui.label('OR union preview: ' + source['union_query'])
                        for query in source['groups']:
                            if query['exact_query'] is not None:
                                ui.label('Group ' + query['label'] + ' exact query: ' +
                                         query['exact_query']).props(
                                             'data-testid=setup-exact-query')
                            else:
                                ui.label('Group ' + query['label'] +
                                         ' disabled/empty — not executable.')
                        for warning in source['warnings']:
                            ui.label('Compiler warning: ' + warning)
                    ui.label('Provider matches: UNKNOWN (not queried).').props(
                        'data-testid=setup-unknown-counts')
                    ui.button('Approve frozen strategy and create pending run',
                              on_click=lambda: act('setup_approve')).props(
                                  'data-testid=setup-approve')
        if state['last_strategy_admission'] is not None:
            done = state['last_strategy_admission']
            ui.label('Strategy version ' + str(done['version_number']) +
                     ' stored; pending run ' + done['run_id'] +
                     '. Queries planned but NOT EXECUTED.').props(
                         'data-testid=setup-approval-result')
        for item in state['runs']:
            rid = item['run_id']
            ui.button(f"Select run/version {item['version_number']} ({rid})",
                      on_click=lambda rid=rid: act('select_run', rid)).props('data-testid=select-run')
        if state['selected_run_id'] is None:
            ui.label('No run selected (explicit selection required).')
        else:
            ui.label('Selected run: ' + state['selected_run_id']).props('data-testid=selected-run')
            render_study_queue(ui,state,act,study_edits)
            data = state['report']
            if data is None:
                ui.label('Report not available.')
            else:
                ui.label('Current run projection (may differ from the retained export).')
                ui.label('Report status: ' + str(data['status'])).props('data-testid=report-status')
                unique = data['counts']['totals'].get('global_unique_publications')
                ui.label('Global unique publications: ' +
                         ('unknown' if unique is None else str(unique))).props('data-testid=unique-count')
                for item in data['queries']:
                    count = item['reported_matches']
                    ui.label('Exact query: ' + item['exact_query']).props('data-testid=exact-query')
                    ui.label('Reported matches: ' +
                             ('unknown' if count is None else str(count))).props('data-testid=query-count')
        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('Combined PubMed + Web of Science execution board '
                     '— all approved OR groups, without new source calls.').props(
                         'data-testid=run-board-heading')
            ui.button('Refresh whole-run evidence (offline, no provider calls)',
                      on_click=lambda: act('run_board_refresh')).props(
                          'data-testid=run-board-refresh')
            board = state['run_execution_board']
            if state['run_board_error'] is not None:
                ui.label('The run board could not validate the original '
                         'local ledger. Source status UNKNOWN; no '
                         'result or count is being inferred.').props(
                             'data-testid=run-board-error')
            elif board is None:
                ui.label('Select Refresh to read all source/group '
                         'checkpoints. No provider request is made.').props(
                             'data-testid=run-board-unread')
            else:
                ui.label('RUN INCOMPLETE — this is one read-only '
                         'reconciliation of saved evidence, not a source '
                         'query or an automatic search.').props(
                             'data-testid=run-board-incomplete')
                master = board.get('reviewed_retained_master')
                run_unique = board.get('reconciled_primary_run_unique_publications')
                ui.label('Saved source records, across group unions: ' +
                         str(board['totals']['source_record_sum']) +
                         '; identifiers lacking metadata: ' +
                         str(board['totals']['identifiers_missing_metadata']) +
                         '; unique publications in the reconciled primary run: ' +
                         ('NOT ESTABLISHED' if run_unique is None else str(run_unique))).props(
                             'data-testid=run-board-totals')
                if master:
                    ui.label(f"Reviewed retained publications: {master['retained_unique_publications']} "
                             f"across {master['source_count']} original records. Sum of group counts: "
                             f"{master['group_count_sum']}.").props('data-testid=reviewed-retained-count')
                if board.get('pubmed_retry_not_before_utc'):
                    ui.label('PubMed requested that the next request be sent at or after ' +
                             board['pubmed_retry_not_before_utc'] + ' (UTC).')
                ui.label('Primary source enumerations reconciled: ' +
                         str(board['primary_source_enumerations_reconciled']) +
                         '; available source metadata retained: ' +
                         str(board['available_primary_metadata_acquired']) +
                         '; complete research search: FALSE.').props(
                             'data-testid=run-board-coverage')
                if not board['approved_query_inventory_matches']:
                    ui.label('Stored queries could not be matched to the approved strategy. '
                             'Run-wide retrieval coverage is unknown.').props(
                                 'data-testid=run-board-plan-mismatch')
                ui.label('Provisional publication identity hypotheses: ' +
                         str(board['totals']['publication_identity_hypotheses']) +
                         ' (NOT a final deduplicated result).')
                for group in board['groups']:
                    group_unique = master['group_counts'][group['group_id']] if master else (0 if run_unique == 0 and group['sources'] else None)
                    ui.label('Concept group ' + group['label'] + ' — reviewed retained publications: ' +
                             ('NOT ESTABLISHED' if group_unique is None else str(group_unique))).props(
                                 'data-testid=run-board-group')
                    for item in group['sources']:
                        provider = ('PubMed' if item['source_name']=='pubmed'
                                    else 'Web of Science Starter')
                        reported = ('UNKNOWN' if
                                    item['reported_matches'] is None else
                                    str(item['reported_matches']))
                        ui.label(provider + ' • ' + item['source_stage'] +
                                 ' • reported hits ' + reported +
                                 ' • retrieved source IDs ' +
                                 str(item['identifiers_retrieved']) +
                                 ' • saved metadata ' +
                                 str(item['metadata_records_retained']) +
                                 ' • count check ' +
                                 item['count_reconciliation']).props(
                                     'data-testid=run-board-source-row')
                        ui.label('Exact stored source expression: ' +
                                 item['exact_query']).props(
                                     'data-testid=run-board-exact-query')
                        if item['warnings']:
                            ui.label('Pending source issues: ' +
                                     ', '.join(item['warnings']))
                        step = item['next_step']
                        allowed = True
                        if step == 'preview_wos':
                            allowed = state['wos_profile_configured']
                        elif step == 'preview_pubmed_metadata':
                            allowed = state['pubmed_profile_configured']
                        if allowed:
                            qid = item['query_id']
                            revision = board['revision']
                            ui.button('Open safe next-step preview / saved '
                                      'checkpoint: ' + provider,
                                      on_click=lambda qid=qid, revision=revision:
                                          act('run_board_select',
                                              {'query_id':qid,'revision':revision})).props(
                                                  'data-testid=run-board-next-step')
                        else:
                            ui.label('Provider profile not configured; '
                                     'original local counts remain readable '
                                     'without external requests.')
                ui.label('This board cannot certify full source snapshots, '
                         'missing abstracts, deduplication, official society '
                         'coverage or completed Preferred Reporting Items for '
                         'Systematic Reviews and Meta-Analyses searches.')

        if state['project'] is not None:
            ui.separator()
            ui.label('Durable candidate-key index — optional LOCAL '
                     'derivative of original source records. It is not '
                     'a deduplicated result or a completed search.').props(
                         'data-testid=candidate-index-heading')
            ui.button('Inspect current index status (READ-ONLY)',
                      on_click=lambda: act('candidate_index_inspect')).props(
                          'data-testid=candidate-index-inspect')
            if state['candidate_index_error'] is not None:
                ui.label('Index receipt not independently verified. '
                         'An interrupted writer may have committed. '
                         'Inspect current durable status before choosing '
                         'another action; never replay an old consent.').props(
                             'data-testid=candidate-index-error')
            index=state['candidate_index_state']
            if index is None:
                ui.label('Index status has not been inspected in this '
                         'session. The original source-based candidate '
                         'queue remains available offline.')
            else:
                ui.label('Index: ' + index['status'] +
                         ' • original source records: ' +
                         str(index['source_records']) +
                         ' • processed: ' +
                         str(index['processed_records']) +
                         ' • cached keys: ' +
                         str(index['indexed_keys']) +
                         ' • unsupported layouts: ' +
                         str(index['unsupported_records']) +
                         ' • search verified: NO • final unique '
                         'publications: UNKNOWN.').props(
                             'data-testid=candidate-index-status')
                if index['status']=='stale':
                    ui.label('Original source evidence changed. '
                             'This generation is not usable; '
                             'explicit rebuild required.').props(
                                 'data-testid=candidate-index-stale')
                if index['status']=='ready':
                    ui.label('Cache is ready for exact-key candidate '
                             'hints only. Reviewer decisions remain '
                             'separate and source-backed.').props(
                                 'data-testid=candidate-index-ready')
                offer=state['candidate_index_offer']
                if offer is None:
                    ui.button('Preview a NEW project-wide source-key '
                              'generation (NO network)',on_click=lambda:
                              act('candidate_index_offer','start')).props(
                                  'data-testid=candidate-index-start-offer')
                    if index['status']=='building':
                        ui.button('Preview ONE bounded continuation '
                                  'batch (up to 128 records)',on_click=lambda:
                                  act('candidate_index_offer','advance')).props(
                                      'data-testid=candidate-index-advance-offer')
                else:
                    ui.label('Unsent ' + offer['action'] +
                             ' • source records ' +
                             str(offer['source_records']) +
                             ' • already processed ' +
                             str(offer['processed_records']) +
                             '. Confirmation writes only derived '
                             'index rows and an audit receipt.').props(
                                 'data-testid=candidate-index-offer')
                    researcher=ui.input('Researcher confirming local index '
                                        'work',value='')
                    ui.button('CONFIRM ' + offer['action'] +
                              ' (ONE bounded SQLite transaction)',
                              on_click=lambda box=researcher:
                                  act('candidate_index_confirm',box.value)).props(
                                      'data-testid=candidate-index-confirm')
                    ui.button('Dismiss uncommitted index action',
                              on_click=lambda:
                              act('candidate_index_dismiss')).props(
                                  'data-testid=candidate-index-dismiss')
            last=state['candidate_index_last_receipt']
            if last is not None:
                ui.label('Last independently reconciled index action: ' +
                         last['action'] + ' • status at receipt: ' +
                         last['status'] + ' • processed: ' +
                         str(last['processed_records']) +
                         '. This does not establish deduplication.').props(
                             'data-testid=candidate-index-outcome')

        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('Run-specific durable potential-duplicate PAIR '
                     'index — local candidate hints, never a unique '
                     'publication count or automatic merge.').props(
                         'data-testid=candidate-pairs-heading')
            ui.button('Inspect selected-run pair checkpoint '
                      '(READ-ONLY, OFFLINE)',on_click=lambda:
                      act('candidate_pairs_inspect')).props(
                          'data-testid=candidate-pairs-inspect')
            if state['candidate_pair_error'] is not None:
                ui.label('Pair index outcome must be re-inspected from '
                         'the original project database. An interrupted '
                         'writer may already have committed. No prior '
                         'confirmation can be replayed.').props(
                             'data-testid=candidate-pairs-error')
            pair_state=state['candidate_pair_state']
            if pair_state is None:
                ui.label('No pair-index checkpoint inspected for this '
                         'run in the current session. The original '
                         'source-backed review queue remains usable.')
            else:
                ui.label('Pair index: '+pair_state['status']+
                         ' • processed source/field keys: '+
                         str(pair_state['processed_source_keys'])+
                         ' • matching-key hints examined: '+
                         str(pair_state['emitted_hints'])+
                         ' • distinct candidate pairs: '+
                         str(pair_state['unique_pairs'])+
                         ' • source-key cache ready: '+
                         ('YES' if pair_state['index_ready'] else 'NO')+
                         '. All numbers are provisional evidence '
                         'counts, not verified publications.').props(
                             'data-testid=candidate-pairs-status')
                if not pair_state['index_ready']:
                    ui.label('PREREQUISITE: Complete the project-wide '
                             'source-key index above first. An empty, '
                             'building or stale source-key index cannot '
                             'be used to build pair hints.').props(
                                 'data-testid=candidate-pairs-prerequisite')
                if pair_state['status']=='stale':
                    ui.label('Original source/index/association/review '
                             'evidence has changed. This pair generation '
                             'cannot be used; an explicit rebuild is '
                             'required.').props(
                                 'data-testid=candidate-pairs-stale')
                if pair_state['status']=='ready_keys_only':
                    ui.label('Exact-key pair hints are indexed. The '
                             'researcher review queue separately joins '
                             'all original audited match/rejection '
                             'receipts; the pair cache alone is not '
                             'the complete reviewer history.').props(
                                 'data-testid=candidate-pairs-ready')
                pair_offer=state['candidate_pair_offer']
                if pair_offer is None:
                    if pair_state['index_ready']:
                        ui.button(
                            'Preview a NEW pair-index generation '
                            '(replaces derived hints for THIS run only)',
                            on_click=lambda:
                                act('candidate_pairs_offer','start')
                        ).props('data-testid=candidate-pairs-start-offer')
                    if (pair_state['index_ready'] and
                            pair_state['status']=='building'):
                        ui.button(
                            'Preview ONE bounded pair-index batch '
                            '(up to 64 keys / 128 matching hints)',
                            on_click=lambda:
                                act('candidate_pairs_offer','advance')
                        ).props('data-testid=candidate-pairs-advance-offer')
                else:
                    ui.label('Uncommitted '+pair_offer['action']+
                             ' • selected run '+pair_offer['run_id']+
                             ' • previously emitted matching hints '+
                             str(pair_offer['emitted_hints'])+
                             '. Exactly ONE confirmed local transaction '
                             'will run. Start may clear only derived '
                             'pair hints; original sources and reviewer '
                             'decisions remain unchanged.').props(
                                 'data-testid=candidate-pairs-offer')
                    researcher=ui.input('Researcher confirming '
                                        'pair-index work',value='')
                    ui.button('CONFIRM '+pair_offer['action']+
                              ' — ONE bounded, audited transaction',
                              on_click=lambda box=researcher:
                                  act('candidate_pairs_confirm',box.value)
                    ).props('data-testid=candidate-pairs-confirm')
                    ui.button('Dismiss uncommitted pair-index action',
                              on_click=lambda:
                                  act('candidate_pairs_dismiss')).props(
                                      'data-testid=candidate-pairs-dismiss')
            last_pair=state['candidate_pair_last_receipt']
            if last_pair is not None:
                ui.label('Last independently reconciled pair-index '
                         'receipt: '+last_pair['action']+
                         ' • state '+last_pair['status']+
                         ' • distinct candidate pairs '+
                         str(last_pair['unique_pairs'])+
                         '. This does not establish deduplication.').props(
                             'data-testid=candidate-pairs-outcome')

        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('Project-wide POTENTIAL DUPLICATE queue — exact '
                     'citation-key hints and historical reviewer receipts, '
                     'NOT automatically merged publications.').props(
                         'data-testid=candidate-queue-heading')
            ui.label('Every retained project run contributes to detection; '
                     'only pairs touching the current run are listed. '
                     'Title, Digital Object Identifier (DOI), PubMed '
                     'identifier and accession matches are not proof. '
                     'Unmaterialised/unsupported records and excessive '
                     'candidate volumes are disclosed or refused, never '
                     'silently skipped. No fuzzy discovery yet.').props(
                         'data-testid=candidate-queue-scope')
            ui.button('Refresh potential duplicates (READ-ONLY, OFFLINE)',
                      on_click=lambda: act('candidate_queue_refresh')).props(
                          'data-testid=candidate-queue-refresh')
            if state['candidate_queue_error'] is not None:
                ui.label('The project candidate queue could not be '
                         'validated. Reinspect current source, identity '
                         'and audit evidence before making decisions.').props(
                             'data-testid=candidate-queue-error')
            candidate_queue = state['candidate_queue']
            if candidate_queue is not None:
                ui.label('Candidate retrieval backend: ' +
                         candidate_queue['index_backend'] +
                         ' • index status: ' +
                         candidate_queue['index_status'] +
                         '. When a generation is not ready, the '
                         'original source-based read is used, not an '
                         'incomplete cache.').props(
                             'data-testid=candidate-queue-backend')
                ui.label('Potential source-record pairs touching this run: ' +
                         str(candidate_queue['candidate_pair_total']) +
                         '; total project records: ' +
                         str(candidate_queue['project_source_records']) +
                         '; not yet materialised: ' +
                         str(candidate_queue['unmaterialised_project_records']) +
                         '; unsupported layouts: ' +
                         str(candidate_queue['unsupported_project_records']) +
                         '. Final unique publications: UNKNOWN.').props(
                             'data-testid=candidate-queue-counts')
                ui.label('Showing ' + str(len(candidate_queue['rows'])) +
                         ' candidate pairs (up to 20). This is exact-key '
                         'or previous-receipt discovery, NOT exhaustive '
                         'biomedical deduplication.').props(
                             'data-testid=candidate-queue-page')
                for entry in candidate_queue['rows']:
                    with ui.card():
                        ui.label('Possible source pair • ' +
                                 ' / '.join(s['source_name'] + ':' +
                                           s['source_record_id']
                                           for s in entry['sources'])).props(
                                               'data-testid=candidate-queue-row')
                        ui.label('Matching original fields: ' +
                                 (', '.join(entry['matched_exact_fields'])
                                  if entry['matched_exact_fields'] else
                                  '(previous reviewer receipt only)') +
                                 ' • decision state ' +
                                 entry['candidate_status'] +
                                 ' • recorded pair decisions ' +
                                 str(entry['prior_decisions_recorded'])).props(
                                     'data-testid=candidate-queue-evidence')
                        for warning in entry['warnings']:
                            ui.label('Candidate review warning: ' +
                                     warning).props(
                                         'data-testid=candidate-queue-warning')
                        if entry['both_in_selected_run']:
                            first, second = entry['retrieval_ids']
                            queue_revision = candidate_queue['revision']
                            ui.button(
                                'Review this exact pair using existing safeguards',
                                on_click=lambda a=first,b=second,r=queue_revision:
                                    act('candidate_queue_review',{
                                        'left':a,'right':b,'revision':r})).props(
                                            'data-testid=candidate-queue-review')
                        else:
                            first, second = entry['retrieval_ids']
                            ui.button('Compare records from two runs', on_click=
                                      lambda a=first,b=second,r=candidate_queue['revision']:
                                      act('candidate_queue_cross_review', {
                                          'left':a,'right':b,'revision':r})).props(
                                              'data-testid=candidate-queue-crossrun')
                if candidate_queue['next_after_pair'] is not None:
                    next_pair = candidate_queue['next_after_pair']
                    queue_revision = candidate_queue['revision']
                    ui.button('Next 20 project candidate pairs (OFFLINE)',
                              on_click=lambda p=next_pair,r=queue_revision:
                                  act('candidate_queue_next',{
                                      'cursor':p,'revision':r})).props(
                                          'data-testid=candidate-queue-next')
        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('Provisional publication results — local, paginated, '
                     'and NOT a verified deduplicated master list.').props(
                         'data-testid=publication-heading')
            ui.label('Each saved source record initially represents a '
                     'separate REVIEW-REQUIRED publication identity. '
                     'Identical titles, digital object identifiers or '
                     'supplement references are NOT merged automatically. '
                     'Original provider records, counts and memberships '
                     'remain unchanged. No abstracts or source metadata '
                     'are exported by this view.').props(
                         'data-testid=publication-scope')
            ui.button('Refresh provisional results from first page (OFFLINE)',
                      on_click=lambda: act('publication_refresh')).props(
                          'data-testid=publication-refresh')
            if state['publication_error'] is not None:
                ui.label('Publication results or preparation cannot be '
                         'verified against the current local source/identity '
                         'evidence. Refresh and inspect original records; '
                         'do not claim success or retry a stale confirmation.').props(
                             'data-testid=publication-error')
            offer = state['publication_materialisation_offer']
            if offer is not None:
                ui.label('Unsent local preparation: ' +
                         str(offer['batch_count']) +
                         ' individual source records, out of ' +
                         str(offer['unmaterialised_retrievals']) +
                         ' still without publication identities. '
                         'This creates only provisional REVIEW-REQUIRED '
                         'identities; it sends ZERO provider requests and '
                         'makes NO deduplication decision.').props(
                             'data-testid=publication-materialise-preview')
                if offer['batch_count']:
                    researcher = ui.input('Researcher recording provisional '
                                          'materialisation',value='')
                    ui.button('CONFIRM one bounded local identity batch',
                              on_click=lambda box=researcher:
                                  act('publication_materialise_confirm',box.value)).props(
                                      'data-testid=publication-materialise-confirm')
                else:
                    ui.label('All currently saved source records in this '
                             'run already have identity links. This does NOT '
                             'mean duplicates have been resolved.').props(
                                 'data-testid=publication-materialise-none')
                ui.button('Dismiss unsent preparation',on_click=lambda:
                          act('publication_materialise_dismiss')).props(
                              'data-testid=publication-materialise-dismiss')
            else:
                ui.button('Preview creation of up to 64 review-required '
                          'identities from saved records (NO NETWORK)',
                          on_click=lambda: act('publication_materialise_offer')).props(
                              'data-testid=publication-materialise-offer')
            last = state['publication_materialisation_last_outcome']
            if last is not None:
                ui.label('Last confirmed local batch: ' +
                         str(last['materialised_in_batch']) +
                         ' identity hypotheses committed; unmaterialised '
                         'source records remaining at receipt: ' +
                         str(last['unmaterialised_retrievals_remaining']) +
                         '. Refresh to read CURRENT results. Verified '
                         'global unique publications: UNKNOWN.').props(
                             'data-testid=publication-materialise-outcome')
            ui.separator()
            ui.label('Optional bounded 128-record preparation — '
                     'ONE explicit approval, at most TWO original '
                     '64-record transactions. The first transaction '
                     'may have committed even if the second fails. '
                     'NO automatic duplicate merging or further '
                     'batch execution.').props(
                         'data-testid=publication-window-heading')
            if state['publication_window_error'] is not None:
                ui.label('Two-batch preparation is not currently verified. '
                         'No success can be inferred from an uncertain '
                         'worker response. Inspect the original saved '
                         'project before preparing anything else.').props(
                             'data-testid=publication-window-error')
            if state['publication_window_reinspect_required']:
                ui.label('RECOVERY REQUIRED: zero, one or two 64-record '
                         'batches may have committed. The previous '
                         'approval was consumed and MUST NOT be retried.').props(
                             'data-testid=publication-window-recovery')
                ui.button('Inspect durable source/identity counts '
                          'after interrupted preparation (READ-ONLY)',
                          on_click=lambda:
                              act('publication_window_inspect')).props(
                                  'data-testid=publication-window-reinspect')
            else:
                window_offer=state['publication_window_offer']
                if window_offer is not None:
                    ui.label('UNSENT original-source approval: ' +
                             str(window_offer['proposed_source_records']) +
                             ' review-required provisional identities in ' +
                             str(window_offer['batch_count']) +
                             ' separate commits of up to 64 each. ' +
                             'Currently unmaterialised originals: ' +
                             str(window_offer['unmaterialised_retrievals']) +
                             '. NO provider requests, verified unique '
                             'count or unattended processing.').props(
                                 'data-testid=publication-window-preview')
                    if window_offer['proposed_source_records'] > 0:
                        author=ui.input('Researcher explicitly authorising '
                                        'THIS finite original-source window',
                                        value='').props('data-testid=publication-window-actor')
                        ui.button('CONFIRM this finite two-batch '
                                  'publication preparation',
                                  on_click=lambda field=author:
                                      act('publication_window_confirm',
                                          field.value)).props(
                                              'data-testid=publication-window-confirm')
                    else:
                        ui.label('No unmaterialised originals remain '
                                 'in this run. This does NOT indicate '
                                 'completed deduplication.').props(
                                     'data-testid=publication-window-no-work')
                    ui.button('Dismiss two-batch offer without writing',
                              on_click=lambda:
                                  act('publication_window_dismiss')).props(
                                      'data-testid=publication-window-dismiss')
                else:
                    ui.button('Preview up to 128 new provisional '
                              'identities in one finite consent window '
                              '(READ-ONLY)',
                              on_click=lambda:
                                  act('publication_window_offer')).props(
                                      'data-testid=publication-window-offer')
                    ui.button('Inspect current unmaterialised originals '
                              '(READ-ONLY)',
                              on_click=lambda:
                                  act('publication_window_inspect')).props(
                                      'data-testid=publication-window-inspect')
            last_window=state['publication_window_last_outcome']
            if last_window is not None:
                ui.label('Last independently verified local two-batch '
                         'receipt: ' +
                         str(last_window['materialised_in_session']) +
                         ' independent provisional identities in ' +
                         str(last_window['committed_batches']) +
                         ' original transactions. Originals still '
                         'unmaterialised at receipt: ' +
                         str(last_window['unmaterialised_retrievals_remaining']) +
                         '. Verified unique publications: UNKNOWN.').props(
                             'data-testid=publication-window-outcome')
            inspected_window=state['publication_window_last_inspection']
            if inspected_window is not None:
                ui.label('Durable source records: ' +
                         str(inspected_window['source_records_retained']) +
                         '; remaining without publication identities: ' +
                         str(inspected_window['unmaterialised_retrievals']) +
                         '; current provisional publication hypotheses: ' +
                         str(inspected_window['existing_publication_hypotheses']) +
                         '. Inspection did NOT authorise any change.').props(
                             'data-testid=publication-window-inspection')
            view = state['publication_page']
            if view is None:
                ui.label('No CURRENT results snapshot displayed. Choose '
                         'Refresh; a saved record without an identity '
                         'is reported separately, never silently omitted.')
            else:
                ui.label('Current run: saved source-record metadata ' +
                         str(view['retrieved_source_records']) +
                         '; provisional linked publication identities ' +
                         str(view['provisional_publication_identities']) +
                         '; still unmaterialised ' +
                         str(view['unmaterialised_source_records']) +
                         '; VERIFIED global unique publications: UNKNOWN.').props(
                             'data-testid=publication-counts')
                reviewed_count = view.get('reviewed_retained_unique_publications')
                if reviewed_count is not None:
                    ui.label(f'Researcher-reviewed union of retained publications: {reviewed_count}.')
                page_status = ('All remain provisional; unseen later pages are not zero results.'
                               if reviewed_count is None else 'The retained master is supported by recorded pair decisions.')
                ui.label('This page has ' + str(len(view['rows'])) +
                         ' entries, maximum 20. ' + page_status).props(
                             'data-testid=publication-page-status')
                if not view['rows']:
                    ui.label('No provisional identities on this page. '
                             'Inspect any unmaterialised records before '
                             'interpreting an empty view.').props(
                                 'data-testid=publication-page-empty')
                for row in view['rows']:
                    with ui.card():
                        ui.label('Publication hypothesis: ' +
                                 row['publication_id']).props(
                                     'data-testid=publication-row')
                        ui.label('Title: ' +
                                 (row['title'] if row['title'] is not None
                                  else '(not resolved from original sources)') +
                                 ' • title evidence: ' + row['title_status']).props(
                                     'data-testid=publication-title')
                        ui.label('Sources: ' + ', '.join(row['source_names']) +
                                 '; source records ' +
                                 str(row['original_source_records_in_run']) +
                                 '; review-required links ' +
                                 str(row['review_required_links']) +
                                 '; confirmed individual links ' +
                                 str(row['confirmed_links']) +
                                 '; final identity NOT VERIFIED.').props(
                                     'data-testid=publication-provisional')
                        for membership in row['group_memberships']:
                            ui.label('Original group membership: ' +
                                     membership['group_label'] +
                                     ' • ' + membership['source_name']).props(
                                         'data-testid=publication-membership')
                        pid = row['publication_id']
                        revision = view['revision']
                        ui.button('Inspect original source evidence',
                                  on_click=lambda pid=pid, revision=revision:
                                      act('publication_detail',
                                          {'publication_id':pid,'revision':revision})).props(
                                              'data-testid=publication-detail-open')
                if view['next_after_publication_id'] is not None:
                    cursor = view['next_after_publication_id']
                    revision = view['revision']
                    ui.button('Next 20 provisional publications (OFFLINE)',
                              on_click=lambda cursor=cursor, revision=revision:
                                  act('publication_next',
                                      {'cursor':cursor,'revision':revision})).props(
                                          'data-testid=publication-next')
                detail = state['publication_detail']
                if detail is not None:
                    ui.separator()
                    ui.label('LOCAL SOURCE PROVENANCE — ' +
                             detail['publication']['publication_id'] +
                             '. A displayed value is not validation of '
                             'bibliographic identity or export rights.').props(
                                 'data-testid=publication-detail-heading')
                    render_study_panel(ui, state, detail, act, study_edits)
                    for omitted in detail['suppressed_chosen_fields']:
                        ui.label('Saved field ' + omitted['field'] +
                                 ' deliberately WITHHELD: its source path '
                                 'is not a validated citation-only path; '
                                 'it may refer to protected abstract '
                                 'or other non-display content.').props(
                                     'data-testid=publication-field-withheld')
                    for chosen in detail['chosen_source_fields']:
                        ui.label('Researcher-chosen ' + chosen['field'] +
                                 ' = ' + str(chosen['value']) +
                                 ' • state ' + chosen['status'] +
                                 ' • source retrieval ' +
                                 chosen['retrieval_id']).props(
                                     'data-testid=publication-chosen-field')
                    for source in detail['source_retrievals']:
                        ui.label('Original source: ' + source['source_name'] +
                                 ' • provider identifier ' + source['source_record_id'] +
                                 ' • link status ' + source['decision_status'] +
                                 ' • abstract availability ' +
                                 source['abstract_status'] +
                                 ' • rights ' + source['rights_status']).props(
                                     'data-testid=publication-source-detail')
                        for field in source['fields']:
                            ui.label(field['field'] + ': ' +
                                     ('(unavailable)' if field['value'] is None
                                      else field['value']) +
                                     ' • original field status ' +
                                     field['status'] +
                                     ' • source path ' +
                                     str(field['source_path'])).props(
                                         'data-testid=publication-field-detail')
                        for membership in source['memberships']:
                            ui.label('Source/group provenance: ' +
                                     membership['group_label'] +
                                     ' • original query state ' +
                                     membership['query_status']).props(
                                         'data-testid=publication-source-membership')
                        if source['included_in_selected_run']:
                            current_retrieval = source['retrieval_id']
                            ui.button(
                                'Select this exact source record for duplicate comparison',
                                on_click=lambda rid=current_retrieval:
                                    act('candidate_choose_source', rid)).props(
                                        'data-testid=candidate-choose-source')
                            if source['decision_status'] == 'confirmed_match':
                                ui.button(
                                    'Preview reversal of CURRENT association (OFFLINE)',
                                    on_click=lambda rid=current_retrieval:
                                        act('candidate_reversal_offer', rid)).props(
                                            'data-testid=candidate-reversal-offer')
                    ui.label('Full abstract display and permission-aware '
                             'bibliography export remain future work. '
                             'No duplicate-candidate decision has been '
                             'made by reading this page.').props(
                                 'data-testid=publication-not-exported')
                if state['candidate_error'] is not None:
                    ui.label('Candidate decision outcome cannot be verified. '
                             'Reopen the current source receipts and audit '
                             'history; do NOT resend an old confirmation.').props(
                                 'data-testid=candidate-error')
                if state['candidate_first'] is not None:
                    ui.label('First selected exact source retrieval: ' +
                             state['candidate_first']['retrieval_id'] +
                             '. Open another publication source detail '
                             'on THIS page and select a second record.').props(
                                 'data-testid=candidate-first')
                pair = state['candidate_offer']
                if pair is not None:
                    ui.separator()
                    ui.label('Publication comparison — explicit HUMAN REVIEW. '
                             'No automatic DOI/title/supplement merge. '
                             'Every matching field is only evidence.').props(
                                 'data-testid=candidate-heading')
                    for source in pair['sources']:
                        ui.label('Reviewed source: ' + source['source_name'] +
                                 ' • ' + source['source_record_id'] +
                                 ' • retrieval ' + source['retrieval_id']).props(
                                     'data-testid=candidate-source')
                    for field in pair['comparison']:
                        ui.label(field['field'] + ': ' +
                                 field['comparison'] +
                                 ' • source A ' + str(field['left']['value']) +
                                 ' (' + field['left']['status'] + ')' +
                                 ' • source B ' + str(field['right']['value']) +
                                 ' (' + field['right']['status'] + ')').props(
                                     'data-testid=candidate-comparison')
                    for warning in pair['warnings']:
                        ui.label('WARNING — ' + warning).props(
                            'data-testid=candidate-warning')
                    ui.label('Pair status: ' + pair['status'] +
                             '; previous decision receipts: ' +
                             str(pair['prior_decision_count']) +
                             '; earlier receipts not shown here: ' +
                             str(pair['prior_decisions_omitted']) +
                             '. The full immutable history remains in the project.')
                    for previous in pair['recent_decisions']:
                        ui.label('Previous audit ' + str(previous['event_id']) +
                                 ': ' + previous['status'] + ' • ' +
                                 previous['actor'] + ' • ' +
                                 previous['evidence']).props(
                                     'data-testid=candidate-audit')
                    reviewer = ui.input('Researcher recording this decision',
                                        value='')
                    rationale = ui.input(
                        'Specific bibliographic evidence or reason '
                        'for this decision', value='')
                    acknowledge = ui.checkbox(
                        'I reviewed and acknowledge every displayed '
                        'comparison warning', value=False)
                    if not pair['pair_already_associated']:
                        first_source, second_source = pair['retrieval_ids']
                        if pair.get('cross_run'):
                            for source in pair['sources']:
                                ui.label(source['source_name'] + ' · run ' + source['run_id'])
                        for label, source_id, position in (
                            ('Associate first source with second publication', first_source, 'first'),
                            ('Associate second source with first publication', second_source, 'second')):
                            if pair.get('cross_run') and not any(
                                    source['retrieval_id'] == source_id and source['run_id'] == pair['run_id']
                                    for source in pair['sources']):
                                continue
                            ui.button('Confirm match: ' + label, on_click=
                                      lambda rid=source_id, box=reviewer, revision=pair['revision'],
                                      note=rationale, ack=acknowledge:
                                      act('candidate_review_decide', {
                                          'decision':'confirmed_match', 'offer_revision':revision,
                                          'move_retrieval_id':rid, 'actor':box.value,
                                          'evidence':note.value, 'acknowledged':ack.value})).props(
                                              'data-testid=candidate-match-' + position)
                        ui.button('CONFIRM NOT THE SAME PUBLICATION '
                                  '(no source record moved)', on_click=
                                  lambda box=reviewer, note=rationale,
                                  ack=acknowledge, revision=pair['revision']:
                                  act('candidate_review_decide', {
                                      'decision':'rejected_match','offer_revision':revision,
                                      'move_retrieval_id':None,
                                      'actor':box.value,'evidence':note.value,
                                      'acknowledged':ack.value})).props(
                                          'data-testid=candidate-reject')
                    else:
                        ui.label('Both records currently share one '
                                 'publication identity. Rejection requires '
                                 'a separate review of the CURRENT reversible '
                                 'association first.')
                    ui.button('Dismiss this uncommitted comparison',
                              on_click=lambda:
                              act('candidate_review_dismiss')).props(
                                  'data-testid=candidate-dismiss')
                undo = state['reversal_offer']
                if undo is not None:
                    ui.separator()
                    ui.label('Reversal PREVIEW only — retrieval ' +
                             undo['retrieval_id'] +
                             ', current association audit event ' +
                             str(undo['association_event_id']) +
                             '. Restores its original publication identity. '
                             'No source metadata or audit event is deleted.').props(
                                 'data-testid=candidate-reversal-preview')
                    ui.label('Original association evidence: ' +
                             undo['original_decision_evidence']).props(
                                 'data-testid=candidate-reversal-evidence')
                    reverser = ui.input(
                        'Researcher recording reversal', value='')
                    reason = ui.input(
                        'Reason for reversing current association', value='')
                    ui.button('CONFIRM reverse CURRENT association',
                              on_click=lambda a=reverser, e=reason:
                              act('candidate_reversal_confirm', {
                                  'actor':a.value,
                                  'evidence':e.value})).props(
                                      'data-testid=candidate-reversal-confirm')
                    ui.button('Dismiss unsent reversal', on_click=lambda:
                              act('candidate_review_dismiss')).props(
                                  'data-testid=candidate-reversal-dismiss')
                outcome = state['candidate_last_outcome']
                if outcome is not None:
                    ui.label('Last decision independently reconciled '
                             'against original SQLite audit event ' +
                             str(outcome['verified_audit_event_id']) +
                             ' • action ' + outcome['action'] +
                             '. Final unique-publication count remains '
                             'UNKNOWN; refresh source evidence for next review.').props(
                                 'data-testid=candidate-result')

        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('Bounded whole-run source coordination — '
                     'EXPLICIT CONFIRMATION required before ANY provider '
                     'request. Experimental, not unattended.').props(
                         'data-testid=run-coordination-heading')
            ui.label('Already prepared provider stages may run in sequence, '
                     'at most TWO stages per consent. The original source '
                     'services enforce the request budgets and stop on '
                     'unknown outcomes. Untouched PubMed queries still '
                     'require explicit Create Date coverage; unprepared '
                     'Web of Science queries still require separate '
                     'licensed metadata retention consent.')
            if state['run_coordination_pending']:
                ui.label('Supervised coordinator state: ' +
                         state['run_coordination_worker_state'] +
                         '; error: ' +
                         str(state['run_coordination_worker_error'])).props(
                             'data-testid=run-coordination-worker')
                ui.label('Running does NOT imply provider access succeeded. '
                         'An interrupted process or uncertain request '
                         'must be inspected, never automatically repeated.')
                progress=state['run_execution_board']
                if progress is not None:
                    for item in progress['queries']:
                        ui.label(item['source_name'] + ' • ' +
                                 item['group_id'] + ' • ' +
                                 item['source_stage'] +
                                 ' • IDs saved ' +
                                 str(item['identifiers_retrieved']) +
                                 ' • metadata rows ' +
                                 str(item['metadata_records_retained'])).props(
                                     'data-testid=run-coordination-progress')
                ui.button('Read durable run progress (NO provider call)',
                          on_click=lambda: act('run_coord_poll')).props(
                              'data-testid=run-coordination-poll')
                if state['run_coordination_worker_state'] != 'running':
                    ui.button('Reconcile STOPPED source coordinator with '
                              'original saved checkpoint evidence',
                              on_click=lambda: act('run_coord_reconcile')).props(
                                  'data-testid=run-coordination-reconcile')
            elif state['run_coordination_offer'] is not None:
                offer=state['run_coordination_offer']
                tasks=offer['tasks']
                if tasks:
                    ui.label('Frozen, unsent work: ' + str(len(tasks)) +
                             ' source stages. Maximum combined external '
                             'HTTP requests: ' +
                             str(offer['max_external_requests']) +
                             '. Each original provider limiter may stop '
                             'earlier due to quotas, network errors, '
                             'count drift or an interrupted request.').props(
                                 'data-testid=run-coordination-budget')
                    for item in tasks:
                        ui.label('To execute after confirmation: ' +
                                 item['source_name'] + ' • group ' +
                                 item['group_id'] + ' • ' +
                                 item['action'] + ' • exact query ' +
                                 item['exact_query'] +
                                 ' • at most ' +
                                 str(item['max_requests']) +
                                 ' source requests.').props(
                                     'data-testid=run-coordination-proposal')
                    ui.label('One approval authorises ONLY the above '
                             'displayed existing source stages. No '
                             'new WoS retention is authorised, no '
                             'filters are applied, and no provider '
                             'quota revalidation is assumed. Your '
                             'application must remain open.').props(
                                 'data-testid=run-coordination-consent')
                    ui.button('CONFIRM one bounded source-coordination session',
                              on_click=lambda: act('run_coord_confirm')).props(
                                  'data-testid=run-coordination-confirm')
                else:
                    ui.label('No already-authorised executable source '
                             'stages are available with current local '
                             'provider configuration. Complete the '
                             'existing source-specific preparation or '
                             'recovery actions first.').props(
                                 'data-testid=run-coordination-no-work')
                for item in offer['preview']['blocked_tasks']:
                    ui.label('Manual prerequisite: ' +
                             item['source_name'] + ' • ' +
                             item['group_id'] + ' • ' +
                             item['blocker']).props(
                                 'data-testid=run-coordination-blocked')
                for item in offer['unavailable']:
                    ui.label('Missing local provider profile: ' +
                             item['source_name'] + ' • ' +
                             item['query_id']).props(
                                 'data-testid=run-coordination-no-profile')
                ui.button('Cancel unsent run coordination',
                          on_click=lambda: act('run_coord_dismiss')).props(
                              'data-testid=run-coordination-dismiss')
            else:
                ui.button('Preview next eligible run-wide source jobs '
                          '(OFFLINE, no source requests)',
                          on_click=lambda: act('run_coord_offer')).props(
                              'data-testid=run-coordination-offer')
            if state['run_coordination_last_outcome'] is not None:
                outcome=state['run_coordination_last_outcome']
                ui.label('Last supervised session: ' +
                         outcome['worker_state'] +
                         '; planned stages ' +
                         str(outcome['planned_step_count']) +
                         '; dispatched stages ' +
                         ('UNKNOWN' if
                          outcome['dispatched_step_count'] is None
                          else str(outcome['dispatched_step_count'])) +
                         '; stop reason ' +
                         str(outcome['stopped_reason']) +
                         '; whole search verified: FALSE.').props(
                             'data-testid=run-coordination-outcome')

        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('Pre-run verification — no source searches are executed.').props(
                'data-testid=preflight-heading')
            if not state['preflight_review_reconciliation_required']:
                ui.button('Verify saved exact source plan',
                          on_click=lambda: act('preflight_inspect')).props(
                              'data-testid=preflight-inspect')
            preview = state['preflight_report']
            if preview is None:
                ui.label('The approved source plan has not yet been verified '
                         'in this session. No PRESS review is recorded here.')
            else:
                ui.label('Validated frozen plan SHA-256: ' +
                         preview['plan_sha256']).props('data-testid=preflight-hash')
                ui.label('Strategy version: ' + str(preview['version_number']) +
                         '; concept groups: ' + str(preview['group_count']) +
                         '; active terms: ' + str(preview['active_term_count']))
                ui.label('Boolean logic: OR across terms and groups; '
                         'no automatic exclusions.')
                ui.label('Recorded limits: ' + preview['limitations'])
                ui.label('Provider counts: UNKNOWN; workload estimate: UNKNOWN '
                         '(no pilot counts obtained).').props('data-testid=preflight-unknown')
                ui.label('Automated compiler checks are not independent PRESS peer review. '
                         'Known-relevant records and PubMed translation have NOT been checked.')
                for group in preview['groups']:
                    ui.label('Approved concept group: ' + group['label']).props(
                        'data-testid=preflight-group')
                    for term in group['terms']:
                        ui.label('Atomic term: ' + term['text'] + ' | origin: ' +
                                 term['origin'] + ' | ' +
                                 ('active' if term['enabled'] else 'disabled') +
                                 ' | rationale: ' + term['rationale']).props(
                                     'data-testid=preflight-term')
                for source in preview['sources']:
                    ui.label('Source coverage: ' + source['source_name'] +
                             ' — ' + source['source_coverage']).props(
                                 'data-testid=preflight-coverage')
                    for query in source['queries']:
                        ui.label('Exact stored query (' + query['group_id'] + '): ' +
                                 query['exact_query']).props(
                                     'data-testid=preflight-query')
                    for warning in source['warnings']:
                        ui.label('Compiler warning: ' + warning)
                for warning in preview['warnings']:
                    ui.label('Pre-run warning: ' + warning)
                previous = preview['last_review']
                if previous is not None:
                    ui.label('Last recorded PRESS checklist: ' +
                             previous['occurred_at_utc'] + ' — ' +
                             previous['reviewer_name'] + ' (' +
                             previous['reviewer_role'] + ', self-reported).').props(
                                 'data-testid=preflight-last-review')
                    ui.label('No independent review has been verified, '
                             'and no search execution is authorised by this receipt.')
                    for item, result in previous['press_items'].items():
                        ui.label('PRESS ' + item + ': ' + result)
                    if previous['known_relevant']:
                        ui.label('Known-relevant items: provided, NOT tested '
                                 'against a search provider.')
                candidate = state['preflight_candidate']
                if state['preflight_review_reconciliation_required']:
                    ui.label('Review outcome uncertain: retry the exact same '
                             'review request to reconcile the audit journal.').props(
                                 'data-testid=preflight-retry-required')
                    ui.button('Retry original pre-run review',
                              on_click=lambda: act('preflight_record')).props(
                                  'data-testid=preflight-retry')
                elif candidate is None:
                    ui.label('PRESS checklist — researcher observations. '
                             'Not reviewed / Needs revision do not imply a pass.')
                    reviewer = ui.input('Reviewing researcher', value='').props(
                        'data-testid=preflight-reviewer')
                    reviewer_role = ui.select({
                        'researcher_self_check': 'Researcher self-check',
                        'independent_peer_reported':
                            'External peer review (user-reported, not verified)'},
                        value='researcher_self_check', label='Review role')
                    press = {}
                    for item in preview['press_items']:
                        press[item] = ui.select({
                            'not_reviewed': 'Not reviewed',
                            'reviewed': 'Reviewed by named person',
                            'needs_revision': 'Needs revision'},
                            value='not_reviewed', label='PRESS: ' + item).props(
                                'data-testid=preflight-press-item')
                    note = ui.textarea('Review notes, concerns, or limitations')
                    known = ui.textarea(
                        'Known-relevant record identifiers (one per line; '
                        'will NOT be checked against provider records)')
                    ui.button('Review and lock these checklist answers',
                              on_click=lambda: act('preflight_offer', dict(
                                  reviewer_name=reviewer.value,
                                  reviewer_role=reviewer_role.value,
                                  press_items={key:box.value
                                               for key, box in press.items()},
                                  review_note=note.value or '',
                                  known_relevant=tuple(
                                      line.strip() for line in (known.value or '').splitlines()
                                      if line.strip())))).props(
                                          'data-testid=preflight-offer')
                else:
                    ui.label('Review answers locked — check before recording.').props(
                        'data-testid=preflight-confirmation')
                    ui.label('Reviewer: ' + candidate['reviewer_name'] +
                             '; role: ' + candidate['reviewer_role'])
                    for item, value in candidate['press_items'].items():
                        ui.label('PRESS ' + item + ': ' + value)
                    ui.label('Note: ' + candidate['review_note'])
                    if candidate['known_relevant']:
                        ui.label('Known-relevant items: ' +
                                 str(len(candidate['known_relevant'])) +
                                 ', not tested against provider.')
                    ui.button('Revise checklist before recording',
                              on_click=lambda: act('preflight_revise')).props(
                                  'data-testid=preflight-revise')
                    ui.button('Confirm and record pre-run checklist',
                              on_click=lambda: act('preflight_record')).props(
                                  'data-testid=preflight-record')
        if (state['selected_run_id'] is not None and
                state['preflight_report'] is not None):
            ui.separator()
            ui.label('PubMed pilot counts — optional single-query '
                     'ESearch requests; NOT a literature retrieval.').props(
                         'data-testid=pubmed-pilot-heading')
            ui.label('All source-run counts remain UNKNOWN until the '
                     'real retrieval pipeline verifies them. A pilot '
                     'count is not a final count and is never added '
                     'across overlapping concept groups.')
            if not state['pubmed_profile_configured']:
                ui.label('Pilot unavailable: no host-configured NCBI '
                         'contact email. The API key/contact cannot '
                         'be supplied by browser controls.').props(
                             'data-testid=pubmed-profile-unavailable')
            elif state['pubmed_pilot_reconciliation_required']:
                ui.label('Pilot outcome uncertain — read original '
                         'audit attempt. NEVER repeat the provider '
                         'request automatically.').props(
                             'data-testid=pubmed-pilot-uncertain')
                ui.button('Inspect original pilot receipt (no network)',
                          on_click=lambda: act('pubmed_pilot_reconcile')).props(
                              'data-testid=pubmed-pilot-reconcile')
            elif state['wos_pilot_reconciliation_required']:
                ui.label('Resolve the Web of Science pilot receipt before '
                         'starting a PubMed pilot.')
            elif state['pubmed_pilot_candidate'] is not None:
                candidate = state['pubmed_pilot_candidate']
                ui.label('Unsent, locked pilot candidate for group ' +
                         candidate['group_id']).props(
                             'data-testid=pubmed-pilot-candidate')
                ui.label('Exact query: ' + candidate['exact_query']).props(
                    'data-testid=pubmed-pilot-query')
                ui.label('This confirmation will make ONE count-only '
                         'HTTPS request to the official PubMed ESearch '
                         'service. No identifiers/metadata will be retrieved. '
                         'Provider rate limits apply.')
                ui.button('Cancel without sending a request',
                          on_click=lambda: act('pubmed_pilot_revise')).props(
                              'data-testid=pubmed-pilot-cancel')
                ui.button('Confirm one PubMed count-only request',
                          on_click=lambda: act('pubmed_pilot_confirm')).props(
                              'data-testid=pubmed-pilot-confirm')
            else:
                ui.label('Select one approved PubMed group query. '
                         'Selecting only previews; a separate click '
                         'must authorise the network request.')
                for source in state['preflight_report']['sources']:
                    if source['source_name'] != 'pubmed':
                        continue
                    for query in source['queries']:
                        qid = query['query_id']
                        ui.label('PubMed ' + query['group_id'] +
                                 ': ' + query['exact_query']).props(
                                     'data-testid=pubmed-pilot-saved-query')
                        ui.button('Preview pilot for group ' +
                                  query['group_id'],
                                  on_click=lambda qid=qid: act(
                                      'pubmed_pilot_offer', qid)).props(
                                          'data-testid=pubmed-pilot-offer')
            prior = state['last_pubmed_pilot']
            if prior is not None:
                ui.label('Last audited pilot attempt: ' +
                         prior['status']).props(
                             'data-testid=pubmed-pilot-status')
                count = prior['reported_matches']
                ui.label('Provider-reported PILOT matches: ' +
                         ('UNKNOWN' if count is None else str(count)) +
                         '. No records retrieved or search completed.').props(
                             'data-testid=pubmed-pilot-count')
                if prior.get('accepted_translation'):
                    ui.label('Accepted PubMed translation: ' +
                             prior['accepted_translation']).props(
                                 'data-testid=pubmed-pilot-translation')
                for warning in prior.get('warnings', []):
                    ui.label('PubMed provider warning: ' + warning)
                for reason in prior.get('review_reasons', []):
                    ui.label('Translation review required: ' + reason)
                if prior['status'] in ('requested_indeterminate',
                                       'not_recorded'):
                    ui.label('Do not automatically retry this UUID. '
                             'A NEW pilot requires a fresh two-step '
                             'selection and confirmation.').props(
                                 'data-testid=pubmed-pilot-no-auto-retry')
                if prior.get('error_code') is not None:
                    ui.label('Pilot failure code: ' + prior['error_code'])
                ui.label('Pilot results never establish final '
                         'retrieval or PRESS peer review.').props(
                             'data-testid=pubmed-pilot-incomplete')
        if (state['selected_run_id'] is not None and
                state['preflight_report'] is not None):
            ui.separator()
            ui.label('Web of Science Starter — optional one-record '
                     'count/quota pilot; NOT a count-only request or '
                     'literature retrieval.').props(
                         'data-testid=wos-pilot-heading')
            ui.label('Starter Topic (TS) includes titles, abstracts '
                     'and indexed keywords; not web-interface All Fields '
                     'or article full text. Pilot counts do NOT '
                     'become verified source/group counts.')
            if not state['wos_profile_configured']:
                ui.label('Pilot unavailable: no trusted host-only '
                         'Starter API key. Browser controls cannot '
                         'supply credentials.').props(
                             'data-testid=wos-profile-unavailable')
            elif state['wos_pilot_reconciliation_required']:
                ui.label('Uncertain original Starter request: inspect '
                         'the SAME audit UUID without any network call. '
                         'A lost outcome can leave the shared quota '
                         'guard blocked pending separate recovery.').props(
                             'data-testid=wos-pilot-uncertain')
                ui.button('Inspect original Starter receipt (no network)',
                          on_click=lambda: act('wos_pilot_reconcile')).props(
                              'data-testid=wos-pilot-reconcile')
            elif state['pubmed_pilot_reconciliation_required']:
                ui.label('Resolve the PubMed pilot receipt before '
                         'starting a Starter pilot.')
            elif state['wos_pilot_candidate'] is not None:
                candidate = state['wos_pilot_candidate']
                ui.label('Unsent, locked Starter group: ' +
                         candidate['group_id']).props(
                             'data-testid=wos-pilot-candidate')
                ui.label('Exact Topic query: ' +
                         candidate['exact_query']).props(
                             'data-testid=wos-pilot-query')
                if candidate['revalidate_quota']:
                    ui.label('EXPLICIT QUOTA REVALIDATION: another '
                             'provider request is being authorised '
                             'after previously observed exhaustion. '
                             'This does not override server cooldowns '
                             'or unknown in-flight attempts.')
                ui.label('Confirmation sends ONE HTTPS GET to the '
                         'official Starter service (page 1, limit 1). '
                         'It can transiently return ONE licensed '
                         'bibliographic record; RESEARCH-Y immediately '
                         'discards it. Only safe count/quota/audit '
                         'evidence is retained. An API request is '
                         'consumed. This is NOT a zero-record '
                         'count-only operation.')
                ui.button('Cancel without sending a Starter request',
                          on_click=lambda: act('wos_pilot_revise')).props(
                              'data-testid=wos-pilot-cancel')
                ui.button('Confirm ONE Starter one-record request',
                          on_click=lambda: act('wos_pilot_confirm')).props(
                              'data-testid=wos-pilot-confirm')
            else:
                ui.label('Preview one approved pending Starter group '
                         'query without contacting the provider. '
                         'A separate confirmation authorises the '
                         'one-record request and quota use.')
                for source in state['preflight_report']['sources']:
                    if source['source_name'] != 'wos':
                        continue
                    for query in source['queries']:
                        qid = query['query_id']
                        ui.label('Starter ' + query['group_id'] +
                                 ': ' + query['exact_query']).props(
                                     'data-testid=wos-pilot-saved-query')
                        ui.button('Preview Starter one-record pilot for ' +
                                  query['group_id'],
                                  on_click=lambda qid=qid: act(
                                      'wos_pilot_offer', qid)).props(
                                          'data-testid=wos-pilot-offer')
                        ui.button('Preview explicit quota revalidation for ' +
                                  query['group_id'],
                                  on_click=lambda qid=qid: act(
                                      'wos_pilot_revalidation_offer', qid)).props(
                                          'data-testid=wos-pilot-revalidation-offer')
            prior = state['last_wos_pilot']
            if prior is not None:
                ui.label('Last audited Starter pilot: ' +
                         prior['status']).props(
                             'data-testid=wos-pilot-status')
                count = prior['reported_matches']
                ui.label('Provisional provider-reported matches: ' +
                         ('UNKNOWN' if count is None else str(count)) +
                         '; zero records retained; not verified retrieval.').props(
                             'data-testid=wos-pilot-count')
                quota = prior.get('quota')
                if isinstance(quota, dict):
                    ui.label('Observed daily quota: allowance=' +
                             str(quota.get('daily_limit')) +
                             ', remaining=' +
                             str(quota.get('daily_remaining')) +
                             ', entitlement=' +
                             str(prior.get('quota_status')))
                if prior.get('retry_after_seconds') is not None:
                    ui.label('Server-directed retry delay recorded; '
                             'new provider requests remain restricted.')
                if prior.get('retry_after_unverifiable'):
                    ui.label('Server retry deadline not representable; '
                             'further requests are blocked.')
                if prior['status'] in ('requested_indeterminate',
                                       'not_recorded'):
                    ui.label('Never resend this UUID. An indeterminate '
                             'provider reservation may remain blocked '
                             'even after a new preview.').props(
                                 'data-testid=wos-pilot-no-auto-retry')
                if prior.get('error_code') is not None:
                    ui.label('Static failure code: ' +
                             prior['error_code'])
                ui.label('Starter does not expose accepted query '
                         'translation. This pilot neither verifies '
                         'source retrieval nor completes PRESS review.').props(
                             'data-testid=wos-pilot-incomplete')
        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('Web of Science Starter — checkpointed source '
                     'acquisition (EXPERIMENTAL).').props(
                         'data-testid=wos-acquisition-heading')
            ui.label('Unlike a pilot, this workflow can store licensed '
                     'source metadata in the local project. Explicit '
                     'retention consent and a separate provider-session '
                     'confirmation are both required. Verify your '
                     'institutional licence before using it.')
            ui.label('One confirmed session uses at most THREE Starter '
                     'requests (a count/identity recheck where required '
                     'and up to two further 50-record pages). '
                     'Provider quota, cooldowns and interruption '
                     'recovery are enforced by the existing checkpoint '
                     'engine. No automatic unattended sessions.')
            ui.label('A reconciled Starter enumeration is NOT a '
                     'verified whole-run search, full abstracts, '
                     'publication deduplication or an atomic provider '
                     'snapshot. Progress is based on durable source '
                     'checkpoint evidence only.')
            if state['wos_acquisition_prepare_pending']:
                ui.label('Local retention plan outcome uncertain. '
                         'Inspect the original checkpoint — never '
                         'silently re-authorise or start a request.').props(
                             'data-testid=wos-acquisition-prepare-uncertain')
                ui.button('Inspect originally authorised checkpoint (no network)',
                          on_click=lambda: act(
                              'wos_acquisition_prepare_reconcile')).props(
                                  'data-testid=wos-acquisition-prepare-reconcile')
            elif state['wos_acquisition_tick_pending']:
                ui.label('Bounded source request session outcome '
                         'uncertain. Do not repeat until checkpoint '
                         'state is reconciled. A lost worker may '
                         'require explicit supervised recovery.').props(
                             'data-testid=wos-acquisition-tick-uncertain')
                ui.button('Read original source checkpoint (no network)',
                          on_click=lambda: act(
                              'wos_acquisition_tick_reconcile')).props(
                                  'data-testid=wos-acquisition-tick-reconcile')
            elif state['wos_acquisition_offer'] is not None:
                candidate = state['wos_acquisition_offer']
                ui.label('Locked exact Starter Topic query: ' +
                         candidate['exact_query']).props(
                             'data-testid=wos-acquisition-exact-query')
                ui.label('You are authorising local retention of all '
                         'provider-returned metadata permitted by your '
                         'institutional licence. This preparation '
                         'itself makes NO network request and does '
                         'not authorise future sessions automatically.')
                ui.button('Cancel retention consent without preparing',
                          on_click=lambda: act('wos_acquisition_dismiss')).props(
                              'data-testid=wos-acquisition-cancel')
                ui.button('Confirm local metadata retention and prepare checkpoint',
                          on_click=lambda: act('wos_acquisition_prepare')).props(
                              'data-testid=wos-acquisition-prepare')
            else:
                if state['report'] is not None:
                    for row in state['report']['queries']:
                        if row['source_name'] != 'wos':
                            continue
                        qid = row['query_id']
                        ui.label('Saved Starter group ' + row['group_id'] +
                                 ': ' + row['exact_query']).props(
                                     'data-testid=wos-acquisition-saved-query')
                        ui.button('Inspect checkpoint for group ' +
                                  row['group_id'],
                                  on_click=lambda qid=qid: act(
                                      'wos_acquisition_read',qid)).props(
                                          'data-testid=wos-acquisition-read')
                        if (state['wos_profile_configured'] and
                                row['status'] == 'pending'):
                            ui.button('Preview full-source retention for ' +
                                      row['group_id'],
                                      on_click=lambda qid=qid: act(
                                          'wos_acquisition_offer',qid)).props(
                                              'data-testid=wos-acquisition-offer')
                if not state['wos_profile_configured']:
                    ui.label('Source execution unavailable without the '
                             'trusted host-only Starter API key. Existing '
                             'checkpoints remain readable.')
            acquisition = state['wos_acquisition']
            if acquisition is not None:
                job = acquisition['checkpoint']
                ui.label('Selected source checkpoint: ' +
                         acquisition['query_id']).props(
                             'data-testid=wos-acquisition-selected')
                ui.label('Durable status: ' + job['status'] +
                         '; stage: ' + job['stage'] +
                         '; reason: ' + job['reason_code']).props(
                             'data-testid=wos-acquisition-status')
                ui.label('Provider matches: ' +
                         ('UNKNOWN' if job['reported_matches'] is None
                          else str(job['reported_matches'])) +
                         '; records actually stored: ' +
                         str(job['records_committed']) +
                         '; pages acquired: ' +
                         str(job['pages_committed']) +
                         '; pages verified: ' +
                         str(job['verification_pages'])).props(
                             'data-testid=wos-acquisition-progress')
                ui.label('Unknown attempted requests: ' +
                         str(job['requests_unknown']) +
                         '; worker reservation active: ' +
                         str(job['worker_active']) +
                         '; next allowed time: ' +
                         str(job['not_before_utc']))
                ui.label('Observed daily quota status (provider facts): ' +
                         str(job['quota']))
                if job['worker_active'] or job['requests_unknown']:
                    ui.label('Worker/transport outcome may be unknown. '
                             'Do NOT automatically retry; separate '
                             'verified recovery is required.').props(
                                 'data-testid=wos-acquisition-recovery-required')
                elif not acquisition['approved_gui_retention']:
                    ui.label('Historical non-GUI checkpoint: no matching '
                             'explicit graphical retention admission; '
                             'view-only in this increment.')
                elif job['enumeration_reconciled']:
                    ui.label('Source identifier enumeration reconciled '
                             'WITH WARNINGS. Full bibliography and '
                             'whole search remain incomplete.').props(
                                 'data-testid=wos-acquisition-partial-complete')
                elif (job['pages_expected'] is not None and
                      job['pages_expected'] > 1 and
                      job['stage'] in ('verify','final')):
                    ui.label('Acquisition pages retained. Multi-page '
                             'identity verification needs a longer '
                             'uninterrupted supervised worker session. '
                             'Short GUI sessions are DISABLED here to '
                             'prevent repeated quota-consuming loops.').props(
                                 'data-testid=wos-acquisition-long-verification-required')
                elif job['status']=='cancelled':
                    ui.label('Checkpoint cancelled; no further requests '
                             'from this interface.')
                elif state['wos_acquisition_tick_offer'] is None:
                    if state['wos_profile_configured']:
                        ui.button('Preview next bounded session (up to THREE requests)',
                                  on_click=lambda: act(
                                      'wos_acquisition_tick_offer')).props(
                                          'data-testid=wos-acquisition-tick-offer')
                        ui.button('Preview explicit quota revalidation session',
                                  on_click=lambda: act(
                                      'wos_acquisition_revalidate_offer')).props(
                                          'data-testid=wos-acquisition-revalidate-offer')
                else:
                    offered = state['wos_acquisition_tick_offer']
                    ui.label('Unsent bounded session for source query ' +
                             offered['query_id'] + ', maximum THREE '
                             'requests. It may retain up to three pages '
                             'of licensed metadata, without silently '
                             'changing your OR-only query.').props(
                                 'data-testid=wos-acquisition-tick-preview')
                    if offered['revalidate_quota']:
                        ui.label('EXPLICIT quota revalidation requested. '
                                 'Does not bypass server cooldown or '
                                 'indeterminate provider reservations.')
                    ui.button('Cancel unsent source session',
                              on_click=lambda: act(
                                  'wos_acquisition_tick_dismiss')).props(
                                      'data-testid=wos-acquisition-tick-cancel')
                    ui.button('CONFIRM bounded Starter source request session',
                              on_click=lambda: act(
                                  'wos_acquisition_tick_confirm')).props(
                                      'data-testid=wos-acquisition-tick-confirm')
        ui.separator()
        ui.label('Web of Science — longer supervised identity verification '
                 '(experimental)').props('data-testid=wos-verification-heading')
        if state['wos_verification_pending']:
            ui.label('An explicitly authorised verification worker is '
                     'running or needs final receipt reconciliation. '
                     'Other project/run operations remain locked.')
            ui.label('Supervisor status: ' +
                     state['wos_verification_worker_state'] +
                     '; error: ' +
                     str(state['wos_verification_worker_error'])).props(
                         'data-testid=wos-verification-worker-state')
            active = state['wos_acquisition']
            if active is not None:
                progress = active['checkpoint']
                ui.label('Durable verification progress: ' +
                         str(progress['verification_pages']) + ' / ' +
                         ('UNKNOWN' if progress['pages_expected'] is None
                          else str(progress['pages_expected'])) +
                         ' pages; recorded source hits ' +
                         str(progress['records_committed']) +
                         '; unknown requests ' +
                         str(progress['requests_unknown'])).props(
                             'data-testid=wos-verification-progress')
                if progress['worker_active'] or progress['requests_unknown']:
                    ui.label('Do not repeat provider calls: the original '
                             'worker or an HTTP outcome may be unknown.')
            ui.button('Refresh source verification status (no provider request)',
                      on_click=lambda: act('wos_verification_poll')).props(
                          'data-testid=wos-verification-poll')
            if state['wos_verification_worker_state'] == 'running':
                ui.button('Request graceful pause after current page',
                          on_click=lambda: act('wos_verification_pause')).props(
                              'data-testid=wos-verification-pause')
            else:
                ui.button('Reconcile stopped worker with durable checkpoint',
                          on_click=lambda: act('wos_verification_reconcile')).props(
                              'data-testid=wos-verification-reconcile')
        elif state['wos_verification_offer'] is not None:
            proposal = state['wos_verification_offer']
            ui.label('Locked exact query: ' + proposal['exact_query']).props(
                'data-testid=wos-verification-locked-query')
            ui.label('Previously captured pages requiring verification: ' +
                     str(proposal['pages_to_verify']) +
                     '; exact maximum provider requests in this session: ' +
                     str(proposal['expected_requests']) +
                     ' (one initial recheck, all verification pages, '
                     'one final recheck). Up to 512 requests supported. '
                     'Rate limits, quota, server Retry-After or source '
                     'change can pause or fail this sweep.').props(
                         'data-testid=wos-verification-budget')
            ui.label('No source request has been sent by this preview. '
                     'Confirmation stores permitted validation evidence '
                     'in the original project and may consume institutional quota. '
                     'The app must remain open; closing it interrupts '
                     'the child and may require explicit recovery.')
            if proposal['revalidate_quota']:
                ui.label('Explicit revalidation requested, but server '
                         'cooldown and unknown previous provider '
                         'requests cannot be bypassed.')
            ui.button('Cancel unsent verification',
                      on_click=lambda: act('wos_verification_dismiss')).props(
                          'data-testid=wos-verification-dismiss')
            ui.button('CONFIRM one bounded supervised verification session',
                      on_click=lambda: act('wos_verification_confirm')).props(
                          'data-testid=wos-verification-confirm')
        else:
            acquired = state['wos_acquisition']
            if (acquired is not None and
                    acquired['approved_gui_retention'] is True and
                    state['wos_profile_configured'] and
                    acquired['checkpoint']['stage'] in ('verify', 'final') and
                    not acquired['checkpoint']['enumeration_reconciled'] and
                    not acquired['checkpoint']['worker_active'] and
                    acquired['checkpoint']['requests_unknown'] == 0):
                ui.label('The existing short-session limit cannot '
                         'finish this verification sweep. A separate '
                         'longer supervised worker can verify the '
                         'already captured pages in one explicit session.')
                ui.button('Preview full source verification workload',
                          on_click=lambda: act('wos_verification_offer')).props(
                              'data-testid=wos-verification-offer')
                ui.button('Preview verification with explicit quota revalidation',
                          on_click=lambda: act(
                              'wos_verification_revalidate_offer')).props(
                                  'data-testid=wos-verification-revalidate')
        if state['wos_verification_last_outcome'] is not None:
            outcome = state['wos_verification_last_outcome']
            ui.label('Last supervised session: ' +
                     outcome['worker_state'] +
                     '; source status: ' + outcome['durable_source_status'] +
                     '; enumeration reconciled: ' +
                     str(outcome['enumeration_reconciled']) +
                     '; whole search verified: FALSE').props(
                         'data-testid=wos-verification-outcome')
        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('PubMed ESearch — supervised identifier retrieval '
                     '(EXPERIMENTAL; metadata is a separate stage).').props(
                         'data-testid=pubmed-source-heading')
            ui.label('Every approved group remains independent and '
                     'the conceptual search is OR-only. No language, '
                     'species or study-type exclusion is applied. '
                     'Identifiers are stored in the project with a '
                     'source checkpoint, NOT treated as a finished '
                     'bibliographic search.').props(
                         'data-testid=pubmed-source-method')
            ui.label('One explicitly confirmed session is limited to '
                     '512 source requests, including count probes; '
                     'individual identifier pages are capped at 200. '
                     'A broader query may need Create Date partitioning, '
                     'but its initial unfiltered count must equal the '
                     'count over the researcher-confirmed date coverage. '
                     'Otherwise results remain INCOMPLETE.')
            if state['pubmed_source_pending']:
                ui.label('Supervised identifier worker: ' +
                         state['pubmed_source_worker_state'] +
                         '; error: ' + str(
                             state['pubmed_source_worker_error'])).props(
                                 'data-testid=pubmed-source-worker-state')
                ui.label('Do not repeat an uncertain source request. '
                         'The original checkpoint must be inspected '
                         'after the worker stops.')
                progress = state['pubmed_source']
                if progress is not None and progress['checkpoint'] is not None:
                    cp=progress['checkpoint']
                    ui.label('Saved source results: ' +
                             str(cp['identifiers_committed']) + ' / ' +
                             str(cp['reported_matches']) + ' PMIDs; ' +
                             str(cp['pages_committed']) + ' / ' +
                             str(cp['pages_expected']) + ' pages; ' +
                             'identifier reconciliation: ' +
                             str(cp['identifiers_reconciled'])).props(
                                 'data-testid=pubmed-source-progress')
                else:
                    ui.label('No durable source checkpoint yet: count '
                             'planning may still be in progress, or '
                             'the source outcome is unknown.').props(
                                 'data-testid=pubmed-source-no-checkpoint')
                ui.button('Refresh original PubMed checkpoint (no HTTP)',
                          on_click=lambda: act('pubmed_identifier_poll')).props(
                              'data-testid=pubmed-source-poll')
                if (state['pubmed_source_worker_state']=='running' and
                        progress is not None and
                        progress['checkpoint'] is not None):
                    ui.button('Request graceful pause after committed page',
                              on_click=lambda: act('pubmed_identifier_pause')).props(
                                  'data-testid=pubmed-source-pause')
                if state['pubmed_source_worker_state'] != 'running':
                    ui.button('Reconcile terminal worker and saved checkpoint',
                              on_click=lambda: act(
                                  'pubmed_identifier_reconcile')).props(
                                      'data-testid=pubmed-source-reconcile')
            elif state['pubmed_source_offer'] is not None:
                choice=state['pubmed_source_offer']
                ui.label('Frozen PubMed All Fields exact query: ' +
                         choice['exact_query']).props(
                             'data-testid=pubmed-source-exact-query')
                ui.label('Explicit administrative Create Date coverage: ' +
                         choice['coverage_start'] + ' to ' +
                         choice['coverage_end'] +
                         '. The range is used only if a large search '
                         'must be partitioned; unfiltered counts must '
                         'reconcile with this coverage.').props(
                             'data-testid=pubmed-source-coverage')
                ui.label('This PREVIEW has made NO provider requests. '
                         'Confirming starts one bounded, supervised '
                         'ESearch session and uses trusted host-only '
                         'NCBI contact settings. The application must '
                         'remain open for source work to continue.')
                ui.button('Cancel unsent PubMed session',
                          on_click=lambda: act('pubmed_identifier_dismiss')).props(
                              'data-testid=pubmed-source-dismiss')
                ui.button('CONFIRM bounded PubMed identifier retrieval',
                          on_click=lambda: act('pubmed_identifier_confirm')).props(
                              'data-testid=pubmed-source-confirm')
            else:
                pubmed_start = ui.input(
                    'Administrative Create Date coverage start (YYYY-MM-DD)',
                    value='1800-01-01').props(
                        'data-testid=pubmed-source-start')
                pubmed_end = ui.input(
                    'Administrative Create Date coverage end (YYYY-MM-DD)',
                    value=date.today().isoformat()).props(
                        'data-testid=pubmed-source-end')
                for row in (state['report']['queries'] if state['report']
                            is not None else ()):
                    if row['source_name'] != 'pubmed':
                        continue
                    qid=row['query_id']
                    ui.label('Saved PubMed query: ' + row['exact_query']).props(
                        'data-testid=pubmed-source-saved-query')
                    ui.button('Read existing checkpoint for ' + row['group_id'],
                              on_click=lambda qid=qid: act(
                                  'pubmed_identifier_read',qid)).props(
                                      'data-testid=pubmed-source-read')
                    if state['pubmed_profile_configured']:
                        ui.button('Preview identifier session for ' +
                                  row['group_id'],
                                  on_click=lambda qid=qid: act(
                                      'pubmed_identifier_offer',dict(
                                          query_id=qid,
                                          coverage_start=pubmed_start.value,
                                          coverage_end=pubmed_end.value))).props(
                                              'data-testid=pubmed-source-offer')
                if not state['pubmed_profile_configured']:
                    ui.label('NCBI ESearch requests require a trusted '
                             'host contact email. Saved checkpoints '
                             'remain readable without credentials.')
            if state['pubmed_source'] is not None and not state['pubmed_source_pending']:
                cp=state['pubmed_source']['checkpoint']
                if cp is not None:
                    if not cp['resume_budget_sufficient']:
                        ui.label('This existing checkpoint requires at least ' +
                                 str(cp['minimum_resume_requests']) +
                                 ' count verification / forward-progress requests. '
                                 'The GUI limit is 512, so another session '
                                 'would make NO progress. Use the original '
                                 'higher-budget PubMed checkpoint resume service '
                                 'outside this experimental GUI, or obtain a '
                                 'separate longer-worker implementation.').props(
                                     'data-testid=pubmed-source-budget-blocked')
                    ui.label('Last inspected PubMed checkpoint: ' +
                             cp['status'] + '; ' +
                             str(cp['identifiers_committed']) +
                             ' identifiers saved; pages ' +
                             str(cp['pages_committed']) + '/' +
                             str(cp['pages_expected']) + '; metadata '
                             'records linked ' +
                             str(cp['metadata_records_linked'])).props(
                                 'data-testid=pubmed-source-saved-progress')
                    if cp['identifiers_reconciled']:
                        ui.label('Identifiers reconciled only. EFetch '
                                 'bibliography/abstract acquisition, '
                                 'deduplication and complete whole-run '
                                 'acceptance remain OUTSTANDING.')
            if state['pubmed_source_last_outcome'] is not None:
                outcome=state['pubmed_source_last_outcome']
                ui.label('Last PubMed worker: ' +
                         outcome['worker_state'] +
                         '; requests reserved: ' +
                         ('UNKNOWN' if outcome['requests_reserved'] is None
                          else str(outcome['requests_reserved'])) +
                         '; whole search verified: FALSE').props(
                             'data-testid=pubmed-source-outcome')
        if state['selected_run_id'] is not None:
            ui.separator()
            ui.label('PubMed — full EFetch bibliographic metadata and abstracts '
                     '(experimental)').props('data-testid=pubmed-metadata-heading')
            ui.label('This stage begins ONLY after the selected PubMed ESearch '
                     'identifier checkpoint reconciles. The source records and '
                     'abstract text are stored privately in the local project; '
                     'their copyright/redistribution status remains distinct. '
                     'Never confuse EFetch metadata with a complete two-source '
                     'research search.')
            if state['pubmed_metadata_pending']:
                ui.label('EFetch worker: ' +
                         state['pubmed_metadata_worker_state'] +
                         '; error: ' +
                         str(state['pubmed_metadata_worker_error'])).props(
                             'data-testid=pubmed-metadata-worker-state')
                saved=state['pubmed_metadata']
                if saved is not None:
                    ui.label('Saved full metadata: ' +
                             str(saved['metadata_records_committed']) + ' / ' +
                             ('UNKNOWN' if saved['identifier_count'] is None
                              else str(saved['identifier_count'])) +
                             ' identifier-linked records; abstract present: ' +
                             str(saved['abstract_present']) +
                             '; abstract not supplied in response: ' +
                             str(saved['abstract_not_supplied'])).props(
                                 'data-testid=pubmed-metadata-progress')
                else:
                    ui.label('No metadata observation yet. An already-sent '
                             'request may have an uncertain outcome.')
                ui.button('Refresh saved EFetch progress (NO HTTP)',
                          on_click=lambda: act('pubmed_metadata_poll')).props(
                              'data-testid=pubmed-metadata-poll')
                if state['pubmed_metadata_worker_state'] != 'running':
                    ui.button('Reconcile terminal EFetch worker with original ledger',
                              on_click=lambda: act(
                                  'pubmed_metadata_reconcile')).props(
                                      'data-testid=pubmed-metadata-reconcile')
            elif state['pubmed_metadata_offer'] is not None:
                proposed=state['pubmed_metadata_offer']
                ui.label('Frozen exact PubMed All Fields query: ' +
                         proposed['exact_query']).props(
                             'data-testid=pubmed-metadata-exact-query')
                ui.label('Original confirmed source identifiers: ' +
                         str(proposed['identifier_count']) +
                         '; already retained metadata records: ' +
                         str(proposed['metadata_records_committed']) +
                         '; still missing: ' +
                         str(proposed['metadata_records_pending'])).props(
                             'data-testid=pubmed-metadata-preview')
                ui.label('One manually confirmed session sends up to ' +
                         str(proposed['max_session_batches']) +
                         ' EFetch requests of at most ' +
                         str(proposed['max_batch_size']) +
                         ' PubMed IDs each. Each successful batch is '
                         'transactional and already saved IDs are '
                         'skipped on a subsequent manual session. '
                         'This preview sends NO request. An interrupted '
                         'POST may consume quota without returning a '
                         'verified result; it will NOT be automatically '
                         'reissued. Keep the app open until the worker stops.')
                ui.button('Cancel unsent EFetch metadata session',
                          on_click=lambda: act('pubmed_metadata_dismiss')).props(
                              'data-testid=pubmed-metadata-dismiss')
                ui.button('CONFIRM bounded EFetch metadata and abstract retrieval',
                          on_click=lambda: act('pubmed_metadata_confirm')).props(
                              'data-testid=pubmed-metadata-confirm')
            else:
                current=state['pubmed_metadata']
                for query in (state['report']['queries'] if
                              state['report'] is not None else ()):
                    if query['source_name'] != 'pubmed':
                        continue
                    qid=query['query_id']
                    ui.button('Inspect saved EFetch metadata for ' +
                              query['group_id'],
                              on_click=lambda qid=qid: act(
                                  'pubmed_metadata_read',qid)).props(
                                      'data-testid=pubmed-metadata-read')
                    if (state['pubmed_profile_configured'] and
                            state['pubmed_source'] is not None and
                            state['pubmed_source']['query_id']==qid and
                            state['pubmed_source']['checkpoint'] is not None and
                            state['pubmed_source']['checkpoint'][
                                'identifiers_reconciled']):
                        ui.button('Preview EFetch metadata session for ' +
                                  query['group_id'],
                                  on_click=lambda qid=qid: act(
                                      'pubmed_metadata_offer',qid)).props(
                                          'data-testid=pubmed-metadata-offer')
                if current is not None:
                    ui.label('EFetch source state: ' + current['status'] +
                             '; metadata records: ' +
                             str(current['metadata_records_committed']) +
                             '; pending: ' +
                             ('UNKNOWN' if current['metadata_records_pending']
                              is None else str(
                                  current['metadata_records_pending']))).props(
                                      'data-testid=pubmed-metadata-saved')
                    ui.label('Abstract supplied: ' +
                             str(current['abstract_present']) +
                             '; not supplied by EFetch: ' +
                             str(current['abstract_not_supplied']))
                    if current['metadata_records_reconciled']:
                        ui.label('Every previously reconciled PubMed identifier '
                                 'has a saved EFetch record. This does NOT '
                                 'establish complete abstract availability, '
                                 'global publication deduplication or a '
                                 'verified whole-run search.').props(
                                     'data-testid=pubmed-metadata-not-whole-run')
                if not state['pubmed_profile_configured']:
                    ui.label('Without configured local PubMed contact '
                             'details, saved EFetch progress is readable '
                             'but new network sessions are unavailable.')
            if state['pubmed_metadata_last_outcome'] is not None:
                last=state['pubmed_metadata_last_outcome']
                ui.label('Last EFetch worker: ' + last['worker_state'] +
                         '; successfully committed batches: ' +
                         ('UNKNOWN' if last['successful_batches'] is None
                          else str(last['successful_batches'])) +
                         '; whole run verified: FALSE').props(
                             'data-testid=pubmed-metadata-outcome')
        render_manifest_consent(ui, state, act)
        for item in state['exports']:
            # Only offer requests belonging to the explicitly selected run.
            if state['selected_run_id'] is None or item['run_id'] != state['selected_run_id']:
                continue
            eid = item['export_id']
            ui.button('Select stored export ' + eid,
                      on_click=lambda eid=eid: act('select_export', eid)).props('data-testid=select-export')
        if state['selected_run_id'] is not None:
            if native:
                ui.button('Choose external workbook folder with Windows dialog',
                          on_click=lambda: act('native_export')).props(
                              'data-testid=native-export-folder')
            else:
                ui.label('External folder selection requires the desktop window.').props(
                    'data-testid=external-folder-unavailable')
            if state['external_destination_candidate'] is not None:
                ui.label('Proposed external folder: ' +
                         state['external_destination_candidate']).props(
                             'data-testid=external-candidate')
                ui.button('Confirm this external destination',
                          on_click=lambda: act('external_confirm')).props(
                              'data-testid=confirm-external-folder')
            if state['external_destination_confirmed']:
                ui.label('Confirmed external destination: ' +
                         state['external_destination_location']).props(
                             'data-testid=external-confirmed')
            if (state['external_destination_candidate'] is not None or
                    state['external_destination_confirmed']):
                ui.button('Clear external folder selection',
                          on_click=lambda: act('external_clear')).props(
                              'data-testid=clear-external-folder')
            ui.label('Default workbook: strategy-summary-' +
                     state['selected_run_id'] + '.xlsx')
            ui.button('Prepare strategy workbook',
                      on_click=lambda: act('prepare')).props('data-testid=prepare')
            if ((state['run_execution_board'] or {}).get('reviewed_retained_master') or state['pending_reviewed_export']
                    or (state['retained_export_report'] or {}).get('format_version') == 2):
                ui.button('Prepare reviewed master workbook with memberships and review receipts',
                          on_click=lambda: act('prepare_reviewed_master')).props('data-testid=prepare-reviewed-master')
        if state['export_reconciliation_required']:
            ui.label('Export journal or inventory needs reconciliation. Retry Prepare '
                     'with the original request ID; do not start another export.').props(
                         'data-testid=recovery-required')
        if state['selected_export_id'] is not None:
            saved = next((item for item in state['exports']
                          if item['export_id'] == state['selected_export_id']), None)
            if saved is None:
                ui.label('Export inventory unavailable — reinspection required.').props('data-testid=export-missing')
            else:
                ui.label('Recorded export phase: ' + saved['recorded_state']).props('data-testid=export-phase')
                ui.label('Recorded destination: ' + saved['destination_kind']).props(
                    'data-testid=destination-kind')
                if (saved['destination_kind'] == 'external' and
                        not state['external_destination_confirmed']):
                    ui.label('EXTERNAL DESTINATION CONFIRMATION REQUIRED — '
                             'choose the original folder again; the path '
                             'is never stored in the project.').props(
                                 'data-testid=external-reconfirm')
                if saved['last_error'] is not None:
                    ui.label('Recorded export error: ' + saved['last_error']).props('data-testid=export-error')
                if saved['recorded_state'] not in ('cancelled', 'published'):
                    ui.button('Cancel pending export', on_click=lambda: act('cancel')).props('data-testid=cancel')
                if saved['recorded_state'] != 'cancelled':
                    ui.button('Resume publication', on_click=lambda: act('resume')).props('data-testid=resume')
            ui.button('Verify workbook', on_click=lambda: act('observe')).props('data-testid=observe')
            ui.label('Export request ID: ' + state['selected_export_id']).props('data-testid=export-id')
        retained = state['retained_export_report']
        if retained is not None:
            ui.label('Retained original export report — frozen when prepared.')
            ui.label('Retained report status: ' + str(retained['status']))
            for item in retained['queries']:
                ui.label('Retained exact query: ' + item['exact_query']).props('data-testid=retained-query')
                count = item['reported_matches']
                ui.label('Retained reported matches: ' +
                         ('unknown' if count is None else str(count))).props('data-testid=retained-count')
        observed = state['observation']
        if observed is not None:
            ui.label('Observed outcome: ' + observed['outcome']).props('data-testid=observation')
            ui.label('Audited workbook success: ' + str(observed['audited_success']))
            if observed['outcome'] == 'destination_confirmation_required':
                ui.label('EXTERNAL DESTINATION CONFIRMATION REQUIRED — '
                         'the output cannot be verified without reselecting '
                         'its original folder.').props('data-testid=external-observe')
            if observed['outcome'] == 'published_receipt_missing':
                ui.label('RECOVERY REQUIRED — the workbook is visible, but the '
                         'final audited publication receipt is missing. '
                         'This is not verified. Resume the existing export '
                         'request to reconcile its original file.').props(
                             'data-testid=receipt-missing')
            if observed['outcome'] in ('not_yet_staged', 'retained_artifact_changed'):
                ui.label('RECOVERY REQUIRED — rendering or staging did not '
                         'produce a verified workbook. The original request '
                         'and retained evidence remain available. Repair the '
                         'failure and resume the same export; this observation '
                         'is not success.').props('data-testid=stage-recovery')
    if error:
        ui.label('Operation error: ' + error).props('data-testid=operation-error')
        if (error == 'worker_interrupted' and
                state['selected_export_id'] is not None):
            ui.label('RECOVERY REQUIRED — the supervised export worker was '
                     'interrupted. No successful workbook is verified. '
                     'Reopen this saved request and inspect its durable '
                     'phase before retrying; do not start a new export.').props(
                         'data-testid=worker-recovery')
