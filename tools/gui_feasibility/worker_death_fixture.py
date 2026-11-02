"""Test-only failure barrier for a *GUI-owned* spawned application worker.

Only the disposable real-project feasibility runner selects this callable as
ApplicationWorker.execute_command. No production command, browser route, export
schema, or credentials accept fault-selection arguments. The trusted runner
kills the direct child AFTER a genuine partial stage write; a surviving
session later recovers with the unmodified production execute_command.
"""
from __future__ import annotations

import os
from pathlib import Path
import time

from research_y.application_commands import execute_command


def publish_gui_owner_marker(path: Path) -> None:
    """Record the *actual* Python GUI host PID, not its Windows venv redirector.

    Called only inside the trusted disposable GUI test process. It writes to
    a freshly allocated private marker and never accepts browser input.
    """
    if not isinstance(path, Path) or not path.is_absolute():
        raise RuntimeError('test_gui_owner_marker_invalid')
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
             getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    fd = os.open(path, flags, 0o600)
    try:
        raw = str(os.getpid()).encode('ascii')
        if os.write(fd, raw) != len(raw):
            raise OSError('test_gui_owner_marker_write_failed')
        os.fsync(fd)
    finally:
        os.close(fd)


def pause_during_retained_stage(command):
    """Run real publication until midway through writing a retained artifact."""
    if command.operation != 'resume_export':
        return execute_command(command)

    marker_text = os.environ.get('RESEARCHY_GUI_TEST_STAGE_MARKER', '')
    marker = Path(marker_text)
    if not marker_text or not marker.is_absolute():
        raise RuntimeError('test_worker_marker_missing')

    from research_y.export_files import Directory
    original_write = Directory.write_new
    reached_stage = False

    def interrupted_write(directory, name, data):
        nonlocal reached_stage
        if not reached_stage and name.startswith('retained-') and name.endswith('.xlsx'):
            reached_stage = True
            # Use the actual guarded exclusive-create/fsync path, but only
            # write a *prefix* of the real workbook before the owner kills us.
            # Never erase or replace this mismatched evidence.
            original_write(directory, name, data[:max(1, len(data) // 2)])
            flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
            fd = os.open(marker, flags, 0o600)
            try:
                payload = str(os.getpid()).encode('ascii')
                if os.write(fd, payload) != len(payload):
                    raise OSError('test_worker_marker_write_failed')
                os.fsync(fd)
            finally:
                os.close(fd)
            # The only expected exit is an externally confirmed, direct-child
            # process termination by the trusted test runner. A timeout is
            # explicitly a failed fixture, never a successful publication.
            time.sleep(90)
            raise RuntimeError('test_worker_was_not_terminated')
        return original_write(directory, name, data)

    Directory.write_new = interrupted_write
    try:
        result = execute_command(command)
        if not reached_stage:
            raise RuntimeError('test_worker_never_entered_stage_write')
        return result
    finally:
        Directory.write_new = original_write
