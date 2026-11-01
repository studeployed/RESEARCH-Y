"""Guarded local export files; exclusive creation and no-overwrite publication.

All names are single components. POSIX operations use an opened directory;
Windows holds non-delete-sharing ancestor handles and rejects reparse points.
These guards are not a sandbox against a hostile process with the same account.
No destructive rename, overwrite, automatic deletion or network access is used.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
from typing import Iterator

MAX_ARTIFACT_BYTES = 128 * 1024 * 1024  # Refuse explicitly, never truncate.


class ExportFileError(ValueError):
    """A path, retained file or publication cannot be verified safely."""


def filename(value: str, *, workbook: bool = False) -> str:
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9.][A-Za-z0-9._ ()-]{0,139}', value)
            or value in ('.', '..') or value.endswith((' ', '.'))
            or value.split('.', 1)[0].upper() in {'CON', 'PRN', 'AUX', 'NUL'}
            or re.fullmatch(r'(COM|LPT)[1-9]', value.split('.', 1)[0], re.I)
            or (workbook and (not value.lower().endswith('.xlsx') or value.startswith('.')))):
        raise ExportFileError('A safe single Windows-compatible file name is required')
    return value


def _ordinary(info: os.stat_result, *, directory: bool) -> None:
    if ((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) is False
            or getattr(info, 'st_file_attributes', 0) & 0x400):  # FILE_ATTRIBUTE_REPARSE_POINT
        raise ExportFileError('Linked, reparse or non-ordinary export path')


def identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


@contextmanager
def _windows_directory(path: Path):
    """Lock this directory against rename/delete and inspect the opened handle."""
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE)
    create.restype = w.HANDLE
    close = kernel.CloseHandle
    close.argtypes, close.restype = (w.HANDLE,), w.BOOL

    class Info(ctypes.Structure):
        _fields_ = [('attributes', w.DWORD), ('creation', w.FILETIME), ('access', w.FILETIME),
                    ('write', w.FILETIME), ('volume', w.DWORD), ('size_high', w.DWORD),
                    ('size_low', w.DWORD), ('links', w.DWORD), ('index_high', w.DWORD),
                    ('index_low', w.DWORD)]

    get_info = kernel.GetFileInformationByHandle
    get_info.argtypes, get_info.restype = (w.HANDLE, ctypes.POINTER(Info)), w.BOOL
    # FILE_LIST_DIRECTORY participates in Windows sharing checks; access=0 is
    # metadata-only and does NOT enforce our no-delete-sharing rename guard.
    # Fail closed if directory-read access is denied; never retry with access=0.
    directory_read_access = 0x0001
    # OPEN_EXISTING, BACKUP_SEMANTICS | OPEN_REPARSE_POINT; share read/write, NOT delete.
    handle = create(str(path), directory_read_access, 3, None, 3, 0x02000000 | 0x00200000, None)
    if handle == w.HANDLE(-1).value:
        raise OSError('Export directory cannot be locked')
    try:
        info = Info()
        if not get_info(handle, ctypes.byref(info)) or info.attributes & 0x400 or not info.attributes & 0x10:
            raise ExportFileError('Export directory is a reparse point or unavailable')
        yield
    finally:
        close(handle)


class Directory:
    """An existing directory opened without resolving symlinks or junctions."""
    def __init__(self, path: Path | str):
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts:
            raise ExportFileError('An absolute existing local directory is required')
        if os.name == 'nt' and (path.drive.startswith('\\\\') or not re.fullmatch(r'[A-Za-z]:', path.drive)):
            raise ExportFileError('Network and device destinations are not supported')
        self.path = path
        self.fd: int | None = None
        self._stack = ExitStack()

    def __enter__(self):
        try:
            if os.name == 'posix':
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                fd = os.open(self.path.anchor, flags)
                self._stack.callback(os.close, fd)
                for part in self.path.parts[1:]:
                    fd = os.open(part, flags, dir_fd=fd)
                    self._stack.callback(os.close, fd)
                self.fd = fd
                info = os.fstat(fd)
            elif os.name == 'nt':
                current = Path(self.path.anchor)
                self._stack.enter_context(_windows_directory(current))
                for part in self.path.parts[1:]:
                    current /= part
                    self._stack.enter_context(_windows_directory(current))
                info = self.path.lstat()
            else:
                raise ExportFileError('Unsupported export platform')
            _ordinary(info, directory=True)
            self.identity = identity(info)
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(self, *args):
        return self._stack.__exit__(*args)

    def _stat(self, name: str) -> os.stat_result:
        filename(name)
        return (os.stat(name, dir_fd=self.fd, follow_symlinks=False) if self.fd is not None
                else (self.path / name).lstat())

    def exists(self, name: str) -> bool:
        try:
            self._stat(name)
            return True  # Also true for a dangling symlink: never overwrite it.
        except FileNotFoundError:
            return False

    def sync(self) -> None:
        if self.fd is not None:
            os.fsync(self.fd)
        # Windows file flush is performed below. No universal directory/power-loss guarantee.

    def mkdir(self, name: str) -> None:
        filename(name)
        try:
            if self.fd is not None:
                os.mkdir(name, mode=0o700, dir_fd=self.fd)
            else:
                (self.path / name).mkdir(mode=0o700)
            self.sync()
        except FileExistsError:
            _ordinary(self._stat(name), directory=True)

    def write_new(self, name: str, data: bytes) -> None:
        filename(name)
        if type(data) is not bytes or not 0 < len(data) <= MAX_ARTIFACT_BYTES:
            raise ExportFileError('Invalid or oversized workbook bytes')
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = (os.open(name, flags, 0o600, dir_fd=self.fd) if self.fd is not None
              else os.open(self.path / name, flags, 0o600))
        try:
            offset = 0
            while offset < len(data):
                written = os.write(fd, memoryview(data)[offset:])
                if written <= 0:
                    raise OSError('Export write made no progress')
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        self.sync()
        # Failed/partial owned stages are retained for explicit recovery, never unlinked blindly.

    def read(self, name: str, *, digest: str, size: int) -> bytes:
        filename(name)
        if type(size) is not int or not 0 < size <= MAX_ARTIFACT_BYTES:
            raise ExportFileError('Invalid artifact size')
        before = self._stat(name)
        _ordinary(before, directory=False)
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = (os.open(name, flags, dir_fd=self.fd) if self.fd is not None
              else os.open(self.path / name, flags))
        try:
            opened = os.fstat(fd)
            _ordinary(opened, directory=False)
            if identity(before) != identity(opened) or opened.st_size != size:
                raise ExportFileError('Retained export identity or size changed')
            blocks, remaining = [], size + 1
            while remaining:
                block = os.read(fd, min(1024 * 1024, remaining))
                if not block:
                    break
                blocks.append(block)
                remaining -= len(block)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        data = b''.join(blocks)
        current = self._stat(name)
        _ordinary(current, directory=False)
        if (identity(current) != identity(opened) or after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns or len(data) != size
                or sha256(data).hexdigest() != digest):
            raise ExportFileError('Retained export checksum or identity changed')
        return data

    def flush(self, name: str) -> None:
        """Retry durability work before accepting an interrupted complete write."""
        before = self._stat(name)
        _ordinary(before, directory=False)
        flags = os.O_RDWR | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = (os.open(name, flags, dir_fd=self.fd) if self.fd is not None
              else os.open(self.path / name, flags))
        try:
            opened = os.fstat(fd)
            _ordinary(opened, directory=False)
            if identity(before) != identity(opened):
                raise ExportFileError('Export file changed before flush')
            os.fsync(fd)
        finally:
            os.close(fd)
        self.sync()

    def same_file(self, left: str, right: str) -> bool:
        a, b = self._stat(left), self._stat(right)
        _ordinary(a, directory=False)
        _ordinary(b, directory=False)
        return identity(a) == identity(b)

    def publish_link(self, stage: str, target: str) -> None:
        """Create a new directory entry, never a destructive replace fallback."""
        filename(stage)
        filename(target, workbook=True)
        _ordinary(self._stat(stage), directory=False)
        if self.fd is not None:
            os.link(stage, target, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        else:
            os.link(self.path / stage, self.path / target, follow_symlinks=False)
        self.sync()
        if not self.same_file(stage, target):
            raise ExportFileError('Final publication identity differs from staged file')


@contextmanager
def project_guard(project) -> Iterator[None]:
    """Refuse linked project storage before the normal database opener can write."""
    with Directory(project.root), Directory(project.root / 'data') as data:
        for path in (project.manifest_path, project.database_path):
            _ordinary(path.lstat(), directory=False)
        yield
