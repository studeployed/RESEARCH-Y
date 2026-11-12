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

from research_y.projects import create_project
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
        new_project = create_project(tmp_path, 'Next project')
        switched = flow.open_native_folder(new_project.root)
        assert switched['selected_run_id'] is None
        assert switched['external_destination_confirmed'] is False
        assert switched['external_destination_candidate'] is None
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
        with pytest.raises(ProjectFlowError, match='^native_selection_unsafe$'):
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
    from desktop_source import project_ui_source
    source = project_ui_source()
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


def test_changed_external_directory_between_selection_and_confirmation_fails_closed(tmp_path):
    project, run_id = fixture(tmp_path)
    original = tmp_path / 'external-target'
    original.mkdir()
    moved = tmp_path / 'moved-target'
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        flow.offer_external_directory(original)
        original.rename(moved)
        original.mkdir()
        with pytest.raises(ProjectFlowError, match='^external_destination_changed$'):
            flow.confirm_external_directory()
        assert flow.state()['external_destination_confirmed'] is False
        assert flow.state()['exports'] == []
        flow.offer_external_directory(original)
        flow.confirm_external_directory()
        original.rename(tmp_path / 'changed-after-confirm')
        original.mkdir()
        with pytest.raises(ProjectFlowError, match='^external_destination_changed$'):
            flow.prepare()
        assert flow.state()['exports'] == [] and flow.selected_export_id is None
    finally:
        flow.close()


def test_verified_success_is_invalidated_on_every_external_destination_change(tmp_path):
    project, run_id = fixture(tmp_path)
    correct = tmp_path / 'verified-output'
    alternate = tmp_path / 'alternate-output'
    correct.mkdir(); alternate.mkdir()
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        flow.offer_external_directory(correct)
        flow.confirm_external_directory()
        flow.prepare(); flow.resume()
        assert flow.observe()['observation']['audited_success'] is True
        offered = flow.offer_external_directory(alternate)
        assert offered['observation'] is None
        assert offered['external_destination_confirmed'] is False
        assert flow.confirm_external_directory()['observation'] is None
        # The saved journal still points to the original filesystem identity.
        observed = flow.observe()['observation']
        assert observed['audited_success'] is False
        assert observed['outcome'] != 'published_verified'
        assert flow.clear_external_directory()['observation'] is None
        flow.offer_external_directory(correct)
        flow.confirm_external_directory()
        assert flow.state()['observation'] is None
        assert flow.observe()['observation']['outcome'] == 'published_verified'
        assert flow.clear_external_directory()['observation'] is None
    finally:
        flow.close()


