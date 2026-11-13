"""Inspect a retained publication's enrichment, or explicitly request one free Crossref DOI lookup."""
import argparse
import json
from pathlib import Path

from research_y.crossref_client import enrich_publication
from research_y.crossref_metadata import inspect_enrichment
from research_y.projects import open_project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("publication_id")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("inspect")
    lookup = commands.add_parser("lookup")
    for key in ("contact", "actor", "revision"):
        lookup.add_argument("--"+key, required=True)
    lookup.add_argument("--confirm", action="store_true", required=True)
    lookup.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    project = open_project(args.project)
    if args.action == "inspect":
        report = inspect_enrichment(project,args.publication_id)
    else:
        report = enrich_publication(project,args.publication_id,contact=args.contact,actor=args.actor,
                 expected_revision=args.revision,confirmed=args.confirm,refresh=args.refresh)
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__ == "__main__":
    main()
