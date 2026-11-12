"""Read local identifier evidence for counts, not full source acceptance.

Check stored hashes, page/index agreement and materialised record links in the
caller's read transaction. Do not repeat translation, partition-geometry, quota
or independent verification-pass validation; those remain connector gates.
"""
from __future__ import annotations

from hashlib import sha256
import re
import sqlite3

from research_y.publication_identity import _hash, _object


class CountIntegrityError(ValueError):
    """Inconsistent local count evidence; do not return a plausible total."""


def _checked(raw: str, digest: str) -> dict:
    if not isinstance(raw, str) or sha256(raw.encode('utf-8')).hexdigest() != digest:
        raise CountIntegrityError("Count evidence checksum mismatch")
    return _object(raw)


def _ids(values: object, source: str) -> tuple[str, ...]:
    pattern = r"[1-9][0-9]{0,31}" if source == 'pubmed' else r"[A-Z][A-Z0-9]*:[A-Za-z0-9._-]{1,240}"
    if (not isinstance(values, list)
            or any(not isinstance(v, str) or re.fullmatch(pattern, v) is None for v in values)
            or len(set(values)) != len(values)):
        raise CountIntegrityError("Invalid or repeated checkpoint identifiers")
    return tuple(values)


def _pubmed(db: sqlite3.Connection, query: dict, materialised: dict[str, dict]):
    qid = query['query_id']
    row = db.execute('SELECT root_query,root_count,plan_json,plan_sha256 FROM '
                     'pubmed_checkpoint_runs WHERE query_id=?', (qid,)).fetchone()
    if row is None:
        return set(materialised), None
    plan = _checked(row[2], row[3])
    if (row[0] != query['exact_query'] or plan.get('root_query') != row[0]
            or plan.get('root_count') != row[1]
            or (query['reported_matches'] is not None and row[1] != query['reported_matches'])):
        raise CountIntegrityError("PubMed count plan differs from query")
    expected = set()
    identifiers = set()
    for partition, offset, size, raw, digest in db.execute(
        'SELECT partition_index,retstart,retmax,page_json,page_sha256 '
        'FROM pubmed_checkpoint_pages WHERE query_id=? ORDER BY partition_index,retstart', (qid,)
    ):
        page = _checked(raw, digest)
        ids = _ids(page.get('pmids'), 'pubmed')
        if (page.get('partition_index') != partition or page.get('retstart') != offset
                or page.get('retmax') != size or len(ids) != size or identifiers.intersection(ids)):
            raise CountIntegrityError("PubMed page count identity mismatch")
        identifiers.update(ids)
        expected.update((value, partition, offset) for value in ids)
    actual = set(db.execute('SELECT pmid,partition_index,retstart FROM pubmed_checkpoint_ids '
                            'WHERE query_id=?', (qid,)).fetchall())
    if actual != expected or not set(materialised).issubset(identifiers) or len(identifiers) > row[1]:
        raise CountIntegrityError("PubMed index or metadata membership mismatch")
    return identifiers, 'stored_hashes_and_identifier_links'


def _wos(db: sqlite3.Connection, query: dict, materialised: dict[str, dict]):
    qid = query['query_id']
    row = db.execute('SELECT plan_json,plan_sha256,baseline_count FROM wos_checkpoint_jobs '
                     'WHERE query_id=?', (qid,)).fetchone()
    if row is None:
        return set(materialised), None
    plan = _checked(row[0], row[1])
    if (any(plan.get(k) != query[k] for k in ('query_id', 'run_id', 'source_name', 'exact_query'))
            or (query['reported_matches'] is not None and row[2] != query['reported_matches'])):
        raise CountIntegrityError("Starter count plan differs from query")
    expected = set()
    identifiers = set()
    for number, attempt_id, uid_digest in db.execute(
        'SELECT page_number,attempt_id,uid_sha256 FROM wos_checkpoint_pages '
        'WHERE query_id=? ORDER BY page_number', (qid,)
    ):
        observation = db.execute('SELECT response_json,response_sha256,descriptor_json,descriptor_sha256 '
                                  'FROM wos_checkpoint_observations WHERE attempt_id=?', (attempt_id,)).fetchone()
        if observation is None:
            raise CountIntegrityError("Missing Starter acquisition observation")
        body, descriptor = _checked(*observation[:2]), _checked(*observation[2:])
        attempt = db.execute('SELECT query_id,purpose,page_number,page_size,outcome,http_status,sent '
                              'FROM wos_checkpoint_attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
        hits = body.get('hits')
        metadata = body.get('metadata')
        if not isinstance(hits, list) or not all(isinstance(r, dict) for r in hits) or not isinstance(metadata, dict):
            raise CountIntegrityError("Malformed Starter acquisition body")
        ids = _ids([r.get('uid') for r in hits], 'wos')
        if (attempt != (qid, 'acquire', number, plan.get('page_size'), 'success', 200, 1)
                or descriptor.get('exact_query') != query['exact_query']
                or descriptor.get('database') != plan.get('database')
                or descriptor.get('requested_page') != number
                or descriptor.get('requested_limit') != plan.get('page_size')
                or metadata.get('page') != number or metadata.get('limit') != plan.get('page_size')
                or metadata.get('total') != row[2] or _hash(list(ids)) != uid_digest
                or identifiers.intersection(ids)):
            raise CountIntegrityError("Starter acquisition count identity mismatch")
        identifiers.update(ids)
        for ordinal, hit in enumerate(hits):
            source = materialised.get(hit['uid'])
            if source is None:
                raise CountIntegrityError("Starter identifier has no query metadata")
            payload = source['original_metadata']
            if (payload.get('record') != hit or payload.get('provider') != 'wos_starter'
                    or payload.get('database') != plan.get('database')):
                raise CountIntegrityError("Starter metadata differs from acquisition")
            expected.add((hit['uid'], number, ordinal, source['retrieval_id'], _hash(hit)))
    actual = set(db.execute('SELECT uid,page_number,ordinal,retrieval_id,record_sha256 '
                            'FROM wos_checkpoint_ids WHERE query_id=?', (qid,)).fetchall())
    if (actual != expected or identifiers != set(materialised)
            or (row[2] is None and identifiers) or (row[2] is not None and len(identifiers) > row[2])):
        raise CountIntegrityError("Starter identifier index or membership mismatch")
    return identifiers, 'stored_hashes_and_identifier_links'


def query_identifiers(db: sqlite3.Connection, query: dict, materialised: dict[str, dict]):
    """Return the local identifier union and its explicitly limited check scope."""
    source = query['source_name']
    has_pubmed = db.execute('SELECT 1 FROM pubmed_checkpoint_runs WHERE query_id=?',
                            (query['query_id'],)).fetchone()
    has_wos = db.execute('SELECT 1 FROM wos_checkpoint_jobs WHERE query_id=?',
                         (query['query_id'],)).fetchone()
    if (has_pubmed and source != 'pubmed') or (has_wos and source != 'wos'):
        raise CountIntegrityError("Checkpoint provider differs from source query")
    if source == 'pubmed':
        return _pubmed(db, query, materialised)
    if source == 'wos':
        return _wos(db, query, materialised)
    return set(materialised), None