def test_swapped_directory_after_host_validation_is_refused_by_worker(tmp_path, monkeypatch):
    """The race can occur after host validation, just before child execution."""
    project, run_id = fixture(tmp_path)
    selected = tmp_path / 'selected-for-export'
    selected.mkdir()
    moved = tmp_path / 'original-folder'
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        flow.offer_external_directory(selected)
        flow.confirm_external_directory()
        confirmed = flow._external_confirmed_identity
        assert confirmed is not None
        original_operation = flow._operation
        swapped = False

        def swap_before_worker(name, **kw):
            nonlocal swapped
            if name == 'prepare_export' and not swapped:
                assert kw['directory'] == str(selected)
                assert kw['expected_directory_identity'] == confirmed
                # This happens AFTER _export_directory verified the
                # original identity, but BEFORE the worker opens it.
                selected.rename(moved)
                selected.mkdir()
                (selected / 'attacker-existing.txt').write_text('keep unchanged')
                swapped = True
            return original_operation(name, **kw)

        monkeypatch.setattr(flow, '_operation', swap_before_worker)
        with pytest.raises(ProjectFlowError, match='^directory_changed$'):
            flow.prepare()
        assert swapped
        assert flow.state()['exports'] == []
        assert flow.state()['selected_export_id'] is None
        assert (selected / 'attacker-existing.txt').read_text() == 'keep unchanged'
        assert list(selected.glob('*.xlsx')) == []
        with sqlite3.connect(project.database_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE event_type LIKE 'workbook_export_v1:%'").fetchone()[0] == 0
    finally:
        flow.close()


@pytest.mark.parametrize('external', [False, True])
def test_inspection_failure_after_committed_receipt_can_retry_same_id(tmp_path, monkeypatch, external):
    """A stale inventory must not strand the old ID or silently mint another."""
    project, run_id = fixture(tmp_path)
    outside = tmp_path / 'trusted-output'
    outside.mkdir()
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        if external:
            flow.offer_external_directory(outside)
            flow.confirm_external_directory()
        original_operation = flow._operation
        failed_once = False
        captured_id = None

        def fail_inspection_after_prepare(name, **kw):
            nonlocal failed_once, captured_id
            if name == 'inspect' and captured_id and not failed_once:
                failed_once = True
                raise ProjectFlowError('worker_unavailable')
            result = original_operation(name, **kw)
            if name == 'prepare_export':
                captured_id = kw['export_id']
            return result

        monkeypatch.setattr(flow, '_operation', fail_inspection_after_prepare)
        with pytest.raises(ProjectFlowError, match='^worker_unavailable$'):
            flow.prepare()
        assert failed_once and captured_id == flow.selected_export_id
        assert flow.state()['export_reconciliation_required'] is True
        assert flow.state()['exports'] == []
        with sqlite3.connect(project.database_path) as db:
            count_before = db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                ('workbook_export_v1:' + captured_id,)).fetchone()[0]
        assert count_before == 1
        recovered = flow.prepare()
        assert recovered['selected_export_id'] == captured_id
        assert recovered['export_reconciliation_required'] is False
        assert len(recovered['exports']) == 1
        with sqlite3.connect(project.database_path) as db:
            count_after = db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type=?",
                ('workbook_export_v1:' + captured_id,)).fetchone()[0]
        assert count_after == count_before
        flow.resume()
        verified = flow.observe()['observation']
        assert verified['outcome'] == 'published_verified'
        assert verified['audited_success'] is True
        dest = outside if external else project.root / 'exports'
        assert (dest / ('strategy-summary-' + run_id + '.xlsx')).exists()
    finally:
        flow.close()


def test_failed_inventory_reinspection_retains_same_prepared_uuid(tmp_path, monkeypatch):
    project, run_id = fixture(tmp_path)
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        original_operation = flow._operation
        unavailable = False
        committed_id = None

        def intermittent_inspect(name, **kw):
            nonlocal unavailable, committed_id
            if name == 'inspect' and unavailable:
                raise ProjectFlowError('worker_unavailable')
            result = original_operation(name, **kw)
            if name == 'prepare_export' and committed_id is None:
                committed_id = kw['export_id']
                unavailable = True
            return result

        monkeypatch.setattr(flow, '_operation', intermittent_inspect)
        with pytest.raises(ProjectFlowError, match='^worker_unavailable$'):
            flow.prepare()
        assert flow.selected_export_id == committed_id
        for _ in range(2):
            with pytest.raises(ProjectFlowError, match='^export_reconciliation_required$'):
                flow.prepare()
            assert flow.selected_export_id == committed_id
            assert flow.state()['export_reconciliation_required']
        unavailable = False
        assert flow.prepare()['selected_export_id'] == committed_id
        assert len(flow.state()['exports']) == 1
    finally:
        flow.close()


