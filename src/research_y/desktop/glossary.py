"""Hover and keyboard-focus help for abbreviations in application labels."""
import re

GLOSSARY = {
    'PRESS': 'Peer Review of Electronic Search Strategies · a structured review of search quality.',
    'PRISMA-S': 'Preferred Reporting Items for Systematic Reviews and Meta-Analyses, search extension · reporting search methods.',
    'API': 'Application programming interface · the connection used to query a database.',
    'AI': 'Artificial intelligence · optional computer-generated suggestions for your review.',
    'LLM': 'Large language model · the model used by the optional search assistant.',
    'MeSH': 'Medical Subject Headings · the indexing vocabulary used by PubMed.',
    'NCBI': 'National Center for Biotechnology Information · the organisation providing PubMed.',
    'WoS': 'Web of Science · a bibliographic database.',
    'DOI': 'Digital object identifier · a persistent identifier for a publication.',
    'PMID': 'PubMed identifier · the record number for an article in PubMed.',
    'TS': 'Topic search · titles, abstracts and indexed keywords in Web of Science.',
    'OR': 'Matches any included term.',
    'AND': 'Requires all combined concepts to match.',
    'RIS': 'Research Information Systems format · a file format for transferring citations.',
    'JATS': 'Journal Article Tag Suite · structured article and abstract data.',
    'UTC': 'Coordinated Universal Time · the time standard used in the audit history.',
    'SHA-256': 'Secure Hash Algorithm, 256-bit · a fingerprint used to check that data has not changed.',
    'UUID': 'Universally unique identifier · the internal reference for an item.',
    'PDF': 'Portable Document Format · a document file.',
    'CSV': 'Comma-separated values · a table stored as plain text.',
    'XML': 'Extensible Markup Language · a structured data format.',
    'JSON': 'JavaScript Object Notation · a structured data format.',
}
_TERMS = re.compile(r'\b(' + '|'.join(map(re.escape, GLOSSARY)) + r')\b')


class ExplainedUi:
    """Delegate rendering while attaching safe text tooltips to labelled output."""
    def __init__(self, ui):
        self.ui = ui

    def __getattr__(self, name):
        return getattr(self.ui, name)

    def label(self, text=''):
        label = self.ui.label(text)
        matches = dict.fromkeys(_TERMS.findall(str(text)))
        if matches:
            label.props('tabindex=0').tooltip('\n'.join(GLOSSARY[key] for key in matches))
        return label
