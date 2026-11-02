"""Real spawn/pipe/lifecycle tests with synthetic service functions, no network."""
from dataclasses import FrozenInstanceError, replace
import json
import multiprocessing as mp
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

import pytest
from research_y import application_worker as worker
from research_y.application_commands import ApplicationCommand, ApplicationCommandError

STAMP = '2026-11-01T00:00:00+00:00'


def command(tmp_path, **kw):
    args = dict(operation='inspect', project_root=str(tmp_path), project_id=str(uuid4()),
                project_name='Synthetic project', project_created_at=STAMP)
    args.update(kw)
    return ApplicationCommand(**args)


def echo(cmd):
    return {'pid': os.getpid(), 'operation': cmd.operation, 'audited_success': False,
            'source_retrieval_verified': False, 'data': [None, 0, 1]}


def slow(cmd):
    (Path(cmd.project_root) / 'entered').write_text(str(os.getpid()))
    time.sleep(30)
    return {'late': True}


def large(cmd):
    return {'data': 'x' * (256 * 1024)}


def oversize(cmd):
    return {'data': 'x' * worker.MAX_RESULT_BYTES}


def fail(cmd):
    raise RuntimeError('PRIVATE_PATH_AND_SECRET_must_not_appear')


def domain_fail(cmd):
    raise ApplicationCommandError('project_busy')


def crash(cmd):
    os._exit(73)


def invalid_result(cmd):
    return ['wrong shape']


def nan_result(cmd):
    return {'value': float('nan')}


def parent_probe(cmd):
    path = Path(cmd.project_root) / 'child-pid'
    path.write_text(str(os.getpid()))
    while True:
        time.sleep(.05)


def wait_for(pool, oid, timeout=15):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        state = pool.poll(oid)
        if state.state != 'running':
            # Status is terminal only once the process has been reaped.
            return state
        time.sleep(.01)
    pytest.fail('bounded worker test did not finish')


def wait_file(path, timeout=15):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(.01)
    pytest.fail('child did not reach test boundary')


