"""Preview abstract boundaries and locators in a locally available JATS supplement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_y.conference_jats import MAX_BYTES, ConferenceInputError, inspect_conference_jats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--landing-url")
    parser.add_argument("--pdf-url")
    parser.add_argument("--pdf-page", action="append", nargs=2, metavar=("XML_ID", "ONE_BASED_PAGE"), default=[])
    args = parser.parse_args(argv)
    try:
        pages = {name: int(number) for name, number in args.pdf_page}
        if len(pages) != len(args.pdf_page):
            raise ConferenceInputError("Repeated PDF page mapping")
        with args.document.open("rb") as stream:
            source = stream.read(MAX_BYTES + 1)
        result = inspect_conference_jats(source, terms=args.term, landing_url=args.landing_url,
                                         pdf_url=args.pdf_url, pdf_pages=pages)
    except (OSError, ValueError):
        parser.error("Could not read the document with the supplied JATS profile, URLs and page mappings")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
