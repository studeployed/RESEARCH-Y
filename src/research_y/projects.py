"""Durable local project creation/opening and research-setup metadata.

First small Phase 1 increment. No network access, GUI, credentials or search
execution is required. Only the single initial database schema is supported;
future migrations are a separately tracked feature.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import unicodedata
from typing import Iterator
from uuid import UUID, uuid4

from research_y.schema import SCHEMA_VERSION, apply_v2_schema
from research_y.checkpoint_schema import apply_v3_schema
from research_y.wos_checkpoint_schema import apply_v4_schema

MANIFEST_FILENAME = "project.ryproj"
DATABASE_RELATIVE_PATH = Path("data") / "researchy.sqlite3"
FORMAT_VERSION = 1
# ASCII 'RSY1' -- identify our SQLite file, not a security signature.
SQLITE_APPLICATION_ID = 0x52535931


class ProjectFormatError(ValueError):
    """A folder or manifest is not a supported, internally consistent project."""


class ProjectVersionError(ProjectFormatError):
    """A project uses a newer or otherwise unsupported format or schema."""


class ProjectMigrationError(ProjectFormatError):
    """An upgrade could not be completed; existing data stays unchanged."""


@dataclass(frozen=True, slots=True)
class Project:
    """Location and immutable identity; no absolute paths are serialized."""

    root: Path
    identifier: UUID
    name: str
    created_at_utc: str

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_FILENAME

    @property
    def database_path(self) -> Path:
        return self.root / DATABASE_RELATIVE_PATH


@dataclass(frozen=True, slots=True)
class ResearchSetup:
    """Research-setup fields retained transactionally in project SQLite."""

    theme: str
    objectives: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError("Project name must be text")
    name = name.strip()
    if not name or len(name) > 200 or any(ord(char) < 32 for char in name):
        raise ValueError("Project name must contain 1–200 printable characters")
    return name


def _safe_folder_name(name: str) -> str:
    # Stable ASCII path for interoperability with Windows and zip archives.
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip("._-")[:80].rstrip(".-")
    if not candidate:
        candidate = "ResearchProject"
    if _windows_reserved(candidate):
        candidate = "ResearchProject-" + candidate
    return candidate


def _windows_reserved(component: str) -> bool:
    # Windows forbids device names even with an extension (e.g. CON.txt).
    base = component.split(".", 1)[0].upper()
    return base in {"CON", "PRN", "AUX", "NUL"} or bool(
        re.fullmatch(r"(?:COM|LPT)[1-9]", base)
    )


def _validate_folder_component(directory_name: str) -> str:
    if not isinstance(directory_name, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", directory_name
    ) or directory_name.endswith(".") or _windows_reserved(directory_name):
        raise ValueError("Project directory must be a safe Windows-compatible single name")
    return directory_name


def _sqlite_connection(path: Path) -> sqlite3.Connection:
    # mode=rw never creates missing databases. A writable connection is also
    # necessary to recover a hot SQLite rollback journal after a crashed writer.
    connection = sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True, timeout=5)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _create_database(database_path: Path, project: Project) -> None:
    # Schema, header values, project identity and audit share one commit.
    # The connection context manager does not begin a transaction for DDL.
    # BEGIN must be inside executescript(), which would commit a transaction
    # opened before that call. On failure the caller removes its new folder.
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;
            PRAGMA application_id={SQLITE_APPLICATION_ID};
            CREATE TABLE project_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                project_uuid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                theme TEXT NOT NULL DEFAULT '',
                objectives TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at_utc TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            PRAGMA user_version=1;
            """
        )
        # Initialise the current schema directly for new projects. Existing
        # schema-v1 projects instead receive a recoverable upgrade on opening.
        apply_v2_schema(connection)
        apply_v3_schema(connection)
        apply_v4_schema(connection)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.execute(
            "INSERT INTO project_metadata "
            "(singleton_id, project_uuid, name, created_at_utc) "
            "VALUES (1, ?, ?, ?)",
            (str(project.identifier), project.name, project.created_at_utc),
        )
        connection.execute(
            "INSERT INTO audit_events (occurred_at_utc, event_type, details_json) "
            "VALUES (?, ?, ?)",
            (
                project.created_at_utc,
                "project_created",
                json.dumps({"project_uuid": str(project.identifier)}, sort_keys=True),
            ),
        )


