from contextlib import closing
import json
import sqlite3

import pytest

from research_y import publication_identity as identity
from research_y.projects import open_project
from research_y.study_classification import read_classification, review_classification, visible_in_filtered_view
from test_publication_identity import store, protected_rows, db_rows
from scripts.review_publication_classification import main


def set_record(project, retrieval, *, types, languages=("eng",), subjects=("Humans",)):
    with closing(sqlite3.connect(project.database_path)) as db, db:
        original = {"source": "NCBI PubMed EFetch XML", "record": {
            "publication_types": list(types), "languages": list(languages), "abstract_status": "present",
            "mesh_headings": [{"descriptor": s} for s in subjects]}}
        db.execute("UPDATE source_retrievals SET original_metadata_json=? WHERE retrieval_id=?",
                   (json.dumps(original), retrieval))
    return identity.materialise_retrieval(project, retrieval, actor="Test researcher")


def review(project, view, dimension, *labels):
    return review_classification(project, view["publication_id"], dimension=dimension, labels=list(labels),
                                 actor="Test researcher", rationale="Checked the original methods",
                                 expected_revision=view["revision"], confirmed=True)


@pytest.mark.parametrize(("types", "research", "design", "format_"), [
    (["Randomized Controlled Trial", "Conference Abstract"], "yes", ["RCT"], "conference abstract"),
    (["Journal Article", "Clinical Trial Protocol"], "no", ["protocol"], "full journal article"),
    (["Systematic Review", "Meta-Analysis"], "no", ["meta-analysis", "systematic review"], "unclear"),
    (["Clinical Trial Protocol", "Randomized Controlled Trial"], "unclear", ["RCT", "protocol"], "unclear"),
])
def test_distinct_dimensions_and_source_paths(store, types, research, design, format_):
    project, ids = store
    pub = set_record(project, ids[0], types=types)
    before = protected_rows(project)
    view = read_classification(project, pub.publication_id)
    assert view["current"]["original_research"] == [research]
    assert view["current"]["design"] == design and view["current"]["format"] == [format_]
    assert view["current"]["population"] == ["human"] and view["current"]["language"] == ["English"]
    evidence = view["evidence"]["design"][0]
    assert evidence["retrieval_id"] == ids[0] and evidence["source_sha256"] == pub.retrievals[0]["source_sha256"]
    assert evidence["path"][:2] == ["record", "publication_types"]
    assert types[evidence["path"][2]] == evidence["value"]
    assert protected_rows(project) == before and not db_rows(project, "classifications")


def test_filters_leave_sources_untouched_and_animal_indexing_alone_cannot_hide_record(store):
    project, ids = store
    pub = set_record(project, ids[0], types=[], languages=["fra"], subjects=["Animals"])
    view = read_classification(project, pub.publication_id)
    before = protected_rows(project)
    assert visible_in_filtered_view(view, hide_non_human_only=True)
    assert not visible_in_filtered_view(view, hide_non_english=True)
    assert view["current"]["population"] == ["unclear"]
    final = review(project, view, "population", "non-human")
    assert not visible_in_filtered_view(final, hide_non_human_only=True)
    assert visible_in_filtered_view(final)
    assert review(project, view, "population", "non-human") == final  # lost-reply retry
    assert read_classification(open_project(project.root), pub.publication_id) == final
    assert protected_rows(project) == before and len(db_rows(project, "classifications")) == 1
    with pytest.raises(identity.StalePublicationError):
        review(project, view, "population", "human")


def test_override_preserved_when_new_linked_source_disagrees(store):
    project, ids = store
    one = set_record(project, ids[0], types=["Journal Article"], subjects=[])
    two = set_record(project, ids[2], types=["Case Reports"])
    view = read_classification(project, one.publication_id)
    corrected = review(project, view, "design", "prospective cohort")
    identity.associate_retrieval(project, ids[2], one.publication_id, expected_source_revision=two.revision,
                    expected_target_revision=one.revision, actor="Test researcher", evidence="Checked records",
                    same_publication_confirmed=True)
    after = read_classification(project, one.publication_id)
    assert after["proposed"]["design"] == ["case report"]
    assert after["current"]["design"] == ["prospective cohort"]
    assert "reviewed_design_conflicts_with_current_evidence" in after["warnings"]
    assert corrected["decisions"]["design"]["event_id"] == after["decisions"]["design"]["event_id"]


@pytest.mark.parametrize("languages", [["und"], ["eng", "fra"], ["fra", "und"], ["xxx"], []])
def test_ambiguous_or_multilingual_records_survive_nonenglish_filter(store, languages):
    project, ids = store
    pub = set_record(project, ids[0], types=[], languages=languages)
    assert visible_in_filtered_view(read_classification(project, pub.publication_id), hide_non_english=True)


def test_cli_reopen_review_and_deleted_projected_decision_cannot_silently_revert(store, capsys):
    project, ids = store
    pub = set_record(project, ids[0], types=["Randomized Controlled Trial"])
    base = [str(project.root), pub.publication_id]
    main([*base, "inspect"])
    rev = json.loads(capsys.readouterr().out)["revision"]
    main([*base, "review", "--dimension", "design", "--label", "RCT", "--actor", "Reviewer",
          "--rationale", "Read original methods", "--revision", rev, "--confirm"])
    record = json.loads(capsys.readouterr().out)
    assert record["decisions"]["design"]["status"] == "user-confirmed"
    with closing(sqlite3.connect(project.database_path)) as db, db:
        db.execute("DELETE FROM classifications WHERE publication_id=?", (pub.publication_id,))
    with pytest.raises(identity.PublicationIntegrityError, match="history"):
        read_classification(project, pub.publication_id)
