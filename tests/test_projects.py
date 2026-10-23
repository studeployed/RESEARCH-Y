"""Offline project-storage contract tests: PROJ-02/03/04, partial AT-01/02."""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import UUID

import pytest

from research_y.projects import (
    DATABASE_RELATIVE_PATH,
    FORMAT_VERSION,
    MANIFEST_FILENAME,
    SQLITE_APPLICATION_ID,
    SCHEMA_VERSION,
    ProjectFormatError,
    ProjectVersionError,
    create_project,
    open_project,
    read_research_setup,
    update_research_setup,
)


def _manifest(project_root: Path) -> dict:
    return json.loads((project_root / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def test_create_project_has_portable_layout_and_immutable_identity(tmp_path: Path) -> None:
    project = create_project(tmp_path, "VV ECMO research")
    assert project.root == tmp_path / "VV-ECMO-research"
    assert project.root.is_dir()
    assert project.database_path.is_file()
    assert project.manifest_path.is_file()
    for dirname in ("data/raw", "documents", "exports", "logs", "backups"):
        assert (project.root / dirname).is_dir()
    manifest = _manifest(project.root)
    assert manifest == {
        "format_version": FORMAT_VERSION,
        "project_id": str(project.identifier),
        "name": "VV ECMO research",
        "created_at_utc": project.created_at_utc,
    }
    assert UUID(manifest["project_id"]).version == 4
    assert str(tmp_path) not in project.manifest_path.read_text(encoding="utf-8")
    assert read_research_setup(project).theme == ""


def test_reopen_and_research_setup_update_are_durable(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Right heart failure")
    update_research_setup(
        project, theme="Right ventricular failure / ECMO", objectives="Broad overview",
    )
    reopened = open_project(project.manifest_path)
    assert reopened == project
    assert read_research_setup(reopened).theme == "Right ventricular failure / ECMO"
    assert read_research_setup(reopened).objectives == "Broad overview"
    with closing(sqlite3.connect(reopened.database_path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("PRAGMA application_id").fetchone()[0] == SQLITE_APPLICATION_ID
        events = conn.execute("SELECT event_type FROM audit_events ORDER BY event_id").fetchall()
        assert events == [("project_created",), ("research_setup_updated",)]


def test_relocate_project_directory_preserves_data_and_identity(tmp_path: Path) -> None:
    first_parent = tmp_path / "first"
    second_parent = tmp_path / "second"
    first_parent.mkdir()
    second_parent.mkdir()
    project = create_project(first_parent, "Guideline literature")
    update_research_setup(project, theme="Guidelines")
    moved_root = Path(shutil.move(str(project.root), str(second_parent / project.root.name)))
    reopened = open_project(moved_root)
    assert reopened.identifier == project.identifier
    assert read_research_setup(reopened).theme == "Guidelines"
    assert reopened.database_path == moved_root / DATABASE_RELATIVE_PATH


def test_existing_folder_is_never_replaced_or_erased(tmp_path: Path) -> None:
    existing = tmp_path / "Study"
    existing.mkdir()
    sentinel = existing / "keep-me.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_project(tmp_path, "Study")
    assert sentinel.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    "unsafe", ["../escape", "..", ".", "/absolute", "CON", "nul.txt", "LPT1", "a/b", "a\\b", "trail.", "sp ace", "", "C:temp"]
)
def test_explicit_directory_names_reject_path_escape_and_windows_devices(
    tmp_path: Path, unsafe: str
) -> None:
    with pytest.raises(ValueError):
        create_project(tmp_path, "Safe", directory_name=unsafe)
    assert not list(tmp_path.iterdir())


def test_user_visible_project_name_is_not_used_as_unsafe_path(tmp_path: Path) -> None:
    name = 'Clinical / "quotes" : test?'
    project = create_project(tmp_path, name)
    assert project.name == name
    assert project.root.parent == tmp_path
    assert project.root.name == "Clinical-quotes-test"


def test_missing_manifest_rejected_and_not_regenerated(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    project.manifest_path.unlink()
    with pytest.raises(ProjectFormatError):
        open_project(project.root)
    assert not project.manifest_path.exists()


def test_corrupt_json_manifest_rejected(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    project.manifest_path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        open_project(project.root)


def test_unsupported_manifest_version_fails_without_mutation(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    data = _manifest(project.root)
    data["format_version"] = FORMAT_VERSION + 1
    project.manifest_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectVersionError):
        open_project(project.root)
    assert _manifest(project.root)["format_version"] == FORMAT_VERSION + 1


def test_manifest_database_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    data = _manifest(project.root)
    data["project_id"] = "12345678-1234-4123-8123-123456789000"
    project.manifest_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="identity"):
        open_project(project.root)


def test_missing_database_not_silently_created(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    project.database_path.unlink()
    with pytest.raises(ProjectFormatError, match="missing"):
        open_project(project.root)
    assert not project.database_path.exists()


def test_unsupported_schema_rejected(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    with closing(sqlite3.connect(project.database_path)) as conn:
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(ProjectVersionError):
        open_project(project.root)


def test_failed_audit_rolls_back_metadata_change(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    update_research_setup(project, theme="Original")
    with closing(sqlite3.connect(project.database_path)) as conn:
        conn.execute(
            "CREATE TRIGGER reject_audit BEFORE INSERT ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        update_research_setup(project, theme="Must not persist")
    assert read_research_setup(project).theme == "Original"


def test_project_name_validation(tmp_path: Path) -> None:
    for invalid in ("", "  ", "control\nchar", "x" * 201):
        with pytest.raises(ValueError):
            create_project(tmp_path, invalid)
    assert not list(tmp_path.iterdir())


def test_sql_text_is_stored_as_data(tmp_path: Path) -> None:
    project = create_project(tmp_path, "Project")
    suspicious = "'); DROP TABLE project_metadata; --"
    update_research_setup(project, theme=suspicious)
    assert read_research_setup(open_project(project.root)).theme == suspicious


def test_manifest_rejects_symlink(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    external = tmp_path / "external-manifest.json"
    shutil.copyfile(project.manifest_path, external)
    project.manifest_path.unlink()
    try:
        project.manifest_path.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"Windows symlinks unavailable: {exc}")
    with pytest.raises(ProjectFormatError, match="symbolic link"):
        open_project(project.root)


def test_disallow_symlink_database_escape(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    original_db = project.database_path
    external_db = tmp_path / "external.sqlite3"
    shutil.copyfile(original_db, external_db)
    original_db.unlink()
    try:
        original_db.symlink_to(external_db)
    except OSError as exc:
        pytest.skip(f"Windows symlinks unavailable: {exc}")
    with pytest.raises(ProjectFormatError, match="symbolic link"):
        open_project(project.root)


def test_missing_identity_and_wrong_application_identifier_rejected(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    with closing(sqlite3.connect(project.database_path)) as conn, conn:
        conn.execute("PRAGMA application_id=7")
    with pytest.raises(ProjectFormatError, match="application identifier"):
        open_project(project.root)


def test_invalid_manifest_shape_and_timestamp_are_rejected(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    original = _manifest(project.root)
    for bad_manifest in (
        [],
        {**original, "format_version": True},
        {**original, "created_at_utc": "2026-10-23T19:00:00"},
        {**original, "project_id": "not-a-uuid"},
    ):
        project.manifest_path.write_text(json.dumps(bad_manifest), encoding="utf-8")
        with pytest.raises(ProjectFormatError):
            open_project(project.root)


def test_database_file_with_invalid_content_rejected(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    project.database_path.write_bytes(b"not a SQLite database")
    with pytest.raises(ProjectFormatError, match="cannot be read"):
        open_project(project.root)


def test_create_project_rejects_bad_parent_without_side_effects(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_project(tmp_path / "absent", "One")
    ordinary_file = tmp_path / "not-a-folder"
    ordinary_file.write_text("not a folder", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        create_project(ordinary_file, "One")
    assert list(tmp_path.iterdir()) == [ordinary_file]


def test_creation_error_does_not_leave_partial_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import research_y.projects as module

    def fail_database(*args: object, **kwargs: object) -> None:
        raise OSError("simulated creation failure")

    monkeypatch.setattr(module, "_create_database", fail_database)
    with pytest.raises(OSError, match="simulated"):
        create_project(tmp_path, "Transient")
    assert not list(tmp_path.iterdir())


def test_unicode_name_and_explicit_directory(tmp_path: Path) -> None:
    project = create_project(tmp_path, "研究", directory_name="Project-2026")
    assert project.root.name == "Project-2026"
    assert open_project(project.root).name == "研究"
    default = create_project(tmp_path, "研究")
    assert default.root.name == "ResearchProject"


def test_update_validates_types(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    with pytest.raises(TypeError):
        update_research_setup(project, theme=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        update_research_setup(project, theme="valid", objectives=None)  # type: ignore[arg-type]
    assert read_research_setup(project).theme == ""


def test_audit_contains_previous_and_current_values(tmp_path: Path) -> None:
    project = create_project(tmp_path, "One")
    update_research_setup(project, theme="First", objectives="Original")
    update_research_setup(project, theme="Second", objectives="Updated")
    with closing(sqlite3.connect(project.database_path)) as conn:
        payloads = conn.execute(
            "SELECT details_json FROM audit_events "
            "WHERE event_type='research_setup_updated' ORDER BY event_id"
        ).fetchall()
    assert len(payloads) == 2
    assert json.loads(payloads[1][0]) == {
        "previous": {"theme": "First", "objectives": "Original"},
        "current": {"theme": "Second", "objectives": "Updated"},
    }
