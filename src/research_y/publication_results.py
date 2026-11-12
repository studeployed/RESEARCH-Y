"""Read-only, paginated local publication hypotheses and source provenance.

A provisional identity is NOT a unique-publication verdict. Never resolve
conflicting metadata, deduplicate, download, export or certify retrieval here.
The existing count/identity validators are authoritative. All reads use one
identity-checked SQLite snapshot; no provider calls or database writes.
"""
from __future__ import annotations

from research_y.application_inspection import _read, ApplicationInspectionError
from research_y import publication_identity as identity, result_counts
from research_y.publication_match_evidence import project_source

METHOD = "provisional-publication-results/1"
PAGE_SIZE = 20
FIELD_LIMIT = 2048
DETAIL_FIELDS = ("title", "doi", "pmid", "accession", "authors", "year",
                 "journal", "pages", "document_types", "source_document_types")
# Only engine-defined status labels may cross into the citation-only GUI.
ABSTRACT_STATES = frozenset(("present", "not_supplied_in_response",
                             "not_returned_by_source", "not_recorded"))
RIGHTS_STATES = frozenset(("licence_review_required",
                          "abstract_redistribution_review_required",
                          "rights_not_verified"))


class PublicationViewError(RuntimeError):
    """Fixed, browser-safe error codes (no private source text or paths)."""

    def __init__(self, code="publication_view_unavailable"):
        self.code = code if code in (
            "publication_view_unavailable", "publication_view_invalid",
            "publication_view_stale", "publication_view_not_in_run",
        ) else "publication_view_unavailable"
        super().__init__(self.code)


def _revision(value, *, optional=False):
    if optional and value is None:
        return
    if (type(value) is not str or len(value) != 64 or
            any(c not in "0123456789abcdef" for c in value)):
        raise PublicationViewError("publication_view_invalid")


def _value(field: dict) -> dict:
    """Explicitly suppress oversized/unreadable source data, never truncate it."""
    status = field["status"]
    if status != "present":
        return dict(status=status, value=None)
    raw = field["value"]
    try:
        value = raw if type(raw) is str else identity._json(raw)
    except (TypeError, ValueError, RecursionError):
        return dict(status="unrenderable_original", value=None)
    if len(value) > FIELD_LIMIT:
        return dict(status="present_too_long_for_bounded_view", value=None)
    return dict(status="present", value=value)


def _source_title(source: dict) -> str | None:
    field = project_source(source)["fields"]["title"]
    found = _value(field)
    return found["value"] if found["status"] == "present" else None


def _citation_chosen_source(snapshot, field: str):
    """Only a canonical, source-backed citation path may be shown in the GUI.

    The general choice service intentionally permits arbitrary research fields
    and paths, including abstracts. A saved researcher 'title' choice is NOT
    proof that its source path is a title; recheck its exact source/path here.
    """
    if field not in DETAIL_FIELDS:
        return None
    selection = snapshot.chosen_fields.get(field)
    if selection is None:
        return None
    event = selection["provenance"]
    source = next((s for s in snapshot.retrievals
                   if s["retrieval_id"] == event["retrieval_id"]), None)
    if source is None:
        return None
    mapped = project_source(source)["fields"].get(field)
    if (mapped is None or mapped["status"] != "present" or
            mapped["path"] != event["path"] or
            mapped["value"] != selection["value"]):
        return None
    return source


def _chosen_title(snapshot) -> tuple[str | None, str]:
    if "title" not in snapshot.chosen_fields:
        return None, "not_chosen"
    if _citation_chosen_source(snapshot, "title") is None:
        return None, "chosen_title_not_citation_path"
    raw = snapshot.chosen_fields["title"]["value"]
    if type(raw) is not str or not raw.strip():
        return None, "chosen_source_value_not_text"
    if len(raw) > FIELD_LIMIT:
        return None, "chosen_source_title_too_long"
    return raw, "explicit_source_choice"


