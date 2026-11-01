"""Actual filesystem operations, not a mocked no-overwrite implementation."""
from hashlib import sha256
import os
from pathlib import Path
import subprocess

import pytest
from research_y import export_files as files


@pytest.mark.parametrize('name', ['', '.', '..', '../x.xlsx', '/x.xlsx', r'a\b.xlsx', 'C:x.xlsx',
    'CON.xlsx', 'LPT1.xlsx', 'nul.xlsx', 'a.xlsx ', 'a.xlsx.', 'a\0.xlsx', 'x.xls', '.hidden.xlsx'])
def test_invalid_workbook_names_refused(name):
    with pytest.raises(files.ExportFileError):
        files.filename(name, workbook=True)


def test_exclusive_write_link_and_independent_file(tmp_path):
    data = b'protocol file contents'
    with files.Directory(tmp_path) as d:
        d.write_new('stage.part', data)
        assert d.read('stage.part', digest=sha256(data).hexdigest(), size=len(data)) == data
        d.flush('stage.part')
        d.publish_link('stage.part', 'report.xlsx')
        assert d.same_file('stage.part', 'report.xlsx')
        with pytest.raises(FileExistsError):
            d.write_new('stage.part', b'changed')
        with pytest.raises(FileExistsError):
            d.publish_link('stage.part', 'report.xlsx')
    assert (tmp_path / 'report.xlsx').read_bytes() == data


def test_short_writes_are_completed(tmp_path, monkeypatch):
    original = os.write
    monkeypatch.setattr(files.os, 'write', lambda fd, data: original(fd, data[:3]))
    with files.Directory(tmp_path) as d:
        d.write_new('stage.part', b'0123456789')
    assert (tmp_path / 'stage.part').read_bytes() == b'0123456789'


def test_zero_write_preserves_partial_without_final_file(tmp_path, monkeypatch):
    monkeypatch.setattr(files.os, 'write', lambda *_: 0)
    with files.Directory(tmp_path) as d, pytest.raises(OSError):
        d.write_new('stage.part', b'data')
    assert not (tmp_path / 'report.xlsx').exists()


@pytest.mark.parametrize('damage', ['size', 'checksum', 'directory'])
def test_read_refuses_damaged_or_nonordinary_files(tmp_path, damage):
    path = tmp_path / 'stage.part'
    if damage == 'directory':
        path.mkdir()
    else:
        path.write_bytes(b'abcdef')
    with files.Directory(tmp_path) as d, pytest.raises(files.ExportFileError):
        d.read('stage.part', digest=sha256(b'abcdef' if damage != 'checksum' else b'xxxxxx').hexdigest(),
               size=5 if damage == 'size' else 6)


def test_unsupported_hardlinks_do_not_fall_back_to_replace(tmp_path, monkeypatch):
    def unsupported(*a, **kw):
        raise OSError('not supported')
    monkeypatch.setattr(files.os, 'link', unsupported)
    with files.Directory(tmp_path) as d:
        d.write_new('stage.part', b'data')
        with pytest.raises(OSError):
            d.publish_link('stage.part', 'report.xlsx')
    assert not (tmp_path / 'report.xlsx').exists()


def test_linked_directory_is_refused(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    link = tmp_path / 'link'
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(real)], check=True, capture_output=True)
    else:
        link.symlink_to(real, target_is_directory=True)
    try:
        with pytest.raises((OSError, files.ExportFileError)):
            with files.Directory(link):
                pass
    finally:
        if os.name == 'nt':
            os.rmdir(link)
        else:
            link.unlink()


def test_windows_directory_lock_or_posix_anchoring(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    renamed = tmp_path / 'renamed'
    with files.Directory(original) as d:
        if os.name == 'nt':
            with pytest.raises(OSError):
                original.rename(renamed)
        else:
            original.rename(renamed)
            original.mkdir()
            d.write_new('anchored.part', b'anchor')
            assert (renamed / 'anchored.part').exists()
            assert not (original / 'anchored.part').exists()


def test_relative_and_parent_paths_are_refused(tmp_path):
    for path in (Path('relative'), tmp_path / '..' / 'sibling'):
        with pytest.raises(files.ExportFileError):
            files.Directory(path)


def test_symlink_file_and_dangling_destination_are_not_followed(tmp_path):
    if os.name == 'nt':
        # Junctions above are exercised without elevation. File symlinks can require
        # Developer Mode; no Windows file-symlink acceptance is inferred from this case.
        pytest.skip('POSIX file-symlink case; Windows junctions are tested separately')
    other = tmp_path / 'other'
    other.write_bytes(b'data')
    (tmp_path / 'source.part').symlink_to(other)
    (tmp_path / 'report.xlsx').symlink_to(tmp_path / 'missing')
    with files.Directory(tmp_path) as d:
        assert d.exists('report.xlsx')
        with pytest.raises(files.ExportFileError):
            d.read('source.part', digest=sha256(b'data').hexdigest(), size=4)
        with pytest.raises(FileExistsError):
            d.write_new('report.xlsx', b'other')
    assert other.read_bytes() == b'data'
