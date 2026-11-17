"""Per-window navigation for the desktop research workflow."""
from contextlib import contextmanager


class ProjectWorkspace:
    def __init__(self):
        self.project_id = None
        self.run_id = None
        self.stage = 'plan'
        self.open_sections = {}

    def render(self, ui, state):
        project_id = state['project']['project_id']
        if self.project_id != project_id:
            self.project_id = project_id
            self.stage = 'search' if state['runs'] else 'plan'
            self.open_sections.clear()
        if self.run_id != state['selected_run_id']:
            self.run_id = state['selected_run_id']
            self.open_sections.clear()
            if self.run_id:
                self.stage = 'search'
        stages = {'plan': 'Plan search', 'search': 'Run search', 'results': 'Results',
                  'export': 'Export', 'details': 'Project details'}
        def remember(event):
            if event.value in stages:
                self.stage = event.value

        with ui.tabs(value=self.stage, on_change=remember).classes('workspace-tabs').props(
                'align=left dense no-caps') as tabs:
            for key, label in stages.items():
                if (key == 'search' and not state['runs']) or (key in ('results', 'export') and not self.run_id):
                    continue
                ui.tab(key, label=label).props(f'data-testid=stage-{key}')
        with ui.tab_panels(tabs, value=self.stage, animated=False).classes('workspace-panels'):
            panels = {key: ui.tab_panel(key) for key in stages}
        # The next action stays above optional tools, regardless of render order.
        with panels['search']:
            search_actions = ui.column()
        collection = {
            'Collect records from both databases': state['run_coordination_pending'],
            'Collect PubMed identifiers': state['pubmed_source_pending'],
            'Collect PubMed article details': state['pubmed_metadata_pending'],
            'Collect Web of Science records': state['wos_acquisition_prepare_pending'] or state['wos_acquisition_tick_pending'],
            'Verify Web of Science coverage': state['wos_verification_pending'],
        }
        collection_panel = None

        @contextmanager
        def area(stage, title=None):
            nonlocal collection_panel
            with search_actions if stage == 'search' and title is None else panels[stage]:
                if title is None:
                    yield
                elif stage == 'search' and title in collection:
                    if collection_panel is None:
                        collection_panel = self.disclosure(ui, 'collection', 'Collect and verify records',
                                                           initial=any(collection.values()))
                    with collection_panel, self.disclosure(ui, (stage, title), title, initial=bool(collection[title])):
                        yield
                else:
                    with self.disclosure(ui, (stage, title), title):
                        yield
        return area

    def disclosure(self, ui, key, title, *, initial=False):
        return ui.expansion(title, value=self.open_sections.get(key, initial),
                            on_value_change=lambda e: self.open_sections.update({key: e.value}))
