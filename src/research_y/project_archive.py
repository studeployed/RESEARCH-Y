"""Portable, checksummed snapshots of a RESEARCH-Y project."""
from __future__ import annotations

from contextlib import closing, contextmanager
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import stat
import struct
import tempfile
import unicodedata
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from research_y.export_files import Directory, _ordinary, identity, project_guard
from research_y.projects import (
    DATABASE_RELATIVE_PATH, MANIFEST_FILENAME, SCHEMA_VERSION, SQLITE_APPLICATION_ID,
    _parse_manifest, _safe_folder_name, _validate_folder_component, _validated_project_connection,
    create_project, open_project,
)

INDEX = "archive.json"
DATABASE = DATABASE_RELATIVE_PATH.as_posix()
FIXED = {MANIFEST_FILENAME, DATABASE}
MAX_TOTAL = 8 * 1024**3
MAX_FILE = 4 * 1024**3
MAX_FILES = 16_384
MAX_INDEX = 8 * 1024**2
CHUNK = 1024**2


class ArchiveError(ValueError):
    """A transfer cannot be verified or safely published."""


def _component(value):
    if (not isinstance(value, str) or not value or value in (".", "..") or len(value)>200
            or value.endswith((" ", ".")) or PureWindowsPath(value).is_reserved()
            or any(c in '<>:"/\\|?*' or ord(c)<32 or ord(c)==127 for c in value)):
        raise ArchiveError("Invalid project archive filename")


def _support(name):
    if not isinstance(name,str) or len(name)>768:
        raise ArchiveError("Invalid supporting file path")
    parts = name.split("/")
    if (len(parts)>16 or not (len(parts)>=2 and parts[0] in {"documents","exports"}
                               or len(parts)>=3 and parts[:2]==["data","raw"])):
        raise ArchiveError("Choose supporting files in documents, exports or data/raw")
    for part in parts:
        _component(part)
    return name


def _portable_key(name):
    return unicodedata.normalize("NFC",name).casefold()


def _check_names(names):
    files, dirs = {}, {}
    for name in names:
        if name not in FIXED:
            _support(name)
        key = _portable_key(name)
        if key in files or key in dirs:
            raise ArchiveError("Conflicting portable file paths")
        files[key] = name
        parts = name.split("/")
        for end in range(1,len(parts)):
            parent = "/".join(parts[:end])
            key = _portable_key(parent)
            if key in files or dirs.setdefault(key,parent) != parent:
                raise ArchiveError("Conflicting portable folder paths")


@contextmanager
def _regular(path, limit):
    """Open one pinned ordinary file and recheck identity and size after streaming."""
    _component(path.name)
    with Directory(path.parent) as directory:
        before = directory._stat_component(path.name)
        _ordinary(before,directory=False)
        if before.st_size > limit:
            raise ArchiveError("Selected file exceeds the supported transfer size")
        flags = os.O_RDONLY | getattr(os,"O_BINARY",0) | getattr(os,"O_NOFOLLOW",0) | getattr(os,"O_NONBLOCK",0)
        fd = os.open(path.name,flags,dir_fd=directory.fd) if directory.fd is not None else os.open(path,flags)
        with os.fdopen(fd,"rb") as stream:
            opened = os.fstat(fd)
            _ordinary(opened,directory=False)
            if identity(opened)!=identity(before):
                raise ArchiveError("File changed before transfer")
            yield stream, opened.st_size
            end = os.fstat(fd)
            current = directory._stat_component(path.name)
            if (identity(current)!=identity(opened) or end.st_size!=opened.st_size
                    or end.st_mtime_ns!=opened.st_mtime_ns):
                raise ArchiveError("File changed during transfer")


def _copy(source, output, size):
    h = sha256()
    remaining = size
    while remaining:
        data = source.read(min(CHUNK,remaining))
        if not data:
            raise ArchiveError("Unexpected end of archive entry")
        output.write(data)
        h.update(data)
        remaining -= len(data)
    if source.read(1):
        raise ArchiveError("Archive entry exceeds its declared size")
    return h.hexdigest()


def _schema(db):
    return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").fetchall()


@lru_cache(maxsize=1)
def _expected_schema():
    with tempfile.TemporaryDirectory() as temp:
        project = create_project(temp,"Archive schema reference")
        with closing(sqlite3.connect(project.database_path)) as db:
            return _schema(db)


def _check_database(root):
    from research_y.project_documents import expected_archived_files
    uri = (root / DATABASE).as_uri()+"?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri,uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        if (db.execute("PRAGMA application_id").fetchone()[0] != SQLITE_APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION
                or _schema(db) != _expected_schema()):
            raise ArchiveError("Unsupported project database schema")
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",) or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ArchiveError("Inconsistent project database")
        links = db.execute("SELECT DISTINCT relative_path FROM documents WHERE relative_path IS NOT NULL")
        return {_support(row[0]) for row in links},expected_archived_files(db)