def _summary(snapshot, run_id, groups):
    present = [s for s in snapshot.retrievals if s["run_id"] == run_id]
    if not present:
        raise PublicationViewError("publication_view_not_in_run")
    # A selected title is a documented researcher choice, not an inferred
    # match. Otherwise show one only for EXACTLY identical raw source titles.
    title, title_state = _chosen_title(snapshot)
    if title_state == "not_chosen":
        variants = {_source_title(s) for s in present}
        if len(variants) == 1 and None not in variants:
            title = next(iter(variants))
            title_state = "same_original_title_in_selected_run"
        elif len(variants - {None}) > 1:
            title_state = "conflicting_original_titles_unresolved"
        elif None in variants and len(variants) > 1:
            title_state = "missing_original_title_in_one_or_more_sources"
        else:
            title_state = "original_title_unavailable"
    memberships = {
        (m["group_id"], m["source_name"])
        for s in present for m in s["memberships"]
        if m["run_id"] == run_id
    }
    return dict(
        publication_id=snapshot.publication_id,
        revision=snapshot.revision,
        title=title, title_status=title_state,
        original_source_records_in_run=len(present),
        additional_source_records_in_other_runs=len(snapshot.retrievals)-len(present),
        source_names=sorted({s["source_name"] for s in present}),
        group_memberships=[
            dict(group_id=g, group_label=groups.get(g, g), source_name=source)
            for g, source in sorted(memberships)
        ],
        review_required_links=sum(s["decision"]["status"] != "confirmed_match" for s in present),
        confirmed_links=sum(s["decision"]["status"] == "confirmed_match" for s in present),
        identity_status="provisional_review_required",
        publication_identity_verified=False,
    )


def _checked(db, project, run_id, revision):
    projection = result_counts._snapshot(db, project, run_id)
    if revision is not None and revision != projection.revision:
        raise PublicationViewError("publication_view_stale")
    return projection


def _page_from_checked(db, project, run_id, counts, after_publication_id):
    """Render one original source-backed page from a single verified snapshot.

    The caller validates identifiers and SHA-256 revision; no second full run
    projection, database connection, implicit merge or provider call occurs.
    """
    if after_publication_id is not None:
        prior = db.execute(
            "SELECT 1 FROM publication_retrievals l "
            "JOIN source_retrievals r ON r.retrieval_id=l.retrieval_id "
            "WHERE r.run_id=? AND l.publication_id=? LIMIT 1",
            (run_id, after_publication_id),
        ).fetchone()
        if prior is None:
            raise PublicationViewError("publication_view_stale")
    ids = [row[0] for row in db.execute(
        "SELECT DISTINCT l.publication_id FROM publication_retrievals l "
        "JOIN source_retrievals r ON r.retrieval_id=l.retrieval_id "
        "WHERE r.run_id=? AND (? IS NULL OR l.publication_id>?) "
        "ORDER BY l.publication_id LIMIT ?",
        (run_id, after_publication_id, after_publication_id, PAGE_SIZE + 1),
    )]
    has_more = len(ids) > PAGE_SIZE
    page_ids = ids[:PAGE_SIZE]
    groups = {g["group_id"]: g["label"] for g in counts.groups}
    rows = [_summary(identity._snapshot(db, pub_id), run_id, groups)
            for pub_id in page_ids]
    from research_y.reviewed_master import retained_union
    reviewed = retained_union(db, counts)
    return dict(
        method=METHOD, project_id=str(project.identifier), run_id=run_id,
        revision=counts.revision, rows=rows, page_size=PAGE_SIZE,
        after_publication_id=after_publication_id,
        next_after_publication_id=page_ids[-1] if has_more else None,
        has_more=has_more,
        provisional_publication_identities=counts.totals["global_publication_identities"],
        unmaterialised_source_records=counts.totals["unmaterialised_retrievals"],
        retrieved_source_records=counts.totals["metadata_source_records"],
        reviewed_retained_unique_publications=None if reviewed is None else reviewed["retained_unique_publications"],
        global_unique_publications=None, deduplication_complete=False,
        source_retrieval_verified=False, verified_complete=False,
        no_network_requests=True,
        warnings=["provisional_publication_identities_not_deduplicated",
                  "source_and_group_memberships_are_not_final_eligibility",
                  "local_source_titles_are_not_redistribution_permissions"],
    )


