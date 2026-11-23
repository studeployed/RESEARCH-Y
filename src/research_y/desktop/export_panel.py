"""One export entry point for articles and audited search reports."""


def render_exports(ui, state, act, *, native):
    ui.label('Save your results').classes('section-title')
    ui.label('Exports include the saved search methods and its current completion status. Abstract text is optional.')
    view = state.get('master_results')
    if not view:
        ui.button('Load saved results', on_click=lambda: act('master_results', dict(operation='ensure', data={})))
        return
    kind = ui.select({'articles': 'Articles (Excel or RIS)', 'strategy': 'Search strategy workbook',
                      'reviewed': 'Reviewed master workbook'}, label='What to save', value='articles')
    filename = ui.input('Filename', value='Search results.xlsx').props('data-testid=export-filename')
    scope = ui.select({'entire': f'All {view["total"]} articles', 'filtered': f'{view["matching"]} filtered articles',
                       'selected': f'{view["selected"]} selected articles'}, label='Articles to include', value='entire')
    rights = ui.checkbox('Include abstract text I have permission to export', value=False)
    sources = ui.select(view['options'].get('source', []), label='Sources whose abstract text I may export', multiple=True, value=[])
    sources.bind_visibility_from(rights, 'value')
    def change_kind(e):
        articles = e.value == 'articles'
        filename.set_value('Search results.xlsx' if articles else 'Search strategy.xlsx' if e.value == 'strategy' else 'Reviewed master.xlsx')
        scope.set_visibility(articles)
        rights.set_visibility(articles)
        if not articles:
            rights.set_value(False)
    kind.on_value_change(change_kind)
    async def save():
        if kind.value == 'articles':
            await act('native_master_export', dict(name=filename.value, revision=view['revision'], scope=scope.value,
                       include_abstracts=rights.value, abstract_sources=sources.value or []))
        else:
            await act('native_workbook_save', dict(name=filename.value, reviewed=kind.value == 'reviewed'))
    ui.button('Choose folder and save', on_click=save).set_enabled(native).props('data-testid=export-save')
    ui.label('For reference managers, use a filename ending in .ris. Reports use .xlsx. Existing files are never overwritten.').classes('review-hint')
    done = state.get('saved_output')
    if done:
        ui.label('Saved and verified · ' + done['filename']).classes('message success').props('data-testid=export-verified')
        ui.label(done['location']).classes('setting-summary')
        with ui.row():
            ui.button('Open file', on_click=lambda: act('native_open_output', False))
            ui.button('Open folder', on_click=lambda: act('native_open_output', True)).props('outline')
    items = [x for x in state['exports'] if x['run_id'] == state['selected_run_id']]
    if items:
        with ui.expansion('Previous report exports'):
            for item in items:
                ui.button(item['filename'] + ' · ' + item['recorded_state'].replace('_', ' '),
                          on_click=lambda eid=item['export_id']: act('select_export', eid)).props('flat')
            if state['selected_export_id']:
                ui.label('Select the original destination folder if asked. Continue checks the existing file before reporting success.')
                ui.button('Continue or verify selected export', on_click=lambda: act('native_workbook_continue'))