def _archive_name(path):
    _component(path.name)
    if path.suffix.lower() != ".researchy":
        raise ArchiveError("Choose a .researchy archive")


def export_archive(project, destination, *, supporting_files=(), transfer_confirmed=False):
    """Publish one transfer; only expressly selected supporting files may travel."""
    destination = Path(destination)
    _archive_name(destination)
    if transfer_confirmed is not True:
        raise ArchiveError("Confirm permission to transfer the project data and selected files")
    if not isinstance(supporting_files,(list,tuple)) or len(supporting_files)>MAX_FILES-2:
        raise ArchiveError("Invalid supporting file selection")
    selected = [_support(name) for name in supporting_files]
    _check_names([*FIXED,*selected])
    with Directory(destination.parent) as target, project_guard(project):
        if destination.exists():
            raise FileExistsError(destination)
        with tempfile.TemporaryDirectory(prefix=".researchy-export-",dir=destination.parent) as temp:
            stage = Path(temp)
            (stage/"data").mkdir()
            with _validated_project_connection(project) as source, closing(sqlite3.connect(stage/DATABASE)) as snapshot:
                source.backup(snapshot,pages=1024)
                # Compact the snapshot so removed/free-page content is excluded.
                snapshot.execute("VACUUM")
            linked,expected = _check_database(stage)
            missing = linked - set(selected)
            if missing:
                raise ArchiveError("Select all linked project documents before transferring the project")
            archive_path = stage/"transfer.partial"
            rows = {}
            total = 0
            with ZipFile(archive_path,"x",compression=ZIP_DEFLATED,compresslevel=3) as archive:
                with _regular(project.manifest_path,65536) as (manifest,size):
                    (stage/MANIFEST_FILENAME).write_bytes(manifest.read(size))
                if _parse_manifest(stage/MANIFEST_FILENAME) != (project.identifier,project.name,project.created_at_utc):
                    raise ArchiveError("Project manifest changed since opening")
                for name in [MANIFEST_FILENAME,DATABASE,*sorted(selected)]:
                    path = stage/name if name in FIXED else project.root/name
                    limit = min(MAX_TOTAL-total,MAX_FILE,65536 if name==MANIFEST_FILENAME else MAX_FILE)
                    with _regular(path,limit) as (source,size), archive.open(name,"w",force_zip64=True) as dest:
                        rows[name] = dict(size=size,sha256=_copy(source,dest,size))
                        if name in expected and rows[name]!=expected[name]:
                            raise ArchiveError("Document bytes differ from the recorded attachment")
                        total += size
                index = json.dumps(dict(format="researchy",version=1,project_id=str(project.identifier),files=rows),
                                   ensure_ascii=True,sort_keys=True).encode()
                if len(index)>MAX_INDEX:
                    raise ArchiveError("Archive file inventory exceeds the supported size")
                archive.writestr(INDEX,index)
            with archive_path.open("r+b") as finished:
                os.fsync(finished.fileno())
            os.link(archive_path,destination)
            target.sync()
    return dict(project_id=str(project.identifier),files=len(rows),bytes=total)


def _unique_object(pairs):
    result = dict(pairs)
    if len(result)!=len(pairs):
        raise ArchiveError("Repeated archive inventory key")
    return result


def _inventory(archive):
    entries = archive.infolist()
    if not 3 <= len(entries) <= MAX_FILES+1:
        raise ArchiveError("Invalid archive file count")
    by_name = {}
    total = 0
    for item in entries:
        name = item.filename
        kind = stat.S_IFMT(item.external_attr>>16)
        if (name in by_name or name!=item.orig_filename or item.is_dir() or item.flag_bits & 1
                or kind not in (0,stat.S_IFREG) or item.compress_type not in (ZIP_STORED,ZIP_DEFLATED)
                or item.file_size > MAX_FILE):
            raise ArchiveError("Unsupported archive member")
        by_name[name] = item
        total += item.file_size
    if (total>MAX_TOTAL+MAX_INDEX or not FIXED|{INDEX} <= by_name.keys()
            or by_name[INDEX].file_size>MAX_INDEX or by_name[MANIFEST_FILENAME].file_size>65536):
        raise ArchiveError("Missing or oversized archive contents")
    _check_names(k for k in by_name if k!=INDEX)
    index = json.loads(archive.read(INDEX),object_pairs_hook=_unique_object)
    if (type(index) is not dict or set(index)!={"format","version","project_id","files"}
            or index["format"]!="researchy" or type(index["version"]) is not int or index["version"]!=1
            or type(index["files"]) is not dict or set(index["files"])!=by_name.keys()-{INDEX}):
        raise ArchiveError("Invalid archive inventory")
    for name,row in index["files"].items():
        if (type(row) is not dict or set(row)!={"size","sha256"} or type(row["size"]) is not int
                or row["size"]!=by_name[name].file_size or not isinstance(row["sha256"],str)
                or not re.fullmatch("[0-9a-f]{64}",row["sha256"])):
            raise ArchiveError("Invalid archive checksum or file size")
    return index


