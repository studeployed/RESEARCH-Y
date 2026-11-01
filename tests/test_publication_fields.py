"""Source-value choices retain provenance, alternatives, missingness and rights."""
from contextlib import closing
import json
import sqlite3

import pytest

from research_y.publication_identity import PublicationIntegrityError, StalePublicationError, read_publication, associate_retrieval
from research_y.publication_fields import select_source_field, clear_source_field
from test_publication_identity import store, pair, move, link_args, db_rows, protected_rows


def select(p, a, retrieval_id, *, field="title", path=("record", "title")):
    return select_source_field(p, a.publication_id, field, retrieval_id=retrieval_id, path=path,
                               expected_revision=a.revision, actor="Researcher", reason="Compared source alternatives")


def test_choice_preserves_conflicting_original_values_missingness_rights_and_source_counts(store):
    p, ids, a, b, merged, _ = move(store)
    protected = protected_rows(p)
    chosen = select(p, merged, ids[0])
    field = chosen.chosen_fields["title"]
    assert field["value"] == "Synthetic title"
    assert field["provenance"]["retrieval_id"] == ids[0]
    assert field["provenance"]["path"] == ["record", "title"]
    assert field["provenance"]["actor"] == "Researcher"
    assert {r["original_metadata"]["record"]["title"] for r in chosen.retrievals} == {"Synthetic title", "Different source title"}
    assert all(r["original_metadata"]["rights_status"] == "licence_review_required" for r in chosen.retrievals)
    assert all(r["original_metadata"]["abstract_status"] == "not_returned_by_source" for r in chosen.retrievals)
    assert protected_rows(p) == protected
    # Chosen storage and audit retain references, not additional licensed text.
    assert "Synthetic title" not in db_rows(p, "publications")[0][2]
    assert all("Synthetic title" not in row[3] for row in db_rows(p, "audit_events"))
    assert not chosen.export_permissions_verified


def test_repeat_selection_does_not_duplicate_audit(store):
    p, ids, a, b = pair(store)
    first = select(p, a, ids[0])
    audit = db_rows(p, "audit_events")
    assert select(p, a, ids[0]) == first
    assert db_rows(p, "audit_events") == audit


def test_list_path_and_numeric_value_are_preserved_exactly(store):
    p, ids, a, b = pair(store)
    chosen = select(p, a, ids[0], field="author", path=("record", "authors", 0, "name"))
    assert chosen.chosen_fields["author"]["value"] == "Synthetic Researcher"
    chosen = select(p, chosen, ids[0], field="year", path=("record", "year"))
    assert type(chosen.chosen_fields["year"]["value"]) is int
    assert set(chosen.chosen_fields) == {"author", "year"}


def test_clear_and_replace_choices_preserves_history_and_prevents_aba(store):
    p, ids, a, b = pair(store)
    chosen = select(p, a, ids[0])
    cleared = clear_source_field(p, a.publication_id, "title", expected_revision=chosen.revision,
                                 actor="Researcher", reason="Reconsider original")
    assert not cleared.chosen_fields and cleared.revision != a.revision
    assert len(db_rows(p, "audit_events")) == 5  # initial project + two identities + select + clear
    with pytest.raises(StalePublicationError):
        select(p, a, ids[0])
    again = select(p, cleared, ids[0])
    assert again.chosen_fields["title"]["event_id"] != chosen.chosen_fields["title"]["event_id"]


def test_moving_selected_source_requires_explicit_clear_first(store):
    p, ids, a, b = pair(store)
    chosen = select(p, a, ids[0])
    with pytest.raises(ValueError, match="Clear"):
        associate_retrieval(p, ids[0], b.publication_id, **link_args(chosen, b))
    cleared = clear_source_field(p, a.publication_id, "title", expected_revision=chosen.revision,
                                 actor="Researcher", reason="Moving source; preserve history")
    merged = associate_retrieval(p, ids[0], b.publication_id, **link_args(cleared, b))
    assert len(merged.retrievals) == 2


@pytest.mark.parametrize("path", [("record", "abstract"), ("record", "missing"), ("record", "authors", -1),
                                  ("record", "authors", True), (), tuple("x" for _ in range(17))],
                         ids=["null", "missing", "negative", "boolean-index", "empty", "too-deep"])
def test_missing_or_invalid_paths_never_fabricate_values(store, path):
    p, ids, a, b = pair(store)
    with pytest.raises(ValueError):
        select(p, a, ids[0], path=path)
    assert read_publication(p, a.publication_id) == a


def test_field_from_another_publication_is_rejected(store):
    p, ids, a, b = pair(store)
    with pytest.raises(ValueError, match="current"):
        select(p, a, ids[1])


@pytest.mark.parametrize("field", ["", "Title", "title;DROP TABLE", "../title", "x" * 65],
                         ids=["empty", "capital", "sql", "path", "long"])
def test_field_names_are_validated(store, field):
    p, ids, a, b = pair(store)
    with pytest.raises(ValueError):
        select(p, a, ids[0], field=field)


def test_audit_sequence_gap_does_not_break_source_choice(store):
    p, ids, a, b = pair(store)
    with closing(sqlite3.connect(p.database_path)) as db, db:
        db.execute("UPDATE sqlite_sequence SET seq=100000 WHERE name='audit_events'")
    chosen = select(p, a, ids[0])
    assert chosen.chosen_fields["title"]["event_id"] == 100001


def test_corrupt_chosen_field_map_is_detected(store):
    p, ids, a, b = pair(store)
    chosen = select(p, a, ids[0])
    with closing(sqlite3.connect(p.database_path)) as db, db:
        state = json.loads(db.execute("SELECT chosen_metadata_json FROM publications WHERE publication_id=?", (a.publication_id,)).fetchone()[0])
        state["fields"]["title"] += 1000
        db.execute("UPDATE publications SET chosen_metadata_json=? WHERE publication_id=?", (json.dumps(state), a.publication_id))
    with pytest.raises(PublicationIntegrityError):
        read_publication(p, a.publication_id)


def test_clear_exact_retry_is_noop_with_old_review_token(store):
    p, ids, a, b = pair(store)
    chosen = select(p, a, ids[0])
    args = dict(expected_revision=chosen.revision, actor="Researcher", reason="Remove selection")
    result = clear_source_field(p, a.publication_id, "title", **args)
    audit = db_rows(p, "audit_events")
    assert clear_source_field(p, a.publication_id, "title", **args) == result
    assert db_rows(p, "audit_events") == audit
