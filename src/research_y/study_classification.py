"""Researcher-reviewable classifications grounded in original publication metadata."""
from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from research_y import publication_identity as identity
from research_y.projects import _utc_now, _validated_project_connection

RULE = "explicit-publication-metadata/1"
EVENT = "publication_classification_review_v1"
DESIGN_TAGS = {
    "randomized controlled trial": "RCT", "clinical trial protocol": "protocol",
    "systematic review": "systematic review", "meta-analysis": "meta-analysis",
    "case reports": "case report", "practice guideline": "guideline", "guideline": "guideline",
    "consensus development conference": "consensus statement", "editorial": "editorial/commentary",
    "scoping review": "scoping review",
}
DESIGNS = set(DESIGN_TAGS.values()) | {
    "non-randomised interventional study", "prospective cohort", "retrospective cohort", "case-control",
    "cross-sectional", "case series", "diagnostic study", "qualitative study", "SRMA", "narrative review",
    "other", "unclear", "position statement", "practice recommendation",
}
FORMATS = {"full journal article", "conference abstract", "conference paper", "journal supplement item",
           "society web document", "preprint", "book/chapter", "other", "unclear"}
LABELS = {"original_research": {"yes", "no", "unclear"}, "design": DESIGNS, "format": FORMATS,
          "language": {"English", "non-English", "multilingual", "unknown"},
          "population": {"human", "non-human", "mixed human/non-human", "not applicable", "unclear"}}
FORMAT_TAGS = {"conference abstract": "conference abstract", "meeting abstract": "conference abstract",
               "conference paper":"conference paper","book":"book/chapter","chapter":"book/chapter",
               "proceedings paper": "conference paper", "preprint": "preprint",
               "journal article": "full journal article"}
# Undetermined, collective, multiple or malformed codes cannot establish a
# non-English-only publication. Resolve only explicitly recognised codes.
LANGUAGES = {"eng", "fra", "fre", "deu", "ger", "spa", "ita", "por", "jpn", "zho", "chi", "rus",
             "nld", "dut", "pol", "kor", "ara", "swe", "dan", "nor", "fin", "ces", "cze", "ell", "gre"}


def _ordered(values):
    return sorted(set(values))


def _proposals(snapshot):
    support = defaultdict(list)
    warnings = set()
    language_groups = []
    for source in snapshot.retrievals:
        payload = source["original_metadata"]
        record = payload.get("record")
        pubmed = source["source_name"] == "pubmed" and payload.get("source") == "NCBI PubMed EFetch XML"
        wos = source["source_name"] == "wos" and payload.get("provider") == "wos_starter"
        society = source["source_name"] == "society" and payload.get("provider") == "manual_society_guidance"
        manual = source["source_name"] == "manual_bibliographic" and payload.get("provider") == source["source_name"]
        conference = source["source_name"] in {"conference_jats","conference_pdf"} and payload.get("provider") == source["source_name"]
        if not isinstance(record, dict) or not (pubmed or wos or society or conference or manual):
            warnings.add("unsupported_source_metadata")
            continue
        def add(dimension, label, path, value):
            support[dimension].append(dict(label=label, path=["record", *path], source_sha256=source["source_sha256"],
                                           retrieval_id=source["retrieval_id"], value=value))
        if conference:
            add("format", "conference abstract", ["locator"], record.get("locator"))
            if not record.get("text"):
                warnings.add("abstract_unavailable")
            continue
        if society:
            add("format", "society web document", ["landing_url"], record.get("landing_url"))
            for index, kind in enumerate(record.get("document_types", [])):
                label = {"clinical practice guideline":"guideline", "practice recommendation":"practice recommendation",
                         "guideline":"guideline", "consensus statement":"consensus statement",
                         "position statement":"position statement"}.get(kind)
                if label:
                    add("design", label, ["document_types",index], kind)
                    add("original_research", "no", ["document_types",index], kind)
            continue
        tag_path = "publication_types" if pubmed else "types"
        tags = record.get(tag_path)
        if isinstance(tags, list):
            for i, tag in enumerate(tags):
                if not isinstance(tag, str):
                    continue
                key = tag.strip().casefold()
                design = DESIGN_TAGS.get(key)
                if design:
                    add("design", design, [tag_path, i], tag)
                    if design in {"RCT", "case report"}:
                        add("original_research", "yes", [tag_path, i], tag)
                    else:
                        add("original_research", "no", [tag_path, i], tag)
                if key in FORMAT_TAGS:
                    add("format", FORMAT_TAGS[key], [tag_path, i], tag)
        if pubmed:
            langs = record.get("languages")
            if isinstance(langs, list) and langs:
                codes = {v.strip().lower() for v in langs if isinstance(v, str)}
                resolved = all(isinstance(v, str) and v.strip().lower() in LANGUAGES for v in langs)
                label = "unknown"
                if resolved:
                    label = "multilingual" if len(codes) > 1 else "English" if codes == {"eng"} else "non-English"
                add("language", label, ["languages"], langs)
                language_groups.append(codes)
            headings = record.get("mesh_headings")
            if isinstance(headings, list):
                for i, heading in enumerate(headings):
                    if isinstance(heading, dict) and heading.get("descriptor") in {"Humans", "Animals"}:
                        add("population", "human" if heading["descriptor"] == "Humans" else "animal_tag",
                            ["mesh_headings", i, "descriptor"], heading["descriptor"])
        if record.get("abstract_status", payload.get("abstract_status")) != "present":
            warnings.add("abstract_unavailable")
    suggested = {}
    for dim in LABELS:
        values = _ordered(item["label"] for item in support[dim])
        fallback = "unknown" if dim == "language" else "unclear"
        if dim == "design":
            suggested[dim] = values or [fallback]
        elif dim == "population" and "animal_tag" in values:
            suggested[dim] = ["mixed human/non-human"] if "human" in values else ["unclear"]
            warnings.add("population_indexing_needs_review")
        elif len(values) == 1:
            suggested[dim] = values
        else:
            suggested[dim] = [fallback]
            if values:
                warnings.add("conflicting_" + dim)
    if language_groups and any(codes != language_groups[0] for codes in language_groups):
        suggested["language"] = ["unknown"]
        warnings.add("conflicting_language")
    if any(v in (["unclear"], ["unknown"]) for v in suggested.values()):
        warnings.add("unresolved_classification")
    return suggested, dict(support), sorted(warnings)