def _check_zip_directory(source):
    # Our writer emits one disk and an uncommented ZIP end record. Bound the
    # central directory before ZipFile reads it into memory (including ZIP64).
    source.seek(0,os.SEEK_END)
    length = source.tell()
    if length < 22:
        raise ArchiveError("Incomplete archive")
    source.seek(-22,os.SEEK_END)
    signature,disk,first_disk,on_disk,count,size,offset,comment = struct.unpack("<4s4H2LH",source.read(22))
    if signature != b"PK\x05\x06" or disk or first_disk or on_disk!=count or comment:
        raise ArchiveError("Unsupported archive directory")
    directory_end = length-22
    if length >= 98:
        source.seek(-42,os.SEEK_END)
        locator = source.read(20)
        if locator.startswith(b"PK\x06\x07"):
            _,disk,position,disks = struct.unpack("<4sLQL",locator)
            if disk or disks!=1 or position!=length-98:
                raise ArchiveError("Unsupported extended archive directory")
            source.seek(position)
            sig,record_size,_,_,disk,first_disk,on_disk,count,size,offset = struct.unpack("<4sQ2H2L4Q",source.read(56))
            if sig!=b"PK\x06\x06" or record_size!=44 or disk or first_disk or on_disk!=count:
                raise ArchiveError("Invalid extended archive directory")
            directory_end = position
    if not 3<=count<=MAX_FILES+1 or size>32*1024**2 or offset+size!=directory_end:
        raise ArchiveError("Archive directory exceeds the supported format")
    source.seek(0)


def _publish_folder(stage,destination):
    if os.name == "nt":
        # Windows rename never replaces an existing destination.
        stage.rename(destination)
        return
    import ctypes
    libc = ctypes.CDLL(None,use_errno=True)
    rename = getattr(libc,"renameat2",None)
    if rename is None:
        raise ArchiveError("Atomic project restore is unavailable on this filesystem")
    rename.argtypes = [ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    with Directory(stage.parent) as src, Directory(destination.parent) as dst:
        if rename(src.fd,os.fsencode(stage.name),dst.fd,os.fsencode(destination.name),1):
            error = ctypes.get_errno()
            raise OSError(error,os.strerror(error),destination)


def import_archive(archive_path, parent, *, directory_name=None):
    """Verify in private staging and atomically publish a new working folder."""
    archive_path, parent = Path(archive_path), Path(parent)
    _archive_name(archive_path)
    if directory_name is not None:
        _validate_folder_component(directory_name)
    with Directory(parent) as target, _regular(archive_path,MAX_TOTAL+64*1024**2) as (source,_):
        with tempfile.TemporaryDirectory(prefix=".researchy-import-",dir=parent) as temp:
            stage = Path(temp)/"project"
            stage.mkdir(mode=0o700)
            try:
                _check_zip_directory(source)
                with ZipFile(source) as archive:
                    index = _inventory(archive)
                    for name,row in index["files"].items():
                        out = stage/name
                        out.parent.mkdir(parents=True,exist_ok=True)
                        with archive.open(name) as entry, out.open("xb") as dest:
                            if _copy(entry,dest,row["size"]) != row["sha256"]:
                                raise ArchiveError("Archive checksum mismatch")
                            dest.flush()
                            os.fsync(dest.fileno())
                linked,expected = _check_database(stage)
                if linked - set(index["files"]):
                    raise ArchiveError("Missing linked document")
                if any(index["files"].get(name)!=receipt for name,receipt in expected.items()):
                    raise ArchiveError("Archived document differs from the recorded attachment")
                restored = open_project(stage)
                if str(restored.identifier)!=index["project_id"]:
                    raise ArchiveError("Archive project identity mismatch")
            except (BadZipFile,sqlite3.DatabaseError,UnicodeError,RecursionError) as exc:
                raise ArchiveError("Project archive could not be verified") from exc
            for folder in ("data/raw","documents","exports","logs","backups"):
                (stage/folder).mkdir(parents=True,exist_ok=True)
            destination = parent/(directory_name or _safe_folder_name(restored.name))
            _publish_folder(stage,destination)
            target.sync()
            return open_project(destination)
