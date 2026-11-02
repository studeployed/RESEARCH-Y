"""Startup/exit races: real children, deliberately retained writers, no network."""
from __future__ import annotations

import gc
import json
import multiprocessing as mp
from multiprocessing import connection, context
import os
from pathlib import Path
import pickle
import subprocess
import sys
import threading
import time
import weakref

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


def _exercise_bootstrap_interruption(root, marker):
    """Return weak references only; no test-owned worker survives a sample."""
    original_entry = worker._child_entry
    worker._child_entry = BlockBeforeArguments(str(marker))
    pool = worker.ApplicationWorker()
    try:
        oid = pool.submit(command(root))
        references = (weakref.ref(pool), weakref.ref(pool._thread))
        wait_file(marker)
        pool.close(grace_seconds=0, kill_seconds=1)
        assert (pool.poll(oid).state, pool.poll(oid).error) == (
            'interrupted', 'worker_interrupted')
        assert pool._process is None and not pool._thread.is_alive()
        return references
    finally:
        try:
            pool.close(grace_seconds=0, kill_seconds=1)
        finally:
            worker._child_entry = original_entry


def _warmup_handle_probe(root):
    # Scope both normal completion and interruption before the measured batch.
    with worker.ApplicationWorker() as pool:
        assert wait_for(pool, pool.submit(command(root))).state == 'returned'
    references = _exercise_bootstrap_interruption(root, root / 'warmup-bootstrap')
    gc.collect()
    assert all(reference() is None for reference in references)


def _measure_handle_probe(root, *, legacy_transfer=False, counter=None):
    """Run only in a disposable host: the legacy control intentionally leaks."""
    if counter is None:
        counter = _windows_handle_count
    original_execute = worker.execute_command
    original_transfer = worker._WindowsSpawnSender
    worker.execute_command = echo
    try:
        _warmup_handle_probe(root)
        counter()  # Load the counter's own native/runtime infrastructure first.
        gc.collect()
        before = counter()
        if legacy_transfer:
            # Restore the original standard PipeConnection reducer, not an
            # invented counter increase. The child dies before stealing its copy.
            worker._WindowsSpawnSender = lambda sender: sender
        samples = []
        for attempt in range(1, 13):
            references = _exercise_bootstrap_interruption(root, root / f'bootstrap-{attempt}')
            gc.collect()
            assert all(reference() is None for reference in references)
            if attempt % 4 == 0:
                samples.append({'attempts': attempt, 'handles': counter()})
        return {'pid': os.getpid(), 'baseline': before, 'samples': samples,
                'legacy_transfer': legacy_transfer, 'interruptions': 12}
    finally:
        worker.execute_command = original_execute
        worker._WindowsSpawnSender = original_transfer


def _isolated_handle_probe(root, *, legacy_transfer=False):
    # Import test helpers but do not start another pytest/plugin session. A
    # process-wide handle count must not include the outer suite's activity.
    code = """
import json, sys
from pathlib import Path
from test_application_worker_shutdown import _measure_handle_probe
if __name__ == '__main__':
    result = _measure_handle_probe(Path(sys.argv[1]), legacy_transfer=sys.argv[2] == 'legacy')
    print(json.dumps(result, sort_keys=True))
"""
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([
        str(Path(__file__).parents[1] / 'src'), str(Path(__file__).parent),
        env.get('PYTHONPATH', '')])
    completed = subprocess.run(
        [sys.executable, '-c', code, str(root), 'legacy' if legacy_transfer else 'current'],
        env=env, capture_output=True, text=True, timeout=120, check=False)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['pid'] != os.getpid()
    assert result['legacy_transfer'] is legacy_transfer
    assert result['interruptions'] == 12
    assert [sample['attempts'] for sample in result['samples']] == [4, 8, 12]
    assert type(result['baseline']) is int and result['baseline'] > 0
    assert all(type(sample['handles']) is int and sample['handles'] > 0
               for sample in result['samples'])
    return result


def test_handle_probe_releases_worker_and_thread_before_sampling(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', echo)
    original_entry = worker._child_entry
    references = _exercise_bootstrap_interruption(tmp_path, tmp_path / 'bootstrap')
    gc.collect()
    assert all(reference() is None for reference in references)
    assert worker._child_entry is original_entry


def test_handle_probe_samples_each_completed_batch_and_restores_hooks(tmp_path, monkeypatch):
    # The preceding test uses a real child. This case checks sample ordering
    # without paying for twelve more spawns on non-Windows test runners.
    original_execute = worker.execute_command
    original_transfer = worker._WindowsSpawnSender
    events = []
    monkeypatch.setattr(gc, 'collect', lambda: events.append('collect'))
    monkeypatch.setattr(sys.modules[__name__], '_warmup_handle_probe',
                        lambda root: events.append('warmup'))
    def exercise(root, marker):
        events.append(marker.name)
        return ()
    monkeypatch.setattr(sys.modules[__name__], '_exercise_bootstrap_interruption', exercise)
    def counter():
        events.append('sample')
        return 100
    result = _measure_handle_probe(tmp_path, counter=counter)
    expected = ['warmup', 'sample', 'collect', 'sample']
    for attempt in range(1, 13):
        expected.extend([f'bootstrap-{attempt}', 'collect'])
        if attempt % 4 == 0:
            expected.append('sample')
    assert events == expected
    assert result['samples'] == [
        {'attempts': 4, 'handles': 100}, {'attempts': 8, 'handles': 100},
        {'attempts': 12, 'handles': 100}]
    assert worker.execute_command is original_execute
    assert worker._WindowsSpawnSender is original_transfer


@pytest.mark.skipif(os.name != 'nt', reason='Requires actual Windows spawn handles')
def test_native_windows_death_before_argument_unpickle_does_not_leak_or_hang(tmp_path):
    result = _isolated_handle_probe(tmp_path)
    # Keep the original allowance, now at every batch boundary, not only the end.
    assert all(sample['handles'] <= result['baseline'] + 2
               for sample in result['samples']), result


@pytest.mark.skipif(os.name != 'nt', reason='Requires actual Windows spawn handles')
def test_native_windows_handle_probe_detects_legacy_parent_duplicate_leak(tmp_path):
    result = _isolated_handle_probe(tmp_path, legacy_transfer=True)
    # Positive leak-detection control: the original transport must fail the same
    # <=2 allowance and show at least one retained writer per interrupted spawn.
    assert all(sample['handles'] >= result['baseline'] + sample['attempts']
               for sample in result['samples']), result
    assert result['samples'][-1]['handles'] > result['baseline'] + 2, result
