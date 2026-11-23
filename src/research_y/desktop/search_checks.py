"""Plain-language labels for the existing audited search checklist."""

CHECKS = {
    'research_objective': ('Does the search match your research question?',
                           'Check that the concepts in your search reflect what you want to find.'),
    'terminology_coverage': ('Have you considered alternative terms?',
                             'Look for missing synonyms, abbreviations and spelling variants.'),
    'boolean_logic': ('Are the terms combined correctly?',
                      'OR finds records matching any of the included phrases.'),
    'source_syntax': ('Does each database understand the query?',
                      'Check database-specific tags, quotation marks and the accepted query where available.'),
    'spelling': ('Are the search terms spelled correctly?',
                 'Check each phrase and any intentional spelling variants.'),
    'search_fields': ('Are you searching the intended fields?',
                      'Review the fields searched by each source, such as titles, abstracts and indexed keywords.'),
    'limits': ('Are the selected limits appropriate?',
               'Check any date or other restrictions, including your decision to keep the search unrestricted.'),
}

ANSWERS = {'not_reviewed': 'Not checked yet', 'reviewed': 'Checked', 'needs_revision': 'Needs changes'}

PRESS_HELP = ('PRESS means Peer Review of Electronic Search Strategies. '
              'These questions are an adapted self-check to help spot search errors. '
              'You can record an external review separately if someone else reviews the strategy.')
