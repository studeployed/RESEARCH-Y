"""Startup/exit races: real children, deliberately retained writers, no network."""
from __future__ import annotations

import gc
import multiprocessing as mp
from multiprocessing import connection, context
import os
from pathlib import Path
import pickle
import threading
import time

import pytest
from research_y import application_worker as worker
from test_application_worker import command, echo, slow, wait_file, wait_for


def silent_exit(sender, operation_id, cmd, execute):
    sender.close()


def abrupt_exit(sender, operation_id, cmd, execute):
    os._exit(73)


def _duplicate_writer(sender):
    if os.name == 'nt':
        import _winapi
        current = _winapi.GetCurrentProcess()
        handle = _winapi.DuplicateHandle(current, sender.fileno(), current, 0,
                                         False, _winapi.DUPLICATE_SAME_ACCESS)
        return connection.PipeConnection(handle, readable=False, writable=True)
    return connection.Connection(os.dup(sender.fileno()), readable=False, writable=True)


class RetainingContext:
    """Keep a writer alive after child death, reproducing the missing EOF."""
    def __init__(self, real):
        self.real = real
        self.writers = []
        self.created = threading.Event()
        self.release_start = None

    def Pipe(self, **kwargs):
        receiver, sender = self.real.Pipe(**kwargs)
        self.writers.append(_duplicate_writer(sender))
        return receiver, sender

    def Process(self, **kwargs):
        process = self.real.Process(**kwargs)
        owner = self
        class ProcessProxy:
            def __getattr__(self, name):
                return getattr(process, name)
            def start(self):
                process.start()
                owner.created.set()
                if owner.release_start is not None:
                    assert owner.release_start.wait(10), 'test did not release startup'
        return ProcessProxy()

    def close_writers(self):
        for writer in self.writers:
            writer.close()


@pytest.mark.parametrize('target', [silent_exit, abrupt_exit])
def test_child_exit_finishes_without_waiting_for_pipe_eof(tmp_path, monkeypatch, target):
    ctx = RetainingContext(mp.get_context('spawn'))
    monkeypatch.setattr(worker.mp, 'get_context', lambda method: ctx)
    monkeypatch.setattr(worker, '_child_entry', target)
    pool = worker.ApplicationWorker()
    try:
        oid = pool.submit(command(tmp_path))
        done = wait_for(pool, oid)
        assert (done.state, done.error, done.result()) == ('interrupted', 'worker_interrupted', None)
        # Still open: only the child's sentinel, not EOF, can release this wait.
        assert all(not writer.closed for writer in ctx.writers)
        assert pool._process is None and not pool._thread.is_alive()
    finally:
        ctx.close_writers()
        pool.close(grace_seconds=1, kill_seconds=1)


def test_shutdown_after_spawn_before_registration_has_no_stuck_receiver(tmp_path, monkeypatch):
    ctx = RetainingContext(mp.get_context('spawn'))
    ctx.release_start = threading.Event()
    monkeypatch.setattr(worker.mp, 'get_context', lambda method: ctx)
    monkeypatch.setattr(worker, 'execute_command', slow)
    pool = worker.ApplicationWorker()
    errors = []
    def close():
        try:
            pool.close(grace_seconds=0, kill_seconds=1)
        except BaseException as exc:
            errors.append(exc)
    closer = None
    try:
        oid = pool.submit(command(tmp_path))
        assert ctx.created.wait(15)
        closer = threading.Thread(target=close)
        closer.start()
        assert pool._stop.wait(2)
        ctx.release_start.set()
        closer.join(5)
        assert not closer.is_alive() and not errors
        assert pool.poll(oid).state == 'interrupted'
        assert pool._process is None and not pool._thread.is_alive()
        assert all(not writer.closed for writer in ctx.writers)
    finally:
        ctx.release_start.set()
        ctx.close_writers()
        if closer is not None:
            closer.join(5)
        pool.close(grace_seconds=1, kill_seconds=1)


def test_complete_buffered_reply_not_discarded_when_child_has_exited(tmp_path, monkeypatch):
    ctx = RetainingContext(mp.get_context('spawn'))
    monkeypatch.setattr(worker.mp, 'get_context', lambda method: ctx)
    monkeypatch.setattr(worker, 'execute_command', echo)
    real_wait = worker.wait_connections
    def after_exit(objects, timeout):
        # Wait for both actual OS objects, not a fabricated ready result.
        ready = real_wait(objects, timeout=15)
        if objects[0] in ready:
            assert real_wait([objects[1]], timeout=15)
        return real_wait(objects, timeout=0)
    monkeypatch.setattr(worker, 'wait_connections', after_exit)
    pool = worker.ApplicationWorker()
    try:
        done = wait_for(pool, pool.submit(command(tmp_path)))
        assert done.state == 'returned' and done.result()['audited_success'] is False
    finally:
        ctx.close_writers(); pool.close()


