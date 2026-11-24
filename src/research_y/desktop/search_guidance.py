"""Human-readable saved plans and orientation for the research journey."""
from datetime import datetime


def strategy_title(theme, version):
    topic = ' '.join((theme or '').split()) or 'Untitled search'
    return f'{topic} · version {version}'


def saved_search_names(runs):
    """Use the frozen theme, never the project's subsequently edited question."""
    names, repeats = {}, {}
    for row in sorted(runs, key=lambda r: (r['created_at_utc'], r['run_id'])):
        version = row['version_number']
        repeats[version] = repeats.get(version, 0) + 1
        title = strategy_title(row.get('strategy_theme'), version)
        if repeats[version] > 1:
            title += f' · repeat {repeats[version]}'
        try:
            saved = datetime.fromisoformat(row['created_at_utc'].replace('Z', '+00:00'))
            when = saved.astimezone().strftime('%d %b %Y, %H:%M')
        except (ValueError, AttributeError):
            when = 'date unavailable'
        names[row['run_id']] = title + ' · saved ' + when
    return names


STAGES = (
    ('plan', 'Plan search',
     'Choose your question, phrases, databases and limits. Preview and save a version you can return to.',
     'Prepare the search plan. Saving it does not contact a database.'),
    ('search', 'Run search',
     'Check the saved plan, optionally try a small database test, then confirm collection to retrieve records.',
     'Review the plan, then use Collect your search results. Collection starts only after you confirm a database request.'),
    ('results', 'Results',
     'Read and organise collected articles. Review possible duplicates, missing details and other flagged items.',
     'Review what has been collected. A visible article list does not mean collection or review is complete.'),
    ('export', 'Export',
     'Choose the articles or search report to save, then create and verify an Excel or reference-manager file.',
     'Save a shareable output. Check its scope and any incomplete-search notices before using it.'),
)

STAGE_HINTS = {key: title + ' · ' + hint for key, title, _, hint in STAGES}
STAGE_HINTS['details'] = 'Project details · Supporting history, search comparisons and advanced settings; not another required search step.'


def render_journey(ui, workspace):
    """A non-sticky overview; its collapsed state survives ordinary redraws."""
    with ui.element('section').classes('journey').props('aria-label="How your search works"'):
        with workspace.disclosure(ui, 'journey', 'How your search works', initial=False):
            with ui.element('ol').classes('journey-stages'):
                for number, (_, title, purpose, _) in enumerate(STAGES, 1):
                    with ui.element('li'):
                        ui.label(f'{number}. {title}').classes('journey-title')
                        ui.label(purpose)
            ui.label('When does the actual search happen? In Run search, after you confirm collection. '
                     'Search checks help catch omissions and mistakes; they do not send requests. '
                     'Optional database tests send a small request to check matches or access, '
                     'but do not collect your article list.').classes('journey-note')
        return ui.label(STAGE_HINTS[workspace.stage]).classes('stage-hint').props('data-testid=stage-guidance')
