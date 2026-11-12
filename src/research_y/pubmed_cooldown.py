"""Respect PubMed Retry-After across ESearch, EFetch and project reopening."""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
import json

from research_y.projects import _validated_project_connection
from research_y.storage import _audit
from research_y.http_timing import retry_after_seconds

EVENT = "pubmed_retry_after_v1"
_project = ContextVar("pubmed_request_project", default=None)


def project_requests(function):
    """Associate this source operation's HTTP calls with its durable project journal."""
    @wraps(function)
    def scoped(project, *args, **kwargs):
        token = _project.set(project)
        try:
            return function(project, *args, **kwargs)
        finally:
            _project.reset(token)
    return scoped


def _latest(db, cursor, last):
    high, = db.execute("SELECT COALESCE(MAX(event_id), 0) FROM audit_events").fetchone()
    if high < cursor:
        cursor = 0
    for (raw,) in db.execute(
        "SELECT details_json FROM audit_events WHERE event_id>? AND event_id<=? AND event_type=?",
        (cursor, high, EVENT),
    ):
        try:
            data = json.loads(raw)
            deadline = datetime.fromisoformat(data["retry_not_before_utc"])
            if deadline.utcoffset() != timedelta(0):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ValueError("Invalid PubMed cooldown evidence") from None
        last = max(last, deadline) if last is not None else deadline
    return high, last


def retry_not_before(db):
    """Read the latest recorded provider deadline in the caller's snapshot."""
    _, latest = _latest(db, 0, None)
    return latest.isoformat() if latest is not None else None


class PubMedCooldown:
    def __init__(self, utcnow):
        self.utcnow = utcnow
        self.deadline = None
        self.cursor = 0
        self.project_key = None

    def pending(self, db=None):
        project = _project.get()
        if project is not None:
            key = (project.identifier, project.database_path)
            if key != self.project_key:
                self.cursor = 0
                self.project_key = key
            if db is not None:
                self.cursor, self.deadline = _latest(db, self.cursor, self.deadline)
            else:
                with _validated_project_connection(project) as reader:
                    reader.execute("BEGIN")
                    self.cursor, self.deadline = _latest(reader, self.cursor, self.deadline)
        return self.deadline if self.deadline is not None and self.utcnow() < self.deadline else None

    def observe(self, headers):
        if headers is None:
            return
        now = self.utcnow().astimezone(timezone.utc)
        deadlines = []
        for name, value in headers.items():
            if name.lower() != "retry-after":
                continue
            delay = retry_after_seconds(value, now)
            if delay is None and isinstance(value, str) and value.strip().isascii() and value.strip().isdecimal():
                deadlines.append(datetime.max.replace(tzinfo=timezone.utc))
                continue
            if delay is None or delay <= 0:
                continue
            try:
                deadlines.append(now + timedelta(seconds=delay))
            except OverflowError:
                deadlines.append(datetime.max.replace(tzinfo=timezone.utc))
        if not deadlines:
            return
        until = max(deadlines)
        self.deadline = max(self.deadline, until) if self.deadline is not None else until
        project = _project.get()
        if project is not None:
            with _validated_project_connection(project) as db:
                db.execute("BEGIN IMMEDIATE")
                _audit(db, kind=EVENT, timestamp=now.isoformat(), details={"retry_not_before_utc": until.isoformat()})
