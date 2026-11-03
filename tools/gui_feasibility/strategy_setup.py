"""Host-memory Research Setup draft for the isolated RESEARCH-Y graphical probe.

A draft is never a source query, approved research version or a persistent job.
All edits invalidate the exact preview. Only the existing compiler and atomic
researcher-approved admission service may create final source plans.
"""
from __future__ import annotations

from uuid import uuid4

from research_y.query_compiler import compile_both
from research_y.storage import ApprovedTerm, StrategyGroup, _groups_snapshot


class DraftError(ValueError):
    """Static UI error without reflecting researcher-supplied terms."""

    def __init__(self, code: str):
        super().__init__(code)


def _text(value, *, allow_empty=False):
    if type(value) is not str or len(value) > 2048:
        raise DraftError('invalid_setup_text')
    value = value.strip()
    if (not allow_empty and not value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DraftError('invalid_setup_text')
    return value


class StrategyDraft:
    def __init__(self):
        self.theme = ''
        self.approved_by = ''
        self.groups = []
        self.preview_data = None

    def _invalidate(self):
        self.preview_data = None

    def _group(self, group_id):
        if type(group_id) is not str:
            raise DraftError('unknown_draft_group')
        for group in self.groups:
            if group['group_id'] == group_id:
                return group
        raise DraftError('unknown_draft_group')

    def _term(self, group, term_id):
        if type(term_id) is not str:
            raise DraftError('unknown_draft_term')
        for term in group['terms']:
            if term['term_id'] == term_id:
                return term
        raise DraftError('unknown_draft_term')

    def update_heading(self, theme, approved_by):
        # Validate both fields before any visible draft mutation.
        heading, reviewer = _text(theme), _text(approved_by)
        self.theme, self.approved_by = heading, reviewer
        self._invalidate()

    def add_group(self, label):
        value = _text(label)
        group = dict(group_id=str(uuid4()), label=value, terms=[])
        self.groups.append(group)
        self._invalidate()
        return group['group_id']

    def rename_group(self, group_id, label):
        self._group(group_id)['label'] = _text(label)
        self._invalidate()

    def remove_group(self, group_id):
        self._group(group_id)
        self.groups = [g for g in self.groups if g['group_id'] != group_id]
        self._invalidate()

    @staticmethod
    def _move(items, key, value, direction, error):
        if type(direction) is not int or direction not in (-1, 1) or type(value) is not str:
            raise DraftError(error)
        index = next((i for i, item in enumerate(items) if item[key] == value), None)
        if index is None:
            raise DraftError(error)
        target = index + direction
        if 0 <= target < len(items):
            items[index], items[target] = items[target], items[index]

    def move_group(self, group_id, direction):
        self._move(self.groups, 'group_id', group_id, direction, 'unknown_draft_group')
        self._invalidate()

    @staticmethod
    def _term_fields(text, origin, rationale, enabled):
        text = _text(text)
        rationale = _text(rationale, allow_empty=True)
        if type(origin) is not str or origin not in ('researcher', 'deterministic', 'ai'):
            raise DraftError('invalid_term_origin')
        if type(enabled) is not bool:
            raise DraftError('invalid_term_state')
        if origin == 'ai' and not rationale:
            raise DraftError('term_rationale_required')
        return dict(text=text, origin=origin, rationale=rationale, enabled=enabled)

    def add_term(self, group_id, text, origin='researcher', rationale='', enabled=True):
        group = self._group(group_id)
        fields = self._term_fields(text, origin, rationale, enabled)
        if any(t['text'] == fields['text'] for t in group['terms']):
            raise DraftError('duplicate_draft_term')
        term_id = str(uuid4())
        group['terms'].append(dict(term_id=term_id, **fields))
        self._invalidate()
        return term_id

    def edit_term(self, group_id, term_id, text, origin, rationale, enabled):
        group = self._group(group_id)
        term = self._term(group, term_id)
        fields = self._term_fields(text, origin, rationale, enabled)
        if any(t is not term and t['text'] == fields['text'] for t in group['terms']):
            raise DraftError('duplicate_draft_term')
        term.update(fields)
        self._invalidate()

    def remove_term(self, group_id, term_id):
        group = self._group(group_id)
        self._term(group, term_id)
        group['terms'] = [term for term in group['terms'] if term['term_id'] != term_id]
        self._invalidate()

    def move_term(self, group_id, term_id, direction):
        group = self._group(group_id)
        self._move(group['terms'], 'term_id', term_id, direction, 'unknown_draft_term')
        self._invalidate()

    def approved_groups(self):
        return tuple(
            StrategyGroup(
                group['group_id'], group['label'],
                tuple(ApprovedTerm(term['text'], term['origin'], True, term['rationale'],
                                   term['enabled']) for term in group['terms'])
            )
            for group in self.groups
        )

    def preview(self):
        # A complete read-only rehearsal using the same immutable compiler as
        # the admission service. No model/provider/worker/storage writes.
        snapshot = dict(format_version=1, theme=_text(self.theme),
                        logic='OR', approved_by=_text(self.approved_by),
                        groups=_groups_snapshot(self.approved_groups()))
        pubmed, wos = compile_both(snapshot)
        preview = dict(
            theme=self.theme, approved_by=self.approved_by, logic='OR',
            group_count=len(self.groups),
            active_term_count=sum(group.active_term_count for group in pubmed.groups),
            terms=snapshot['groups'],
            limitations='none selected; no default language/species/study-type exclusions',
            sources=[
                dict(name=source.source_name, coverage=source.source_coverage,
                     union_query=source.logical_union_query,
                     warnings=list(source.warnings),
                     groups=[dict(group_id=group.group_id, label=group.label,
                                  term_count=group.approved_term_count,
                                  active_terms=group.active_term_count,
                                  exact_query=group.exact_group_query,
                                  execution_status='not_executed',
                                  reported_matches=None)
                             for group in source.groups])
                for source in (pubmed, wos)
            ],
            provider_execution='not_performed', provider_counts='unknown',
            source_retrieval_verified=False,
        )
        self.preview_data = preview
        return preview

    def state(self):
        # Defensive snapshot: browser rendering cannot mutate the draft.
        return dict(theme=self.theme, approved_by=self.approved_by,
                    groups=[dict(group_id=group['group_id'], label=group['label'],
                                 terms=[dict(term) for term in group['terms']])
                            for group in self.groups],
                    preview=None if self.preview_data is None else
                    dict(self.preview_data))
