"""Terminal completion and readiness share the public lifecycle boundary."""
from dataclasses import replace
import threading
from uuid import uuid4

import pytest
from research_y import application_worker as worker
from test_application_worker import command, echo, domain_fail, crash, wait_for


@pytest.mark.parametrize('fn,terminal', [(echo, 'returned'), (domain_fail, 'failed'), (crash, 'interrupted')])
def test_terminal_status_waits_for_supervisor_exit(tmp_path, monkeypatch, fn, terminal):
    """Hold the exact status-publication/thread-exit gap without timing guesses."""
    original = worker.ApplicationWorker._supervise
    reached, release = threading.Event(), threading.Event()
    def held_tail(self, command, operation_id, stop):
        original(self, command, operation_id, stop)
        reached.set()
        assert release.wait(15), 'test failed to release supervisor tail'
    monkeypatch.setattr(worker.ApplicationWorker, '_supervise', held_tail)
    monkeypatch.setattr(worker, 'execute_command', fn)
    pool = worker.ApplicationWorker(); cmd = command(tmp_path)
    try:
        oid = pool.submit(cmd)
        assert reached.wait(15)
        # A terminal status is not public until the supervisor has exited.
        assert pool.poll(oid).state == 'running'
        assert pool.submit(cmd) == oid
        with pytest.raises(worker.ApplicationWorkerError, match='worker_busy'):
            pool.submit(replace(cmd, run_id=str(uuid4())))
        release.set()
        done = wait_for(pool, oid)
        assert done.state == terminal
        assert not pool._thread.is_alive()
    finally:
        release.set()
        pool.close(grace_seconds=2)


@pytest.mark.parametrize('different', [False, True])
def test_immediate_resubmit_after_terminal_is_fresh_without_private_join(tmp_path, monkeypatch, different):
    monkeypatch.setattr(worker, 'execute_command', echo)
    with worker.ApplicationWorker() as pool:
        cmd = command(tmp_path)
        first_id = pool.submit(cmd)
        first = wait_for(pool, first_id)
        next_cmd = replace(cmd, run_id=str(uuid4())) if different else cmd
        second_id = pool.submit(next_cmd)
        assert second_id != first_id
        second = wait_for(pool, second_id)
        assert first.state == second.state == 'returned'
        assert first.result()['pid'] != second.result()['pid']


def test_close_publishes_terminal_only_after_join(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', echo)
    pool = worker.ApplicationWorker(); oid = pool.submit(command(tmp_path))
    pool.close(grace_seconds=10)
    assert pool.poll(oid).state == 'returned'
    assert not pool._thread.is_alive() and pool._process is None
