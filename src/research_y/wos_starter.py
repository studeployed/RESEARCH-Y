"""P1-05a: strict Web of Science Starter response and quota interpretation.

No network, database writes, automatic enrichment or whole-source acceptance.
Starter Topic search is narrower than web All Fields and not article full text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Mapping, Sequence

MAX_PAGE_SIZE = 50
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
EXPECTED_DAILY_LIMIT = 5000
DATABASES = frozenset(("WOS", "WOK", "BCI", "BIOABS", "BIOSIS", "CCC", "DIIDW",
                       "DRCI", "MEDLINE", "PPRN", "RC", "ZOOREC"))
SOURCE_COVERAGE = (
    "Web of Science Starter Topic (TS): title, abstract, author keywords and "
    "Keywords Plus; narrower than web-interface All Fields; not article full text."
)
# Quoted OR-only expressions emitted by the existing source query compiler.
_TOPIC_QUERY = re.compile(r'TS=\("[^"\\*?$\x00-\x1f\x7f]+"(?: OR "[^"\\*?$\x00-\x1f\x7f]+")*\)\Z')
_UID = re.compile(r"[A-Z][A-Z0-9]*:[A-Za-z0-9._-]{1,240}\Z")


class WoSStarterError(RuntimeError):
    """Only fixed category/status data; never include provider text or secrets."""

    def __init__(self, code: str, *, http_status: int | None = None,
                 retryable: bool = False, retry_after_seconds: float | None = None):
        # Category strings are internal constants, not provider response content.
        super().__init__(f"Web of Science Starter: {code}")
        self.code = code
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def validate_request(query: str, database: str, page: int, limit: int) -> None:
    if not isinstance(query, str) or len(query.encode("utf-8")) > 65536 or not _TOPIC_QUERY.fullmatch(query):
        raise WoSStarterError("invalid_approved_topic_query")
    if not isinstance(database, str) or database not in DATABASES:
        raise WoSStarterError("invalid_database")
    if type(page) is not int or not 1 <= page <= 2**31 - 1:
        raise WoSStarterError("invalid_page")
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise WoSStarterError("invalid_page_size")


@dataclass(frozen=True, slots=True)
class WoSQuota:
    daily_limit: int | None = None
    daily_remaining: int | None = None
    per_second_limit: int | None = None
    valid: bool = True

    @property
    def entitlement_status(self) -> str:
        if not self.valid or self.daily_limit is None:
            return "unverified"
        if self.daily_limit < EXPECTED_DAILY_LIMIT:
            return "below_required_institutional_allowance"
        return "institutional_allowance_observed"

    @property
    def can_continue(self) -> bool:
        return (self.valid and self.entitlement_status == "institutional_allowance_observed"
                and self.daily_remaining is not None and self.daily_remaining > 0)


def parse_quota(headers: Mapping[str, str]) -> WoSQuota:
    """Observe named daily quota headers; absent/invalid is UNKNOWN, not 5,000.

    Header presence and meaning must also be confirmed in the live entitlement
    smoke. Per-second/annual quotas never establish the daily entitlement.
    """
    if not isinstance(headers, Mapping):
        return WoSQuota(valid=False)
    lowered: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            return WoSQuota(valid=False)
        name = key.lower()
        if name in lowered and lowered[name] != value:
            return WoSQuota(valid=False)
        lowered[name] = value
    values: list[int | None] = []
    for name in ("x-ratelimit-limit-day", "x-ratelimit-remaining-day", "x-ratelimit-limit-second"):
        value = lowered.get(name)
        if value is None:
            values.append(None)
        elif re.fullmatch(r"[0-9]{1,12}", value.strip()):
            values.append(int(value))
        else:
            return WoSQuota(valid=False)
    daily, remaining, per_second = values
    if ((daily is not None and daily < 1) or (per_second is not None and per_second < 1)
            or (daily is not None and remaining is not None and remaining > daily)):
        return WoSQuota(valid=False)
    return WoSQuota(daily, remaining, per_second)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError("Non-finite JSON value")


@dataclass(frozen=True, slots=True)
class WoSRecord:
    uid: str
    raw_json: str = field(repr=False)
    abstract_status: str = "not_returned_by_source"
    rights_status: str = "licence_review_required"

    def as_dict(self) -> dict:
        """An independent copy containing ALL supplied source fields, not enrichment."""
        return json.loads(self.raw_json)


@dataclass(frozen=True, slots=True)
class WoSPage:
    exact_query: str = field(repr=False)
    database: str
    page: int
    limit: int
    reported_matches: int
    records: tuple[WoSRecord, ...] = field(repr=False)
    quota: WoSQuota
    response_sha256: str
    retrieved_at_utc: str
    response_json: str = field(repr=False)
    sort_field: str = "LD+A"
    accepted_translation: None = None
    translation_status: str = "not_exposed_by_starter_contract"
    source_retrieval_verified: bool = False

    @property
    def estimated_total_pages(self) -> int:
        return (self.reported_matches + self.limit - 1) // self.limit


def parse_document_page(payload: bytes, *, exact_query: str, database: str,
                        requested_page: int, requested_limit: int,
                        retrieved_at_utc: str, headers: Mapping[str, str]) -> WoSPage:
    validate_request(exact_query, database, requested_page, requested_limit)
    if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE_BYTES:
        raise WoSStarterError("invalid_or_oversized_response")
    try:
        stamp = datetime.fromisoformat(retrieved_at_utc)
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError("UTC required")
        text = payload.decode("utf-8")
        data = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
    except (ValueError, UnicodeError, TypeError, AttributeError, RecursionError):
        raise WoSStarterError("invalid_source_response") from None
    if not isinstance(data, dict):
        raise WoSStarterError("invalid_source_response")
    # Even an HTTP 200 can contain a source rejection or warning; never accept it.
    if any(data.get(key) not in (None, [], {}, "") for key in
           ("error", "errors", "error_description", "warning", "warnings", "ERROR")):
        raise WoSStarterError("source_error_or_warning")
    metadata, hits = data.get("metadata"), data.get("hits")
    if not isinstance(metadata, dict) or not isinstance(hits, list):
        raise WoSStarterError("missing_page_metadata")
    total, page, limit = (metadata.get(name) for name in ("total", "page", "limit"))
    if any(type(value) is not int for value in (total, page, limit)) or not 0 <= total <= 2**63-1:
        raise WoSStarterError("invalid_source_counts")
    if page != requested_page or limit != requested_limit:
        raise WoSStarterError("page_identity_mismatch")
    offset = (page-1)*limit
    if (page > 1 and offset >= total) or len(hits) != min(limit, max(0, total-offset)):
        raise WoSStarterError("truncated_or_unexpected_page")
    seen: set[str] = set()
    records = []
    for record in hits:
        if not isinstance(record, dict):
            raise WoSStarterError("invalid_source_record")
        uid = record.get("uid")
        if not isinstance(uid, str) or not _UID.fullmatch(uid) or (database == "WOS" and not uid.startswith("WOS:")):
            raise WoSStarterError("missing_or_invalid_accession")
        if uid in seen:
            raise WoSStarterError("duplicate_accession")
        seen.add(uid)
        # Starter's published schema has no abstract field; unexpected fields are
        # retained rather than discarded or interpreted as complete abstracts.
        status = "returned_uninterpreted" if any(record.get(k) is not None for k in ("abstract", "abstracts")) else "not_returned_by_source"
        records.append(WoSRecord(uid, json.dumps(record, ensure_ascii=False, sort_keys=True,
                                                 separators=(",", ":"), allow_nan=False), status))
    return WoSPage(exact_query, database, page, limit, total, tuple(records),
                   parse_quota(headers), sha256(payload).hexdigest(), retrieved_at_utc, text)


def validate_page_sequence(pages: Sequence[WoSPage]) -> tuple[str, ...]:
    """Validate a contiguous prefix only; not proof of exhaustive retrieval."""
    if not pages:
        return ()
    first = pages[0]
    ids: list[str] = []
    seen: set[str] = set()
    for index, current in enumerate(pages, 1):
        if (current.page != index or current.exact_query != first.exact_query
                or current.database != first.database or current.limit != first.limit
                or current.sort_field != first.sort_field):
            raise WoSStarterError("page_sequence_mismatch")
        if current.reported_matches != first.reported_matches:
            raise WoSStarterError("source_count_changed")
        for record in current.records:
            if record.uid in seen:
                raise WoSStarterError("cross_page_duplicate")
            seen.add(record.uid)
            ids.append(record.uid)
    return tuple(ids)
