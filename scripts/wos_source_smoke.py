"""Manual-only Starter entitlement and two-page smoke; never a full retrieval.

The fixed public Topic query avoids proprietary study terms. Public evidence
contains counts, hashes and missingness only, not licensed record content.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

from research_y.wos_starter import SOURCE_COVERAGE, WoSStarterError, validate_page_sequence
from research_y.wos_starter_client import WoSStarterClient

QUERY = 'TS=("ECMO")'
DATABASE = "WOS"


def run_smoke(client: WoSStarterClient) -> dict:
    evidence = {
        "source": "Web of Science Starter", "query": QUERY, "database": DATABASE,
        "source_coverage": SOURCE_COVERAGE, "sort_field": "LD+A",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "incomplete", "reason_code": "not_executed",
        "reported_matches": None, "access_probe_records_received": 0,
        "validated_sample_records": 0, "pages": [], "quota_observations": [],
        "accepted_translation": None,
        "translation_status": "not_exposed_by_starter_contract",
        "source_retrieval_verified": False,
        "full_retrieval_tested": False, "durable_recovery_tested": False,
        "licensed_record_content_exported": False,
        "requests_made": 0,
    }
    try:
        pilot = client.fetch_page(QUERY, database=DATABASE, page=1, limit=1)
        evidence["reported_matches"] = pilot.reported_matches
        evidence["access_probe_records_received"] = len(pilot.records)
        evidence["quota_observations"].append(asdict(pilot.quota))
        evidence["entitlement_status"] = pilot.quota.entitlement_status
        evidence["pilot_response_sha256"] = pilot.response_sha256
        if pilot.quota.entitlement_status != "institutional_allowance_observed":
            evidence["reason_code"] = "institutional_entitlement_not_verified"
            return evidence
        if not pilot.quota.can_continue:
            evidence["reason_code"] = "daily_quota_unavailable_or_exhausted"
            return evidence
        if pilot.reported_matches <= 50:
            evidence["reason_code"] = "too_few_matches_for_two_page_smoke"
            return evidence
        pages = []
        for number in (1, 2):
            page = client.fetch_page(QUERY, database=DATABASE, page=number, limit=50)
            # Preserve safe available response facts even if count drift is found.
            evidence["quota_observations"].append(asdict(page.quota))
            evidence["pages"].append({
                "page": page.page, "limit": page.limit,
                "reported_matches": page.reported_matches,
                "records_received": len(page.records),
                "response_sha256": page.response_sha256,
                "retrieved_at_utc": page.retrieved_at_utc,
                "records_with_title": sum(bool(x.as_dict().get("title")) for x in page.records),
                "records_without_abstract": sum(x.abstract_status == "not_returned_by_source" for x in page.records),
            })
            if (page.quota.entitlement_status != "institutional_allowance_observed"
                    or page.quota.daily_remaining is None):
                raise WoSStarterError("quota_or_entitlement_changed")
            if page.reported_matches != pilot.reported_matches:
                raise WoSStarterError("source_count_changed")
            if number == 1 and page.records[0].uid != pilot.records[0].uid:
                raise WoSStarterError("first_accession_changed")
            pages.append(page)
            identifiers = validate_page_sequence(pages)
            evidence["validated_sample_records"] = len(identifiers)
        evidence["sample_accession_union_sha256"] = sha256(
            "\n".join(sorted(identifiers)).encode("utf-8")).hexdigest()
        evidence["status"] = "entitlement_and_two_page_sample_verified"
        evidence["reason_code"] = "sample_only_not_complete_retrieval"
        return evidence
    except WoSStarterError as exc:
        evidence["reason_code"] = exc.code
        evidence["http_status"] = exc.http_status
        evidence["retryable"] = exc.retryable
        evidence["retry_after_seconds"] = exc.retry_after_seconds
        return evidence
    except Exception:
        evidence["reason_code"] = "unexpected_error"
        return evidence
    finally:
        evidence["requests_made"] = client.requests_made


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2)+"\n",
                    encoding="utf-8")
    temp.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    key = os.environ.get("RESEARCHY_WOS_STARTER_API_KEY")
    if not key:
        print("Not run: configure the private RESEARCHY_WOS_STARTER_API_KEY secret.", file=sys.stderr)
        return 2
    try:
        result = run_smoke(WoSStarterClient(api_key=key, request_budget=3))
        commit = os.environ.get("GITHUB_SHA", "")
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        result["commit_sha"] = commit if re.fullmatch(r"[a-f0-9]{40}", commit) else None
        result["github_run_id"] = run_id if re.fullmatch(r"[0-9]{1,20}", run_id) else None
        _save(args.output, result)
        print(json.dumps({k: result[k] for k in (
            "status", "reason_code", "reported_matches", "validated_sample_records",
            "requests_made", "source_retrieval_verified", "durable_recovery_tested")}, sort_keys=True))
        return 0 if result["status"] == "entitlement_and_two_page_sample_verified" else 3
    except Exception:
        print("Starter smoke could not complete safely; no source acceptance claimed.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
