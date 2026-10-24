"""Count-only PubMed ESearch and conservative query-translation inspection.

This is an early source-acceptance probe, NOT a full search connector. It never
retrieves publication IDs, claims a completed search, or adds/changes metadata.
Network tests use fixtures; live source verification is a separate manual gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from research_y.query_compiler import CompiledSource

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
MAX_RESPONSE_BYTES = 512 * 1024
# Default deliberately remains below the unauthenticated NCBI 3 requests/s cap.
MIN_SECONDS_BETWEEN_REQUESTS = 0.4


class PubMedProbeError(RuntimeError):
    """A source query could not be verified; never treat its count as zero."""

    def __init__(self, message: str, *, retryable: bool = False, http_status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class PubMedCountProbe:
    exact_query: str
    accepted_translation: str
    reported_matches: int
    checked_at_utc: str
    warnings: tuple[str, ...]
    review_reasons: tuple[str, ...]
    translation_matches_submitted: bool
    provider: str = "PubMed ESearch"
    # A count-only request cannot establish that any records were retrieved.
    retrieved_records: int = 0
    retrieval_verified: bool = False

    @property
    def review_required(self) -> bool:
        return bool(self.review_reasons)


@dataclass(frozen=True, slots=True)
class PubMedGroupProbe:
    group_id: str
    chunk_results: tuple[PubMedCountProbe, ...]
    reported_group_matches: int | None
    status: str
    retrieval_verified: bool = False


class _RejectRedirects(HTTPRedirectHandler):
    """Do not follow cross-origin redirects or HTTPS downgrade from ESearch."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_http(request: Request, timeout: float) -> bytes:
    with build_opener(_RejectRedirects()).open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    return body


