"""Provisional workbook consent controls for the opened local project."""
from __future__ import annotations


def render_manifest_consent(ui, state, act):
    run_id = state['selected_run_id']
    if run_id is None:
        return
    opened = bool(state['manifest_offer'] or state['manifest_receipt'] or state['manifest_history'])
    with ui.expansion('Provisional source workbook', value=opened).props('data-testid=manifest-panel'):
        offer = state['manifest_offer']
        if state['manifest_pending']:
            ui.label('Confirmation outcome unknown. Inspect the stored receipt before retrying.')
            ui.button('Inspect pending consent', on_click=lambda: act('manifest_reconcile'))
        elif offer is None and not state['manifest_save_running']:
            name = ui.input('Workbook filename', value=f'provenance-{run_id}.xlsx')
            actor = ui.input('Researcher recording consent').props('data-testid=manifest-actor')
            ui.button('Preview workbook consent', on_click=lambda: act(
                'manifest_preview', {'output_name': name.value, 'actor': actor.value})).props('data-testid=manifest-preview')
        elif offer is not None:
            ui.label(f"Run {offer['run_id']} · INCOMPLETE").props('data-testid=manifest-offer')
            ui.label(f"Original source records: {offer['selected_run_original_sources']}. "
                     f"Provisional identities: {offer['provisional_publication_identities']}. "
                     f"Unmaterialised originals: {offer['unmaterialised_original_sources']}. "
                     "Verified unique publications: unknown.")
            ui.label(f"Source revision: {offer['original_revision']}")
            ui.label(f"Destination: exports/{offer['output_name']}")
            ui.label(f"Researcher: {offer['actor']}")
            ui.label('This records consent for a source-provenance workbook. File publication is a separate action.')
            ui.button('Record this consent', on_click=lambda key=offer['offer_token']: act(
                'manifest_confirm', key)).props('data-testid=manifest-confirm')
            ui.button('Cancel preview', on_click=lambda key=offer['offer_token']: act('manifest_dismiss', key))
        if not state['manifest_pending'] and not state['manifest_save_running']:
            ui.button('Find saved consents', on_click=lambda: act('manifest_history')).props('data-testid=manifest-history')
            history = state['manifest_history']
            if history is not None:
                if not history['entries']:
                    ui.label('No saved workbook consents on this page.')
                for entry in history['entries']:
                    ui.button(f"{entry['output_name']} · {entry['authorised_at_utc']}",
                              on_click=lambda key=entry['export_id']: act('manifest_inspect', key)).props(
                                  'data-testid=manifest-inspect')
                if history['next_before_event_id'] is not None:
                    ui.button('Older consents', on_click=lambda: act('manifest_older'))
        receipt = state['manifest_receipt']
        if receipt:
            status = ('Current source revision' if receipt['current_revision_matches']
                      else 'Source changed; a new preview and consent are required')
            ui.label(f"Consent receipt {receipt['audit_event_id']} · {receipt['output_name']} · {status}").props(
                'data-testid=manifest-receipt')
            if state['manifest_save_running']:
                ui.label('Checking and saving the approved workbook…')
            else:
                if receipt['current_revision_matches']:
                    ui.button('Save or resume this workbook', on_click=lambda key=receipt['export_id']: act(
                        'manifest_save', key)).props('data-testid=manifest-save')
                ui.button('Check workbook and publication receipt', on_click=lambda key=receipt['export_id']: act(
                    'manifest_check_file', key)).props('data-testid=manifest-check-file')
            result = state['manifest_save_result']
            if result:
                if result['audited_publication_success']:
                    ui.label(f"Verified workbook: exports/{result['output_name']} · "
                             f"publication receipt {result['publication_receipt_id']}").props(
                                 'data-testid=manifest-file-verified')
                elif result['state'] == 'published_previous_revision':
                    ui.label('Verified historical workbook. The current source revision has changed.')
                else:
                    ui.label('Workbook status: ' + result['state'].replace('_', ' '))
            if state['manifest_save_error']:
                ui.label('Workbook verification or save failed: ' + state['manifest_save_error'] +
                         '. Check the original receipt and files before retrying.')
