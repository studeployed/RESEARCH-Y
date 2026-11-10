"""Read-only SHA-256 of authoritative original project search evidence.

Only explicit, immutable-or-researcher-controlled source/query/run/membership
rows are covered. Publication identities and append-only audit events change
during permitted 64-row materialisation and are separately revision-checked.
This helper never exposes original metadata or credentials to a browser.
"""
from __future__ import annotations

from hashlib import sha256

from research_y import publication_identity as identity

_ORIGINAL_SCOPE_SQL = (
    ("strategy_versions",
     "SELECT strategy_version_id,version_number,approved_at_utc,snapshot_json "
     "FROM strategy_versions ORDER BY strategy_version_id"),
    ("strategy_groups",
     "SELECT strategy_version_id,group_id,label,group_order "
     "FROM strategy_groups ORDER BY strategy_version_id,group_id"),
    ("search_runs",
     "SELECT run_id,strategy_version_id,created_at_utc,status,completed_at_utc "
     "FROM search_runs ORDER BY run_id"),
    ("source_queries",
     "SELECT query_id,run_id,strategy_version_id,group_id,source_name,"
     "exact_query,parameters_json,reported_matches,status,executed_at_utc "
     "FROM source_queries ORDER BY query_id"),
    ("source_retrievals",
     "SELECT retrieval_id,run_id,source_name,source_record_id,"
     "retrieved_at_utc,original_metadata_json FROM source_retrievals "
     "ORDER BY retrieval_id"),
    ("query_retrievals",
     "SELECT query_id,retrieval_id,run_id,source_name "
     "FROM query_retrievals ORDER BY query_id,retrieval_id"),
)


def original_scope_digest(db) -> str:
    """Stream all original scope rows from the caller's current SQLite snapshot.

    The caller supplies its read transaction or BEGIN IMMEDIATE writer lock.
    No second connection, cache, transient lock or repair is created here.
    """
    digest = sha256()
    for name, query in _ORIGINAL_SCOPE_SQL:
        digest.update(name.encode("ascii") + b"\0")
        for row in db.execute(query):
            digest.update(identity._json(row).encode("utf-8") + b"\n")
    return digest.hexdigest()