@pytest.mark.parametrize('stop_at', ['before-wait', 'during-wait'])
def test_shutdown_wins_over_ready_response(stop_at, monkeypatch):
    stop = threading.Event()
    class Receiver:
        def recv_bytes(self, maximum):
            pytest.fail('a stopping operation must not consume a reply')
    class Process:
        sentinel = object()
    receiver = Receiver()
    if stop_at == 'before-wait':
        stop.set()
    def ready(objects, timeout):
        stop.set()
        return [receiver]
    monkeypatch.setattr(worker, 'wait_connections', ready)
    with pytest.raises(EOFError):
        worker._receive_response(receiver, Process(), stop)


def test_wait_timeout_is_not_a_worker_failure(monkeypatch):
    stop = threading.Event()
    class Receiver:
        def recv_bytes(self, maximum):
            assert maximum == worker.MAX_RESULT_BYTES
            return b'reply'
    class Process:
        sentinel = object()
    receiver = Receiver(); calls = []
    def ready(objects, timeout):
        calls.append(timeout)
        return [] if len(calls) < 3 else [receiver]
    monkeypatch.setattr(worker, 'wait_connections', ready)
    assert worker._receive_response(receiver, Process(), stop) == b'reply'
    assert calls == [.05, .05, .05]


def test_windows_transfer_duplicates_directly_into_spawning_child(monkeypatch):
    calls = []
    class Sender:
        def fileno(self): return 123
    class Popen:
        def duplicate_for_child(self, handle):
            calls.append(handle)
            return 456
    monkeypatch.setattr(context, 'get_spawning_popen', lambda: Popen())
    fn, args = worker._WindowsSpawnSender(Sender()).__reduce__()
    assert calls == [123] and args == (456,)
    assert fn is worker._rebuild_windows_sender


def test_windows_transfer_refuses_nonspawn_serialisation(monkeypatch):
    monkeypatch.setattr(context, 'get_spawning_popen', lambda: None)
    with pytest.raises(RuntimeError, match='spawn'):
        pickle.dumps(worker._WindowsSpawnSender(object()))


def test_windows_transfer_failure_does_not_fall_back_to_parent_duplicate(monkeypatch):
    class Sender:
        def fileno(self): return 123
    class Popen:
        def duplicate_for_child(self, handle):
            raise OSError('synthetic duplication failure')
    monkeypatch.setattr(context, 'get_spawning_popen', lambda: Popen())
    with pytest.raises(OSError):
        worker._WindowsSpawnSender(Sender()).__reduce__()


def test_rebuilt_windows_sender_is_write_only(monkeypatch):
    seen = []
    def factory(handle, **kwargs):
        seen.append((handle, kwargs))
        return 'sender'
    monkeypatch.setattr(connection, 'PipeConnection', factory, raising=False)
    assert worker._rebuild_windows_sender(456) == 'sender'
    assert seen == [(456, {'readable': False, 'writable': True})]


def _restore_before_arguments(marker):
    # Unpickling the target precedes unpickling its arguments, including sender.
    Path(marker).write_text(str(os.getpid()))
    time.sleep(30)
    return worker._child_entry


class BlockBeforeArguments:
    def __init__(self, marker): self.marker = marker
    def __reduce__(self): return _restore_before_arguments, (self.marker,)


def _windows_handle_count():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetProcessHandleCount.restype = wintypes.BOOL
    count = wintypes.DWORD()
    if not kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    return count.value


@pytest.mark.skipif(os.name != 'nt', reason='Requires actual Windows spawn handles')
def test_native_windows_death_before_argument_unpickle_does_not_leak_or_hang(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', echo)
    # Warm up one spawn before measuring persistent interpreter infrastructure.
    with worker.ApplicationWorker() as warmup:
        assert wait_for(warmup, warmup.submit(command(tmp_path))).state == 'returned'
    gc.collect()
    before = _windows_handle_count()
    for attempt in range(12):
        marker = tmp_path / f'bootstrap-{attempt}'
        monkeypatch.setattr(worker, '_child_entry', BlockBeforeArguments(str(marker)))
        pool = worker.ApplicationWorker()
        try:
            oid = pool.submit(command(tmp_path))
            wait_file(marker)
            pool.close(grace_seconds=0, kill_seconds=1)
            assert pool.poll(oid).state == 'interrupted'
            assert pool._process is None and not pool._thread.is_alive()
        finally:
            pool.close(grace_seconds=0, kill_seconds=1)
    gc.collect()
    # A one-per-spawn leaked duplicate would add 12, not <=2 handles.
    assert _windows_handle_count() <= before + 2