def test_real_spawn_returns_detached_result_and_reaps_child(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', echo)
    with worker.ApplicationWorker() as pool:
        oid = pool.submit(command(tmp_path))
        done = wait_for(pool, oid)
        assert done.state == 'returned' and done.error is None
        data = done.result()
        assert data['pid'] != os.getpid() and not data['audited_success']
        data['data'].append(99)
        assert pool.poll(oid).result()['data'] == [None, 0, 1]
        assert 'result_json' not in repr(done)
        with pytest.raises(FrozenInstanceError):
            done.state = 'made-up'
    assert pool._process is None


def test_submit_poll_responsive_during_work_and_double_click_coalesced(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', slow)
    pool = worker.ApplicationWorker()
    cmd = command(tmp_path)
    try:
        oid = pool.submit(cmd)
        wait_file(tmp_path / 'entered')
        for _ in range(100):
            assert pool.poll(oid).state == 'running'
            assert pool.submit(cmd) == oid
        with pytest.raises(worker.ApplicationWorkerError, match='worker_busy'):
            pool.submit(replace(cmd, run_id=str(uuid4())))
    finally:
        pool.close(grace_seconds=0, kill_seconds=1)
    assert pool.poll(oid).state == 'interrupted'
    assert pool._process is None and not pool._thread.is_alive()


def test_large_pipe_response_is_drained_without_blocking_poll(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', large)
    with worker.ApplicationWorker() as pool:
        done = wait_for(pool, pool.submit(command(tmp_path)))
        assert done.state == 'returned'
        assert len(done.result()['data']) == 256 * 1024


@pytest.mark.parametrize('fn,error', [(fail,'operation_failed'), (domain_fail,'project_busy'),
    (invalid_result,'operation_failed'), (nan_result,'operation_failed'), (oversize,'result_too_large')])
def test_child_failures_are_static_no_partial_results(tmp_path, monkeypatch, fn, error):
    monkeypatch.setattr(worker, 'execute_command', fn)
    with worker.ApplicationWorker() as pool:
        done = wait_for(pool, pool.submit(command(tmp_path)))
        assert (done.state, done.error, done.result()) == ('failed', error, None)
        assert 'PRIVATE' not in repr(done)


def test_real_child_crash_is_interrupted_not_success(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', crash)
    with worker.ApplicationWorker() as pool:
        done = wait_for(pool, pool.submit(command(tmp_path)))
        assert (done.state, done.error, done.result()) == ('interrupted', 'worker_interrupted', None)
    assert pool._process is None


def test_close_before_first_submit_idempotent_and_refuses_new_work(tmp_path):
    pool = worker.ApplicationWorker()
    pool.close(); pool.close()
    with pytest.raises(worker.ApplicationWorkerError, match='worker_closed'):
        pool.submit(command(tmp_path))


def test_close_during_startup_is_reaped_or_explicitly_unconfirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', slow)
    for _ in range(3):
        pool = worker.ApplicationWorker()
        oid = pool.submit(command(tmp_path))
        pool.close(grace_seconds=0, kill_seconds=1)
        assert pool.poll(oid).state == 'interrupted'
        assert pool._process is None and not pool._thread.is_alive()


def test_graceful_close_keeps_returned_result(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', echo)
    pool = worker.ApplicationWorker()
    oid = pool.submit(command(tmp_path))
    pool.close(grace_seconds=10)
    assert pool.poll(oid).state == 'returned'


def test_context_manager_exception_also_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', echo)
    pool = worker.ApplicationWorker()
    with pytest.raises(ValueError):
        with pool:
            pool.submit(command(tmp_path))
            raise ValueError('caller failure')
    assert pool._process is None and not pool._thread.is_alive()


@pytest.mark.parametrize('value', [-1,31,True,None,float('nan'),float('inf'),'1'])
def test_invalid_shutdown_timeout_refused(value):
    pool = worker.ApplicationWorker()
    with pytest.raises(worker.ApplicationWorkerError, match='invalid_timeout'):
        pool.close(grace_seconds=value)
    pool.close()


def test_unknown_operation_never_returns_latest_result(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', echo)
    with worker.ApplicationWorker() as pool:
        with pytest.raises(worker.ApplicationWorkerError, match='unknown_operation'):
            pool.poll(str(uuid4()))
        done = wait_for(pool, pool.submit(command(tmp_path)))
        with pytest.raises(worker.ApplicationWorkerError, match='unknown_operation'):
            pool.poll(str(uuid4()))
        assert done.state == 'returned'


def test_concurrent_submits_coalesce_identical_and_refuse_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'execute_command', slow)
    pool = worker.ApplicationWorker(); cmd = command(tmp_path)
    results = []
    try:
        threads = [threading.Thread(target=lambda: results.append(pool.submit(cmd))) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(2)
        assert len(results) == 8 and len(set(results)) == 1
    finally:
        pool.close(grace_seconds=0, kill_seconds=1)


@pytest.mark.parametrize('patch', [dict(id='other'), dict(state='success'), dict(error='SECRET'),
    dict(result=[]), dict(extra=0), dict(state='failed', error='unknown-secret', result=None)])
def test_invalid_response_envelopes_rejected(patch):
    value = dict(id='id', state='returned', error=None, result={}); value.update(patch)
    with pytest.raises(ValueError):
        worker._decode(json.dumps(value), 'id')


@pytest.mark.parametrize('raw', ['[]', '{}', 'bad', '{"id":"id","id":"id"}',
    '{"id":"id","state":"returned","error":null,"result":{"x":NaN}}'])
def test_malformed_duplicate_and_nonfinite_response_rejected(raw):
    with pytest.raises(ValueError): worker._decode(raw, 'id')


@pytest.mark.parametrize('patch', [dict(operation='eval'),dict(project_root='relative'),
    dict(project_id='bad'),dict(project_created_at='2026-11-01'),dict(project_name=''),
    dict(run_id='bad'),dict(export_id=str(uuid4())),dict(directory='relative')])
def test_invalid_commands_fail_before_process(tmp_path, patch):
    with pytest.raises(ApplicationCommandError, match='invalid_command'):
        command(tmp_path, **patch)


def test_command_repr_does_not_expose_paths_or_names(tmp_path):
    cmd = command(tmp_path, project_name='Private topic')
    assert str(tmp_path) not in repr(cmd) and 'Private' not in repr(cmd)
    with pytest.raises(ApplicationCommandError):
        worker.ApplicationWorker().submit({'operation':'inspect'})


def pid_alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes as w
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.argtypes=(w.DWORD,w.BOOL,w.DWORD); k.OpenProcess.restype=w.HANDLE
        k.GetExitCodeProcess.argtypes=(w.HANDLE,ctypes.POINTER(w.DWORD)); k.GetExitCodeProcess.restype=w.BOOL
        k.CloseHandle.argtypes=(w.HANDLE,); k.CloseHandle.restype=w.BOOL
        h=k.OpenProcess(0x1000,False,pid)
        if not h: return False
        try:
            code=w.DWORD()
            return bool(k.GetExitCodeProcess(h,ctypes.byref(code))) and code.value==259
        finally: k.CloseHandle(h)
    try:
        # A reaped-or-zombie child cannot continue performing application work.
        status=Path(f'/proc/{pid}/stat').read_text()
        return status.rsplit(')',1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def test_abrupt_host_exit_does_not_leave_worker_running(tmp_path):
    code = '''
import sys,time
from pathlib import Path
from research_y import application_worker as w
from test_application_worker import command,parent_probe
if __name__ == '__main__':
    w.execute_command=parent_probe
    p=w.ApplicationWorker(); p.submit(command(Path(sys.argv[1])))
    time.sleep(60)
'''
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(Path(__file__).parents[1]/'src'),str(Path(__file__).parent),env.get('PYTHONPATH','')])
    parent=subprocess.Popen([sys.executable,'-c',code,str(tmp_path)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    child=None
    try:
        child=int(wait_file(tmp_path/'child-pid'))
        assert pid_alive(child)
        parent.kill(); parent.wait(timeout=5)
        until=time.monotonic()+8
        while pid_alive(child) and time.monotonic()<until: time.sleep(.05)
        assert not pid_alive(child), 'orphan application worker still running'
    finally:
        if parent.poll() is None: parent.kill(); parent.wait(timeout=5)
        if child is not None and pid_alive(child):
            import signal
            os.kill(child,signal.SIGTERM)


@pytest.mark.parametrize('fn,error',[ (echo,None), (domain_fail,'project_busy'),
    (fail,'operation_failed'), (invalid_result,'operation_failed'), (nan_result,'operation_failed')])
def test_child_protocol_encoding_and_sender_cleanup(tmp_path,monkeypatch,fn,error):
    # Direct protocol test complements real spawn cases; suppress watcher here.
    class NoThread:
        def __init__(self,**kw): pass
        def start(self): pass
    class Sender:
        closed=False
        raw=None
        def send_bytes(self,raw): self.raw=raw
        def close(self): self.closed=True
    monkeypatch.setattr(worker.threading,'Thread',NoThread)
    sender=Sender()
    worker._child_entry(sender,'id',command(tmp_path),fn)
    result=worker._decode(sender.raw,'id')
    assert sender.closed and result['error']==error


def test_child_oversize_refuses_whole_result(tmp_path,monkeypatch):
    class NoThread:
        def __init__(self,**kw): pass
        def start(self): pass
    class Sender:
        def send_bytes(self,raw): self.raw=raw
        def close(self): self.closed=True
    monkeypatch.setattr(worker.threading,'Thread',NoThread)
    monkeypatch.setattr(worker,'MAX_RESULT_BYTES',100)
    sender=Sender(); worker._child_entry(sender,'id',command(tmp_path),large)
    assert worker._decode(sender.raw,'id')['error']=='result_too_large'
    assert sender.closed


def test_broken_sender_closed_without_exception_echo(tmp_path,monkeypatch):
    class NoThread:
        def __init__(self,**kw): pass
        def start(self): pass
    class Sender:
        def send_bytes(self,raw): raise BrokenPipeError('private')
        def close(self): self.closed=True
    monkeypatch.setattr(worker.threading,'Thread',NoThread)
    sender=Sender(); worker._child_entry(sender,'id',command(tmp_path),echo)
    assert sender.closed


def test_thread_start_failure_is_explicit(tmp_path,monkeypatch):
    def bad_start(self): raise RuntimeError('PRIVATE')
    monkeypatch.setattr(worker.threading.Thread,'start',bad_start)
    pool=worker.ApplicationWorker(); oid=pool.submit(command(tmp_path))
    assert pool.poll(oid).error=='worker_start_failed'
    pool.close()


def test_process_start_setup_failure_is_explicit(tmp_path,monkeypatch):
    def bad_context(*a): raise OSError('PRIVATE')
    monkeypatch.setattr(worker.mp,'get_context',bad_context)
    with worker.ApplicationWorker() as pool:
        done=wait_for(pool,pool.submit(command(tmp_path)))
        assert done.error=='worker_start_failed'


def test_unconfirmed_shutdown_keeps_ownership_and_can_retry():
    class Process:
        alive=True
        killed=0
        closed=False
        def is_alive(self): return self.alive
        def kill(self): self.killed+=1
        def join(self,*a): pass
        def close(self): self.closed=True
    pool=worker.ApplicationWorker(); p=Process(); pool._process=p
    with pytest.raises(worker.ApplicationWorkerError,match='shutdown_unconfirmed'):
        pool.close(grace_seconds=0,kill_seconds=0)
    assert pool._closed and pool._process is p and p.killed==1
    p.alive=False; pool.close(grace_seconds=0,kill_seconds=0)
    assert p.closed and pool._process is None