def create_project(
    parent_directory: Path | str, name: str, *, directory_name: str | None = None
) -> Project:
    """Create a uniquely identified project without overwriting an existing path.

    The new root folder is reserved with an exclusive mkdir. Failure during
    initialisation removes only this newly allocated folder; pre-existing
    folders and their contents are never modified.
    """
    name = _validate_name(name)
    parent = Path(parent_directory).expanduser().resolve(strict=True)
    if not parent.is_dir():
        raise NotADirectoryError(parent)
    component = _validate_folder_component(
        directory_name if directory_name is not None else _safe_folder_name(name)
    )
    project_root = parent / component
    project = Project(
        root=project_root,
        identifier=uuid4(),
        name=name,
        created_at_utc=_utc_now(),
    )
    project_root.mkdir(mode=0o700, exist_ok=False)
    try:
        for relative_path in ("data/raw", "documents", "exports", "logs", "backups"):
            (project_root / relative_path).mkdir(parents=True, mode=0o700)
        _create_database(project.database_path, project)
        manifest = {
            "format_version": FORMAT_VERSION,
            "project_id": str(project.identifier),
            "name": project.name,
            "created_at_utc": project.created_at_utc,
        }
        with project.manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
        return open_project(project_root)
    except BaseException:
        # Only the path this function exclusively created can be removed.
        shutil.rmtree(project_root)
        raise


