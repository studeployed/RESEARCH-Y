"""One targeted request to the free Crossref Works endpoint, with durable project-wide pacing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from http.client import HTTPException
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request

from research_y import publication_identity as identity
from research_y.crossref_metadata import MAX_RESPONSE, _target, inspect_enrichment, record_work_response
from research_y.http_timing import retry_after_seconds
from research_y.projects import _validated_project_connection

RESERVED = "crossref_request_reserved_v1"
FINISHED = "crossref_request_finished_v1"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(request):
    try:
        stream = build_opener(_NoRedirect()).open(request, timeout=20)
    except HTTPError as error:
        stream = error
    with stream:
        headers = {k.lower(): v for k, v in stream.headers.items()}
        if stream.status != 200:
            return stream.status, headers, b""
        return stream.status, headers, stream.read(MAX_RESPONSE + 1)


def _wait(headers, status, now):
    delay = 1.0
    limit, interval = headers.get("x-rate-limit-limit", ""), headers.get("x-rate-limit-interval", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)s", interval.strip())
    if m and limit.isascii() and limit.isdigit() and 0 < int(limit) <= 1_000_000:
        # A single serial client using the entire reported interval satisfies
        # both fixed-window and token-bucket interpretations of the limit.
        delay = max(delay, float(m.group(1)))
    retry = retry_after_seconds(headers.get("retry-after"), now)
    if retry is not None:
        delay = max(delay, retry)
    elif status in (429, 503):
        delay = max(delay, 60)
    return delay


def enrich_publication(project, publication_id, *, contact, actor, expected_revision,
                       confirmed, refresh=False, transport=_get, now=lambda: datetime.now(timezone.utc)):
    """Explicitly fetch once. Successful or not-found receipts are reused until an explicit refresh."""
    identity._text(actor, 200)
    if (confirmed is not True or type(refresh) is not bool or not isinstance(contact, str)
            or len(contact) > 254 or parseaddr(contact)[1] != contact
            or not re.fullmatch(r"[^\s@<>\x00-\x1f\x7f]+@[^\s@<>\x00-\x1f\x7f]+\.[^\s@<>\x00-\x1f\x7f]+", contact)):
        raise ValueError("Valid contact and explicit authorization required")
    view = inspect_enrichment(project,publication_id)
    target = view["target"]
    if expected_revision != target["revision"]:
        raise identity.StalePublicationError("Inspect the current DOI before requesting enrichment")
    if target["doi"] is None:
        return dict(status=target["status"], requested=False)
    cached = view["current"]
    if not refresh and cached and cached["outcome"] in ("metadata_available","metadata_gap","not_found"):
        return dict(status="cached", requested=False, receipt=cached)
    at = now().astimezone(timezone.utc)
    request = Request(target["request_url"]+"?"+urlencode({"mailto":contact}),
                      headers={"Accept":"application/json","User-Agent":"RESEARCH-Y/0.1 (mailto:"+contact+")"})
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        if _target(db, publication_id) != target:
            raise identity.StalePublicationError("Source evidence changed")
        last = db.execute("SELECT event_id,event_type FROM audit_events WHERE event_type IN (?,?) "
                          "ORDER BY event_id DESC LIMIT 1", (RESERVED, FINISHED)).fetchone()
        if last:
            event = identity._event(db,last[0],last[1])
            deadline = datetime.fromisoformat(event["not_before_utc"])
            if at < deadline:
                return dict(status="provider_hold", requested=False, not_before_utc=event["not_before_utc"])
        # A terminated process leaves this conservative lease. The HTTP client
        # has a shorter timeout. The next request is an explicit user action.
        reservation = identity._audit(db, RESERVED, dict(version=1, at_utc=at.isoformat(),
                   publication_id=publication_id, doi=target["doi"], not_before_utc=(at+timedelta(minutes=5)).isoformat()))
    status, headers, body = 0, {}, b""
    try:
        status, headers, body = transport(request)
    except (OSError, URLError, HTTPException):
        pass
    finished = now().astimezone(timezone.utc)
    try:
        delay = _wait(headers, status, finished)
        deadline = finished + timedelta(seconds=delay)
    except (ValueError, OverflowError):
        deadline = datetime.max.replace(tzinfo=timezone.utc)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        identity._audit(db,FINISHED,dict(version=1,at_utc=finished.isoformat(),reservation=reservation,
              publication_id=publication_id, doi=target["doi"], http_status=status or None,
              not_before_utc=deadline.isoformat()))
    if not status:
        return dict(status="unknown_request_outcome",requested=True)
    receipt = record_work_response(project, publication_id, expected_revision=expected_revision,
              requested_doi=target["doi"], status_code=status, body=body,
              retrieved_at_utc=finished.isoformat(), actor=actor, confirmed=True)
    return dict(status=receipt["outcome"], requested=True, receipt=receipt)
