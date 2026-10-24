"""Offline broad-OR query compiler for approved RESEARCH-Y strategy snapshots.

No provider requests, hit counts, automatic term mapping, or source-side
completeness claims occur here. The user must review exact queries and the
provider connector must verify accepted/translated queries before execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping


class QueryCompilationError(ValueError):
    """Cannot faithfully compile an approved strategy for a source."""


class QuerySizeError(QueryCompilationError):
    """At least one atomic term is too large for a configured source limit."""


SOURCE_COVERAGE = {
    "pubmed": (
        "PubMed indexed record All Fields, not article full text. Every atomic "
        "term is quoted and explicitly [All Fields] tagged. Check the actual "
        "accepted PubMed translation and phrase-index warnings before execution; "
        "quoted phrases may not always be recognised."
    ),
    "wos": (
        "Web of Science Starter Topic (TS): title, abstract, author keywords "
        "and Keywords Plus. Not web-interface All Fields or article full text."
    ),
}


@dataclass(frozen=True, slots=True)
class QueryChunk:
    """An independently executable OR subset; a group may require >1 chunk."""

    ordinal: int
    exact_query: str
    atomic_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompiledGroup:
    group_id: str
    label: str
    approved_term_count: int
    active_term_count: int
    exact_group_query: str | None
    chunks: tuple[QueryChunk, ...]


@dataclass(frozen=True, slots=True)
class CompiledSource:
    source_name: str
    snapshot_sha256: str
    source_coverage: str
    groups: tuple[CompiledGroup, ...]
    logical_union_query: str
    union_fits_limit: bool
    max_query_bytes: int | None
    warnings: tuple[str, ...]
    # These are deliberate non-claims: no provider has been queried yet.
    executed: bool = False
    reported_matches: None = None


def _validate_text(text: Any, *, context: str) -> str:
    if not isinstance(text, str) or not text or not text.strip():
        raise QueryCompilationError(f"{context} must be non-empty text")
    if text != text.strip():
        raise QueryCompilationError(f"{context} has unreviewed outer whitespace")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise QueryCompilationError(f"{context} includes control characters")
    return text


def _validate_literal(text: Any, *, context: str) -> str:
    value = _validate_text(text, context=context)
    # Search-language constructs inside an atomic term cannot be safely treated
    # as literals by both providers; do not guess at escaping or silently edit.
    if any(mark in value for mark in ('"', "\\", "*", "?", "$")):
        raise QueryCompilationError(
            f"{context} contains unsupported quote/escape/wildcard syntax; "
            "edit the atomic term and approve it before compiling"
        )
    return value


def _source_expression(source_name: str, terms: tuple[str, ...]) -> str:
    if not terms:
        raise ValueError("No active terms")
    quoted = [f'"{term}"' for term in terms]
    if source_name == "pubmed":
        tagged = [f"{part}[All Fields]" for part in quoted]
        return "(" + " OR ".join(tagged) + ")"
    if source_name == "wos":
        return "TS=(" + " OR ".join(quoted) + ")"
    raise ValueError("Unsupported source")


def _chunks(
    source_name: str,
    terms: tuple[str, ...],
    max_query_bytes: int | None,
) -> tuple[QueryChunk, ...]:
    if not terms:
        return ()
    if max_query_bytes is None:
        return (QueryChunk(1, _source_expression(source_name, terms), terms),)

    parts: list[QueryChunk] = []
    current: list[str] = []
    for term in terms:
        proposal = tuple((*current, term))
        size = len(_source_expression(source_name, proposal).encode("utf-8"))
        if size <= max_query_bytes:
            current.append(term)
            continue
        if not current:
            raise QuerySizeError(
                f"Atomic term {term!r} exceeds source limit of "
                f"{max_query_bytes} UTF-8 bytes; never truncate it"
            )
        existing = tuple(current)
        parts.append(QueryChunk(len(parts) + 1, _source_expression(source_name, existing), existing))
        current = [term]
        if len(_source_expression(source_name, (term,)).encode("utf-8")) > max_query_bytes:
            raise QuerySizeError(
                f"Atomic term {term!r} exceeds source limit of "
                f"{max_query_bytes} UTF-8 bytes; never truncate it"
            )
    if current:
        existing = tuple(current)
        parts.append(QueryChunk(len(parts) + 1, _source_expression(source_name, existing), existing))
    return tuple(parts)


def compile_source(
    approved_snapshot: Mapping[str, Any],
    source_name: str,
    *,
    max_query_bytes: int | None = None,
) -> CompiledSource:
    """Compile stored approved terms, not unapproved suggestions or draft text.

    Optional ``max_query_bytes`` is supplied by a connector after verifying its
    actual provider/transport ceiling. It is not an invented provider default.
    All executable chunks must be run and identifier unions reconciled later.
    """
    if source_name not in SOURCE_COVERAGE:
        raise QueryCompilationError(f"Unsupported source: {source_name!r}")
    if max_query_bytes is not None and (
        type(max_query_bytes) is not int or max_query_bytes < 1
    ):
        raise QueryCompilationError("max_query_bytes must be a positive integer or None")
    if not isinstance(approved_snapshot, Mapping):
        raise QueryCompilationError("Approved snapshot must be a mapping")
    if type(approved_snapshot.get("format_version")) is not int or approved_snapshot["format_version"] != 1:
        raise QueryCompilationError("Unsupported approved strategy snapshot format")
    if approved_snapshot.get("logic") != "OR":
        raise QueryCompilationError("Initial strategies must be approved OR-only snapshots")
    _validate_text(approved_snapshot.get("theme"), context="research theme")
    _validate_text(approved_snapshot.get("approved_by"), context="approver")
    stored_groups = approved_snapshot.get("groups")
    if not isinstance(stored_groups, list) or not stored_groups:
        raise QueryCompilationError("An approved strategy requires named groups")

    try:
        canonical = json.dumps(approved_snapshot, ensure_ascii=False, sort_keys=True,
                               allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise QueryCompilationError("Approved snapshot is not valid JSON") from exc
    digest = sha256(canonical.encode("utf-8")).hexdigest()

    groups: list[CompiledGroup] = []
    group_ids: set[str] = set()
    order_values: set[int] = set()
    warnings: list[str] = [SOURCE_COVERAGE[source_name]]
    full_group_queries: list[str] = []
    any_partitioned = False
    for index, group in enumerate(stored_groups):
        if not isinstance(group, dict):
            raise QueryCompilationError("Invalid group in approved snapshot")
        group_id = _validate_text(group.get("group_id"), context="group_id")
        label = _validate_text(group.get("label"), context="group label")
        position = group.get("group_order")
        if type(position) is not int or position != index or position in order_values:
            raise QueryCompilationError("Approved group ordering is inconsistent")
        if group_id in group_ids:
            raise QueryCompilationError("Approved snapshot has duplicate group ids")
        order_values.add(position)
        group_ids.add(group_id)
        terms = group.get("terms")
        if not isinstance(terms, list):
            raise QueryCompilationError(f"Group {group_id}: terms must be an ordered list")
        active: list[str] = []
        for atomic_index, term in enumerate(terms):
            if not isinstance(term, dict):
                raise QueryCompilationError(f"Group {group_id}: invalid atomic term")
            context = f"Group {group_id} term {atomic_index + 1}"
            value = _validate_literal(term.get("text"), context=context)
            if term.get("approved") is not True:
                raise QueryCompilationError(f"{context} was not approved")
            if term.get("origin") not in ("researcher", "deterministic", "ai"):
                raise QueryCompilationError(f"{context} has unknown provenance")
            if term.get("origin") == "ai" and not str(term.get("rationale", "")).strip():
                raise QueryCompilationError(f"{context} needs an AI rationale")
            if type(term.get("enabled")) is not bool:
                raise QueryCompilationError(f"{context} has invalid enabled state")
            if term["enabled"]:
                active.append(value)

        active_tuple = tuple(active)
        full_query = _source_expression(source_name, active_tuple) if active_tuple else None
        executable = _chunks(source_name, active_tuple, max_query_bytes)
        if len(executable) > 1:
            any_partitioned = True
        if full_query is not None:
            full_group_queries.append(full_query)
        else:
            warnings.append(f"Group {group_id} has no active terms and will not be searched")
        groups.append(CompiledGroup(group_id, label, len(terms), len(active), full_query, executable))

    if not full_group_queries:
        raise QueryCompilationError("No active approved search terms to execute")
    union = "(" + " OR ".join(full_group_queries) + ")"
    union_fits = max_query_bytes is None or len(union.encode("utf-8")) <= max_query_bytes
    if any_partitioned:
        warnings.append(
            "Source limit required splitting at OR boundaries. All chunks must "
            "be executed; do not sum their reported counts, reconcile unique "
            "source identifiers to establish the union."
        )
    if not union_fits:
        warnings.append(
            "Logical full-union preview exceeds the configured source limit; "
            "the connector must execute the bounded chunks, not the preview."
        )
    return CompiledSource(
        source_name=source_name, snapshot_sha256=digest,
        source_coverage=SOURCE_COVERAGE[source_name], groups=tuple(groups),
        logical_union_query=union, union_fits_limit=union_fits,
        max_query_bytes=max_query_bytes, warnings=tuple(warnings),
    )


def compile_both(
    approved_snapshot: Mapping[str, Any],
    *,
    pubmed_max_query_bytes: int | None = None,
    wos_max_query_bytes: int | None = None,
) -> tuple[CompiledSource, CompiledSource]:
    """Prepare transparent previews for both mandatory primary sources."""
    return (
        compile_source(approved_snapshot, "pubmed", max_query_bytes=pubmed_max_query_bytes),
        compile_source(approved_snapshot, "wos", max_query_bytes=wos_max_query_bytes),
    )
