"""Trusted native folder-selection contract and genuine project integration.

The pywebview dialog is represented by a fake async window in core tests.
Actual Windows dialog selection by a human remains a separate acceptance gate;
the native lifecycle probe confirms only that the controls are rendered.
"""
import asyncio
import inspect
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from research_y.projects import create_project, open_project
from tools.gui_feasibility.native_folder_selection import (
    NativeFolderError, checked_folder, select_from_native_window,
)
from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.real_project_app import run
from tools.gui_feasibility.run_real_project import fixture


@pytest.mark.parametrize('result', [None, [], ()])
def test_cancelled_native_selection_never_becomes_a_path(result):
    assert checked_folder(result) is None


@pytest.mark.parametrize('result', [
    'C:/fake', 17, [None], [Path('/tmp')], ['/tmp/one', '/tmp/two'],
    ['relative/path'], ['../outside'], ['/tmp/../outside'],
    ['http://127.0.0.1/project'], ['/tmp/bad\x00folder'],
])
def test_invalid_browser_like_or_ambiguous_dialog_results_fail_closed(result):
    with pytest.raises(NativeFolderError, match='^native_selection_invalid$'):
        checked_folder(result)


def test_missing_or_non_directory_native_choices_fail_without_echoing_path(tmp_path):
    missing = tmp_path / 'SENSITIVE-MISSING-PROJECT'
    document = tmp_path / 'sensitive.txt'
    document.write_text('not a project')
    for candidate in (missing, document):
        with pytest.raises(NativeFolderError, match='^native_selection_unsafe$') as exc:
            checked_folder((str(candidate),))
        assert 'SENSITIVE' not in str(exc.value)
        assert str(tmp_path) not in str(exc.value)


def test_symlink_or_junction_escape_rejected_even_when_target_exists(tmp_path):
    actual = tmp_path / 'actual-parent'
    actual.mkdir()
    linked = tmp_path / 'linked'
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(linked), str(actual)],
                       check=True, capture_output=True)
    else:
        linked.symlink_to(actual, target_is_directory=True)
    try:
        with pytest.raises(NativeFolderError, match='^native_selection_unsafe$'):
            checked_folder((str(linked),))
    finally:
        if os.name == 'nt':
            os.rmdir(linked)
        else:
            linked.unlink()


def test_native_dialog_is_async_os_only_and_provides_single_checked_folder(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setitem(sys.modules, 'webview',
                        SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=42)))

    class FakeWindow:
        async def create_file_dialog(self, **kwargs):
            seen.update(kwargs)
            return (str(tmp_path),)

    assert asyncio.run(select_from_native_window(FakeWindow())) == tmp_path
    assert seen == {'dialog_type': 42, 'allow_multiple': False}


def test_native_dialog_cancel_and_error_do_not_disclose_exception(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'webview',
                        SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=7)))

    class CancelWindow:
        async def create_file_dialog(self, **kwargs):
            return None

    class FailingWindow:
        async def create_file_dialog(self, **kwargs):
            raise RuntimeError('private path /SENSITIVE/ should not be echoed')

    assert asyncio.run(select_from_native_window(CancelWindow())) is None
    with pytest.raises(NativeFolderError, match='^native_dialog_unavailable$') as exc:
        asyncio.run(select_from_native_window(FailingWindow()))
    assert 'SENSITIVE' not in str(exc.value)


def test_host_only_picker_opens_real_projects_with_correct_identity(tmp_path):
    first = create_project(tmp_path, 'First')
    second = create_project(tmp_path, 'Second')
    flow = RealProjectFlow(selected_root=first.root, selected_parent=tmp_path)
    try:
        assert flow.open_selected()['project']['project_id'] == str(first.identifier)
        chosen = flow.open_native_folder(second.root)
        assert chosen['project']['project_id'] == str(second.identifier)
        assert chosen['selected_run_id'] is None
        assert chosen['selected_export_id'] is None
        assert open_project(chosen['project']['location']).identifier == second.identifier
        with pytest.raises(ProjectFlowError, match='^native_selection_unsafe$'):
            flow.open_native_folder(tmp_path / 'missing')
        assert flow.state()['project']['project_id'] == str(second.identifier)
    finally:
        flow.close()


def test_host_native_parent_creation_respects_exclusive_project_paths(tmp_path):
    selected = tmp_path / 'selected-parent'
    selected.mkdir()
    flow = RealProjectFlow(selected_root=tmp_path / 'missing', selected_parent=tmp_path)
    name = '<img src=x onerror="alert(1)">'
    try:
        state = flow.create_native_parent(selected, name)
        assert state['project']['name'] == name
        location = Path(state['project']['location'])
        assert location.parent == selected
        assert str(open_project(location).identifier) == state['project']['project_id']
        with pytest.raises(ProjectFlowError, match='^project_creation_failed$'):
            flow.create_native_parent(selected, name)
        assert flow.state()['project']['name'] == name
        assert len([x for x in selected.iterdir() if x.is_dir()]) == 1
    finally:
        flow.close()


