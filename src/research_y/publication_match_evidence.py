"""Conservative source-field comparisons, not bibliographic identity verification.

Only explicit PubMed/Starter record paths are read. No provider access, fuzzy
threshold, abstract copying, inferred identifier scope or automatic merge.
Normalised comparisons never replace source values. Unknown is not agreement.
"""
from __future__ import annotations

import re
from typing import Any

RULE_VERSION = "source-pair-comparison/1"
_MISSING = object()
_INVALID = object()


def _at(value: Any, path: tuple[str, ...]) -> Any:
    for part in path:
        if not isinstance(value, dict):
            return _MISSING if value is _MISSING else _INVALID
        value = value.get(part, _MISSING)
    return value


def _string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        return None
    return " ".join(value.strip().split()).casefold()


def _doi(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                   "http://dx.doi.org/", "doi:"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):].strip()
            break
    # Structural candidate syntax only, NOT a DOI registration check. Retain
    # punctuation and encoding: stripping/decoding them can change identity.
    if not re.fullmatch(r"10\.[0-9]{4,9}/[^\s\x00-\x1f\x7f]+", value):
        return None
    return value.lower()


def _pmid(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,31}", value) else None


def _uid(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9]*:[A-Za-z0-9._-]{1,240}", value) else None


def _year(value: Any) -> str | None:
    if type(value) is int:
        value = str(value)
    return value if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{3}", value) else None


def _field(payload: dict, path: tuple[str, ...], normalise=_string, *, many=False) -> dict:
    raw = _at(payload, path)
    out = {"path": list(path), "status": "missing", "value": None, "normalised": None}
    if raw is _MISSING:
        return out
    if raw is _INVALID:
        out["status"] = "malformed"
        return out
    out["value"] = raw
    if raw in (None, "", [], {}):
        out["status"] = "not_supplied"
        return out
    items = raw if many and isinstance(raw, list) else [raw]
    values = [normalise(v) for v in items]
    if any(v is None for v in values):
        out["status"] = "malformed"
    elif len(set(values)) != 1:
        out["status"] = "multiple_values"
    else:
        out.update(status="present", normalised=values[0])
    return out


def _authors(raw: Any, pubmed: bool) -> str | None:
    if not isinstance(raw, list) or not raw:
        return None
    names = []
    for author in raw:
        if not isinstance(author, dict):
            return None
        if pubmed:
            collective = author.get("collective_name")
            if collective:
                name = _string(collective)
            else:
                last = _string(author.get("last_name"))
                first = _string(author.get("fore_name") or author.get("initials"))
                name = f"{last}, {first}" if last and first else None
        else:
            name = _string(author.get("displayName"))
        if not name:
            return None
        names.append(name)
    # Ordered structured encoding; never join names with an ambiguous delimiter.
    from research_y.publication_identity import _json
    return _json(names)


def _publication_year(raw: Any) -> str | None:
    if (not isinstance(raw, list) or any(not isinstance(d, dict) or not isinstance(d.get("kind"), str)
                                          for d in raw)):
        return None
    dates = [d for d in raw if isinstance(d, dict) and isinstance(d.get("kind"), str)
             and (d["kind"] == "journal_pub_date" or d["kind"].startswith("article_"))]
    if not dates:
        return None
    years = [_year(d.get("year")) for d in dates]
    return years[0] if None not in years and len(set(years)) == 1 else None


def _tags(raw: Any) -> str | None:
    if not isinstance(raw, list) or not raw:
        return None
    values = [_string(v) for v in raw]
    if None in values:
        return None
    from research_y.publication_identity import _json
    return _json(sorted(set(values)))


