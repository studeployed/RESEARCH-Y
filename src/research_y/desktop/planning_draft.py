"""Project-contained, optimistic-concurrency storage for unfinished search plans.

Draft receipts never approve a strategy or authorize a provider request. Existing
projects need no schema migration; their latest immutable strategy is the initial
read-only plan. Preview data is deliberately rebuilt rather than trusted on load.
"""
import json
from contextlib import nullcontext
from copy import deepcopy
from uuid import uuid4, UUID

from research_y.projects import _validated_project_connection, _utc_now
from research_y.publication_identity import _audit
from research_y.desktop.strategy_setup import StrategyDraft, DraftError, _text

EVENT = 'planning_draft_v1'


def _latest(db):
    return db.execute('SELECT event_id, details_json FROM audit_events WHERE event_type=? '
                      'ORDER BY event_id DESC LIMIT 1', (EVENT,)).fetchone()


def restore(data):
    """Validate persisted input with the same rules as interactive entry."""
    if not isinstance(data, dict) or len(json.dumps(data)) > 2_000_000:
        raise DraftError('Saved draft cannot be read. Keep the project and contact support.')
    result = StrategyDraft(_text(data.get('theme', ''), allow_empty=True), data.get('objectives', ''))
    from research_y.storage import validated_objectives
    result.objectives = validated_objectives(result.objectives)
    result.approved_by = _text(data.get('approved_by', ''), allow_empty=True)
    result.set_scope(**data.get('search_scope', {}))
    for group in data.get('groups', []):
        gid = result.add_group(group['label'])
        result.groups[-1]['group_id'] = _text(group.get('group_id', gid))
        gid = result.groups[-1]['group_id']
        for term in group['terms']:
            tid = result.add_term(gid, term['text'], origin=term['origin'], rationale=term['rationale'])
            result.edit_term(gid, tid, text=term['text'], origin=term['origin'],
                             rationale=term['rationale'], enabled=term['enabled'])
            stored = result.groups[-1]['terms'][-1]
            stored['term_id'] = _text(term.get('term_id', str(uuid4())))
            if 'expansion_path' in term:
                stored['expansion_path'] = tuple(_text(p) for p in term['expansion_path'])
    if len({g['group_id'] for g in result.groups}) != len(result.groups):
        raise DraftError('Invalid saved group identifiers.')
    for g in result.groups:
        if len({t['term_id'] for t in g['terms']}) != len(g['terms']):
            raise DraftError('Invalid saved term identifiers.')
    # Pending suggestions are advisory. Preserve only offers linked to this draft,
    # with their provenance intact; accepted terms already live in the groups.
    for offer in data.get('suggestions', []):
        result._term(result._group(offer['group_id']), offer['source_term_id'])
        if offer['origin'] not in ('ai', 'deterministic') or offer['status'] not in ('pending', 'accepted', 'edited', 'rejected'):
            raise DraftError('Invalid saved suggestion.')
        for key in ('suggestion_id', 'text', 'seed', 'method', 'reason'):
            _text(offer[key])
        if offer['origin'] == 'ai' and type(offer.get('event_id')) is not int:
            raise DraftError('Invalid saved suggestion receipt.')
        result.suggestions[offer['suggestion_id']] = deepcopy(offer)
    return result


def load(project, default):
    with _validated_project_connection(project) as db:
        row = _latest(db)
        if row:
            payload = json.loads(row[1])
            if payload['mode'] not in ('draft', 'saved'):
                raise DraftError('Invalid saved planning state.')
            approval_id = payload.get('approval_id')
            if approval_id is not None:
                if str(UUID(approval_id)) != approval_id:
                    raise DraftError('Invalid saved approval request.')
                from research_y.strategy_admission import _identity
                approved = db.execute('SELECT version_number, snapshot_json FROM strategy_versions WHERE strategy_version_id=?',
                                      (_identity('strategy', approval_id),)).fetchone()
                if approved:
                    return restore(json.loads(approved[1])), 'saved', approved[0], row[0], None
            if payload['mode'] == 'saved':
                approved = db.execute('SELECT snapshot_json FROM strategy_versions WHERE version_number=?',
                                      (payload['base_version'],)).fetchone()
                if not approved:
                    raise DraftError('The saved search is unavailable.')
                return restore(json.loads(approved[0])), 'saved', payload['base_version'], row[0], None
            return restore(payload['draft']), payload['mode'], payload['base_version'], row[0], approval_id
        saved = db.execute('SELECT version_number, snapshot_json FROM strategy_versions '
                           'ORDER BY version_number DESC LIMIT 1').fetchone()
    if saved:
        return restore(json.loads(saved[1])), 'saved', saved[0], None, None
    return default, 'draft', None, None, None


def save(project, draft, mode, base_version, expected, *, connection=None, approval_id=None):
    data = draft.state()
    data.pop('preview')
    restore(data)
    with nullcontext(connection) if connection is not None else _validated_project_connection(project) as db:
        if connection is None:
            db.execute('BEGIN IMMEDIATE')
        row = _latest(db)
        if (row[0] if row else None) != expected:
            raise DraftError('The plan changed in another window. Reopen the project before editing.')
        return _audit(db, EVENT, dict(version=1, at_utc=_utc_now(), mode=mode, base_version=base_version,
                                     draft=data, approval_id=approval_id))
