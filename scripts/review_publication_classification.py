"""Inspect or explicitly review publication labels in an existing RESEARCH-Y project."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_y.projects import open_project
from research_y.study_classification import LABELS, read_classification, review_classification


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("publication_id")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("inspect")
    decide = commands.add_parser("review")
    decide.add_argument("--dimension", choices=tuple(LABELS), required=True)
    decide.add_argument("--label", action="append", required=True)
    for name in ("actor", "rationale", "revision"):
        decide.add_argument("--" + name, required=True)
    decide.add_argument("--confirm", action="store_true", required=True)
    args = parser.parse_args(argv)
    project = open_project(args.project)
    try:
        if args.action == "inspect":
            result = read_classification(project, args.publication_id)
        else:
            result = review_classification(project, args.publication_id, dimension=args.dimension,
                     labels=args.label, actor=args.actor, rationale=args.rationale,
                     expected_revision=args.revision, confirmed=args.confirm)
    except (KeyError, ValueError):
        parser.error("Classification unavailable or changed; inspect the publication and its evidence")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
