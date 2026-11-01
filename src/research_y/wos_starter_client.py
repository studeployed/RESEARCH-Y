"""Fixed-origin, secret-safe, rate-paced Starter transport (no implicit retries).

Daily quota/persistent multi-day job orchestration belongs to P1-05b. This
client exposes observed limits and retry timing without guessing reset times.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import threading
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from research_y.wos_starter import (MAX_RESPONSE_BYTES, WoSPage, WoSQuota,
                                  WoSStarterError, parse_document_page, parse_quota,
                                  validate_request)

DOCUMENTS_URL = "https://api.clarivate.com/apis/wos-starter/v1/documents"
MIN_REQUEST_INTERVAL = 1.05  # Conservative even for trial's one request/second.


@dataclass(frozen=True, slots=True)
class WoSHTTPResponse:
    status: int
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_http(request: Request, timeout: float) -> WoSHTTPResponse:
    with build_opener(_RejectRedirects()).open(request, timeout=timeout) as response:
        return WoSHTTPResponse(response.status, dict(response.headers),
                               response.read(MAX_RESPONSE_BYTES + 1))


def _retry_after(headers: Mapping[str, str], now: datetime) -> float | None:
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if not isinstance(value, str):
        return None
    try:
        if value.strip().isascii() and value.strip().isdecimal():
            seconds = float(value.strip())
        else:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                return None
            seconds = max(0.0, (when-now).total_seconds())
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


class WoSStarterClient:
    """Serial requests; first access probe allowed, continuation needs quota evidence.

    The key is a header only. Response/exception text is never printed. Request
    budget includes unsuccessful attempts. A new client is not durable recovery.
    """

    def __init__(self, *, api_key: str, request_budget: int = 3, timeout: float = 20,
                 transport: Callable[[Request, float], WoSHTTPResponse] = _read_http,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if (not isinstance(api_key, str) or not api_key or len(api_key) > 4096
                or not api_key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in api_key)):
            raise WoSStarterError("invalid_api_key")
        if type(request_budget) is not int or not 1 <= request_budget <= 10000:
            raise WoSStarterError("invalid_request_budget")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise WoSStarterError("invalid_timeout")
        self._key = api_key
        self._transport, self._clock, self._sleep, self._utc_now = transport, clock, sleep, utc_now
        self._budget, self._timeout = request_budget, timeout
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self._retry_not_before = 0.0
        self._blocked = False
        self.requests_made = 0
        self.quota = WoSQuota()

    @property
    def requests_remaining(self) -> int:
        """Local client allowance only; not provider quota or retry permission.

        The checkpoint worker uses this to pause before reserving work that the
        client would refuse. The existing locked transport guard still enforces
        the hard limit independently, including unsuccessful attempts.
        """
        return max(0, self._budget - self.requests_made)

    @property
    def retry_after_remaining(self) -> float:
        """Server-directed remaining delay, for persistence across process restarts."""
        return max(0.0, self._retry_not_before - self._clock())

    def fetch_page(self, exact_query: str, *, database: str = "WOS", page: int = 1,
                   limit: int = 50) -> WoSPage:
        validate_request(exact_query, database, page, limit)
        # Never allow a key to be echoed in persisted query evidence.
        if self._key in exact_query:
            raise WoSStarterError("credential_in_query")
        with self._lock:
            if self.requests_made >= self._budget:
                raise WoSStarterError("request_budget_exhausted")
            if self._clock() < self._retry_not_before:
                raise WoSStarterError("retry_not_due", retryable=True,
                                      retry_after_seconds=self._retry_not_before-self._clock())
            if self._blocked:
                raise WoSStarterError("explicit_revalidation_required")
            if self.requests_made and not self.quota.can_continue:
                raise WoSStarterError("quota_or_entitlement_unverified")
            fields = {"db": database, "q": exact_query, "limit": str(limit),
                      "page": str(page), "sortField": "LD+A"}
            request = Request(DOCUMENTS_URL + "?" + urlencode(fields),
                              headers={"X-ApiKey": self._key, "Accept": "application/json",
                                       "User-Agent": "RESEARCHY/0.1"}, method="GET")
            now = self._clock()
            if now < self._next_allowed:
                self._sleep(self._next_allowed-now)
            self._next_allowed = self._clock()+MIN_REQUEST_INTERVAL
            self.requests_made += 1
            try:
                response = self._transport(request, self._timeout)
            except HTTPError as exc:
                response = WoSHTTPResponse(exc.code, dict(exc.headers or {}), b"")
                exc.close()
            except (URLError, TimeoutError, OSError):
                self._blocked = True
                raise WoSStarterError("network_error", retryable=True) from None
            except Exception:
                self._blocked = True
                raise WoSStarterError("transport_error") from None
            if (not isinstance(response, WoSHTTPResponse)
                    or type(response.status) is not int
                    or not isinstance(response.headers, Mapping)):
                self._blocked = True
                raise WoSStarterError("invalid_transport_response")
            self.quota = parse_quota(response.headers)
            delay = _retry_after(response.headers, self._utc_now())
            if delay is not None:
                self._retry_not_before = self._clock()+delay
            if response.status != 200:
                self._blocked = True
                code = ("authentication_or_entitlement_denied" if response.status in (401, 403)
                        else "quota_or_rate_limited" if response.status == 429
                        else "redirect_refused" if response.status in (301, 302, 303, 307, 308)
                        else "http_error")
                raise WoSStarterError(code, http_status=response.status,
                                      retryable=response.status in (429, 500, 502, 503, 504),
                                      retry_after_seconds=delay)
            # Fail closed if a malicious/unexpected provider echoes the key in
            # parsed text (including escaped JSON); no mutated source evidence.
            try:
                result = parse_document_page(response.body, exact_query=exact_query,
                    database=database, requested_page=page, requested_limit=limit,
                    retrieved_at_utc=self._utc_now().astimezone(timezone.utc).isoformat(),
                    headers=response.headers)
                import json
                values = [json.loads(result.response_json)]
                while values:
                    value = values.pop()
                    if isinstance(value, str) and self._key in value:
                        raise WoSStarterError("credential_echo_in_source")
                    if isinstance(value, dict):
                        values.extend(value.keys())
                        values.extend(value.values())
                    elif isinstance(value, list):
                        values.extend(value)
            except WoSStarterError:
                self._blocked = True
                raise
            return result
