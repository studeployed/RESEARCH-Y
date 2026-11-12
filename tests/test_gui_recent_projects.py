"""Private, host-owned recent launcher history: real projects and failure paths.

No graphical dependency or provider connection is needed for these tests.
The actual GUI launcher/Windows button remains exercised separately by the
isolated graphical lifecycle matrix.
"""
from concurrent.futures import ThreadPoolExecutor
import inspect
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
from uuid import uuid4

import pytest

from research_y.projects import create_project, open_project
from tools.gui_feasibility.recent_projects import (
    APPLICATION_ID, FILENAME, MAX_ENTRIES, RecentProjects, RecentProjectsError,
)
from tools.gui_feasibility.real_project_flow import ProjectFlowError, RealProjectFlow
from tools.gui_feasibility.run_real_project import fixture
from tools.gui_feasibility.real_project_app import run
from tools.gui_feasibility.run_real_project import run_app, transport_steps


def _flow(root, parent, history):
    return RealProjectFlow(selected_root=root, selected_parent=parent,
                           recent_parent=history)


def test_recent_history_is_empty_until_real_successful_open(tmp_path):
    history = tmp_path / 'private-history'
    recent = RecentProjects(history)
    assert recent.items() == []
    assert not history.exists()
    project = create_project(tmp_path, 'Tested project')
    flow = _flow(tmp_path / 'missing', tmp_path, history)
    try:
        assert flow.state()['project'] is None
        assert flow.state()['recent_projects'] == []
        assert flow.open_native_folder(project.root)['project']['project_id'] == str(project.identifier)
        assert flow.state()['recent_projects'] == [
            {'project_id': str(project.identifier),
             'name': project.name, 'location': str(project.root)}]
        assert flow.state()['selected_run_id'] is None
        assert flow.state()['recent_history_error'] is None
    finally:
        flow.close()
    assert recent.items()[0]['project_id'] == str(project.identifier)
    assert history.is_dir()
    assert (history / FILENAME).is_file()
    with sqlite3.connect(history / FILENAME) as db:
        assert db.execute('PRAGMA application_id').fetchone()[0] == APPLICATION_ID


def test_explicit_recent_reopen_survives_fresh_launcher_and_keeps_run_unselected(tmp_path):
    history = tmp_path / 'launcher-history'
    project, run_id = fixture(tmp_path)
    first = _flow(project.root, tmp_path, history)
    try:
        first.open_selected()
        first.select_run(run_id)
        export_id = first.prepare()['selected_export_id']
        assert first.state()['selected_run_id'] == run_id
    finally:
        first.close()

    # This launcher has no valid preselected project folder. The only path
    # source is the local catalog entry, which is revalidated by the host.
    later = _flow(tmp_path / 'nonexistent', tmp_path, history)
    try:
        before = later.state()
        assert before['project'] is None and before['selected_run_id'] is None
        assert len(before['recent_projects']) == 1
        state = later.open_recent(str(project.identifier))
        assert state['project']['project_id'] == str(project.identifier)
        assert state['selected_run_id'] is None
        assert state['selected_export_id'] is None
        assert len(state['exports']) == 1
        assert not state['source_retrieval_verified']
        later.select_run(run_id)
        later.select_export(export_id)
        assert later.observe()['observation']['audited_success'] is False
    finally:
        later.close()


def test_relocation_updates_one_uuid_without_automatic_filesystem_search(tmp_path):
    import shutil
    history = tmp_path / 'private-history'
    project = create_project(tmp_path, 'Movable')
    initial = _flow(project.root, tmp_path, history)
    try:
        initial.open_selected()
    finally:
        initial.close()
    old = project.root
    moved = tmp_path / 'moved-project'
    shutil.move(old, moved)
    stale = _flow(tmp_path / 'not-found', tmp_path, history)
    try:
        with pytest.raises(ProjectFlowError, match='^recent_project_unavailable$'):
            stale.open_recent(str(project.identifier))
        assert stale.state()['project'] is None
        assert stale.state()['recent_projects'][0]['location'] == str(old)
        updated = stale.open_native_folder(moved)
        assert updated['recent_projects'] == [{
            'project_id': str(project.identifier), 'name': project.name,
            'location': str(moved),
        }]
    finally:
        stale.close()
    another = _flow(tmp_path / 'not-found', tmp_path, history)
    try:
        assert another.open_recent(str(project.identifier))['project']['location'] == str(moved)
    finally:
        another.close()
    assert len(RecentProjects(history).items()) == 1


