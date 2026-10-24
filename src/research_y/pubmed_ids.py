"""Bounded PubMed ESearch identifier pagination with truthful incomplete results.

Phase 1 P1-04a: real ID-page transport and deterministic reconciliation, not
metadata retrieval or whole-search completeness. Counts above the conservative
single-window ceiling are explicitly routed to later disjoint partitioning.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from research_y.pubmed_probe import (
    MAX_RESPONSE_BYTES,
    PubMedESearchProbeClient,
    PubMedProbeError,
    _review_translation,
    _translate_warning_map,
)

# ESearch's PubMed-specific hard ceiling is 10,000 IDs; deliberately operate
# below it until the partitioning algorithm has been verified separately.
DEFAULT_SINGLE_QUERY_CEILING = 9000
DEFAULT_PAGE_SIZE = 200
MAX_COUNT_DIGITS = 20
MAX_PMID_DIGITS = 32


@dataclass(frozen=True, slots=True)
class PubMedIdentifierPage:
    exact_query: str
    retstart: int
    requested_retmax: int
    reported_matches: int
    pmids: tuple[str, ...]
    accepted_translation: str
    warnings: tuple[str, ...]
    review_reasons: tuple[str, ...]
    response_sha256: str
    retrieved_at_utc: str

    @property
    def review_required(self) -> bool:
        return bool(self.review_reasons)


@dataclass(frozen=True, slots=True)
class PubMedIdentifierResult:
    exact_query: str
    status: str
    reported_matches: int | None
    pmids: tuple[str, ...]
    pages: tuple[PubMedIdentifierPage, ...]
    errors: tuple[str, ...] = ()
    # Even complete ID pagination is not an end-to-end verified source search.
    source_retrieval_verified: bool = False

    @property
    def identifiers_reconciled(self) -> bool:
        return self.status == "identifiers_reconciled_metadata_pending"


def _nonnegative_integer(value: Any, *, field: str) -> int:
    if type(value) is int and value >= 0:
        return value
    if (isinstance(value, str) and 1 <= len(value) <= MAX_COUNT_DIGITS
            and value.isascii() and value.isdecimal()):
        return int(value)
    raise PubMedProbeError(f"PubMed identifier page has an invalid {field}")


def parse_identifier_page(
    payload: bytes,
    *,
    exact_query: str,
    retstart: int,
    retmax: int,
    retrieved_at_utc: str,
) -> PubMedIdentifierPage:
    """Parse and validate one ESearch result without pretending it is complete."""
    if type(retstart) is not int or type(retmax) is not int or retstart < 0 or retmax <= 0:
        raise ValueError("Identifier pagination requires nonnegative offset and positive size")
    if retstart + retmax > 10000:
        raise ValueError("Identifier pagination cannot exceed PubMed's 10000-ID window")
    if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE_BYTES:
        raise PubMedProbeError("PubMed returned an oversized or invalid identifier page")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PubMedProbeError("PubMed returned malformed identifier JSON") from exc
    if not isinstance(data, dict) or "error" in data or "ERROR" in data:
        raise PubMedProbeError("PubMed identifier request returned a provider error")
    result = data.get("esearchresult")
    if not isinstance(result, dict) or "error" in result or "ERROR" in result:
        raise PubMedProbeError("PubMed identifier request returned invalid search data")
    count = _nonnegative_integer(result.get("count"), field="reported count")
    actual_start = _nonnegative_integer(result.get("retstart"), field="retstart")
    actual_max = _nonnegative_integer(result.get("retmax"), field="retmax")
    if actual_start != retstart or actual_max > retmax:
        raise PubMedProbeError("PubMed identifier page boundaries differ from the request")
    translation = result.get("querytranslation")
    if not isinstance(translation, str) or not translation.strip():
        raise PubMedProbeError("PubMed identifier page omitted the accepted translation")
    warnings = (
        _translate_warning_map(result.get("warninglist"), field="warninglist")
        + _translate_warning_map(result.get("errorlist"), field="errorlist")
    )
    listed = result.get("idlist")
    if not isinstance(listed, list):
        raise PubMedProbeError("PubMed identifier page omitted the ID list")
    pmids: list[str] = []
    for ident in listed:
        # Canonical PubMed identifiers are decimal positive integers, not
        # automatically reparsed DOI/PMCID fields or arbitrary string labels.
        if (not isinstance(ident, str) or not 1 <= len(ident) <= MAX_PMID_DIGITS
                or not ident.isascii() or not ident.isdecimal() or int(ident) <= 0):
            raise PubMedProbeError("PubMed identifier page contained an invalid PMID")
        if str(int(ident)) != ident:
            raise PubMedProbeError("PubMed identifier page contained a noncanonical PMID")
        pmids.append(ident)
    if len(pmids) != len(set(pmids)):
        raise PubMedProbeError("PubMed identifier page contains repeated PMIDs")
    if len(pmids) > retmax or actual_max > retmax:
        raise PubMedProbeError("PubMed identifier page exceeded the requested page size")
    return PubMedIdentifierPage(
        exact_query=exact_query,
        retstart=retstart,
        requested_retmax=retmax,
        reported_matches=count,
        pmids=tuple(pmids),
        accepted_translation=translation,
        warnings=warnings,
        review_reasons=_review_translation(exact_query, translation, warnings),
        response_sha256=hashlib.sha256(payload).hexdigest(),
        retrieved_at_utc=retrieved_at_utc,
    )


def retrieve_bounded_identifiers(
    client: PubMedESearchProbeClient,
    exact_query: str,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_records: int = DEFAULT_SINGLE_QUERY_CEILING,
    on_verified_page: Callable[[PubMedIdentifierPage], None] | None = None,
) -> PubMedIdentifierResult:
    """Fetch a small stable set of PubMed IDs, retaining incomplete evidence.

    An optional callback can transactionally persist each reconciled page. It
    must finish persisting before returning; durable resumption and >10,000
    disjoint partitioning are later, separately tested increments. This method
    never upgrades the full source/run status to completed_verified.
    """
    if type(page_size) is not int or not 1 <= page_size <= 1000:
        raise ValueError("page_size must be an integer between 1 and 1000")
    if type(max_records) is not int or not 1 <= max_records <= DEFAULT_SINGLE_QUERY_CEILING:
        raise ValueError("max_records must be between 1 and the safe single-window ceiling")
    if on_verified_page is not None and not callable(on_verified_page):
        raise TypeError("on_verified_page must be callable")
    if not isinstance(exact_query, str) or not exact_query.strip():
        raise ValueError("An exact approved PubMed query is required")

    try:
        preview = client.probe(exact_query)
    except PubMedProbeError as exc:
        return PubMedIdentifierResult(exact_query, "incomplete", None, (), (),
                                       (str(exc),))
    count = preview.reported_matches
    if preview.review_required:
        return PubMedIdentifierResult(
            exact_query, "query_review_required", count, (), (),
            tuple(preview.review_reasons),
        )
    if count > max_records:
        return PubMedIdentifierResult(
            exact_query, "partition_required", count, (), (),
            ("Count exceeds the bounded single-query window; disjoint partitioning required",),
        )
    if count == 0:
        return PubMedIdentifierResult(exact_query, "identifiers_reconciled_metadata_pending", 0, (), ())

    ids: list[str] = []
    pages: list[PubMedIdentifierPage] = []
    seen: set[str] = set()
    for offset in range(0, count, page_size):
        requested = min(page_size, count - offset)
        try:
            payload = client.fetch_esearch_page(exact_query, retstart=offset, retmax=requested)
            page = parse_identifier_page(
                payload, exact_query=exact_query, retstart=offset, retmax=requested,
                retrieved_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            if page.review_required:
                return PubMedIdentifierResult(
                    exact_query, "query_review_required", count, tuple(ids), tuple(pages),
                    ("Translation or warnings changed during paginated retrieval",),
                )
            if page.reported_matches != count:
                raise PubMedProbeError("PubMed reported count changed between pages")
            if len(page.pmids) != requested:
                raise PubMedProbeError("PubMed page is shorter than the expected ID window")
            if seen.intersection(page.pmids):
                raise PubMedProbeError("PubMed returned overlapping identifiers across pages")
            if on_verified_page is not None:
                try:
                    on_verified_page(page)
                except Exception:
                    # A callback may raise PubMedProbeError itself, possibly
                    # containing sensitive local paths. Never echo its message.
                    return PubMedIdentifierResult(
                        exact_query, "incomplete", count, tuple(ids), tuple(pages),
                        ("Identifier page checkpoint failed; no completion is claimed",),
                    )
        except PubMedProbeError as exc:
            return PubMedIdentifierResult(
                exact_query, "incomplete", count, tuple(ids), tuple(pages), (str(exc),),
            )
        pages.append(page)
        ids.extend(page.pmids)
        seen.update(page.pmids)
    if len(ids) != count or len(seen) != count:
        return PubMedIdentifierResult(
            exact_query, "incomplete", count, tuple(ids), tuple(pages),
            ("Retrieved PubMed identifiers do not reconcile with reported count",),
        )
    return PubMedIdentifierResult(
        exact_query, "identifiers_reconciled_metadata_pending", count,
        tuple(ids), tuple(pages),
    )