def _detail_from_checked(db, project, run_id, counts, publication_id):
    """Render the original citation-only detail in the caller's snapshot."""
    snapshot = identity._snapshot(db, publication_id)
    groups = {g["group_id"]: g["label"] for g in counts.groups}
    summary = _summary(snapshot, run_id, groups)
    retrievals = []
    for source in snapshot.retrievals:
        projected = project_source(source)
        fields = []
        for name in DETAIL_FIELDS:
            original = projected["fields"][name]
            display = _value(original)
            fields.append(dict(
                field=name, source_path=original["path"],
                status=display["status"], value=display["value"],
            ))
        metadata = source["original_metadata"]
        record = metadata.get("record") if isinstance(metadata.get("record"), dict) else {}
        abstract_state = record.get("abstract_status", metadata.get("abstract_status"))
        if type(abstract_state) is not str or abstract_state not in ABSTRACT_STATES:
            abstract_state = "not_recorded_or_malformed"
        rights = metadata.get("rights_status")
        if type(rights) is not str or rights not in RIGHTS_STATES:
            rights = ("abstract_redistribution_review_required"
                      if metadata.get("rights_review_required_for_abstract_redistribution") is True
                      else "rights_not_verified")
        memberships = [
            dict(group_id=m["group_id"], group_label=groups.get(m["group_id"], m["group_id"]),
                 source_name=m["source_name"], query_status=m["status"],
                 parent_run_status=m["run_status"],
                 reported_matches=m["reported_matches"])
            for m in source["memberships"] if m["run_id"] == run_id
        ]
        retrievals.append(dict(
            retrieval_id=source["retrieval_id"],
            run_id=source["run_id"],
            source_name=source["source_name"],
            source_record_id=source["source_record_id"],
            decision_status=source["decision"]["status"],
            included_in_selected_run=source["run_id"] == run_id,
            memberships=memberships,
            abstract_status=abstract_state,
            rights_status=rights,
            comparison_warnings=projected["warnings"],
            fields=fields,
        ))
    chosen = []
    suppressed = []
    for field, record in sorted(snapshot.chosen_fields.items()):
        # Field names alone are not a licence or a source-field type:
        # a user can save 'title' pointing at abstract text. Validate
        # the exact canonical citation path before emitting bytes.
        if _citation_chosen_source(snapshot, field) is None:
            suppressed.append(dict(
                field=field, reason="not_permitted_citation_source_path"))
            continue
        display = _value(dict(status="present", value=record["value"]))
        event = record["provenance"]
        chosen.append(dict(field=field, status=display["status"],
                           value=display["value"],
                           retrieval_id=event["retrieval_id"],
                           source_path=event["path"], event_id=record["event_id"]))
    return dict(
        method=METHOD, project_id=str(project.identifier), run_id=run_id,
        revision=counts.revision, publication=summary,
        chosen_source_fields=chosen, suppressed_chosen_fields=suppressed,
        source_retrievals=retrievals,
        abstract_text_displayed=False,
        redistribution_permission_established=False,
        global_unique_publications=None, deduplication_complete=False,
        source_retrieval_verified=False, verified_complete=False,
        no_network_requests=True,
    )


def read_publication_page(project, run_id: str, *, after_publication_id: str | None = None,
                          expected_revision: str | None = None) -> dict:
    """Read one revision-bound provisional page; never infer unique publications."""
    try:
        identity._identifier(run_id)
        _revision(expected_revision, optional=True)
        if after_publication_id is not None:
            if expected_revision is None:
                raise PublicationViewError("publication_view_invalid")
            identity._identifier(after_publication_id)
        with _read(project) as db:
            counts = _checked(db, project, run_id, expected_revision)
            return _page_from_checked(db, project, run_id, counts, after_publication_id)
    except PublicationViewError:
        raise
    except Exception:
        raise PublicationViewError() from None


def read_publication_detail(project, run_id: str, publication_id: str, *,
                            expected_revision: str) -> dict:
    """Revalidate the complete original run before displaying citation detail."""
    try:
        identity._identifier(run_id)
        identity._identifier(publication_id)
        _revision(expected_revision)
        with _read(project) as db:
            counts = _checked(db, project, run_id, expected_revision)
            return _detail_from_checked(db, project, run_id, counts, publication_id)
    except PublicationViewError:
        raise
    except Exception:
        raise PublicationViewError() from None


def read_publication_page_detail(project, run_id: str, publication_id: str, *,
                                 after_publication_id: str | None,
                                 expected_revision: str) -> dict:
    """Atomically recheck the shown page AND its selected citation-only detail.

    One full source/identity/count validation is performed inside a single
    original read-only SQLite transaction. The publication must be on the
    validated 20-row page, including the same keyset cursor and revision.
    No cached count, unverified source, browser-supplied SQL or write is used.
    """
    try:
        identity._identifier(run_id)
        identity._identifier(publication_id)
        _revision(expected_revision)
        if after_publication_id is not None:
            identity._identifier(after_publication_id)
        with _read(project) as db:
            counts = _checked(db, project, run_id, expected_revision)
            page = _page_from_checked(db, project, run_id, counts, after_publication_id)
            if not any(row["publication_id"] == publication_id for row in page["rows"]):
                raise PublicationViewError("publication_view_stale")
            detail = _detail_from_checked(db, project, run_id, counts, publication_id)
            if detail["revision"] != page["revision"]:
                raise PublicationViewError("publication_view_stale")
            return dict(
                method="provisional-publication-page-detail/1",
                project_id=str(project.identifier), run_id=run_id,
                revision=counts.revision, page=page, detail=detail,
                source_retrieval_verified=False,
                deduplication_complete=False, verified_complete=False,
                global_unique_publications=None, no_network_requests=True,
            )
    except PublicationViewError:
        raise
    except Exception:
        raise PublicationViewError() from None
