"""Admit researcher-selected JATS blocks against an existing original collection retrieval."""
from __future__ import annotations

from uuid import UUID, uuid5

from research_y import publication_identity as identity
from research_y.conference_jats import inspect_conference_jats
from research_y.projects import _utc_now, _validated_project_connection

EVENT = "conference_abstract_admission_v1"
METHOD = "jats-direct-subarticles/1"


def _preview(db, retrieval_id, inspection, method=METHOD):
    source = identity._source(db, identity._identifier(retrieval_id))
    revision = identity._hash([method, source["source_sha256"], inspection])
    return dict(original_retrieval_id=retrieval_id, original_source_sha256=source["source_sha256"],
                run_id=source["run_id"], revision=revision, extraction=inspection)


def preview_extraction(project, retrieval_id, payload, **options):
    inspection = inspect_conference_jats(payload, **options)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        return _preview(db, retrieval_id, inspection)


def admit_extraction(project, retrieval_id, payload, *, locators, expected_revision, actor,
                     confirmed, retention_authorized, **options):
    if confirmed is not True or retention_authorized is not True:
        raise ValueError("Confirmed review and permission to retain abstract text are required")
    identity._text(actor, 200)
    inspection = inspect_conference_jats(payload, **options)
    return _admit(project, retrieval_id, inspection, locators, expected_revision, actor, METHOD, "conference_jats")


def _preview_pdf_block(project, retrieval_id, page_view, **selection):
    from research_y import conference_pdf
    inspection = conference_pdf.select_block(page_view,**selection)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN")
        return _preview(db,retrieval_id,inspection,conference_pdf.METHOD)


def admit_pdf_block(project, retrieval_id, payload, *, page, selection, expected_revision, actor, confirmed,
                    retention_authorized):
    from research_y import conference_pdf
    if confirmed is not True or retention_authorized is not True:
        raise ValueError("Confirm the abstract and local text retention")
    identity._text(actor,200)
    inspection = conference_pdf.select_block(conference_pdf.read_page(payload,page),**selection)
    return _admit(project,retrieval_id,inspection,[inspection["abstracts"][0]["locator"]],expected_revision,
                  actor,conference_pdf.METHOD,"conference_pdf")


def _admit(project, retrieval_id, inspection, locators, expected_revision, actor, method, provider):
    by_locator = {a["locator"]:a for a in inspection["abstracts"]}
    if (not isinstance(locators, list) or not locators or any(not isinstance(k, str) or k not in by_locator
                                                             for k in locators) or len(set(locators)) != len(locators)):
        raise ValueError("Select distinct locators present in the preview")
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        view = _preview(db, retrieval_id, inspection, method)
        if expected_revision != view["revision"]:
            raise identity.StalePublicationError("Source or extraction changed; reopen the preview")
        # Reopening or reselecting a block cannot create another publication
        # from the same original, exact document bytes and positional locator.
        namespace = UUID(retrieval_id)
        container_key = str(uuid5(namespace, inspection["source_sha256"]))
        container = dict(version=1, method=method, retrieval_id=retrieval_id,
                         original_source_sha256=view["original_source_sha256"],
                         document_sha256=inspection["source_sha256"], fields=inspection["container"])
        raw_container = identity._json(container)
        previous = db.execute("SELECT metadata_json FROM containers WHERE container_id=?", (container_key,)).fetchone()
        if previous is None:
            db.execute("INSERT INTO containers VALUES(?,?)", (container_key, raw_container))
        elif previous[0] != raw_container:
            raise identity.StalePublicationError("Container differs from previously admitted provenance")
        results = []
        for locator in locators:
            block = by_locator[locator]
            child = str(uuid5(UUID(container_key), locator))
            source_key = f"{container_key}:{locator}"
            # Term matches describe this researcher's search and can change
            # between previews. Keep them in the review receipt.
            original = dict(provider=provider, record={k:v for k,v in block.items() if k != "matched_terms"},
                            container_id=container_key, original_retrieval_id=retrieval_id,
                            document_sha256=inspection["source_sha256"], rights_status="local_retention_confirmed")
            raw = identity._json(original)
            row = db.execute("SELECT original_metadata_json FROM source_retrievals WHERE retrieval_id=?", (child,)).fetchone()
            if row is None:
                if provider == "conference_pdf":
                    # A second selection of overlapping page text requires reconciliation.
                    start, end = block["text_start"], block["text_end"]
                    prior = db.execute(
                        "SELECT 1 FROM source_retrievals WHERE run_id=? AND source_name=? AND "
                        "json_extract(original_metadata_json,'$.container_id')=? AND "
                        "json_extract(original_metadata_json,'$.record.pdf_page')=? AND "
                        "json_extract(original_metadata_json,'$.record.text_start')<? AND "
                        "json_extract(original_metadata_json,'$.record.text_end')>? LIMIT 1",
                        (view["run_id"],provider,container_key,block["pdf_page"],end,start)).fetchone()
                    if prior:
                        raise ValueError("This passage overlaps an already retained abstract on this page")
                stamp = _utc_now()
                db.execute("INSERT INTO source_retrievals VALUES(?,?,?,?,?,?)",
                           (child, view["run_id"], provider, source_key, stamp, raw))
                publication = str(uuid5(UUID(child), "publication"))
                db.execute("INSERT INTO publications(publication_id,created_at_utc) VALUES(?,?)", (publication, stamp))
                source = identity._source(db, child)
                identity._record_link(db, source, before=None, after=publication, previous_event_id=None,
                    status="review_required", action="materialise", actor=actor,
                    evidence="Researcher selected an explicitly located individual abstract")
                db.execute("INSERT INTO publication_containers VALUES(?,?)", (publication, container_key))
                identity._audit(db, EVENT, dict(version=1, at_utc=stamp, method=method, actor=actor,
                     expected_revision=expected_revision, original_retrieval_id=retrieval_id, retrieval_id=child,
                     publication_id=publication, container_id=container_key, locator=locator,
                     matched_terms=block["matched_terms"], source_sha256=source["source_sha256"]))
            elif row[0] != raw:
                raise identity.StalePublicationError("Retained abstract differs; review existing evidence")
            link = identity._link(db, child)
            if link is None or not db.execute("SELECT 1 FROM publication_containers WHERE publication_id=? AND container_id=?",
                                               (link[0], container_key)).fetchone():
                raise identity.PublicationIntegrityError("Missing retained abstract association")
            results.append(dict(retrieval_id=child, publication_id=link[0], locator=locator))
        return dict(container_id=container_key, original_retrieval_id=retrieval_id, admitted=results,
                    selected_count=len(results), extracted_count=len(by_locator),
                    unresolved_blocks=inspection["unresolved"])
