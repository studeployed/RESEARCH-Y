"""Use a local RESEARCH-Y project to record a confirmed society directory, visit or guidance item."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_y.projects import open_project
from research_y.publication_identity import _object
from research_y.society_sources import import_guidance, list_societies, list_society_visits, record_society_visit, save_society
from research_y.society_guidance_review import suggest_societies, relate_guidance, attach_journal_manifestation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    cmd = parser.add_subparsers(dest="command", required=True)
    cmd.add_parser("directory")
    cmd.add_parser("suggest").add_argument("terms",nargs="+")
    cmd.add_parser("visits").add_argument("society_id")
    for name in ("save-society", "record-visit", "import-guidance", "relate", "attach-journal"):
        sub = cmd.add_parser(name)
        sub.add_argument("input_json", type=Path)
        sub.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args(argv)
    project = open_project(args.project)
    try:
        if args.command == "suggest":
            result = suggest_societies(args.terms)
        elif args.command == "directory":
            result = list_societies(project)
        elif args.command == "visits":
            result = list_society_visits(project, args.society_id)
        else:
            with args.input_json.open("rb") as f:
                payload = f.read(1_000_001)
            if len(payload) > 1_000_000:
                raise ValueError("Input exceeds limit")
            arguments = _object(payload.decode("utf-8-sig"))
            action = {"save-society": save_society, "record-visit": record_society_visit,
                      "import-guidance": import_guidance, "relate":relate_guidance,
                      "attach-journal":attach_journal_manifestation}[args.command]
            result = action(project, confirmed=args.confirm, **arguments)
            if args.command == "attach-journal":
                result = {"publication_id":result.publication_id,"revision":result.revision,
                          "source_count":len(result.retrievals)}
    except (OSError, KeyError, ValueError, TypeError):
        parser.error("Society operation could not be completed with the supplied project, revision and evidence")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