def test_pending_export_reconciles_before_stale_external_folder_is_checked(tmp_path, monkeypatch):
    """A lost response and failed initial inspect must not strand an export."""
    project, run_id = fixture(tmp_path)
    selected = tmp_path / 'original-output'
    selected.mkdir()
    moved = tmp_path / 'moved-output'
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        flow.offer_external_directory(selected)
        flow.confirm_external_directory()
        original_operation = flow._operation
        failed_receipt_reply = False
        block_inspection = False
        export_id = None

        def fail_after_receipt(name, **kwargs):
            nonlocal failed_receipt_reply, block_inspection, export_id
            if name == 'inspect' and block_inspection:
                raise ProjectFlowError('worker_unavailable')
            result = original_operation(name, **kwargs)
            if name == 'prepare_export' and not failed_receipt_reply:
                failed_receipt_reply = True
                block_inspection = True
                export_id = kwargs['export_id']
                raise ProjectFlowError('worker_interrupted')
            return result

        monkeypatch.setattr(flow, '_operation', fail_after_receipt)
        with pytest.raises(ProjectFlowError, match='^worker_interrupted$'):
            flow.prepare()
        assert failed_receipt_reply and export_id
        assert flow._pending_export_id == export_id
        assert flow.selected_export_id is None
        assert flow.state()['export_reconciliation_required'] is True

        # The original filesystem path disappears during the inspection outage.
        selected.rename(moved)
        selected.mkdir()
        block_inspection = False
        # Reinspection must succeed first, even though the folder validation
        # must now fail. The original ID becomes selected; clearing the stale
        # location and choosing its actual relocated identity is permitted.
        with pytest.raises(ProjectFlowError, match='^external_destination_changed$'):
            flow.prepare()
        assert flow._pending_export_id is None
        assert flow.selected_export_id == export_id
        assert flow.state()['exports'][0]['export_id'] == export_id
        assert flow.state()['export_reconciliation_required'] is False
        flow.clear_external_directory()
        flow.offer_external_directory(moved)
        flow.confirm_external_directory()
        assert flow.prepare()['selected_export_id'] == export_id
        flow.resume()
        assert flow.observe()['observation']['outcome'] == 'published_verified'
        assert (moved / ('strategy-summary-' + run_id + '.xlsx')).is_file()
        assert list(selected.iterdir()) == []
        with sqlite3.connect(project.database_path) as db:
            events = db.execute(
                'SELECT COUNT(*) FROM audit_events WHERE event_type=?',
                ('workbook_export_v1:' + export_id,)).fetchone()[0]
        assert events == 5  # prepared, staging, staged, publishing, published
        assert len(flow.state()['exports']) == 1
    finally:
        flow.close()


def test_pending_without_receipt_keeps_same_uuid_when_new_folder_selected(tmp_path, monkeypatch):
    """Only verified no-receipt permits a new folder, never a new request ID."""
    project, run_id = fixture(tmp_path)
    original = tmp_path / 'first-folder'
    original.mkdir()
    old_moved = tmp_path / 'old-folder-moved'
    flow = _flow(tmp_path, project)
    try:
        flow.open_selected(); flow.select_run(run_id)
        flow.offer_external_directory(original)
        flow.confirm_external_directory()
        operation = flow._operation
        first_failure = True
        inspection_unavailable = False
        pending = None

        def lost_before_receipt(name, **kwargs):
            nonlocal first_failure, inspection_unavailable, pending
            if name == 'prepare_export' and first_failure:
                pending = kwargs['export_id']
                first_failure = False
                inspection_unavailable = True
                raise ProjectFlowError('worker_interrupted')
            if name == 'inspect' and inspection_unavailable:
                raise ProjectFlowError('worker_unavailable')
            return operation(name, **kwargs)

        monkeypatch.setattr(flow, '_operation', lost_before_receipt)
        with pytest.raises(ProjectFlowError, match='^worker_interrupted$'):
            flow.prepare()
        assert pending == flow._pending_export_id
        assert flow.selected_export_id is None
        with sqlite3.connect(project.database_path) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE event_type LIKE 'workbook_export_v1:%'").fetchone()[0] == 0

        original.rename(old_moved)
        original.mkdir()
        inspection_unavailable = False
        with pytest.raises(ProjectFlowError, match='^external_destination_changed$'):
            flow.prepare()
        assert flow._pending_export_id == pending
        assert flow.selected_export_id is None

        # Explicit folder change is permitted only after reinspection has
        # established no existing receipt for the same tentative UUID.
        flow.clear_external_directory()
        assert flow._pending_export_id == pending
        flow.offer_external_directory(original)
        flow.confirm_external_directory()
        prepared = flow.prepare()
        assert prepared['selected_export_id'] == pending
        assert len(prepared['exports']) == 1
        flow.resume()
        assert flow.observe()['observation']['outcome'] == 'published_verified'
        output_name = 'strategy-summary-' + run_id + '.xlsx'
        assert (original / output_name).is_file()
        assert not (old_moved / output_name).exists()
    finally:
        flow.close()