def _view(db, publication_id):
    snapshot = identity._snapshot(db, identity._identifier(publication_id))
    if not snapshot.active:
        raise ValueError("Publication has no active source")
    proposed, evidence, warnings = _proposals(snapshot)
    decisions = {}
    rows = db.execute("SELECT classification_id,dimension,label,review_status,provenance_json,classified_at_utc "
                      "FROM classifications WHERE publication_id=? ORDER BY rowid", (publication_id,))
    seen_events = set()
    for row in rows:
        cid, dimension, label, status, provenance, stamp = row
        pointer = identity._object(provenance)
        event = identity._event(db, pointer.get("event_id"), EVENT)
        if (event.get("publication_id"), event.get("classification_id"), event.get("dimension"),
                identity._json(event.get("labels")), event.get("status"), event.get("at_utc")) != (
                publication_id, cid, dimension, label, status, stamp):
            raise identity.PublicationIntegrityError("Classification record differs from its review receipt")
        decisions[dimension] = dict(event, event_id=pointer["event_id"])
        seen_events.add(pointer["event_id"])
    recorded = {i for (i,) in db.execute("SELECT event_id FROM audit_events WHERE event_type=? "
                "AND json_extract(details_json,'$.publication_id')=?", (EVENT, publication_id))}
    if recorded != seen_events:
        raise identity.PublicationIntegrityError("Classification history is incomplete")
    current = {dimension: decisions[dimension]["labels"] if dimension in decisions else value
               for dimension, value in proposed.items()}
    for dim, decision in decisions.items():
        if decision["evidence_revision"] != snapshot.revision and proposed[dim] != current[dim]:
            warnings.append("reviewed_" + dim + "_conflicts_with_current_evidence")
    revision = identity._hash([RULE, snapshot.revision, {d: v["event_id"] for d, v in decisions.items()}])
    statuses = {dim: decisions[dim]["status"] if dim in decisions else
                ("requires-review" if warnings else "machine-provisional") for dim in LABELS}
    return dict(publication_id=publication_id, rule=RULE, revision=revision, evidence_revision=snapshot.revision,
                proposed=proposed, evidence=evidence, current=current, decisions=decisions, review_status=statuses,
                warnings=warnings,
                explicit_non_human_only="population" in decisions and current["population"] == ["non-human"])


def read_classification(project, publication_id):
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        return _view(db, publication_id)


def review_classification(project, publication_id, *, dimension, labels, actor, rationale, expected_revision,
                          confirmed, proposal_event_id=None):
    if (confirmed is not True or dimension not in LABELS or not isinstance(labels, list) or not labels
            or any(not isinstance(v, str) or v not in LABELS[dimension] for v in labels)
            or len(labels) != len(set(labels)) or len(labels) > 1 and (dimension != "design" or "unclear" in labels)):
        raise ValueError("Explicit confirmation and valid independent classification labels required")
    labels = _ordered(labels)
    identity._text(actor, 200)
    identity._text(rationale, 2000)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        view = _view(db, publication_id)
        prior = view["decisions"].get(dimension)
        fields = [publication_id, dimension, labels, actor, rationale, expected_revision]
        if proposal_event_id is not None:
            proposal = identity._event(db, proposal_event_id, "local_study_proposal_v1")
            if (proposal["publication_id"] != publication_id or proposal["evidence_revision"] != view["evidence_revision"]
                    or dimension not in proposal["generated"]["proposals"]):
                raise identity.StalePublicationError("Model proposal no longer matches the source")
            fields.append(proposal_event_id)
        request = identity._hash(fields)
        if prior and prior["request_sha256"] == request:
            return view
        if view["revision"] != expected_revision:
            raise identity.StalePublicationError("Review the changed classification evidence")
        stamp, cid = _utc_now(), str(uuid4())
        status = "user-confirmed" if labels == view["proposed"][dimension] else "user-corrected"
        event = dict(version=1, at_utc=stamp, publication_id=publication_id, classification_id=cid,
                     dimension=dimension, labels=labels, actor=actor, rationale=rationale, rule=RULE,
                     status=status, request_sha256=request, evidence_revision=view["evidence_revision"],
                     prior_event_id=prior["event_id"] if prior else None)
        if proposal_event_id is not None:
            event["proposal_event_id"] = proposal_event_id
        receipt = identity._audit(db, EVENT, event)
        db.execute("INSERT INTO classifications VALUES(?,?,?,?,?,?,?)",
                   (cid, publication_id, dimension, identity._json(labels), status,
                    identity._json({"event_id": receipt}), stamp))
        return _view(db, publication_id)


def visible_in_filtered_view(view, *, hide_non_english=False, hide_non_human_only=False):
    return not ((hide_non_english and view["current"]["language"] == ["non-English"]) or
                (hide_non_human_only and view["explicit_non_human_only"]))
