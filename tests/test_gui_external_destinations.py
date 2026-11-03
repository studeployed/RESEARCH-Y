"""Host-confirmed external workbook destinations in the isolated GUI.

All source/query data are synthetic. These tests exercise the real project,
worker, immutable report and append-only workbook export services without a
browser-supplied path or optional graphical dependency.
"""
from pathlib import Path
import os
import sqlite3
import subprocess
from zipfile import ZipFile

import pytest

from tools.gui_feasibility.real_project_flow import RealProjectFlow, ProjectFlowError
from tools.gui_feasibility.run_real_project import fixture


def _flow(tmp_path, project):
    return RealProjectFlow(selected_root=project.root, selected_parent=tmp_path)


def test_external_save_requires_two_explicit_host_steps_and_keeps_original_journal(tmp_path):
    project, run_id = fixture(tmp_path)
    outside = tmp_path / 'trusted-external'
    outside.mkdir()
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected()
        flow.select_run(run_id)
        with pytest.raises(ProjectFlowError, match='^external_destination_not_selected$'):
            flow.confirm_external_directory()
        offered = flow.offer_external_directory(outside)
        assert offered['external_destination_candidate'] == str(outside)
        assert offered['external_destination_confirmed'] is False
        with pytest.raises(ProjectFlowError, match='^external_destination_confirmation_required$'):
            flow.prepare()
        assert flow.state()['exports'] == [] and flow.selected_export_id is None
        confirmed = flow.confirm_external_directory()
        assert confirmed['external_destination_candidate'] is None
        assert confirmed['external_destination_confirmed'] is True
        assert confirmed['external_destination_location'] == str(outside)
        prepared = flow.prepare()
        export_id = prepared['selected_export_id']
        assert prepared['exports'][0]['destination_kind'] == 'external'
        assert prepared['exports'][0]['recorded_state'] == 'prepared'
        assert flow.prepare()['selected_export_id'] == export_id
        assert not prepared['exports'][0]['audited_success']
        flow.resume()
        verified = flow.observe()
        assert verified['observation']['outcome'] == 'published_verified'
        assert verified['observation']['audited_success'] is True
        assert verified['source_retrieval_verified'] is False
        filename = 'strategy-summary-' + run_id + '.xlsx'
        assert not (project.root / 'exports' / filename).exists()
        with ZipFile(outside / filename) as workbook:
            assert workbook.testzip() is None and 'xl/workbook.xml' in workbook.namelist()
        with sqlite3.connect(project.database_path) as db:
            entries = [x[0] for x in db.execute(
                "SELECT details_json FROM audit_events WHERE event_type=?",
                ('workbook_export_v1:' + export_id,))]
        assert entries and all(str(outside) not in entry for entry in entries)
    finally:
        flow.close()


def test_restarted_external_request_requires_new_confirmation_and_never_retargets(tmp_path):
    project, run_id = fixture(tmp_path)
    correct = tmp_path / 'correct-external'
    wrong = tmp_path / 'wrong-external'
    correct.mkdir(); wrong.mkdir()
    first = _flow(tmp_path, project)
    try:
        first.open_selected(); first.select_run(run_id)
        first.offer_external_directory(correct)
        first.confirm_external_directory()
        export_id = first.prepare()['selected_export_id']
        first.resume()
        assert first.observe()['observation']['audited_success'] is True
    finally:
        first.close()
    filename = 'strategy-summary-' + run_id + '.xlsx'
    second = _flow(tmp_path, project)
    try:
        second.open_selected(); second.select_run(run_id)
        second.select_export(export_id)
        assert second.state()['external_destination_confirmed'] is False
        unknown = second.observe()['observation']
        assert unknown['outcome'] == 'destination_confirmation_required'
        assert unknown['audited_success'] is False
        with pytest.raises(ProjectFlowError, match='^external_destination_confirmation_required$'):
            second.resume()
        with pytest.raises(ProjectFlowError, match='^external_destination_confirmation_required$'):
            second.prepare()
        second.offer_external_directory(wrong)
        second.confirm_external_directory()
        with pytest.raises(ProjectFlowError, match='^directory_changed$'):
            second.resume()
        assert not (wrong / filename).exists()
        second.offer_external_directory(correct)
        second.confirm_external_directory()
        assert second.resume()['selected_export_id'] == export_id
        observed = second.observe()
        assert observed['observation']['outcome'] == 'published_verified'
        assert len(observed['exports']) == 1
        assert (correct / filename).exists()
    finally:
        second.close()