def test_old_launcher_contracts_remain_compatible(tmp_path):
    flow = RealProjectFlow(selected_root=tmp_path / 'missing', selected_parent=tmp_path)
    try:
        with pytest.raises(ProjectFlowError, match='^invalid_project$'):
            flow.open_selected()
        created = flow.create_selected('Valid')
        assert created['project']['name'] == 'Valid'
    finally:
        flow.close()
    manifest = Path(created['project']['location']) / 'project.ryproj'
    old_launcher = RealProjectFlow(selected_root=manifest, selected_parent=tmp_path)
    try:
        assert old_launcher.open_selected()['project']['project_id'] == (
            created['project']['project_id'])
    finally:
        old_launcher.close()


def test_failed_native_open_inspection_keeps_active_run_and_export(tmp_path, monkeypatch):
    original_project, run_id = fixture(tmp_path)
    other = create_project(tmp_path, 'Another research project')
    flow = RealProjectFlow(selected_root=original_project.root, selected_parent=tmp_path)
    try:
        flow.open_selected()
        flow.select_run(run_id)
        original_export_id = flow.prepare()['selected_export_id']
        before = flow.state()
        original_operation = flow._operation_for_project

        def fail_only_other(project, operation, **kwargs):
            if project.identifier == other.identifier and operation == 'inspect':
                raise ProjectFlowError('worker_interrupted')
            return original_operation(project, operation, **kwargs)

        monkeypatch.setattr(flow, '_operation_for_project', fail_only_other)
        with pytest.raises(ProjectFlowError, match='^worker_interrupted$'):
            flow.open_native_folder(other.root)

        after = flow.state()
        assert after == before
        assert flow.project.identifier == original_project.identifier
        assert flow._root == original_project.root
        assert after['selected_run_id'] == run_id
        assert after['selected_export_id'] == original_export_id
        observed = flow.observe()
        assert observed['observation']['audited_success'] is False
        assert observed['selected_export_id'] == original_export_id
    finally:
        flow.close()


def test_failed_native_create_inspection_preserves_active_project_and_new_folder(
        tmp_path, monkeypatch):
    original_project, run_id = fixture(tmp_path)
    parent = tmp_path / 'separate-create-parent'
    parent.mkdir()
    flow = RealProjectFlow(selected_root=original_project.root, selected_parent=tmp_path)
    try:
        flow.open_selected()
        flow.select_run(run_id)
        original_export_id = flow.prepare()['selected_export_id']
        before = flow.state()
        original_operation = flow._operation_for_project

        def fail_only_created(project, operation, **kwargs):
            if project.root.parent == parent and operation == 'inspect':
                raise ProjectFlowError('worker_interrupted')
            return original_operation(project, operation, **kwargs)

        monkeypatch.setattr(flow, '_operation_for_project', fail_only_created)
        with pytest.raises(ProjectFlowError, match='^worker_interrupted$'):
            flow.create_native_parent(parent, 'New candidate')

        # Creation has already committed; do not silently destroy it or
        # pretend the active session was switched to the uninspectable project.
        created = list(parent.iterdir())
        assert len(created) == 1
        assert open_project(created[0]).name == 'New candidate'
        assert flow.state() == before
        assert flow.project.identifier == original_project.identifier
        assert flow._root == original_project.root
        assert flow._parent == tmp_path
        assert flow.state()['selected_export_id'] == original_export_id
        assert flow.observe()['selected_run_id'] == run_id
    finally:
        flow.close()


def test_malformed_candidate_inspection_cannot_switch_project(tmp_path, monkeypatch):
    original_project = create_project(tmp_path, 'Good project')
    other = create_project(tmp_path, 'Bad projection')
    flow = RealProjectFlow(selected_root=original_project.root, selected_parent=tmp_path)
    try:
        flow.open_selected()
        before = flow.state()
        original_operation = flow._operation_for_project

        def bad_read_model(project, operation, **kwargs):
            if project.identifier == other.identifier and operation == 'inspect':
                return {'snapshot': {'runs': 'not-a-list', 'exports': []}}
            return original_operation(project, operation, **kwargs)

        monkeypatch.setattr(flow, '_operation_for_project', bad_read_model)
        with pytest.raises(ProjectFlowError, match='^invalid_worker_result$'):
            flow.open_native_folder(other.root)
        assert flow.state() == before
        assert flow.project.identifier == original_project.identifier
    finally:
        flow.close()


def test_native_buttons_are_host_owned_not_client_supplied_paths():
    code = inspect.getsource(run)
    chooser = inspect.getsource(select_from_native_window)
    assert "name in ('native_open', 'native_create')" in code
    assert "selected = await select_from_native_window(app.native.main_window)" in code
    assert "await asyncio.to_thread(flow.open_native_folder, selected)" in code
    assert "await asyncio.to_thread(flow.create_native_parent," in code
    assert 'data-testid=native-open-folder' in code
    assert 'data-testid=native-create-folder' in code
    assert 'create_file_dialog' not in code
    assert 'window.create_file_dialog(' in chooser
    assert 'allow_multiple=False' in chooser
    assert 'webview.FileDialog.FOLDER' in chooser
    assert 'directory' not in inspect.signature(RealProjectFlow.observe).parameters
