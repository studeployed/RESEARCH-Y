"""Plain-language labels for the existing audited search checklist."""

CHECKS = {
    'research_objective': ('Does the search match your research question?',
                           'Check that the concepts in your search reflect what you want to find.'),
    'terminology_coverage': ('Have you considered alternative terms?',
                             'Look for missing synonyms, abbreviations and spelling variants.'),
    'boolean_logic': ('Are the terms combined correctly?',
                      'OR finds records matching any of the included phrases.'),
    'source_syntax': ('Database checks and warnings reviewed',
                      'Read Database checks beside this list. Checked records your review of the available evidence and limitations; it does not certify an untested query. Use Needs changes for a query problem, or Not checked yet if you have not reviewed the evidence.'),
    'spelling': ('Are the search terms spelled correctly?',
                 'Check each phrase and any intentional spelling variants.'),
    'search_fields': ('The database coverage shown suits this search',
                      'PubMed uses indexed-record All Fields. Web of Science Starter uses Topic. Neither searches full article text. Review the coverage shown beside this list.'),
    'limits': ('Are the selected limits appropriate?',
               'Check any date or other restrictions, including your decision to keep the search unrestricted.'),
}

ANSWERS = {'not_reviewed': 'Not checked yet', 'reviewed': 'Checked', 'needs_revision': 'Needs changes'}

PRESS_HELP = ('PRESS means Peer Review of Electronic Search Strategies. '
              'These questions are an adapted self-check to help spot search errors. '
              'You can record an external review separately if someone else reviews the strategy.')
