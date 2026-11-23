"""Repeatable keyboard entry, retaining rejected values across panel refreshes."""


def render_entry(ui, workspace, act, *, key, label, button_text, action, data_key, data=None):
    values = workspace.entry_values
    values.setdefault(key, '')
    field = ui.input(label).bind_value(values, key).props(f'data-testid={key}')
    submitting = False

    async def submit():
        nonlocal submitting
        if submitting:
            return
        if not (field.value or '').strip():
            status.set_text('Enter a value first.')
            field.run_method('focus')
            return
        submitting = True
        field.disable()
        button.disable()
        status.set_text('Adding…')
        workspace.focus_entry = key
        outcome = await act('setup_edit', dict(action=action, data={**(data or {}), data_key: field.value}))
        submitting = False
        if outcome is not True:
            workspace.focus_entry = None
            status.set_text(outcome or 'Could not add this entry. Try again.')
            field.enable()
            button.enable()
            field.run_method('focus')

    # Native input submission excludes IME composition and repeated keydown.
    field.on('keydown.enter', submit,
             js_handler='(event) => { if (!event.isComposing && !event.repeat) { event.preventDefault(); emit(); } }')
    with ui.row().classes('items-center'):
        button = ui.button(button_text, on_click=submit).props(
            'data-testid=setup-add-group' if action == 'add_group' else 'data-testid=setup-add-term')
        status = ui.label().props('role=status aria-live=polite')
    if workspace.focus_entry == key:
        workspace.focus_entry = None
        field.run_method('focus')
