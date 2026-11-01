"""Windows sharing-access regression; native behavior is not inferred from fakes."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

from research_y import export_files as files


class _Function:
    """Callable with ctypes declaration attributes, used only by contract tests."""
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


@pytest.fixture
def kernel(monkeypatch):
    state = SimpleNamespace(handle=123, attributes=0x10, info_ok=True)

    def info(handle, pointer):
        assert handle == state.handle
        pointer._obj.attributes = state.attributes
        return state.info_ok

    api = SimpleNamespace(
        CreateFileW=_Function(lambda *args: state.handle),
        GetFileInformationByHandle=_Function(info),
        CloseHandle=_Function(lambda handle: True),
    )

    def load(name, *, use_last_error):
        assert name == 'kernel32' and use_last_error is True
        return api

    # Linux can check call arguments/lifetimes, not native Windows lock behavior.
    monkeypatch.setattr(ctypes, 'WinDLL', load, raising=False)
    return state, api


def test_directory_handle_requests_sharing_participating_read_access(kernel):
    _, api = kernel
    path = Path('synthetic-directory')
    with files._windows_directory(path):
        call, = api.CreateFileW.calls
        assert call == (str(path), 0x0001, 3, None, 3, 0x02200000, None)
        assert api.CloseHandle.calls == []
    assert api.CloseHandle.calls == [(123,)]


@pytest.mark.parametrize('error', [RuntimeError, KeyboardInterrupt], ids=['error', 'interruption'])
def test_directory_handle_closes_when_guarded_body_raises(kernel, error):
    _, api = kernel
    with pytest.raises(error):
        with files._windows_directory(Path('synthetic-directory')):
            raise error('synthetic body failure')
    assert api.CloseHandle.calls == [(123,)]


@pytest.mark.parametrize('attributes,info_ok', [(0x410, True), (0x80, True), (0x10, False)],
                         ids=['reparse', 'not-directory', 'inspection-failure'])
def test_unverified_handle_is_closed_without_entering_body(kernel, attributes, info_ok):
    state, api = kernel
    state.attributes, state.info_ok = attributes, info_ok
    entered = []
    with pytest.raises(files.ExportFileError):
        with files._windows_directory(Path('synthetic-directory')):
            entered.append(True)
    assert entered == []
    assert api.CloseHandle.calls == [(123,)]


def test_denied_directory_read_never_retries_with_zero_access(kernel):
    state, api = kernel
    state.handle = wintypes.HANDLE(-1).value
    with pytest.raises(OSError, match='cannot be locked'):
        with files._windows_directory(Path('synthetic-directory')):
            pytest.fail('Failed open entered the guard')
    assert len(api.CreateFileW.calls) == 1
    assert api.CreateFileW.calls[0][1] == 0x0001
    assert api.GetFileInformationByHandle.calls == []
    assert api.CloseHandle.calls == []


@pytest.mark.skipif(os.name != 'nt', reason='Requires native Windows sharing checks')
@pytest.mark.parametrize('target', ['leaf', 'ancestor'])
def test_native_windows_blocks_rename_from_another_process_then_releases(tmp_path, target):
    parent = tmp_path / 'parent'
    leaf = parent / 'leaf'
    leaf.mkdir(parents=True)
    source = leaf if target == 'leaf' else parent
    destination = source.with_name(source.name + '-moved')
    script = (
        'import os, sys\n'
        'try:\n'
        '    os.rename(sys.argv[1], sys.argv[2])\n'
        'except OSError as error:\n'
        '    print(error.winerror)\n'
        'else:\n'
        '    sys.exit(7)\n'
    )
    with files.Directory(leaf):
        result = subprocess.run([sys.executable, '-c', script, str(source), str(destination)],
                                capture_output=True, text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == '32'  # ERROR_SHARING_VIOLATION, not an unrelated error.
        assert source.is_dir() and not destination.exists()
    source.rename(destination)
    assert destination.is_dir() and not source.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Requires native Windows sharing checks')
def test_native_windows_blocks_empty_directory_deletion_then_releases(tmp_path):
    directory = tmp_path / 'empty'
    directory.mkdir()
    with files.Directory(directory):
        with pytest.raises(OSError) as caught:
            directory.rmdir()
        assert caught.value.winerror == 32
        assert directory.is_dir()
    directory.rmdir()
    assert not directory.exists()


@pytest.mark.skipif(os.name != 'nt', reason='Requires native Windows handle lifetimes')
@pytest.mark.parametrize('error', [RuntimeError, KeyboardInterrupt], ids=['error', 'interruption'])
def test_native_windows_releases_all_ancestors_after_body_exception(tmp_path, error):
    parent = tmp_path / 'parent'
    leaf = parent / 'leaf'
    leaf.mkdir(parents=True)
    with pytest.raises(error):
        with files.Directory(leaf):
            raise error('synthetic body failure')
    leaf.rename(parent / 'new-leaf')
    parent.rename(tmp_path / 'new-parent')
    assert (tmp_path / 'new-parent' / 'new-leaf').is_dir()


@pytest.mark.skipif(os.name != 'nt', reason='Requires native Windows handle lifetimes')
def test_native_windows_failed_descendant_open_releases_ancestor_handles(tmp_path, monkeypatch):
    parent = tmp_path / 'parent'
    leaf = parent / 'leaf'
    leaf.mkdir(parents=True)
    real_guard = files._windows_directory

    @contextmanager
    def denied_child(path):
        if path == leaf:
            raise OSError('synthetic denied directory')
        with real_guard(path):
            yield

    monkeypatch.setattr(files, '_windows_directory', denied_child)
    with pytest.raises(OSError, match='synthetic denied directory'):
        with files.Directory(leaf):
            pytest.fail('Failed descendant open entered the directory')
    parent.rename(tmp_path / 'moved-parent')
    assert (tmp_path / 'moved-parent' / 'leaf').is_dir()
