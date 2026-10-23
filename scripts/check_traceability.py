"""Ensure every numbered specification requirement and acceptance test is mapped."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "RESEARCH-Y_SPEC.md"
MAP = ROOT / "docs" / "requirements-traceability.csv"

# Restrict matching to actual spec requirement headers, not internal references.
REQUIREMENTS = re.compile(r"\*\*((?:METH|ARCH|PROJ|SEARCH|SRC|RUN|DATA|DUP|CONF|GUIDE|CLASS|AI|UI|COUNT|AUDIT|EXPORT|SEC)-\d{2})\b")
ACCEPTANCE = re.compile(r"^\|\s*(AT-\d{2})\s*\|", re.MULTILINE)
VALID_PHASES = {"0", "1", "2", "3"}
VALID_STATUSES = {"planned", "partial", "verified"}


def inspect() -> list[str]:
    spec_text = SPEC.read_text(encoding="utf-8")
    required = REQUIREMENTS.findall(spec_text) + ACCEPTANCE.findall(spec_text)
    defined_acceptance = set(ACCEPTANCE.findall(spec_text))
    duplicate_spec = sorted(key for key, n in Counter(required).items() if n != 1)
    with MAP.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    ids = [row.get("requirement_id", "") for row in rows]
    duplicate_map = sorted(key for key, n in Counter(ids).items() if n != 1)
    problems = []
    if duplicate_spec:
        problems.append(f"Specification identifier duplicated: {duplicate_spec}")
    if duplicate_map:
        problems.append(f"Traceability identifier duplicated: {duplicate_map}")
    if missing := sorted(set(required) - set(ids)):
        problems.append(f"Missing identifiers: {missing}")
    if extra := sorted(set(ids) - set(required)):
        problems.append(f"Unexpected identifiers: {extra}")
    for row in rows:
        ident = row.get("requirement_id", "")
        if row.get("phase") not in VALID_PHASES:
            problems.append(f"{ident}: invalid phase")
        if row.get("status") not in VALID_STATUSES:
            problems.append(f"{ident}: invalid status")
        references = row.get("acceptance_tests", "")
        if not references:
            problems.append(f"{ident}: absent acceptance or evaluation reference")
        else:
            unknown_refs = set(references.split(",")) - defined_acceptance
            if unknown_refs:
                problems.append(f"{ident}: nonexistent acceptance reference {sorted(unknown_refs)}")
        if not row.get("test_reference"):
            problems.append(f"{ident}: absent test reference")
    return problems


def main() -> int:
    problems = inspect()
    if problems:
        print("\n".join(problems))
        return 1
    print("Traceability mapping consistent with approved specification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