def test_stale_or_forged_recent_entries_cannot_change_active_project(tmp_path):
    history = tmp_path / 'private-history'
    first = create_project(tmp_path, 'Original')
    other = create_project(tmp_path, 'Other')
    flow = _flow(first.root, tmp_path, history)
    try:
        flow.open_selected()
        before = flow.state()
        for identifier in ('bad', str(uuid4()), '../wrong'):
            with pytest.raises(ProjectFlowError, match='^recent_(selection_invalid|project_unknown)$'):
                flow.open_recent(identifier)
            assert flow.state() == before
        # An advisory local catalog has been tampered with to point the same
        # UUID at another real project. Neither the full path nor the source
        # of the tampering is accepted; the verified manifest UUID controls.
        with sqlite3.connect(history / FILENAME) as db:
            db.execute('UPDATE recent_projects SET project_root=? WHERE project_uuid=?',
                       (str(other.root), str(first.identifier)))
        with pytest.raises(ProjectFlowError, match='^recent_project_identity_mismatch$'):
            flow.open_recent(str(first.identifier))
        assert flow.state() == before
        assert flow.project.identifier == first.identifier
    finally:
        flow.close()


def test_mismatched_legacy_recent_uuid_cannot_trigger_migration(tmp_path):
    history = tmp_path / 'history'
    selected = create_project(tmp_path, 'Selected')
    unrelated = create_project(tmp_path, 'Different older project')

    # Mark the unrelated database as a supported older schema. If it is
    # actually opened, the core migration pathway would create a backup and
    # append a schema_migrated audit event BEFORE returning. This test must
    # reject the catalog identity without opening the unrelated project.
    with sqlite3.connect(unrelated.database_path) as db:
        db.execute('PRAGMA user_version=3')
        prior_events = db.execute(
            'SELECT COUNT(*) FROM audit_events').fetchone()[0]
    assert list((unrelated.root / 'backups').iterdir()) == []

    flow = _flow(selected.root, tmp_path, history)
    try:
        flow.open_selected()
        prior_state = flow.state()
        with sqlite3.connect(history / FILENAME) as db:
            db.execute('UPDATE recent_projects SET project_root=? WHERE project_uuid=?',
                       (str(unrelated.root), str(selected.identifier)))
        with pytest.raises(ProjectFlowError, match='^recent_project_identity_mismatch$'):
            flow.open_recent(str(selected.identifier))
        assert flow.state() == prior_state
        assert flow.project.identifier == selected.identifier
    finally:
        flow.close()

    with sqlite3.connect(unrelated.database_path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0] == prior_events
        assert db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type='schema_migrated'"
        ).fetchone()[0] == 0
    assert list((unrelated.root / 'backups').iterdir()) == []


def test_recent_catalog_corruption_preserved_not_silently_rebuilt(tmp_path):
    history = tmp_path / 'private-history'
    history.mkdir()
    dbfile = history / FILENAME
    corrupt = b'not a SQLite catalog; private garbage survives'
    dbfile.write_bytes(corrupt)
    with pytest.raises(RecentProjectsError, match='^recent_history_unavailable$'):
        RecentProjects(history).items()
    project = create_project(tmp_path, 'Still usable')
    flow = _flow(project.root, tmp_path, history)
    try:
        assert flow.state()['recent_history_error'] == 'recent_history_unavailable'
        state = flow.open_selected()
        assert state['project']['project_id'] == str(project.identifier)
        assert state['recent_history_error'] == 'recent_history_unavailable'
        assert state['recent_projects'] == []
        with pytest.raises(ProjectFlowError, match='^recent_history_unavailable$'):
            flow.open_recent(str(project.identifier))
    finally:
        flow.close()
    assert dbfile.read_bytes() == corrupt


