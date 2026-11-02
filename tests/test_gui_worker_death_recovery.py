"""Real supervisor-owned worker death while writing a retained Excel artifact.

Unlike external subprocess fixtures, this test launches the actual
ApplicationWorker created by RealProjectFlow, waits for that child's guarded
partial write and terminates precisely that worker. It then reopens the real
project with an ordinary worker to verify its immutable recovery contract.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import inspect
import os
from pathlib import Path
import signal
import sqlite3
from uuid import uuid4
import threading
import time
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from research_y import application_worker, workbook_exports
from research_y.application_inspection import observe_export_request, read_export_report
from research_y.projects import open_project
from tools.gui_feasibility.real_project_flow import ProjectFlowError, RealProjectFlow
from tools.gui_feasibility.run_prototype import wait_until
from tools.gui_feasibility.run_real_project import fixture, run_app, transport_steps
from tools.gui_feasibility.real_project_app import run
from tools.gui_feasibility.worker_death_fixture import (
    pause_during_retained_stage, publish_gui_owner_marker)


def _marker_matches_live_worker(marker, child):
    """Never consume an O_EXCL-created or partially written PID marker."""
    return (child is not None and child.is_alive() and marker.is_file()
            and marker.read_text(encoding='ascii') == str(child.pid))


def event_count(project, export_id):
    with closing(sqlite3.connect(project.database_path)) as db:
        return db.execute('SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                          (f'{workbook_exports.EVENT}:{export_id}',)).fetchone()[0]


def test_actual_supervised_worker_death_keeps_original_request_and_partial_stage(
        tmp_path, monkeypatch):
    project, run_id = fixture(tmp_path)
    export_id = str(uuid4())
    output_name = 'strategy-summary-' + run_id + '.xlsx'
    workbook_exports.prepare_workbook_export(project, run_id, output_name, export_id=export_id)
    original_report_sha = read_export_report(project, export_id).sha256
    assert event_count(project, export_id) == 1
    marker = tmp_path / 'private-worker-pid'
    monkeypatch.setenv('RESEARCHY_GUI_TEST_STAGE_MARKER', str(marker))
    original_execute = application_worker.execute_command
    monkeypatch.setattr(application_worker, 'execute_command', pause_during_retained_stage)

    flow = RealProjectFlow(selected_root=project.root, selected_parent=tmp_path)
    try:
        assert flow.open_selected()['selected_run_id'] is None
        flow.select_run(run_id)
        flow.select_export(export_id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(flow.resume)
            wait_until(lambda: _marker_matches_live_worker(
                marker, flow._worker._process), timeout=30)
            child = flow._worker._process
            assert child is not None and child.is_alive()
            child_pid = int(marker.read_text(encoding='ascii'))
            # Only the known direct child created by THIS supervisor can die.
            assert child_pid == child.pid and child_pid > 0 and child_pid != os.getpid()
            os.kill(child_pid, signal.SIGTERM)
            with pytest.raises(ProjectFlowError, match='^worker_interrupted$'):
                future.result(timeout=30)
        damaged_state = flow.state()
        assert damaged_state['selected_run_id'] == run_id
        assert damaged_state['selected_export_id'] == export_id
        assert damaged_state['observation'] is None
        assert len(damaged_state['exports']) == 1
        assert damaged_state['exports'][0]['recorded_state'] == 'staging'
        assert damaged_state['exports'][0]['last_error'] is None
        assert damaged_state['source_retrieval_verified'] is False
        negative = flow.observe()['observation']
        assert negative['outcome'] == 'retained_artifact_changed'
        assert negative['audited_success'] is False
        assert event_count(project, export_id) == 2
    finally:
        flow.close()
        monkeypatch.setattr(application_worker, 'execute_command', original_execute)
        monkeypatch.delenv('RESEARCHY_GUI_TEST_STAGE_MARKER')

    with workbook_exports._transaction(project, write=False) as db:
        state = workbook_exports._required(db, project, export_id)
    partial = (project.root / 'exports' / workbook_exports.STORE /
               state['stage']['name'])
    partial_bytes = partial.read_bytes()
    partial_identity = (partial.stat().st_dev, partial.stat().st_ino)
    assert 0 < len(partial_bytes) < state['stage']['size']
    assert sha256(partial_bytes).hexdigest() != state['stage']['sha256']
    assert not (project.root / 'exports' / output_name).exists()

    reopened = open_project(project.root)
    normal = RealProjectFlow(selected_root=reopened.root, selected_parent=tmp_path)
    try:
        normal.open_selected()
        normal.select_run(run_id)
        normal.select_export(export_id)
        publication = normal.resume()
        assert publication['selected_export_id'] == export_id
        assert publication['observation'] is None
        assert publication['exports'][0]['recorded_state'] == 'published'
        observed = normal.observe()
        assert observed['observation']['outcome'] == 'published_verified'
        assert observed['observation']['audited_success'] is True
        assert observed['source_retrieval_verified'] is False
        assert event_count(reopened, export_id) == 6
        normal.resume()
        assert event_count(reopened, export_id) == 6
    finally:
        normal.close()
    assert read_export_report(reopened, export_id).sha256 == original_report_sha
    assert partial.is_file() and partial.read_bytes() == partial_bytes
    assert (partial.stat().st_dev, partial.stat().st_ino) == partial_identity
    workbook = project.root / 'exports' / output_name
    with ZipFile(workbook) as archive:
        assert archive.testzip() is None and 'xl/workbook.xml' in archive.namelist()
    assert sha256(workbook.read_bytes()).hexdigest() == (
        observe_export_request(reopened, export_id).request.artifact_sha256)


def test_test_only_worker_death_is_not_a_browser_fault_action():
    app_source = inspect.getsource(run)
    driver = inspect.getsource(run_app)
    transport = inspect.getsource(transport_steps)
    assert "if args.scenario == 'worker_killed':" in app_source
    assert "application_worker.execute_command = pause_during_retained_stage" in app_source
    assert "data-testid=worker-recovery" in app_source
    assert "last_error['code'] == 'worker_interrupted'" in app_source
    assert "worker_death_not_reported" in transport
    assert "worker_parent_mismatch" in inspect.getsource(
        __import__('tools.gui_feasibility.run_real_project', fromlist=['terminate_marked_gui_worker'])
        .terminate_marked_gui_worker)
    assert "RESEARCHY_GUI_TEST_STAGE_MARKER" in driver
    assert "os.kill(pid, signal.SIGTERM)" in inspect.getsource(
        __import__('tools.gui_feasibility.run_real_project', fromlist=['terminate_marked_gui_worker'])
        .terminate_marked_gui_worker)
    assert 'directory' not in inspect.signature(RealProjectFlow.resume).parameters
    assert 'marker' not in inspect.signature(RealProjectFlow.resume).parameters


def test_empty_worker_pid_marker_is_retried_before_safe_termination(tmp_path, monkeypatch):
    import tools.gui_feasibility.run_real_project as runner

    marker = tmp_path / 'private-worker-stage-pid'
    owner_marker = tmp_path / 'private-gui-owner-pid'
    owner_marker.write_text('12345', encoding='ascii')
    marker.touch()  # O_EXCL creation has happened; os.write has NOT happened.
    encountered_empty = threading.Event()
    stopped = threading.Event()
    status = {'terminated': False, 'error': None}
    original_sleep = time.sleep
    killed = []

    def observe_pending_marker(delay):
        if marker.exists() and marker.stat().st_size == 0:
            encountered_empty.set()
        return original_sleep(delay)

    monkeypatch.setattr(runner.time, 'sleep', observe_pending_marker)
    monkeypatch.setattr(runner, '_worker_parent_is_gui',
                        lambda pid, parent: (pid, parent) == (54321, 12345))
    monkeypatch.setattr(runner.os, 'kill',
                        lambda pid, sig: killed.append((pid, sig)))
    fake_host = SimpleNamespace(pid=12345, poll=lambda: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(runner.terminate_marked_gui_worker,
                             fake_host, marker, owner_marker, stopped, status)
        try:
            assert encountered_empty.wait(timeout=3), (
                'monitor rejected O_EXCL marker before the PID was written')
            assert not result.done()
            marker.write_text('54321', encoding='ascii')
            result.result(timeout=3)
        finally:
            stopped.set()
    assert killed == [(54321, signal.SIGTERM)]
    assert status == {'terminated': True, 'error': None,
                      'phase': 'signal_sent', 'gui_owner_relation': 'direct'}


def test_unrelated_process_marker_is_rejected_without_killing(tmp_path, monkeypatch):
    import tools.gui_feasibility.run_real_project as runner

    marker = tmp_path / 'wrong-parent-pid'
    marker.write_text('54321', encoding='ascii')
    owner_marker = tmp_path / 'private-gui-owner-pid'
    owner_marker.write_text('12345', encoding='ascii')
    status = {'terminated': False, 'error': None}
    stopped = threading.Event()
    monkeypatch.setattr(runner, '_worker_parent_is_gui', lambda pid, parent: False)
    def forbidden_kill(*_):
        pytest.fail('test monitor attempted to kill a nonchild process')
    monkeypatch.setattr(runner.os, 'kill', forbidden_kill)
    runner.terminate_marked_gui_worker(
        SimpleNamespace(pid=12345, poll=lambda: None),
        marker, owner_marker, stopped, status)
    assert status == {'terminated': False, 'error': 'worker_parent_mismatch',
                      'phase': 'parentage_check', 'gui_owner_relation': 'direct'}


def test_gui_owner_marker_is_exclusive_and_identifies_real_python_process(tmp_path):
    marker = tmp_path / 'private-gui-owner-pid'
    publish_gui_owner_marker(marker)
    assert marker.read_text(encoding='ascii') == str(os.getpid())
    with pytest.raises(FileExistsError):
        publish_gui_owner_marker(marker)
    assert marker.read_text(encoding='ascii') == str(os.getpid())


def test_unrelated_gui_owner_cannot_authorise_termination(tmp_path, monkeypatch):
    import tools.gui_feasibility.run_real_project as runner

    marker = tmp_path / 'private-worker-stage-pid'
    owner_marker = tmp_path / 'private-gui-owner-pid'
    marker.write_text('54321', encoding='ascii')
    owner_marker.write_text('65432', encoding='ascii')
    stopped = threading.Event()
    status = {'terminated': False, 'error': None}
    monkeypatch.setattr(runner, '_gui_owner_matches_launcher',
                        lambda owner, launcher: False)
    def forbidden_parentage(*_):
        pytest.fail('worker parentage checked for unauthorised GUI host')
    monkeypatch.setattr(runner, '_worker_parent_is_gui', forbidden_parentage)
    monkeypatch.setattr(runner.os, 'kill',
                        lambda *_: pytest.fail('nonowned worker would have been killed'))
    runner.terminate_marked_gui_worker(
        SimpleNamespace(pid=12345, poll=lambda: None),
        marker, owner_marker, stopped, status)
    assert status == {'terminated': False, 'error': 'gui_owner_mismatch',
                      'phase': 'gui_owner_check'}


@pytest.mark.skipif(os.name != 'nt', reason='Windows venv Python redirector only')
def test_windows_verified_launcher_child_owner_not_arbitrary_descendant(monkeypatch):
    import tools.gui_feasibility.run_real_project as runner
    # On Windows, Python's venv launcher can start a base interpreter as its
    # immediate child. Require that exact one-hop relationship, not a grandchild
    # or any unrelated process. Direct launch must remain valid too.
    monkeypatch.setattr(runner, 'windows_process_table',
                        lambda: {220: 110, 330: 220, 440: 999})
    assert runner._gui_owner_matches_launcher(110, 110)
    assert runner._gui_owner_matches_launcher(220, 110)
    assert not runner._gui_owner_matches_launcher(330, 110)
    assert not runner._gui_owner_matches_launcher(440, 110)
    assert not runner._gui_owner_matches_launcher(-1, 110)


def test_integration_marker_must_match_live_child_before_consumption(tmp_path):
    marker = tmp_path / 'private-worker-pid'
    child = SimpleNamespace(pid=54321, is_alive=lambda: True)
    assert not _marker_matches_live_worker(marker, child)
    marker.touch()  # O_EXCL has returned but write has not started.
    assert not _marker_matches_live_worker(marker, child)
    marker.write_text('543', encoding='ascii')  # incomplete PID
    assert not _marker_matches_live_worker(marker, child)
    marker.write_text('54321', encoding='ascii')
    assert _marker_matches_live_worker(marker, child)
    assert not _marker_matches_live_worker(
        marker, SimpleNamespace(pid=54321, is_alive=lambda: False))