def test_external_selection_must_not_leak_across_run_or_project_or_local_export(tmp_path):
    project, run_id = fixture(tmp_path)
    other = tmp_path / 'external'
    other.mkdir()
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected()
        with pytest.raises(ProjectFlowError, match='^run_selection_required$'):
            flow.offer_external_directory(other)
        flow.select_run(run_id)
        flow.offer_external_directory(other)
        flow.select_run(run_id)
        assert flow.state()['external_destination_candidate'] is None
        flow.offer_external_directory(other)
        flow.confirm_external_directory()
        flow.clear_external_directory()
        assert flow.state()['external_destination_confirmed'] is False
        local_id = flow.prepare()['selected_export_id']
        assert flow.state()['exports'][0]['destination_kind'] == 'project_exports'
        with pytest.raises(ProjectFlowError, match='^external_destination_not_applicable$'):
            flow.offer_external_directory(other)
        flow.select_export(local_id)
        assert flow.state()['external_destination_confirmed'] is False
        flow.resume()
        assert flow.observe()['observation']['outcome'] == 'published_verified'
    finally:
        flow.close()


def test_host_picker_refuses_browser_paths_project_internals_and_unsafe_links(tmp_path):
    project, run_id = fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    linked = tmp_path / 'linked'
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        with pytest.raises(ProjectFlowError, match='^native_selection_invalid$'):
            flow.offer_external_directory(str(outside))
        with pytest.raises(ProjectFlowError, match='^external_destination_invalid$'):
            flow.offer_external_directory(project.root / 'exports')
        with pytest.raises(ProjectFlowError, match='^native_selection_unsafe$'):
            flow.offer_external_directory(tmp_path / 'missing')
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(linked), str(outside)],
                           check=True, capture_output=True)
        else:
            linked.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ProjectFlowError, match='^native_selection_unsafe


def test_external_confirmation_is_not_a_browser_path_endpoint():
    import inspect
    from tools.gui_feasibility.real_project_app import run
    source = inspect.getsource(run)
    assert "name == 'native_export'" in source
    assert "await select_from_native_window(app.native.main_window)" in source
    assert "flow.offer_external_directory, selected" in source
    assert "name == 'external_confirm'" in source
    assert "flow.confirm_external_directory()" in source
    assert 'create_file_dialog' not in source
    assert 'flow.offer_external_directory(value)' not in source
    assert 'flow.offer_external_directory, value' not in source
    assert 'data-testid=native-export-folder' in source
    assert 'data-testid=external-reconfirm' in source
):
            flow.offer_external_directory(linked)
        assert flow.state()['external_destination_confirmed'] is False
        assert flow.state()['exports'] == []
    finally:
        flow.close()
        if linked.is_symlink() or (os.name == 'nt' and linked.exists()):
            if os.name == 'nt':
                os.rmdir(linked)
            else:
                linked.unlink()


def test_external_confirmation_is_not_a_browser_path_endpoint():
    import inspect
    from tools.gui_feasibility.real_project_app import run
    source = inspect.getsource(run)
    assert "name == 'native_export'" in source
    assert "await select_from_native_window(app.native.main_window)" in source
    assert "flow.offer_external_directory, selected" in source
    assert "name == 'external_confirm'" in source
    assert "flow.confirm_external_directory()" in source
    assert 'create_file_dialog' not in source
    assert "'native_export', 'external_confirm'" not in source  # no browser paths
    assert 'data-testid=native-export-folder' in source
    assert 'data-testid=external-reconfirm' in source