def project_source(source: dict) -> dict:
    """Read explicit local source paths; all returned values remain unverified."""
    payload = source["original_metadata"]
    kind = source["source_name"]
    pubmed = kind == "pubmed" and payload.get("source") == "NCBI PubMed EFetch XML"
    wos = kind == "wos" and payload.get("provider") == "wos_starter"
    supported = (pubmed or wos) and isinstance(payload.get("record"), dict)
    paths = {
        "title": (("record", "title"), _string, False),
        "doi": (("record", "identifiers", "doi"), _doi, True),
        "pmid": (("record", "pmid") if pubmed else ("record", "identifiers", "pmid"), _pmid, True),
        "accession": (("record", "uid"), _uid, False),
        "authors": (("record", "authors") if pubmed else ("record", "names", "authors"),
                    lambda x: _authors(x, pubmed), False),
        "year": (("record", "publication_dates") if pubmed else ("record", "source", "publishYear"),
                 _publication_year if pubmed else _year, False),
        "journal": (("record", "journal", "title") if pubmed else ("record", "source", "sourceTitle"), _string, False),
        "pages": (("record", "journal", "pages") if pubmed else ("record", "source", "pages", "range"), _string, False),
        "document_types": (("record", "publication_types") if pubmed else ("record", "types"), _tags, False),
        "source_document_types": (("record", "publication_types") if pubmed else ("record", "sourceTypes"), _tags, False),
    }
    fields = {name: _field(payload if supported else {}, path, normalise, many=many)
              for name, (path, normalise, many) in paths.items()}
    warnings = []
    if not supported:
        warnings.append("unsupported_source_layout")
    else:
        identity = fields["pmid" if pubmed else "accession"]
        if identity["normalised"] != source["source_record_id"]:
            warnings.append("source_identifier_unverified")
        # PubMed's redundant identifier list must not hide contradictory values.
        if pubmed:
            additional = _field(payload, ("record", "identifiers", "pmid"), _pmid, many=True)
            if additional["status"] not in ("missing", "not_supplied") and (
                additional["status"] != "present" or additional["normalised"] != identity["normalised"]
            ):
                warnings.append("conflicting_source_identifiers")
        types = (fields["document_types"]["normalised"] or "") + (fields["source_document_types"]["normalised"] or "")
        if any(term in types for term in ("abstract", "proceedings", "conference", "supplement")):
            warnings.append("abstract_or_container_scope_requires_review")
        record = payload["record"]
        source_container = record.get("source") if isinstance(record.get("source"), dict) else {}
        if (any(record.get(k) for k in ("container", "supplement", "conference", "abstractNumber"))
                or source_container.get("supplement")):
            warnings.append("container_or_abstract_metadata_present")
        if fields["doi"]["status"] == "present":
            warnings.append("doi_scope_and_registration_unverified")
    return {"fields": fields, "warnings": warnings,
            "identifier_scope": "source_record_scope_unverified",
            "source_sha256": source["source_sha256"], "retrieval_id": source["retrieval_id"]}


def compare_sources(left: dict, right: dict) -> dict:
    """Build candidate evidence only. Contradictions are never resolved here."""
    sides = [project_source(left), project_source(right)]
    comparisons = {}
    warnings = set(sides[0]["warnings"] + sides[1]["warnings"])
    for name in sides[0]["fields"]:
        a, b = (s["fields"][name] for s in sides)
        if a["status"] != "present" or b["status"] != "present":
            outcome = "not_comparable"
        else:
            outcome = "equal" if a["normalised"] == b["normalised"] else "different"
        comparisons[name] = outcome
        if outcome == "different":
            warnings.add(f"{name}_different")
        for field in (a, b):
            if field["status"] in ("malformed", "multiple_values"):
                warnings.add(f"{name}_{field['status']}")
    candidate_hint = any(comparisons[k] == "equal" for k in ("doi", "pmid", "accession", "title"))
    if not candidate_hint:
        warnings.add("no_supporting_identity_agreement")
    if any(v == "not_comparable" for v in comparisons.values()):
        warnings.add("incomplete_comparison_fields")
    return {"rule_version": RULE_VERSION, "sides": sides, "comparisons": comparisons,
            "warnings": sorted(warnings), "candidate_hint": candidate_hint,
            "automatic_match_allowed": False, "status": "review_required"}
