"""Opt-in live PubMed ESearch translation and one-record EFetch smoke check.

Not an exhaustive search. Contact email is supplied privately at runtime;
no project data is changed and no abstract text or API keys are printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from research_y.pubmed_probe import PubMedESearchProbeClient, PubMedProbeError
from research_y.pubmed_ids import parse_identifier_page
from research_y.pubmed_metadata import PubMedEFetchClient, PubMedMetadataError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Exact approved PubMed All Fields expression")
    args = parser.parse_args(argv)
    email = os.environ.get("RESEARCHY_NCBI_CONTACT_EMAIL")
    if not email:
        print("Not run: set RESEARCHY_NCBI_CONTACT_EMAIL privately.", file=sys.stderr)
        return 2
    try:
        esearch = PubMedESearchProbeClient(
            email=email, api_key=os.environ.get("RESEARCHY_NCBI_API_KEY") or None,
        )
        count = esearch.probe(args.query)
        if count.review_required:
            print(json.dumps({"source": "PubMed", "result": "query_review_required",
                              "submitted": args.query, "accepted_translation": count.accepted_translation,
                              "warnings": count.warnings, "reasons": count.review_reasons}, indent=2))
            return 3
        if count.reported_matches == 0:
            print(json.dumps({"source": "PubMed", "result": "zero_count",
                              "accepted_translation": count.accepted_translation,
                              "retrieval_verified": False}, indent=2))
            return 0
        payload = esearch.fetch_esearch_page(args.query, retstart=0, retmax=1)
        page = parse_identifier_page(
            payload, exact_query=args.query, retstart=0, retmax=1,
            retrieved_at_utc=count.checked_at_utc,
        )
        if page.review_required or page.reported_matches != count.reported_matches:
            print("Incomplete: provider changed query translation or count.", file=sys.stderr)
            return 3
        batch = PubMedEFetchClient(esearch).fetch(page.pmids)
        record = batch.records[0]
        print(json.dumps({
            "source": "PubMed ESearch / EFetch", "result": "single_record_metadata_received",
            "submitted": args.query, "accepted_translation": count.accepted_translation,
            "reported_matches": count.reported_matches, "retrieved_pmid": record.pmid,
            "title": record.title, "abstract_status": record.abstract_status,
            "abstract_section_count": len(record.abstract_sections),
            "abstract_copyright_notice_present": bool(record.abstract_copyright),
            "metadata_acquired_at_utc": batch.retrieved_at_utc,
            "source_retrieval_verified": False,
        }, indent=2, ensure_ascii=False))
        return 0
    except (PubMedProbeError, PubMedMetadataError, ValueError):
        print("PubMed smoke test failed; no source completeness is claimed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