def _clean_messages(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(item for item in value if item.strip())
    raise PubMedProbeError(f"PubMed returned invalid {field} content")


def _translate_warning_map(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise PubMedProbeError(f"PubMed returned an invalid {field}")
    messages: list[str] = []
    for label, details in value.items():
        if not isinstance(label, str):
            raise PubMedProbeError(f"PubMed returned an invalid {field} entry")
        for detail in _clean_messages(details, field=label):
            messages.append(f"{label}: {detail}")
    return tuple(messages)


def _review_translation(
    exact_query: str, accepted: str, warnings: tuple[str, ...],
) -> tuple[str, ...]:
    """Flag unexpected translation and provider warnings, never certify semantics."""
    reasons: list[str] = []
    if warnings:
        reasons.append("PubMed reported warnings/errors requiring query review")
    if accepted.strip() != exact_query.strip():
        reasons.append("PubMed query translation differs from the submitted query")
    if re.search(r"\[(?:MeSH\s+(?:Terms|Major Topic|Subheading)|MeSH)\]", accepted, re.I):
        reasons.append("PubMed may have introduced unwanted Medical Subject Headings mapping")
    outside_quotes = re.sub(r'"[^"\n]*"', '""', accepted)
    # Internal, explicit disjoint Create-Date partitions necessarily intersect
    # an OR-only concept query with ONE date interval. This is not a new user
    # concept operator. Exempt only the exact accepted and correctly shaped
    # internal suffix; unexpected extra AND/NOT still triggers review.
    if accepted.strip() == exact_query.strip() and re.fullmatch(
        r"\(.+\) AND \(\d{4}/\d{2}/\d{2}:\d{4}/\d{2}/\d{2}\[crdt\]\)",
        exact_query.strip(), flags=re.DOTALL,
    ):
        outside_quotes = re.sub(
            r" AND \(\d{4}/\d{2}/\d{2}:\d{4}/\d{2}/\d{2}\[crdt\]\)$",
            "", outside_quotes,
        )
    if re.search(r"\b(?:AND|NOT)\b", outside_quotes, flags=re.I):
        reasons.append("PubMed translation includes AND/NOT outside quoted literals")
    return tuple(reasons)


def parse_esearch_count(payload: bytes, exact_query: str, *, checked_at_utc: str) -> PubMedCountProbe:
    """Parse ESearch JSON strictly, surfacing embedded HTTP-200 provider errors."""
    if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE_BYTES:
        raise PubMedProbeError("PubMed ESearch returned an oversized or invalid response")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise PubMedProbeError("PubMed ESearch returned malformed JSON") from exc
    if not isinstance(parsed, dict) or "error" in parsed or "ERROR" in parsed:
        raise PubMedProbeError("PubMed ESearch returned a provider error")
    data = parsed.get("esearchresult")
    if not isinstance(data, dict) or "error" in data or "ERROR" in data:
        raise PubMedProbeError("PubMed ESearch did not return a valid search result")
    count_value = data.get("count")
    if (isinstance(count_value, str) and 1 <= len(count_value) <= 20
            and count_value.isascii() and count_value.isdecimal()):
        count = int(count_value)
    elif type(count_value) is int and 0 <= count_value < 10**20:
        count = count_value
    else:
        raise PubMedProbeError("PubMed ESearch returned no valid count")
    translation = data.get("querytranslation")
    if not isinstance(translation, str) or not translation.strip():
        raise PubMedProbeError("PubMed ESearch omitted the accepted query translation")
    if data.get("idlist") not in ([], None):
        raise PubMedProbeError("Count-only PubMed ESearch unexpectedly returned record IDs")
    if str(data.get("retmax", "0")) != "0":
        raise PubMedProbeError("PubMed ESearch did not honour retmax=0")
    warnings = (
        _translate_warning_map(data.get("warninglist"), field="warninglist")
        + _translate_warning_map(data.get("errorlist"), field="errorlist")
    )
    reasons = _review_translation(exact_query, translation, warnings)
    identical = translation.strip() == exact_query.strip()
    return PubMedCountProbe(
        exact_query=exact_query,
        accepted_translation=translation,
        reported_matches=count,
        checked_at_utc=checked_at_utc,
        warnings=warnings,
        review_reasons=reasons,
        translation_matches_submitted=identical,
    )


class PubMedESearchProbeClient:
    """Sequential, rate-paced ESearch count/translation probe.

    Contact details are supplied at runtime. API keys are never persisted,
    printed or included in an exception. Requests use HTTPS POST, not a URL
    bearing credentials, and only a fixed official NCBI endpoint.
    """

    def __init__(
        self,
        *,
        email: str,
        tool: str = "RESEARCHY",
        api_key: str | None = None,
        timeout: float = 20.0,
        transport: Callable[[Request, float], bytes] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Valid NCBI E-utilities contact email is required")
        if not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,50}", tool):
            raise ValueError("NCBI tool identifier must be a no-spaces software name")
        if api_key is not None and (not isinstance(api_key, str) or not api_key.strip()):
            raise ValueError("An API key must be nonblank text when provided")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise ValueError("Network timeout must be between 0 and 60 seconds")
        self._email, self._tool, self._api_key = email, tool, api_key
        self._timeout = float(timeout)
        self._transport = transport or _read_http
        self._clock, self._sleep = clock, sleep
        self._next_allowed = 0.0

    def _pace(self) -> None:
        now = self._clock()
        if now < self._next_allowed:
            self._sleep(self._next_allowed - now)
            now = self._clock()
        self._next_allowed = now + MIN_SECONDS_BETWEEN_REQUESTS

    def fetch_esearch_page(
        self, exact_query: str, *, retstart: int = 0, retmax: int = 0,
    ) -> bytes:
        """Submit a fixed-endpoint ESearch POST for counts or a bounded ID page.

        Request validation enforces PubMed's 10,000-identifier ESearch window.
        It is not a whole-search completeness check and never follows redirects.
        """
        if not isinstance(exact_query, str) or not exact_query.strip():
            raise ValueError("A compiled exact PubMed query is required")
        if any(ord(c) < 32 for c in exact_query):
            raise ValueError("Compiled PubMed query cannot contain control characters")
        if type(retstart) is not int or retstart < 0:
            raise ValueError("retstart must be a nonnegative integer")
        if type(retmax) is not int or not 0 <= retmax <= 1000:
            raise ValueError("retmax must be an integer from 0 to 1000")
        if retstart + retmax > 10000:
            raise ValueError("PubMed ESearch cannot page beyond its 10000-ID window")
        if retmax == 0 and retstart != 0:
            raise ValueError("Count-only requests require retstart zero")
        fields = {
            "db": "pubmed", "term": exact_query, "retmode": "json",
            "retmax": str(retmax), "tool": self._tool, "email": self._email,
        }
        if retstart:
            fields["retstart"] = str(retstart)
        if self._api_key:
            fields["api_key"] = self._api_key
        request = Request(
            ESEARCH_URL,
            data=urlencode(fields).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "RESEARCHY/0.1"},
            method="POST",
        )
        self._pace()
        try:
            return self._transport(request, self._timeout)
        except HTTPError as exc:
            raise PubMedProbeError(
                f"PubMed ESearch HTTP {exc.code}; count or identifiers not verified",
                retryable=exc.code in (429, 500, 502, 503, 504),
                http_status=exc.code,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise PubMedProbeError(
                "PubMed ESearch network error; count or identifiers not verified",
                retryable=True,
            ) from None

    def probe(self, exact_query: str) -> PubMedCountProbe:
        """Count-only query with accepted translation and warning inspection."""
        result = self.fetch_esearch_page(exact_query, retmax=0)
        return parse_esearch_count(
            result, exact_query,
            checked_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


def probe_compiled_group(
    compiled_source: CompiledSource,
    group_id: str,
    client: PubMedESearchProbeClient,
) -> PubMedGroupProbe:
    """Probe each executable chunk; never sum overlapping chunk counts."""
    if compiled_source.source_name != "pubmed":
        raise ValueError("This ESearch probe only supports compiled PubMed queries")
    group = next((g for g in compiled_source.groups if g.group_id == group_id), None)
    if group is None:
        raise KeyError(f"Unknown PubMed strategy group: {group_id}")
    if not group.chunks:
        return PubMedGroupProbe(group_id, (), None, "unsearched_disabled_group")
    reports = tuple(client.probe(chunk.exact_query) for chunk in group.chunks)
    if any(report.review_required for report in reports):
        status = "translation_review_required"
    elif len(reports) > 1:
        status = "partitioned_requires_identifier_union"
    else:
        status = "count_reported_not_retrieved"
    # For partitioned groups, counts may overlap even with exact OR grouping.
    count = reports[0].reported_matches if len(reports) == 1 else None
    return PubMedGroupProbe(group_id, reports, count, status)
