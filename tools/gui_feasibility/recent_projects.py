"""Private launcher-only recent project index for isolated GUI feasibility.

The catalog is NOT a research/project database. It stores only an immutable
project UUID, display name, host-selected local path and local recency; never
credentials, provider responses, exports, source counts or project contents.

SQLite serialises concurrent GUI-host writers. The index is advisory: reopening
ALWAYS revalidates the actual project and matching immutable UUID. A damaged or
unsupported index fails closed; there is no silent reset or destructive cleanup.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import stat
import time
from uuid import UUID

from research_y.export_files import Directory, ExportFileError

FILENAME = 'recent-projects.sqlite3'
APPLICATION_ID = 0x52595243  # 'RYRC' -- a format discriminator, not an authentication signature
FORMAT_VERSION = 1
MAX_ENTRIES = 12
MAX_INDEX_BYTES = 2 * 1024 * 1024


class RecentProjectsError(ValueError):
    """A static code that cannot reveal an original filesystem path."""

    def __init__(self, code='recent_history_unavailable'):
        super().__init__(code if code in {
            'recent_history_unavailable', 'recent_selection_invalid',
            'recent_project_unknown',
        } else 'recent_history_unavailable')


def _canonical_uuid(value):
    if type(value) is not str:
        raise RecentProjectsError('recent_selection_invalid')
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise RecentProjectsError('recent_selection_invalid') from None
    if str(parsed) != value:
        raise RecentProjectsError('recent_selection_invalid')
    return value


def _valid_row(row):
    project_id, name, location, visited_ns = row
    _canonical_uuid(project_id)
    if (type(name) is not str or not name or len(name) > 200
            or any(ord(ch) < 32 for ch in name)):
        raise RecentProjectsError()
    if type(location) is not str or not location or len(location) > 4096:
        raise RecentProjectsError()
    path = Path(location)
    if not path.is_absolute() or '..' in path.parts or str(path) != location:
        raise RecentProjectsError()
    if type(visited_ns) is not int or visited_ns <= 0:
        raise RecentProjectsError()
    return {'project_id': project_id, 'name': name, 'location': location}


class RecentProjects:
    def __init__(self, private_parent: Path):
        parent = Path(private_parent)
        if not parent.is_absolute() or '..' in parent.parts:
            raise RecentProjectsError()
        self.parent = parent
        self.path = parent / FILENAME

    def _safe_file(self):
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return False
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size > MAX_INDEX_BYTES
                or bool(getattr(info, 'st_file_attributes', 0) &
                        getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))):
            raise RecentProjectsError()
        return True

    @contextmanager
    def _db(self, *, create=False):
        try:
            if create:
                self.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if not self.parent.is_dir():
                if create:
                    raise RecentProjectsError()
                yield None
                return
            with Directory(self.parent):
                existing = self._safe_file()
                if not existing and not create:
                    yield None
                    return
                with closing(sqlite3.connect(str(self.path), timeout=5)) as db:
                    db.execute('PRAGMA busy_timeout=5000')
                    if not existing:
                        # Multiple GUI hosts may race to create their private
                        # catalog. BEGIN IMMEDIATE serialises first use; the
                        # second creator re-reads the header after acquiring
                        # the lock instead of trying to recreate the table.
                        db.execute('BEGIN IMMEDIATE')
                        app_id = db.execute('PRAGMA application_id').fetchone()[0]
                        version = db.execute('PRAGMA user_version').fetchone()[0]
                        if (app_id, version) == (0, 0):
                            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                            db.execute('''CREATE TABLE recent_projects (
                                project_uuid TEXT PRIMARY KEY,
                                project_name TEXT NOT NULL,
                                project_root TEXT NOT NULL,
                                visited_ns INTEGER NOT NULL CHECK(visited_ns > 0)
                            )''')
                            db.execute(f'PRAGMA user_version={FORMAT_VERSION}')
                        elif (app_id, version) != (APPLICATION_ID, FORMAT_VERSION):
                            raise RecentProjectsError()
                        db.commit()
                        if os.name != 'nt':
                            os.chmod(self.path, 0o600)
                    elif (db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                          or db.execute('PRAGMA user_version').fetchone()[0] != FORMAT_VERSION):
                        raise RecentProjectsError()
                    # Check before returning a connection so corruption, wrong
                    # schema and unsafe aliases cannot silently become an empty list.
                    fields = db.execute('PRAGMA table_info(recent_projects)').fetchall()
                    if [r[1] for r in fields] != [
                            'project_uuid', 'project_name', 'project_root', 'visited_ns']:
                        raise RecentProjectsError()
                    yield db
        except RecentProjectsError:
            raise
        except (OSError, sqlite3.Error, ExportFileError, ValueError, TypeError):
            raise RecentProjectsError() from None

    def items(self):
        with self._db() as db:
            if db is None:
                return []
            rows = db.execute('SELECT project_uuid,project_name,project_root,visited_ns '
                              'FROM recent_projects '
                              'ORDER BY visited_ns DESC,project_uuid ASC').fetchall()
            if len(rows) > MAX_ENTRIES:
                raise RecentProjectsError()
            return [_valid_row(row) for row in rows]

    def get(self, project_id):
        project_id = _canonical_uuid(project_id)
        with self._db() as db:
            if db is None:
                raise RecentProjectsError('recent_project_unknown')
            row = db.execute('SELECT project_uuid,project_name,project_root,visited_ns '
                             'FROM recent_projects WHERE project_uuid=?', (project_id,)).fetchone()
            if row is None:
                raise RecentProjectsError('recent_project_unknown')
            return _valid_row(row)

    def record(self, project):
        """Record only a successfully opened, inspected real project.

        UUID is the identity key: opening a moved project updates its one
        catalog entry rather than duplicating it. Concurrent writers use
        SQLite BEGIN IMMEDIATE and never mutate research project metadata.
        """
        project_id = _canonical_uuid(str(project.identifier))
        entry = _valid_row((project_id, project.name, str(project.root), time.time_ns()))
        with self._db(create=True) as db:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('''INSERT INTO recent_projects
                    (project_uuid,project_name,project_root,visited_ns)
                    VALUES (?,?,?,?)
                    ON CONFLICT(project_uuid) DO UPDATE SET
                        project_name=excluded.project_name,
                        project_root=excluded.project_root,
                        visited_ns=excluded.visited_ns''',
                    (entry['project_id'], entry['name'], entry['location'], time.time_ns()))
                db.execute('''DELETE FROM recent_projects WHERE project_uuid NOT IN (
                    SELECT project_uuid FROM recent_projects
                    ORDER BY visited_ns DESC,project_uuid ASC LIMIT ?)''',
                    (MAX_ENTRIES,))
        return self.items()
