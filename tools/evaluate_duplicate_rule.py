"""Evaluate an exact bibliographic rule against ASySD's adjudicated pair groups."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from math import comb
from pathlib import Path

from research_y.publication_match_evidence import bibliographic_key


def fingerprint(row):
    """Require all five fields. Treat exported missing values as missing evidence."""
    return bibliographic_key(*(row[name] for name in ("doi", "title", "year", "journal", "pages")))


def evaluate(rows):
    groups, keys, intersections = Counter(), Counter(), Counter()
    seen = set()
    for row in rows:
        record, group = row["record_id"], row["duplicateid"]
        if not record.isdecimal() or not group.isdecimal() or record in seen:
            raise ValueError("Invalid adjudicated record or group")
        seen.add(record)
        groups[group] += 1
        key = fingerprint(row)
        if key is not None:
            keys[key] += 1
            intersections[key, group] += 1
    if not seen:
        raise ValueError("Empty benchmark")

    def pairs(counts):
        return sum(comb(size, 2) for size in counts.values())

    eligible, actual, agree = pairs(keys), pairs(groups), pairs(intersections)
    return dict(records=len(seen), adjudicated_groups=len(groups), total_pairs=comb(len(seen), 2),
                comparable_records=keys.total(), proposed_pairs=eligible,
                true_positives=agree, false_positives=eligible-agree, false_negatives=actual-agree,
                true_negatives=comb(len(seen), 2)-eligible-actual+agree)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--encoding", choices=("utf-8-sig", "latin-1"), default="utf-8-sig")
    args = parser.parse_args()
    with args.file.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with args.file.open(encoding=args.encoding, newline="") as stream:
        print(json.dumps(dict(input_sha256=digest, **evaluate(csv.DictReader(stream))), indent=2))


if __name__ == "__main__":
    main()
