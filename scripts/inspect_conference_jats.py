"""Preview abstract boundaries and locators in a locally available JATS supplement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_y.conference_jats import MAX_BYTES, ConferenceInputError, inspect_conference_jats
from research_y.conference_project import admit_extraction, preview_extraction
from research_y.projects import open_project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--landing-url")
    parser.add_argument("--pdf-url")
    parser.add_argument("--pdf-page", action="append", nargs=2, metavar=("XML_ID", "ONE_BASED_PAGE"), default=[])
    parser.add_argument("--project", type=Path)
    parser.add_argument("--original-retrieval")
    parser.add_argument("--admit-locator", action="append")
    parser.add_argument("--revision")
    parser.add_argument("--actor")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--allow-local-retention", action="store_true")
    args = parser.parse_args(argv)
    if (args.project is None) != (args.original_retrieval is None):
        parser.error("Project and original retrieval must be supplied together")
    if args.admit_locator and not (args.project and args.actor and args.revision and args.confirm and args.allow_local_retention):
        parser.error("Admission requires the original project preview, a researcher, confirmation and local retention permission")
    if not args.admit_locator and any((args.actor, args.revision, args.confirm, args.allow_local_retention)):
        parser.error("A review decision requires at least one explicit locator")
    try:
        pages = {name: int(number) for name, number in args.pdf_page}
        if len(pages) != len(args.pdf_page):
            raise ConferenceInputError("Repeated PDF page mapping")
        with args.document.open("rb") as stream:
            source = stream.read(MAX_BYTES + 1)
        options = dict(terms=args.term, landing_url=args.landing_url, pdf_url=args.pdf_url, pdf_pages=pages)
        if args.project is None:
            result = inspect_conference_jats(source, **options)
        elif not args.admit_locator:
            result = preview_extraction(open_project(args.project), args.original_retrieval, source, **options)
        else:
            result = admit_extraction(open_project(args.project), args.original_retrieval, source,
                                      locators=args.admit_locator, actor=args.actor, expected_revision=args.revision,
                                      confirmed=args.confirm, retention_authorized=args.allow_local_retention, **options)
    except (OSError, KeyError, ValueError):
        parser.error("Could not read the document with the supplied JATS profile, URLs and page mappings")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
