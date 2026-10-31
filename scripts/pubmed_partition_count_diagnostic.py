"""P1-04h: two-request, manual-only PubMed Create Date count diagnosis.

This intentionally does not invoke partitioned retrieval, fetch identifiers,
write to a project database, or infer successful publication retrieval.
It reports the source's actual count/translation and the rejection reasons.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Callable
from urllib.parse import parse_qs
from urllib.request import Request

from research_y.pubmed_partition import DateWindow
from research_y.pubmed_probe import (
    ESEARCH_URL, PubMedCountProbe, PubMedESearchProbeClient, PubMedProbeError, _read_http,
)

QUERY = '("ECMO"[All Fields])'
WINDOW_START = date(1900, 1, 1)
MIN_MATCHES = 10_001
MAX_MATCHES = 30_000
MAX_SOURCE_REQUESTS = 2
EVIDENCE_NAME = "pubmed-partition-count-diagnostic.json"


class DiagnosticError(ValueError):
    """The fixed, non-retrieval diagnostic cannot safely proceed."""


class _CountOnlyTransport:
    """Allow exactly the fixed root and its one date-range count, never IDs."""

    def __init__(self, permitted_queries: tuple[str, str],
                 backend: Callable[[Request, float], bytes]):
        self.permitted_queries = permitted_queries
        self.backend = backend
        self.calls: list[str] = []

    def __call__(self, request: Request, timeout: float) -> bytes:
        if request.full_url != ESEARCH_URL or request.get_method() != "POST":
            raise DiagnosticError("Non-count diagnostic endpoint was attempted")
        try:
            args = parse_qs(request.data.decode("utf-8"), strict_parsing=True)
        except (UnicodeError, ValueError):
            raise DiagnosticError("Invalid diagnostic request") from None
        if (args.get("db") != ["pubmed"] or args.get("retmode") != ["json"]
                or args.get("retmax") != ["0"] or "retstart" in args
                or args.get("term") not in ([self.permitted_queries[0]],
                                            [self.permitted_queries[1]])):
            raise DiagnosticError("Non-count or unauthorised diagnostic request")
        if len(self.calls) >= MAX_SOURCE_REQUESTS:
            raise DiagnosticError("Two-request diagnostic budget exhausted")
        query = args["term"][0]
        self.calls.append(query)
        return self.backend(request, timeout)


def _redact(value: str, *, secrets: tuple[str, ...]) -> str:
    """Never copy runtime secrets from provider-controlled text to public evidence."""
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def _source_record(probe: PubMedCountProbe, *, secrets: tuple[str, ...]) -> dict[str, object]:
    accepted = _redact(probe.accepted_translation, secrets=secrets)
    warnings = [_redact(warning, secrets=secrets) for warning in probe.warnings]
    reasons = [_redact(reason, secrets=secrets) for reason in probe.review_reasons]
    return {
        "submitted_query": probe.exact_query,
        "accepted_translation": accepted,
        "provider_text_redacted": accepted != probe.accepted_translation
            or any(x != y for x, y in zip(warnings, probe.warnings)),
        "reported_matches": probe.reported_matches,
        "checked_at_utc": probe.checked_at_utc,
        "warnings": warnings,
        "review_reasons": reasons,
        "review_required": probe.review_required,
        "translation_matches_submitted": probe.translation_matches_submitted,
        "retrieved_records": 0,
    }


def _source_error(exc: Exception) -> dict[str, object]:
    """Controlled error categories only. Never publish arbitrary exception strings."""
    if isinstance(exc, PubMedProbeError):
        if exc.http_status is not None:
            return {"category": "http_error", "http_status": exc.http_status,
                    "retryable": exc.retryable}
        if exc.retryable:
            return {"category": "network_error", "retryable": True}
        return {"category": "invalid_source_response", "retryable": False}
    if isinstance(exc, DiagnosticError):
        return {"category": "diagnostic_safety_refusal", "retryable": False}
    return {"category": "unexpected_error", "retryable": False}


def _write_evidence(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    temp.replace(path)


def diagnose(
    contact: str, api_key: str | None, *,
    output_path: Path,
    now: datetime | None = None,
    transport: Callable[[Request, float], bytes] = _read_http,
) -> dict[str, object]:
    """Probe the literal root then first complete Create Date interval, count-only.

    A result with matching counts still cannot establish disjoint partitions,
    identifier retrieval, checkpoint recoverability, or source completeness.
    """
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("A timezone-aware diagnostic instant is required")
    window = DateWindow(WINDOW_START, moment.astimezone(timezone.utc).date() + timedelta(days=1))
    partition_query = window.query_for(QUERY)
    guard = _CountOnlyTransport((QUERY, partition_query), backend=transport)
    client = PubMedESearchProbeClient(email=contact, api_key=api_key, transport=guard)
    secrets = (contact, api_key or "")

    evidence: dict[str, object] = {
        "diagnostic": "P1-04h PubMed count-only first partition",
        "status": "incomplete",
        "reason_code": "not_executed",
        "checked_at_utc": moment.astimezone(timezone.utc).isoformat(),
        "repository_commit_sha": os.environ.get("GITHUB_SHA"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "query": QUERY,
        "date_window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "root": None,
        "partition": None,
        "reported_count_difference": None,
        "counts_reconciled": False,
        "source_requests": 0,
        "identifier_pages_requested": 0,
        "retrieved_unique_pmids": 0,
        "identifiers_reconciled": False,
        "source_retrieval_verified": False,
        "metadata_acquired": False,
        "error": None,
    }

    def persist() -> dict[str, object]:
        evidence["source_requests"] = len(guard.calls)
        _write_evidence(output_path, evidence)
        return evidence

    try:
        root = client.probe(QUERY)
    except Exception as exc:
        evidence["reason_code"] = "root_count_request_failed"
        evidence["error"] = _source_error(exc)
        return persist()
    evidence["root"] = _source_record(root, secrets=secrets)
    if root.review_required:
        evidence["status"] = "query_review_required"
        evidence["reason_code"] = "root_translation_or_warnings"
        return persist()
    if not MIN_MATCHES <= root.reported_matches <= MAX_MATCHES:
        evidence["reason_code"] = "root_count_outside_diagnostic_safety_bounds"
        return persist()

    # Unlike the normal retrieval, do not suppress the actual accepted
    # translation and warning details when the first partition needs review.
    try:
        part = client.probe(partition_query, allow_crdt_partition=True)
    except Exception as exc:
        evidence["reason_code"] = "partition_count_request_failed"
        evidence["error"] = _source_error(exc)
        return persist()
    evidence["partition"] = _source_record(part, secrets=secrets)
    evidence["reported_count_difference"] = part.reported_matches - root.reported_matches
    evidence["counts_reconciled"] = part.reported_matches == root.reported_matches

    if part.review_required:
        evidence["status"] = "query_review_required"
        evidence["reason_code"] = "partition_translation_or_warnings"
    elif not evidence["counts_reconciled"]:
        evidence["reason_code"] = "create_date_coverage_count_mismatch"
    else:
        evidence["status"] = "count_only_reconciled"
        evidence["reason_code"] = "no_first_partition_count_discrepancy"
    return persist()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    contact = os.environ.get("RESEARCHY_NCBI_CONTACT_EMAIL", "")
    key = os.environ.get("RESEARCHY_NCBI_API_KEY") or None
    if not contact:
        print("Contact secret absent; no NCBI request attempted.", file=sys.stderr)
        return 2
    try:
        result = diagnose(contact, key, output_path=args.output)
    except Exception:
        # Unexpected errors must never echo transport exceptions or credentials.
        print("Diagnostic could not be executed safely; no success claimed.", file=sys.stderr)
        return 3
    public_summary = {
        "status": result["status"],
        "reason_code": result["reason_code"],
        "source_requests": result["source_requests"],
        "root": result["root"],
        "partition": result["partition"],
        "reported_count_difference": result["reported_count_difference"],
        "identifier_pages_requested": 0,
        "source_retrieval_verified": False,
        "error": result["error"],
    }
    print(json.dumps(public_summary, sort_keys=True, ensure_ascii=False))
    return 0 if result["status"] == "count_only_reconciled" else 3


if __name__ == "__main__":
    raise SystemExit(main())
