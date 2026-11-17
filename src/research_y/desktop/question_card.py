"""Editable question and adjacent save feedback for the Windows workspace."""


def render_question(ui, workspace, state, act):
    draft = state['strategy_draft']
    saved = state['saved_question']
    project_id = workspace.project_id

    def edit():
        workspace.question_inputs = {key: draft[key] for key in ('theme', 'objectives', 'approved_by')}
        card.refresh()

    def cancel():
        workspace.question_inputs = None
        card.refresh()

    @ui.refreshable
    def card():
        ui.label('Research question').classes('section-title')
        if saved and workspace.question_inputs is None:
            ui.label(saved['theme']).classes('question-theme')
            if saved['objectives']:
                ui.label(saved['objectives']).classes('question-objectives')
            with ui.row().classes('items-center'):
                ui.button('Edit question', on_click=edit).props('outline data-testid=question-edit')
                ui.label('✓ Saved').classes('question-saved').props(
                    'role=status aria-live=polite data-testid=question-saved')
            if not draft['approved_by']:
                ui.label('Before previewing a new search, use Edit question to enter your name for this session.')
            return

        if workspace.question_inputs is None:
            workspace.question_inputs = {key: draft[key] for key in ('theme', 'objectives', 'approved_by')}
        values = workspace.question_inputs
        theme = ui.input('Research theme').bind_value(values, 'theme').props('data-testid=setup-theme')
        objectives = ui.textarea('Research objectives (optional)').bind_value(values, 'objectives').props(
            'data-testid=setup-objectives')
        reviewer = ui.input('Approving researcher’s name').bind_value(values, 'approved_by').props(
            'data-testid=setup-approver')

        async def save():
            if not theme.value or not theme.value.strip():
                status.set_text('Enter a research theme, then save again.')
                return
            if not reviewer.value or not reviewer.value.strip():
                status.set_text('Enter your name, then save again.')
                return
            status.set_text('Saving…')
            for control in (theme, objectives, reviewer, button):
                control.disable()
            message = await act('save_question', (project_id, dict(values)))
            if message:
                status.set_text(message)
                for control in (theme, objectives, reviewer, button):
                    control.enable()

        with ui.row().classes('items-center'):
            button = ui.button('Save question', on_click=save).props('data-testid=setup-save-heading')
            status = ui.label().props('role=status aria-live=polite data-testid=question-message')
            if saved:
                cancel_button = ui.button('Cancel edit', on_click=cancel).props('flat')
                cancel_button.bind_enabled_from(button, 'enabled')

    card()
