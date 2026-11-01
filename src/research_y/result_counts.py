"""P1-06c: consistent, read-only counts with explicit denominators and limits.

A present-day publication-identity projection for one run is not an immutable
historical report, exhaustive deduplication or verified source acquisition.
No view filters, source requests, writes, migrations or status promotion.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import sqlite3
from typing import Any, Iterator

from research_y import publication_candidates as candidates
from research_y import publication_identity as identity
from research_y.projects import Project, SQLITE_APPLICATION_ID, _parse_manifest
from research_y.result_count_ledger import CountIntegrityError, _ids, query_identifiers
from research_y.schema import RUN_STATUSES, SCHEMA_VERSION

METHOD = 'run-count-projection/1'


@dataclass(frozen=True, slots=True)
class RunCountProjection:
    project_id: str
    run_id: str
    strategy_version_id: str
    stored_run_status: str
    revision: str
    queries: tuple[dict[str, Any], ...]
    groups: tuple[dict[str, Any], ...]
    sources: tuple[dict[str, Any], ...]
    totals: dict[str, Any]
    reviews: dict[str, int]
    warnings: tuple[str, ...]
    method: str = METHOD
    projection_scope: str = 'current_identity_projection_for_run'
    historical_snapshot: bool = False
    verified_complete: bool = False
    deduplication_complete: bool = False
    candidate_discovery_complete: bool = False
    source_retrieval_verified: bool = False
    full_checkpoint_validation_performed: bool = False
    export_permissions_verified: bool = False
    status: str = 'incomplete'

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextmanager
def _read_connection(project: Project) -> Iterator[sqlite3.Connection]:
    """Validate and count on one read-only handle; legacy files need explicit open.

    Do not use the ordinary project connection here: that path can migrate an
    old store. Read-only mode can also refuse a hot journal needing recovery;
    open the project through its existing recovery workflow before retrying.
    """
    if not isinstance(project, Project):
        raise TypeError('An opened project is required')
    path = project.database_path
    if (project.manifest_path.is_symlink() or (project.root / 'data').is_symlink()
            or path.is_symlink() or not path.is_file()):
        raise CountIntegrityError('Missing or linked count database')
    if _parse_manifest(project.manifest_path) != (project.identifier, project.name, project.created_at_utc):
        raise CountIntegrityError('Project manifest identity changed')
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=5)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise CountIntegrityError('Open and migrate the project before reading counts')
        if db.execute('PRAGMA application_id').fetchone()[0] != SQLITE_APPLICATION_ID:
            raise CountIntegrityError('Wrong count database application identifier')
        row = db.execute('SELECT project_uuid,name,created_at_utc FROM project_metadata '
                         'WHERE singleton_id=1').fetchone()
        if row != (str(project.identifier), project.name, project.created_at_utc):
            raise CountIntegrityError('Count database identity mismatch')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise CountIntegrityError('Broken count evidence references')
        yield db


def _nonnegative(value: Any) -> int | None:
    if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
        raise CountIntegrityError('Invalid stored reported count')
    return value


def _status(value: Any) -> str:
    if value not in RUN_STATUSES:
        raise CountIntegrityError('Unknown stored run or query status')
    return value


def _numeric_reconciliation(reported: int | None, retrieved: int) -> tuple[str, int | None]:
    if reported is None:
        return 'unknown', None
    difference = retrieved - reported
    return ('equal' if not difference else 'shortfall' if difference < 0 else 'excess'), difference


def _review_counts(db, sources):
    # Validate the journal once, rather than once for every pair in the run.
    # This does not discover new pairs and has no 32-record input limit.
    receipts = candidates._receipts(db, None)
    latest, by_key = {}, {}
    run_keys = {tuple(candidates._source_key(s)) for s in sources.values()}
    relevant = []
    prior_run = 0
    for receipt in receipts:
        pair = tuple(receipt['pair'])
        key = tuple(tuple(k) for k in receipt['source_keys'])
        latest[pair] = receipt
        by_key[key] = receipt['event_id']
        if set(pair).intersection(sources):
            relevant.append(receipt)
        elif all(k in run_keys for k in key):
            prior_run += 1
            relevant.append(receipt)
    counts = dict(recorded_pair_decisions=0, current_confirmed_matches=0,
                  current_rejected_matches=0, stale_decisions=0,
                  decisions_conflicting_with_current_links=0,
                  prior_run_receipts_available=prior_run)
    for pair, receipt in latest.items():
        if not set(pair).intersection(sources):
            continue
        counts['recorded_pair_decisions'] += 1
        snapshots, _, _, keys, state = candidates._state(db, pair)
        key = tuple(tuple(k) for k in keys)
        current = (receipt['post_state_sha256'] == state
                   and receipt['method'] == candidates.RULE_VERSION
                   and by_key.get(key) == receipt['event_id'])
        if current:
            name = 'current_confirmed_matches' if receipt['status'] == 'confirmed_match' else 'current_rejected_matches'
            counts[name] += 1
        else:
            counts['stale_decisions'] += 1
        together = snapshots[0].publication_id == snapshots[1].publication_id
        if together != (receipt['status'] == 'confirmed_match'):
            counts['decisions_conflicting_with_current_links'] += 1
    return counts, identity._hash(relevant)


def _source_rows(db, run_id):
    result = {}
    for (rid,) in db.execute('SELECT retrieval_id FROM source_retrievals WHERE run_id=? ORDER BY retrieval_id', (run_id,)):
        identity._identifier(rid)
        source = identity._source(db, rid)
        identity._text(source['source_name'], 200)
        identity._text(source['source_record_id'])
        _status(source['run_status'])
        payload = source['original_metadata']
        if source['source_name'] in ('pubmed', 'wos'):
            record = payload.get('record')
            field = 'pmid' if source['source_name'] == 'pubmed' else 'uid'
            if not isinstance(record, dict) or record.get(field) != source['source_record_id']:
                raise CountIntegrityError('Source metadata identifier mismatch')
            _ids([source['source_record_id']], source['source_name'])
        result[rid] = source
    return result


def _identity_rows(db, sources):
    links, snapshots = {}, {}
    for rid in sources:
        link = identity._link(db, rid)
        if link is not None:
            links[rid] = link
            if link[0] not in snapshots:
                identity._identifier(link[0])
                snapshots[link[0]] = identity._snapshot(db, link[0])
    return links, snapshots


def _query_rows(db, run_id, sources):
    columns = ('query_id', 'run_id', 'strategy_version_id', 'group_id', 'source_name',
               'exact_query', 'parameters_json', 'reported_matches', 'status', 'executed_at_utc')
    queries = [dict(zip(columns, row)) for row in db.execute(
        'SELECT query_id,run_id,strategy_version_id,group_id,source_name,exact_query,parameters_json,'
        'reported_matches,status,executed_at_utc FROM source_queries WHERE run_id=? ORDER BY query_id', (run_id,))]
    members = defaultdict(set)
    for qid, rid in db.execute('SELECT query_id,retrieval_id FROM query_retrievals WHERE run_id=?', (run_id,)):
        if rid not in sources:
            raise CountIntegrityError('Query membership lost its source record')
        members[qid].add(rid)
    qids = {q['query_id'] for q in queries}
    if set(members) - qids:
        raise CountIntegrityError('Query membership belongs to another run')
    identifiers, scopes = {}, {}
    for query in queries:
        identity._identifier(query['query_id'])
        identity._text(query['source_name'], 200)
        _status(query['status'])
        _nonnegative(query['reported_matches'])
        identity._object(query['parameters_json'])
        qid = query['query_id']
        materialised = {sources[r]['source_record_id']: sources[r] for r in members[qid]}
        if len(materialised) != len(members[qid]):
            raise CountIntegrityError('Repeated source record in one query')
        identifiers[qid], scopes[qid] = query_identifiers(db, query, materialised)
    return queries, members, identifiers, scopes


def _snapshot(db, project, run_id):
    run = db.execute('SELECT strategy_version_id,created_at_utc,status,completed_at_utc '
                     'FROM search_runs WHERE run_id=?', (run_id,)).fetchone()
    if run is None:
        raise CountIntegrityError('Unknown search run')
    _status(run[2])
    strategy_id = identity._identifier(run[0])
    strategy = db.execute('SELECT snapshot_json FROM strategy_versions WHERE strategy_version_id=?', (strategy_id,)).fetchone()
    if strategy is None:
        raise CountIntegrityError('Missing approved strategy')
    identity._object(strategy[0])
    group_rows = db.execute('SELECT group_id,label,group_order FROM strategy_groups '
                            'WHERE strategy_version_id=? ORDER BY group_order,group_id', (strategy_id,)).fetchall()
    sources = _source_rows(db, run_id)
    links, snapshots = _identity_rows(db, sources)
    queries, members, identifiers, scopes = _query_rows(db, run_id, sources)
    warnings = {'source_acceptance_not_established', 'candidate_discovery_incomplete',
                'publication_counts_are_identity_hypotheses', 'current_not_historical_projection',
                'extracted_abstract_count_not_implemented'}
    if run[2] != 'completed_verified':
        warnings.add('stored_run_not_verified')
    if not queries:
        warnings.add('no_planned_queries')
    query_results, by_group_source = [], defaultdict(list)
    for q in queries:
        qid = q['query_id']
        by_group_source[q['group_id'], q['source_name']].append(q)
        reconciliation, delta = _numeric_reconciliation(q['reported_matches'], len(identifiers[qid]))
        missing = len(identifiers[qid]) - len(members[qid])
        qwarnings = []
        if q['reported_matches'] is None:
            qwarnings.append('reported_count_unknown')
        if reconciliation in ('shortfall', 'excess'):
            qwarnings.append('identifier_count_' + reconciliation)
        if q['status'] != 'completed_verified':
            qwarnings.append('query_not_verified')
        if missing:
            qwarnings.append('identifiers_without_metadata')
        warnings.update(qwarnings)
        query_results.append(dict(
            query_id=qid, group_id=q['group_id'], source_name=q['source_name'],
            stored_query_status=q['status'], reported_matches=q['reported_matches'],
            retrieved_source_records=len(identifiers[qid]), metadata_source_records=len(members[qid]),
            identifiers_without_metadata=missing, numeric_reconciliation=reconciliation,
            retrieved_minus_reported=delta, checkpoint_check_scope=scopes[qid],
            source_retrieval_verified=False, warnings=tuple(qwarnings)))
    source_names = sorted({'pubmed', 'wos'} | {s['source_name'] for s in sources.values()}
                          | {q['source_name'] for q in queries})
    groups = []
    for group_id, label, _ in group_rows:
        group_retrievals = set()
        rows = []
        for name in source_names:
            selected = by_group_source[group_id, name]
            ids, rids = set(), set()
            for q in selected:
                ids.update(identifiers[q['query_id']])
                rids.update(members[q['query_id']])
            group_retrievals.update(rids)
            reported = selected[0]['reported_matches'] if len(selected) == 1 else None
            report_state = ('not_planned' if not selected else 'union_not_established' if len(selected) > 1
                            else 'unknown' if reported is None else 'reported_single_query')
            if report_state in ('not_planned', 'union_not_established'):
                warnings.add(report_state)
            reconcile, delta = _numeric_reconciliation(reported, len(ids))
            rows.append(dict(source_name=name, query_ids=tuple(q['query_id'] for q in selected),
                             reported_matches=reported, reported_count_status=report_state,
                             retrieved_source_records=len(ids), metadata_source_records=len(rids),
                             identifiers_without_metadata=len(ids) - len(rids),
                             numeric_reconciliation=reconcile, retrieved_minus_reported=delta,
                             source_retrieval_verified=False))
        pubs = {links[r][0] for r in group_retrievals if r in links}
        groups.append(dict(group_id=group_id, label=label, sources=tuple(rows),
                           publication_identities=len(pubs), group_unique_publications=None,
                           unmaterialised_retrievals=len(group_retrievals - links.keys()),
                           deduplication_complete=False))
    assigned = set().union(*members.values()) if members else set()
    queryless = sources.keys() - assigned
    if queryless:
        warnings.add('queryless_source_records')
    if sources.keys() - links.keys():
        warnings.add('unmaterialised_retrievals')
    per_source = []
    for name in source_names:
        raw = {s['source_record_id'] for s in sources.values() if s['source_name'] == name}
        ids = set(raw)
        for q in queries:
            if q['source_name'] == name:
                ids.update(identifiers[q['query_id']])
        # Missing metadata is computed across all groups here, not summed.
        abstract_states = Counter()
        for source in sources.values():
            if source['source_name'] == name:
                payload = source['original_metadata']
                record = payload.get('record')
                state = (record.get('abstract_status') if name == 'pubmed' and isinstance(record, dict)
                         else payload.get('abstract_status'))
                if state is not None and not isinstance(state, str):
                    raise CountIntegrityError('Malformed abstract availability state')
                abstract_states[state or 'not_recorded'] += 1
        per_source.append(dict(source_name=name, source_unique_records=len(ids),
                               metadata_source_records=len(raw), identifiers_without_metadata=len(ids - raw),
                               queryless_source_records=sum(sources[r]['source_name'] == name for r in queryless),
                               abstract_status_counts=dict(sorted(abstract_states.items()))))
    reviews, receipts_hash = _review_counts(db, sources)
    if reviews['stale_decisions']:
        warnings.add('recorded_decisions_need_review')
    if reviews['decisions_conflicting_with_current_links']:
        warnings.add('recorded_decisions_conflict_with_links')
    totals = dict(
        source_record_sum=sum(s['source_unique_records'] for s in per_source),
        metadata_source_records=len(sources),
        identifiers_without_metadata=sum(s['identifiers_without_metadata'] for s in per_source),
        unmaterialised_retrievals=len(sources.keys() - links.keys()), queryless_source_records=len(queryless),
        global_publication_identities=len(snapshots), global_unique_publications=None,
        group_publication_identity_sum=sum(g['publication_identities'] for g in groups),
        identities_with_review_required_links_in_run=len({link[0] for link in links.values()
                                                         if link[2]['status'] == 'review_required'}),
        extracted_individual_abstracts=None, extracted_abstract_count_status='not_implemented',
        inactive_identities_included=False,
    )
    revision = identity._hash([
        METHOD, str(project.identifier), run_id, run, strategy[0], group_rows, queries,
        [(q, sorted(ids)) for q, ids in sorted(identifiers.items())],
        [(r, s['source_sha256']) for r, s in sorted(sources.items())],
        [(p, s.revision) for p, s in sorted(snapshots.items())], receipts_hash,
        query_results, groups, per_source, totals, reviews, sorted(warnings),
    ])
    return RunCountProjection(str(project.identifier), run_id, strategy_id, run[2], revision,
                              tuple(query_results), tuple(groups), tuple(per_source), totals,
                              reviews, tuple(sorted(warnings)))


def read_run_counts(project: Project, run_id: str) -> RunCountProjection:
    """Count the entire run; no filtered subset or completion override is accepted.

    Numeric equality is not source acceptance. Unsupported or inconsistent
    evidence raises without migrating, repairing, returning zero or writing data.
    The result contains aggregate counts, identifiers and hashes, not abstracts.
    """
    identity._identifier(run_id)
    try:
        with _read_connection(project) as db:
            return _snapshot(db, project, run_id)
    except CountIntegrityError:
        raise
    except (sqlite3.DatabaseError, identity.PublicationIntegrityError, KeyError,
            TypeError, ValueError, RecursionError):
        raise CountIntegrityError('Count evidence cannot be read consistently; open or recover the project first') from None
