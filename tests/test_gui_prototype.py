"""Dependency-free contract tests; actual framework/native evidence is separate."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.gui_feasibility.prototype_guard import LaunchSession, PrototypeGuard, BOOTSTRAP_HTML, SOCKET_PATH
from tools.gui_feasibility.run_prototype import validate_result, environment, ExperimentFailure

TOKEN = 'a' * 64
PORT = 18765
ORIGIN = f'http://127.0.0.1:{PORT}'.encode()
HOST = f'127.0.0.1:{PORT}'.encode()


def call(*, session=None, path='/', method='GET', kind='http', headers=(), body=b'',
         more=False, raw=None, query=b'', client=('127.0.0.1', 10)):
    session = session or LaunchSession(PORT, TOKEN)
    sent, reached = [], []
    async def app(scope, receive, send):
        reached.append(scope)
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.accept'})
        else:
            await send({'type': 'http.response.start', 'status': 200,
                        'headers': [(b'access-control-allow-origin', b'*'), (b'cache-control', b'public')]})
            await send({'type': 'http.response.body', 'body': b'ok'})
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': more}
    async def send(message):
        sent.append(message)
    scope = {'type': kind, 'path': path, 'raw_path': raw or path.encode(),
             'method': method, 'headers': [(b'host', HOST), *headers],
             'query_string': query, 'client': client}
    asyncio.run(PrototypeGuard(app, session=session)(scope, receive, send))
    return sent, reached


def owner():
    session = LaunchSession(PORT, TOKEN)
    cookie = session.redeem(TOKEN.encode()).split(b';', 1)[0]
    return session, cookie


def test_one_use_secret_not_in_public_bootstrap_or_repr():
    session, cookie = owner()
    assert TOKEN.encode() not in BOOTSTRAP_HTML and TOKEN not in repr(session)
    assert b'history.replaceState' in BOOTSTRAP_HTML
    assert not session.redeem(TOKEN.encode())
    assert session.authorized(cookie)
    assert not session.authorized(cookie + b'; ' + cookie)
    session.revoke()
    assert not session.authorized(cookie) and not session.redeemed


def test_concurrent_redemption_has_one_winner():
    session = LaunchSession(PORT, TOKEN)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: session.redeem(TOKEN.encode()), range(16)))
    assert sum(value is not None for value in values) == 1


def test_expired_launch_fails_closed_without_clock_sleep():
    now = [10]
    session = LaunchSession(PORT, TOKEN, clock=lambda: now[0])
    now[0] = 70
    assert session.redeem(TOKEN.encode()) is None
    assert not session.redeemed


@pytest.mark.parametrize('port', [0, 80, 1023, 65536, True, None, '8000'])
def test_invalid_port(port):
    with pytest.raises(ValueError): LaunchSession(port, TOKEN)


@pytest.mark.parametrize('token', ['', 'x' * 64, 'a' * 63, 'a' * 65, None, 3])
def test_invalid_launch_secret(token):
    with pytest.raises(ValueError): LaunchSession(PORT, token)


@pytest.mark.parametrize('cookie', [b'', b'wrong=unknown', b'researchy_probe_18765=invalid'])
def test_bad_cookies_never_reach_inner_application(cookie):
    session, _ = owner()
    sent, reached = call(session=session, headers=[(b'cookie', cookie)])
    assert sent[0]['status'] == 403 and not reached


@pytest.mark.parametrize('path', ['/', '/_probe/state', '/favicon.ico',
    '/_nicegui/3.18.0/static/vue.global.prod.js', '/_nicegui/3.18.0/components/label.js',
    '/_nicegui/3.18.0/libraries/test.js', '/_nicegui/3.18.0/esm/module/index.js'])
def test_owner_read_allowed_with_safe_response_headers(path):
    session, cookie = owner()
    sent, reached = call(session=session, path=path, headers=[(b'cookie', cookie)])
    assert sent[0]['status'] == 200 and len(reached) == 1
    response = dict(sent[0]['headers'])
    assert b'access-control-allow-origin' not in response
    assert response[b'cache-control'] == b'no-store'
    assert b"frame-ancestors 'none'" in response[b'content-security-policy']


@pytest.mark.parametrize('path', ['/private', '/docs', '/openapi.json',
    '/_nicegui/3.18.0/upload/1', '/_nicegui/3.18.0/download/1',
    '/_nicegui/3.18.0/dynamic_resources/1', '/_nicegui/3.18.0/static/../secret',
    '/_nicegui/3.18.0/static/%252e%252e/secret', '/_nicegui/3.18.0/static/\\secret',
    '/_nicegui/99/static/main.js', '/C:/private', '//private'])
def test_arbitrary_or_unsafe_paths_rejected_even_for_owner(path):
    session, cookie = owner()
    sent, reached = call(session=session, path=path, headers=[(b'cookie', cookie)])
    assert sent[0]['status'] == 403 and not reached


@pytest.mark.parametrize('extra', [
    (b'origin', b'https://foreign.example'), (b'origin', b'null'),
    (b'origin', ORIGIN + b'/'), (b'origin', b'http://127.0.0.1:9999'),
    (b'sec-fetch-site', b'cross-site'), (b'sec-fetch-site', b'same-site'),
    (b'host', b'foreign.example'), (b'HOST', HOST)])
def test_wrong_origin_host_and_duplicate_host_rejected(extra):
    session, cookie = owner()
    sent, reached = call(session=session, headers=[(b'cookie', cookie), extra])
    assert sent[0]['status'] == 403 and not reached


@pytest.mark.parametrize('header', [b'cookie', b'origin', b'sec-fetch-site', b'content-length', b'x-researchy-bootstrap'])
def test_duplicate_sensitive_headers_fail_closed(header):
    session, cookie = owner()
    headers = [(b'cookie', cookie)] if header != b'cookie' else []
    sent, reached = call(session=session, headers=headers + [(header, b'x'), (header.upper(), b'x')])
    assert sent[0]['status'] == 403 and not reached


@pytest.mark.parametrize('client', [None, ('192.0.2.1', 1), ('::1', 1)])
def test_only_explicit_ipv4_loopback_allowed(client):
    session, cookie = owner()
    sent, reached = call(session=session, headers=[(b'cookie', cookie)], client=client)
    assert sent[0]['status'] == 403 and not reached


def test_bootstrap_session_is_empty_same_origin_post_and_httponly():
    session = LaunchSession(PORT, TOKEN)
    headers = [(b'origin', ORIGIN), (b'x-researchy-bootstrap', TOKEN.encode())]
    sent, reached = call(session=session, path='/session', method='POST', headers=headers)
    assert sent[0]['status'] == 204 and not reached and session.redeemed
    cookie = dict(sent[0]['headers'])[b'set-cookie']
    assert b'HttpOnly' in cookie and b'SameSite=Strict' in cookie
    assert TOKEN.encode() not in cookie


@pytest.mark.parametrize('kwargs', [
    {'body': b'{}'}, {'more': True}, {'query': b'token=secret'},
    {'headers': [(b'x-researchy-bootstrap', TOKEN.encode())]},
    {'headers': [(b'origin', ORIGIN), (b'x-researchy-bootstrap', TOKEN.encode()), (b'content-length', b'1')]},
    {'headers': [(b'origin', ORIGIN), (b'x-researchy-bootstrap', TOKEN.encode()), (b'transfer-encoding', b'chunked')]},
])
def test_bad_bootstrap_requests_do_not_spend_secret(kwargs):
    session = LaunchSession(PORT, TOKEN)
    fields = {'path': '/session', 'method': 'POST',
              'headers': [(b'origin', ORIGIN), (b'x-researchy-bootstrap', TOKEN.encode())], **kwargs}
    sent, reached = call(session=session, **fields)
    assert sent[0]['status'] == 403 and not reached and not session.redeemed
    assert session.redeem(TOKEN.encode()) is not None


@pytest.mark.parametrize('path', ['/_probe/start', '/_probe/stop'])
@pytest.mark.parametrize('valid', [True, False])
def test_mutations_require_origin_and_empty_body(path, valid):
    session, cookie = owner()
    sent, reached = call(session=session, path=path, method='POST',
        headers=[(b'cookie', cookie), (b'origin', ORIGIN)], body=b'' if valid else b'{"path":"secret"}')
    assert sent[0]['status'] == (200 if valid else 403)
    assert bool(reached) is valid


@pytest.mark.parametrize('origin', [None, b'null', ORIGIN])
@pytest.mark.parametrize('authenticated', [True, False])
def test_websocket_origin_and_owner_cookie(origin, authenticated):
    session, cookie = owner()
    headers = [(b'cookie', cookie)] if authenticated else []
    if origin is not None: headers.append((b'origin', origin))
    sent, reached = call(session=session, path=SOCKET_PATH, kind='websocket', headers=headers,
                         query=b'EIO=4&transport=websocket')
    valid = authenticated and origin == ORIGIN
    assert sent[0]['type'] == ('websocket.accept' if valid else 'websocket.close')
    assert bool(reached) is valid


def test_revoked_session_blocks_socket_and_page():
    session, cookie = owner()
    session.revoke()
    assert call(session=session, headers=[(b'cookie', cookie)])[0][0]['status'] == 403
    assert call(session=session, path=SOCKET_PATH, kind='websocket',
        headers=[(b'cookie', cookie), (b'origin', ORIGIN)])[0][0]['type'] == 'websocket.close'


def example_result():
    return {'state': 'transport_host_stopped', 'synthetic_only': True, 'gui_acceptance': False,
        'shutdown': {'worker_reaped': True, 'supervisor_stopped': True, 'session_revoked': True,
        'operation_state': 'returned', 'operation_error': None,
        'result': {'synthetic': True, 'search_complete': False, 'audited_export': False}}}


@pytest.mark.parametrize('field', ['worker_reaped', 'supervisor_stopped', 'session_revoked'])
def test_driver_rejects_missing_cleanup_evidence(field):
    result = example_result()
    del result['shutdown'][field]
    with pytest.raises(ExperimentFailure): validate_result(result, 'transport', 'complete')


@pytest.mark.parametrize('field,value', [('gui_acceptance', True), ('synthetic_only', False), ('state', 'failed')])
def test_driver_rejects_overclaim_or_failure(field, value):
    result = example_result(); result[field] = value
    with pytest.raises(ExperimentFailure): validate_result(result, 'transport', 'complete')


def test_driver_wont_count_transport_as_native():
    result = example_result()
    validate_result(result, 'transport', 'complete')
    with pytest.raises(ExperimentFailure): validate_result(result, 'native', 'complete')


def test_driver_does_not_inherit_source_secrets_or_python_injection(tmp_path, monkeypatch):
    monkeypatch.setenv('RESEARCHY_WOS_STARTER_API_KEY', 'not-for-child')
    monkeypatch.setenv('GITHUB_TOKEN', 'not-for-child')
    monkeypatch.setenv('PYTHONSTARTUP', 'not-for-child')
    env = environment(tmp_path, PORT, TOKEN, False)
    assert all(key not in env for key in ('RESEARCHY_WOS_STARTER_API_KEY', 'GITHUB_TOKEN', 'PYTHONSTARTUP'))
    assert env['RESEARCHY_PROTOTYPE_LAUNCH'] == TOKEN
    assert 'RESEARCHY_PROTOTYPE_NATIVE_URL' not in env


def test_experiment_does_not_adopt_packages_or_accept_browser_paths():
    text = (ROOT / 'tools/gui_feasibility/prototype_app.py').read_text(encoding='utf-8')
    assert "host='127.0.0.1'" in text and 'reload=False' in text and 'on_air=None' in text
    assert 'proxy_headers=False' in text and 'access_log=False' in text
    assert 'worker.execute_command = synthetic_work' in text
    assert 'TemporaryDirectory' in text and 'create_file_dialog' not in text


def test_workflow_keeps_native_execution_explicit_and_failure_visible():
    text = (ROOT / '.github/workflows/gui-lifecycle-probe.yml').read_text(encoding='utf-8')
    assert 'os: [ubuntu-latest, windows-latest]' in text
    assert 'python-version: ["3.12", "3.13"]' in text
    assert '--native' in text and "if: runner.os == 'Windows'" in text
    assert '--require-hashes' in text and 'gui_dependency_probe.py verify' in text
    assert 'continue-on-error' not in text and 'pull_request_target' not in text
    assert 'persist-credentials: false' in text and 'contents: read' in text
    assert 'secrets.' not in text and 'private-process.log' not in text
    assert 'system_site_packages=False' in text
