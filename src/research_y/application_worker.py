"""One supervised spawn process per local operation, independent of GUI frameworks.

Only trusted host code may submit ApplicationCommand objects. A private pipe is
new for each invocation and receives bounded JSON, not untrusted pickle. Results
are observations, not a persistent job queue or research-completeness evidence.
Explicit shutdown may interrupt an operation; it NEVER cancels its durable export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import multiprocessing as mp
from multiprocessing.connection import wait as wait_connections
import os
import threading
from uuid import uuid4

from research_y.application_commands import ApplicationCommand, ApplicationCommandError, execute_command

MAX_RESULT_BYTES = 32 * 1024 * 1024  # Explicit refusal, not truncation or a retrieval limit.
WORKER_ERRORS = frozenset({'worker_busy', 'worker_closed', 'unknown_operation',
    'invalid_timeout', 'worker_start_failed', 'worker_interrupted', 'worker_protocol_failed',
    'result_too_large', 'shutdown_unconfirmed', 'operation_failed'})


class ApplicationWorkerError(RuntimeError):
    def __init__(self, code: str):
        self.code = code if code in WORKER_ERRORS else 'operation_failed'
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class OperationStatus:
    operation_id: str
    operation: str
    export_id: str | None
    state: str  # running / returned / failed / interrupted; NOT source/export status.
    error: str | None = None
    result_json: str | None = field(default=None, repr=False)

    def result(self) -> dict | None:
        return json.loads(self.result_json) if self.result_json is not None else None


def _encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _rebuild_windows_sender(handle):
    from multiprocessing.connection import PipeConnection
    return PipeConnection(handle, readable=False, writable=True)


class _WindowsSpawnSender:
    """Transfer ownership into the child, not a parent-side steal-on-unpickle copy.

    CPython's default PipeConnection reducer duplicates a Windows writer in the
    parent until the child unpickles it. Early child death can leave that writer
    open, preventing EOF and leaking a handle. Use the spawn transport's existing
    direct-child duplication instead. This internal CPython 3.12/3.13 boundary
    is deliberately isolated and covered by native-Windows lifecycle tests.
    """
    def __init__(self, sender):
        self.sender = sender

    def __reduce__(self):
        from multiprocessing.context import get_spawning_popen
        popen = get_spawning_popen()
        if popen is None:
            raise RuntimeError('Sender transfer requires an active spawn')
        handle = popen.duplicate_for_child(self.sender.fileno())
        return _rebuild_windows_sender, (handle,)


def _receive_response(receiver, process, stop):
    # Child death is independent of pipe EOF (a duplicate writer can keep a pipe
    # open). Wait on both, and give explicit shutdown priority over a late reply.
    # A complete reply buffered before normal child exit must still be consumed.
    while not stop.is_set():
        ready = wait_connections([receiver, process.sentinel], timeout=.05)
        if stop.is_set():
            break
        if receiver in ready:
            return receiver.recv_bytes(MAX_RESULT_BYTES)
        if process.sentinel in ready:
            break
    raise EOFError


def _watch_parent():
    parent = mp.parent_process()
    if parent is not None:
        parent.join()
        os._exit(74)  # Fail closed after owner death; preserve service checkpoints.


def _child_entry(sender, operation_id, command, execute):
    # A daemon process cannot create child processes. The watcher also handles
    # abrupt parent termination, not only multiprocessing's normal-exit cleanup.
    threading.Thread(target=_watch_parent, daemon=True, name='researchy-parent-watch').start()
    try:
        try:
            result = execute(command)
            if type(result) is not dict:
                raise ValueError
            message = _encode({'id': operation_id, 'state': 'returned', 'error': None, 'result': result})
            if len(message) > MAX_RESULT_BYTES:
                message = _encode({'id': operation_id, 'state': 'failed', 'error': 'result_too_large', 'result': None})
        except ApplicationCommandError as exc:
            message = _encode({'id': operation_id, 'state': 'failed', 'error': exc.code, 'result': None})
        except BaseException:
            # Never print exception text/tracebacks from the host's service work.
            message = _encode({'id': operation_id, 'state': 'failed', 'error': 'operation_failed', 'result': None})
        sender.send_bytes(message)
    except (OSError, EOFError):
        pass
    finally:
        sender.close()


def _decode(raw, expected_id):
    from research_y.application_commands import SERVICE_ERRORS
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if (type(value) is not dict or set(value) != {'id', 'state', 'error', 'result'}
            or value['id'] != expected_id):
        raise ValueError
    if value['state'] == 'returned':
        if value['error'] is not None or type(value['result']) is not dict:
            raise ValueError
    elif value['state'] == 'failed':
        if (type(value['error']) is not str or value['error'] not in SERVICE_ERRORS | WORKER_ERRORS
                or value['result'] is not None):
            raise ValueError
    else:
        raise ValueError
    return value


def _timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 30:
        raise ApplicationWorkerError('invalid_timeout')


class ApplicationWorker:
    """One active operation; conflicting submits fail instead of building a queue.

    submit/poll do not perform database, rendering or file-verification work.
    Use close from a lifecycle thread, NOT the GUI event loop: it waits a bounded
    grace period, then terminates/kills and reaps the owned child. A false stop is
    never reported as success. A fresh worker can recover retained exports by ID.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._process = None
        self._command = None
        self._status = None
        self._pending_status = None
        self._closed = False
        self._stop = threading.Event()

    def submit(self, command: ApplicationCommand) -> str:
        if type(command) is not ApplicationCommand:
            raise ApplicationCommandError('invalid_command')
        command.__post_init__()
        with self._lock:
            self._refresh_completed_locked()
            if self._closed:
                raise ApplicationWorkerError('worker_closed')
            if self._thread is not None and self._thread.is_alive():
                if self._command == command:
                    return self._status.operation_id  # Coalesce an in-flight double click.
                raise ApplicationWorkerError('worker_busy')
            operation_id = str(uuid4())
            self._command = command
            self._stop = threading.Event()
            self._pending_status = None
            self._status = OperationStatus(operation_id, command.operation, command.export_id, 'running')
            self._thread = threading.Thread(target=self._supervise,
                args=(command, operation_id, self._stop), daemon=True, name='researchy-local-operation')
            try:
                self._thread.start()
            except Exception:
                self._status = OperationStatus(operation_id, command.operation, command.export_id,
                                               'failed', 'worker_start_failed')
                self._thread = None
            return operation_id

    def _refresh_completed_locked(self):
        # The child result is only public once its supervisor has actually exited.
        # This keeps terminal poll() and readiness for submit() the same boundary;
        # callers need neither private thread access nor a racy is_alive workaround.
        if (self._pending_status is not None and self._thread is not None
                and not self._thread.is_alive()):
            self._status = self._pending_status
            self._pending_status = None

    def poll(self, operation_id: str) -> OperationStatus:
        with self._lock:
            self._refresh_completed_locked()
            if self._status is None or self._status.operation_id != operation_id:
                raise ApplicationWorkerError('unknown_operation')
            return self._status

    def _signal(self, *, kill=False):
        with self._lock:
            process = self._process
            if process is not None and process.is_alive():
                try:
                    process.kill() if kill else process.terminate()
                except OSError:
                    pass  # close must still prove shutdown, not assume it.

    def _supervise(self, command, operation_id, stop):
        receiver = sender = process = None
        state, error, payload = 'interrupted', 'worker_interrupted', None
        started = False
        try:
            if stop.is_set():
                return
            ctx = mp.get_context('spawn')
            receiver, sender = ctx.Pipe(duplex=False)
            child_sender = _WindowsSpawnSender(sender) if os.name == 'nt' else sender
            process = ctx.Process(target=_child_entry,
                args=(child_sender, operation_id, command, execute_command), daemon=True)
            process.start()
            started = True
            sender.close(); sender = None
            with self._lock:
                self._process = process
            if stop.is_set():
                self._signal()
            message = _decode(_receive_response(receiver, process, stop), operation_id)
            process.join()  # Supervisor only; close() can still signal the child.
            if not process.is_alive() and process.exitcode == 0 and not stop.is_set():
                state, error = message['state'], message['error']
                payload = _encode(message['result']).decode() if state == 'returned' else None
        except (EOFError, BrokenPipeError):
            pass
        except (ValueError, TypeError, UnicodeError, RecursionError):
            state, error = 'failed', 'worker_protocol_failed'
        except Exception:
            state, error = ('failed', 'worker_start_failed') if not started else ('interrupted', 'worker_interrupted')
        finally:
            if sender is not None:
                sender.close()
            if receiver is not None:
                receiver.close()
            if process is not None and started:
                # Only the supervisor joins/closes process handles. Shutdown may
                # signal it under the lock, but cannot race with Process.close.
                process.join(0)
                if process.is_alive():
                    self._signal(kill=True)
                    process.join(2)
                if process.is_alive():
                    # Retain ownership; close() reports an unconfirmed shutdown.
                    with self._lock:
                        self._closed = True
                        self._pending_status = OperationStatus(operation_id, command.operation, command.export_id,
                                                               'interrupted', 'shutdown_unconfirmed')
                    return
                with self._lock:
                    self._process = None
                    process.close()
            elif process is not None:
                process.close()
            if stop.is_set():
                state, error, payload = 'interrupted', 'worker_interrupted', None
            with self._lock:
                self._pending_status = OperationStatus(operation_id, command.operation, command.export_id,
                                                       state, error, payload)

    def close(self, *, grace_seconds: float = 2, kill_seconds: float = 2) -> None:
        """Stop accepting tasks, finish bounded work or interrupt without cancellation.

        Return only after the supervisor and owned child have exited. An OS-level
        failure to stop raises shutdown_unconfirmed and keeps the worker closed.
        Durable export outcomes must be re-inspected after interruption.
        """
        _timeout(grace_seconds); _timeout(kill_seconds)
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join(grace_seconds)
            if thread.is_alive():
                self._stop.set()
                self._signal()
                thread.join(kill_seconds)
                if thread.is_alive():
                    self._signal(kill=True)
                    thread.join(2)
        # Retry a previous exceptional stop even if its supervisor already exited.
        if thread is None or not thread.is_alive():
            with self._lock:
                leftover = self._process
            if leftover is not None and leftover.is_alive():
                self._stop.set()
                self._signal(kill=True)
                leftover.join(kill_seconds)
        with self._lock:
            self._refresh_completed_locked()
            process = self._process
            live = process is not None and process.is_alive()
        if live or (thread is not None and thread.is_alive()):
            raise ApplicationWorkerError('shutdown_unconfirmed')
        # A retained, already-dead exceptional child also needs reaping/closing.
        if process is not None:
            with self._lock:
                process.join(0); process.close(); self._process = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