def test_recent_catalog_rejects_linked_database(tmp_path):
    history = tmp_path / 'history'
    history.mkdir()
    source = tmp_path / 'sensitive.txt'
    source.write_text('do not modify')
    catalog = history / FILENAME
    if os.name == 'nt':
        os.link(source, catalog)
    else:
        catalog.symlink_to(source)
    with pytest.raises(RecentProjectsError, match='^recent_history_unavailable$'):
        RecentProjects(history).items()
    assert source.read_text() == 'do not modify'


def test_fully_valid_catalog_rejects_unsupported_version_without_deletion(tmp_path):
    history = tmp_path / 'history'
    project = create_project(tmp_path, 'Version test')
    recents = RecentProjects(history)
    recents.record(project)
    with sqlite3.connect(recents.path) as db:
        db.execute('PRAGMA user_version=999')
    original_bytes = recents.path.read_bytes()
    with pytest.raises(RecentProjectsError, match='^recent_history_unavailable$'):
        recents.items()
    assert recents.path.read_bytes() == original_bytes


def test_header_validation_waits_for_concurrent_schema_commit(tmp_path):
    history = tmp_path / 'history'
    history.mkdir()
    catalog = RecentProjects(history)
    # Simulate another GUI host after creating its SQLite file and building
    # the correct schema but BEFORE the initialization transaction commits.
    # An unlocked PRAGMA read would see a temporary 0 application ID.
    with sqlite3.connect(catalog.path, timeout=5) as writer:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute(f'PRAGMA application_id={APPLICATION_ID}')
        writer.execute('''CREATE TABLE recent_projects (
            project_uuid TEXT PRIMARY KEY,
            project_name TEXT NOT NULL,
            project_root TEXT NOT NULL,
            visited_ns INTEGER NOT NULL CHECK(visited_ns > 0)
        )''')
        writer.execute('PRAGMA user_version=1')
        started = threading.Event()
        def blocked_reader():
            started.set()
            return catalog.items()
        with ThreadPoolExecutor(max_workers=1) as workers:
            reading = workers.submit(blocked_reader)
            assert started.wait(timeout=3)
            time.sleep(.1)
            assert not reading.done(), 'Catalog reader bypassed the writer lock'
            writer.commit()
            assert reading.result(timeout=5) == []
    assert catalog.items() == []


def test_concurrent_updates_are_transactional_and_bounded(tmp_path):
    projects = [create_project(tmp_path, f'Project {i:02d}') for i in range(20)]
    history = tmp_path / 'launcher-history'
    catalog = RecentProjects(history)
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(catalog.record, projects))
    rows = catalog.items()
    assert len(rows) == MAX_ENTRIES
    assert len({r['project_id'] for r in rows}) == MAX_ENTRIES
    for row in rows:
        assert open_project(row['location']).name == row['name']


def test_no_implicit_project_change_on_failed_recent_db_open(tmp_path):
    history = tmp_path / 'history'
    project = create_project(tmp_path, 'Original')
    another = create_project(tmp_path, 'Second')
    flow = _flow(project.root, tmp_path, history)
    try:
        flow.open_selected()
        initial = flow.state()
        # Unregistered IDs cannot open arbitrary valid folders.
        with pytest.raises(ProjectFlowError, match='^recent_project_unknown$'):
            flow.open_recent(str(another.identifier))
        assert flow.project.identifier == project.identifier
        assert flow.state() == initial
    finally:
        flow.close()


def test_recent_gui_exposes_only_host_catalog_uuid_not_browser_path():
    from desktop_source import project_ui_source
    source = project_ui_source()
    transport = inspect.getsource(transport_steps)
    driver = inspect.getsource(run_app)
    assert "if name == 'recent_open':" in source
    assert "flow.open_recent(value)" in source
    assert "data-testid=open-recent" in source
    assert "state['recent_projects']" in source
    assert "RESEARCHY_GUI_RECENTS_PARENT" in driver
    assert "parent / 'not-an-open-project' if scenario == 'recent_open'" in driver
    assert "if action in ('open', 'recent_open')" in transport
    assert "client_supplied_recent_path" not in source