def _parse_manifest(path: Path) -> tuple[UUID, str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectFormatError(f"Cannot read valid project manifest: {path}") from exc
    if not isinstance(data, dict):
        raise ProjectFormatError("Project manifest must be a JSON object")
    if type(data.get("format_version")) is not int:
        raise ProjectFormatError("Missing or invalid project format version")
    if data["format_version"] != FORMAT_VERSION:
        raise ProjectVersionError(f"Unsupported project format: {data['format_version']}")
    try:
        identifier = UUID(data["project_id"])
        name = _validate_name(data["name"])
        created_at_utc = data["created_at_utc"]
        timestamp = datetime.fromisoformat(created_at_utc)
        if not isinstance(created_at_utc, str) or timestamp.tzinfo is None or (
            timestamp.utcoffset() != timedelta(0)
        ):
            raise ValueError("Timestamp must have UTC timezone")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ProjectFormatError("Invalid project identity in manifest") from exc
    if str(identifier) != data["project_id"] or name != data["name"]:
        raise ProjectFormatError("Noncanonical project UUID or project name")
    return identifier, name, created_at_utc


def _snapshot_before_upgrade(
    project: Project, connection: sqlite3.Connection, expected_version: int = 1,
) -> Path:
    """Create a verified, independently readable SQLite snapshot before DDL."""
    backups = project.root / "backups"
    backups.mkdir(mode=0o700, exist_ok=True)
    filename = f"researchy-before-v{expected_version + 1}-{uuid4().hex}.sqlite3"
    snapshot = backups / filename
    temporary = backups / f"{filename}.partial"
    try:
        with closing(sqlite3.connect(temporary)) as destination:
            connection.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Snapshot integrity check failed")
            if destination.execute("PRAGMA user_version").fetchone()[0] != expected_version:
                raise sqlite3.DatabaseError("Unexpected snapshot schema version")
        temporary.replace(snapshot)
    except (OSError, sqlite3.DatabaseError) as exc:
        temporary.unlink(missing_ok=True)
        raise ProjectMigrationError("Could not create a recoverable migration snapshot") from exc
    return snapshot


def _upgrade_v1_project(project: Project, connection: sqlite3.Connection) -> None:
    """Apply the v1→v2 migration atomically, after a consistent snapshot."""
    snapshot = _snapshot_before_upgrade(project, connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        # Fail safely if a concurrent writer changed the schema since inspection.
        if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise sqlite3.DatabaseError("Schema changed during migration")
        apply_v2_schema(connection)
        apply_v3_schema(connection)
        apply_v4_schema(connection)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.execute(
            "INSERT INTO audit_events (occurred_at_utc, event_type, details_json) "
            "VALUES (?, ?, ?)",
            (_utc_now(), "schema_migrated", json.dumps({
                "from_version": 1,
                "to_version": SCHEMA_VERSION,
                "backup": snapshot.name,
            }, sort_keys=True)),
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise ProjectMigrationError(
            f"Schema upgrade failed; original data and snapshot preserved: {snapshot.name}"
        ) from exc


def _upgrade_v2_project(project: Project, connection: sqlite3.Connection) -> None:
    """Create v3 PubMed checkpoints with an independently verified v2 backup.

    Backup publication precedes all schema DDL. A failed audit or DDL insert
    rolls back the complete migration and preserves the pre-migration store.
    """
    snapshot = _snapshot_before_upgrade(project, connection, expected_version=2)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise sqlite3.DatabaseError("Schema changed during migration")
        apply_v3_schema(connection)
        apply_v4_schema(connection)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.execute(
            "INSERT INTO audit_events (occurred_at_utc, event_type, details_json) "
            "VALUES (?, ?, ?)",
            (_utc_now(), "schema_migrated", json.dumps({
                "from_version": 2, "to_version": SCHEMA_VERSION,
                "backup": snapshot.name,
            }, sort_keys=True)),
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise ProjectMigrationError(
            f"Schema upgrade failed; original data and snapshot preserved: {snapshot.name}"
        ) from exc


def _upgrade_v3_project(project: Project, connection: sqlite3.Connection) -> None:
    """Add Starter checkpoints atomically, preserving a verified v3 snapshot."""
    snapshot = _snapshot_before_upgrade(project, connection, expected_version=3)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("PRAGMA user_version").fetchone()[0] != 3:
            raise sqlite3.DatabaseError("Schema changed during migration")
        apply_v4_schema(connection)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.execute(
            "INSERT INTO audit_events (occurred_at_utc,event_type,details_json) VALUES (?,?,?)",
            (_utc_now(), "schema_migrated", json.dumps({
                "from_version": 3, "to_version": SCHEMA_VERSION,
                "backup": snapshot.name,
            }, sort_keys=True)),
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise ProjectMigrationError(
            f"Schema upgrade failed; original data and snapshot preserved: {snapshot.name}"
        ) from exc


@contextmanager
def _validated_project_connection(project: Project) -> Iterator[sqlite3.Connection]:
    """Validate and operate on one open SQLite handle, with crash recovery.

    The non-creating writable connection can roll back a hot journal before
    validation. All subsequent reads/writes use the *same* verified handle:
    a directory replacement after validation cannot redirect a later open.
    """
    db_path = project.database_path
    if (project.root / "data").is_symlink() or db_path.is_symlink():
        raise ProjectFormatError("Project database may not be a symbolic link")
    if not db_path.is_file():
        raise ProjectFormatError("Project SQLite database is missing")
    try:
        connection = _sqlite_connection(db_path)
    except sqlite3.DatabaseError as exc:
        raise ProjectFormatError("Project database cannot be opened") from exc
    with closing(connection):
        try:
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if schema_version not in (1, 2, 3, SCHEMA_VERSION):
                raise ProjectVersionError(f"Unsupported database schema: {schema_version}")
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            if application_id != SQLITE_APPLICATION_ID:
                raise ProjectFormatError("SQLite application identifier does not match")
            row = connection.execute(
                "SELECT project_uuid, name, created_at_utc "
                "FROM project_metadata WHERE singleton_id=1"
            ).fetchone()
            if row != (str(project.identifier), project.name, project.created_at_utc):
                raise ProjectFormatError("Manifest and SQLite identity do not agree")
        except sqlite3.DatabaseError as exc:
            raise ProjectFormatError("Project database cannot be read") from exc
        if schema_version == 1:
            _upgrade_v1_project(project, connection)
        elif schema_version == 2:
            _upgrade_v2_project(project, connection)
        elif schema_version == 3:
            _upgrade_v3_project(project, connection)
        # Do not convert operational exceptions inside yield into format errors.
        # In particular, an audit-insert failure must rollback *and* remain
        # identifiable as a failed write, not a malformed project.
        with connection:
            yield connection


def open_project(folder_or_manifest: Path | str) -> Project:
    """Read and validate an existing project without creating missing data."""
    provided = Path(folder_or_manifest).expanduser()
    # A directory itself may legitimately be named "project.ryproj".
    if provided.name == MANIFEST_FILENAME and provided.is_file():
        provided = provided.parent
    root = provided.resolve(strict=True)
    if not root.is_dir():
        raise ProjectFormatError("Expected a project directory or project.ryproj")
    manifest_path = root / MANIFEST_FILENAME
    if manifest_path.is_symlink():
        raise ProjectFormatError("Project manifest may not be a symbolic link")
    identifier, name, created_at_utc = _parse_manifest(manifest_path)
    project = Project(root, identifier, name, created_at_utc)
    with _validated_project_connection(project):
        pass
    return project


def read_research_setup(project: Project) -> ResearchSetup:
    """Retrieve saved theme/objectives, never silently creating a database."""
    with _validated_project_connection(project) as connection:
        theme, objectives = connection.execute(
            "SELECT theme, objectives FROM project_metadata WHERE singleton_id=1"
        ).fetchone()
    return ResearchSetup(theme=theme, objectives=objectives)


def update_research_setup(project: Project, *, theme: str, objectives: str = "") -> None:
    """Transactionally save theme/objectives and one corresponding audit event."""
    if not isinstance(theme, str) or not isinstance(objectives, str):
        raise TypeError("Theme and objectives must be text")
    with _validated_project_connection(project) as connection:
        connection.execute("BEGIN IMMEDIATE")
        old_theme, old_objectives = connection.execute(
            "SELECT theme, objectives FROM project_metadata WHERE singleton_id=1"
        ).fetchone()
        connection.execute(
            "UPDATE project_metadata SET theme=?, objectives=? WHERE singleton_id=1",
            (theme, objectives),
        )
        connection.execute(
            "INSERT INTO audit_events (occurred_at_utc, event_type, details_json) "
            "VALUES (?, ?, ?)",
            (
                _utc_now(),
                "research_setup_updated",
                json.dumps(
                    {
                        "previous": {"theme": old_theme, "objectives": old_objectives},
                        "current": {"theme": theme, "objectives": objectives},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
