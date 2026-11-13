"""Count retained publication identities when current human pair decisions establish their partition."""
from __future__ import annotations

from collections import Counter, defaultdict
import re

from research_y import publication_candidates as candidates, publication_identity as identity

METHOD = "reviewed-retained-publication-union/1"


def _supported_partition(owners, evidence):
    by_publication = defaultdict(set)
    for rid, pub_id in owners.items():
        by_publication[pub_id].add(rid)
    connected, separate, reviewed, pairs = defaultdict(set), set(), set(), set()
    previous_event = 0
    for event_id, left, right, status, digest in evidence:
        if (type(event_id) is not int or event_id <= previous_event or left not in owners or right not in owners
                or left >= right or (left, right) in pairs or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            return None
        pairs.add((left, right))
        previous_event = event_id
        reviewed.update((left, right))
        if status == 'confirmed_match' and owners[left] == owners[right]:
            connected[left].add(right)
            connected[right].add(left)
        elif status == 'rejected_match' and owners[left] != owners[right]:
            separate.add(tuple(sorted((owners[left], owners[right]))))
        else:
            return None
    k = len(by_publication)
    if reviewed != owners.keys() or len(separate) != k * (k - 1) // 2:
        return None
    for members in by_publication.values():
        unseen = members.copy()
        stack = [unseen.pop()]
        while stack:
            neighbours = connected[stack.pop()] & unseen
            unseen.difference_update(neighbours)
            stack.extend(neighbours)
        if unseen:
            return None
    return by_publication


def retained_union(db, counts, *, include_rows=False, primary=False):
    """Return a supported union or None. No new pairs are generated or decided.

    Each retained original must have current evidence. Sources grouped into a
    publication must be connected by confirmed matches. Every pair of distinct
    publications must have a current explicit rejection between their sources.
    This is a sufficient proof from existing decisions, independent of source
    completeness. It never requires the researcher to make additional decisions.
    """
    totals, reviews = counts.totals, counts.reviews
    n = totals['metadata_source_records']
    k = totals['global_publication_identities']
    distinct = k * (k - 1) // 2
    if (not n or not k or totals['unmaterialised_retrievals'] or totals['queryless_source_records']
            or reviews['stale_decisions'] or reviews['decisions_conflicting_with_current_links']
            or not reviews['recorded_pair_decisions'] or reviews['current_confirmed_matches'] < n - k
            or reviews['current_rejected_matches'] < distinct):
        return None
    owners = dict(db.execute(
        'SELECT r.retrieval_id,p.publication_id FROM source_retrievals r JOIN publication_retrievals p '
        'ON p.retrieval_id=r.retrieval_id WHERE r.run_id=? ' +
        ("AND r.source_name NOT IN ('conference_jats','society')" if primary else ""), (counts.run_id,)))
    if len(owners) != n or len(set(owners.values())) != k:
        raise identity.PublicationIntegrityError('Master identity coverage is inconsistent')

    # The count projection validated the complete journal and checked the
    # latest decision on every pair touching this run against its current
    # evidence, method, source-key history and association. Reuse the same
    # read transaction; earlier decisions for a pair are historical.
    receipts = candidates._receipts(db, None)
    latest = {tuple(r['pair']): r for r in receipts if all(rid in owners for rid in r['pair'])}
    evidence = sorted([r['event_id'], *pair, r['status'], r['comparison_sha256']] for pair, r in latest.items())
    by_publication = _supported_partition(owners, evidence)
    if by_publication is None:
        return None
    proof = {
        'method': METHOD, 'source_count': n, 'retained_unique_publications': k,
        'group_counts': {g['group_id']: g['publication_identities'] for g in counts.groups},
        'group_count_sum': totals['group_publication_identity_sum'],
        'comparison_receipts': len(evidence), 'distinct_publication_pairs': distinct,
        'evidence_sha256': identity._hash(evidence),
    }
    if include_rows:
        proof['decisions'] = evidence
        proof['publications'] = [[pub_id, len(members)] for pub_id, members in sorted(by_publication.items())]
        proof['memberships'] = [list(row) for row in db.execute(
            'SELECT p.publication_id,m.retrieval_id,q.source_name,q.query_id,q.group_id '
            'FROM query_retrievals m JOIN source_queries q ON q.query_id=m.query_id '
            'JOIN publication_retrievals p ON p.retrieval_id=m.retrieval_id '
            'WHERE m.run_id=? AND q.run_id=m.run_id AND q.source_name=m.source_name '
            'ORDER BY p.publication_id,m.retrieval_id,q.query_id', (counts.run_id,))]
    return proof


def validate_captured_union(proof, counts):
    """Reconcile the stored IDs and denominators before rendering a captured report."""
    required = {'method', 'source_count', 'retained_unique_publications', 'group_counts', 'group_count_sum',
                'comparison_receipts', 'distinct_publication_pairs', 'evidence_sha256', 'publications', 'memberships', 'decisions'}
    if not isinstance(proof, dict) or set(proof) != required or proof['method'] != METHOD:
        raise ValueError('Unknown reviewed master method')
    totals = counts['totals']
    n, k = proof['source_count'], proof['retained_unique_publications']
    groups = {g['group_id']: g['publication_identities'] for g in counts['groups']}
    if (any(type(proof[name]) is not int for name in ('source_count', 'retained_unique_publications',
            'group_count_sum', 'comparison_receipts', 'distinct_publication_pairs'))
            or not 0 < k <= n or n != totals['metadata_source_records'] or k != totals['global_publication_identities']
            or totals['unmaterialised_retrievals'] or totals['queryless_source_records']
            or counts['reviews']['stale_decisions'] or counts['reviews']['decisions_conflicting_with_current_links']
            or not re.fullmatch(r'[0-9a-f]{64}', proof['evidence_sha256'])
            or proof['distinct_publication_pairs'] != k * (k - 1) // 2
            or not max(1, n - k + proof['distinct_publication_pairs']) <= proof['comparison_receipts'] <= counts['reviews']['recorded_pair_decisions']
            or proof['group_counts'] != groups or any(type(v) is not int for v in proof['group_counts'].values())
            or proof['group_count_sum'] != sum(groups.values())):
        raise ValueError('Reviewed master totals disagree')
    pubs = {}
    for pub_id, number in proof['publications']:
        identity._identifier(pub_id)
        if pub_id in pubs or type(number) is not int or number < 1:
            raise ValueError('Invalid master publication')
        pubs[pub_id] = number
    queries = {q['query_id']:q for q in counts['queries']}
    owners, group_ids, query_ids = {}, defaultdict(set), defaultdict(set)
    for pub_id, rid, source, query_id, group_id in proof['memberships']:
        identity._identifier(rid)
        query = queries[query_id]
        if (pub_id not in pubs or owners.setdefault(rid, pub_id) != pub_id or rid in query_ids[query_id]
                or (source, group_id) != (query['source_name'], query['group_id'])):
            raise ValueError('Invalid reviewed source membership')
        query_ids[query_id].add(rid)
        group_ids[group_id].add(pub_id)
    if (len(pubs) != k or len(owners) != n or Counter(owners.values()) != pubs
            or any(len(group_ids[g]) != expected for g, expected in groups.items())
            or any(len(query_ids[qid]) != q['metadata_source_records'] for qid, q in queries.items())):
        raise ValueError('Reviewed master rows do not reconcile')
    evidence = proof['decisions']
    if (not isinstance(evidence, list) or len(evidence) != proof['comparison_receipts']
            or identity._hash(evidence) != proof['evidence_sha256'] or _supported_partition(owners, evidence) is None):
        raise ValueError('Reviewed master decisions do not establish the captured union')
