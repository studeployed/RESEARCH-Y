"""Opt-in, single-query live PubMed acceptance smoke test.

No project data is changed. Pass an NCBI contact email through the environment;
never put API keys or contact values into a public repository or CI fixture.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from research_y.pubmed_probe import PubMedESearchProbeClient, PubMedProbeError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Exact, researcher-reviewed PubMed query")
    args = parser.parse_args(argv)
    email = os.environ.get("RESEARCHY_NCBI_CONTACT_EMAIL")
    if not email:
        print("Not run: set RESEARCHY_NCBI_CONTACT_EMAIL privately before a live probe.", file=sys.stderr)
        return 2
    try:
        client = PubMedESearchProbeClient(
            email=email, api_key=os.environ.get("RESEARCHY_NCBI_API_KEY") or None
        )
        report = client.probe(args.query)
    except (PubMedProbeError, ValueError) as exc:
        print(f"PubMed acceptance not verified: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "exact_query": report.exact_query,
        "accepted_translation": report.accepted_translation,
        "reported_matches": report.reported_matches,
        "checked_at_utc": report.checked_at_utc,
        "warnings": report.warnings,
        "review_reasons": report.review_reasons,
        "review_required": report.review_required,
        "retrieval_verified": False,
    }, indent=2))
    return 3 if report.review_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
