"""Experimental loopback boundary. Synthetic feasibility only, not production auth.

The launch secret stays in a URL fragment, is redeemed once, then replaced by an
HttpOnly session cookie. No research data, arbitrary paths or credential APIs.
This does not protect against hostile native software running as the same user.
"""
from __future__ import annotations

import asyncio
from hmac import compare_digest
import re
import secrets
import threading
import time

BOOTSTRAP_HTML = b'''<!doctype html><meta charset="utf-8"><title>RESEARCH-Y prototype</title>
<p id="status">Opening isolated synthetic prototype...</p><script>
(async () => {
  const token = location.hash.slice(1);
  history.replaceState(null, '', '/bootstrap');
  const response = await fetch('/session', {method: 'POST', credentials: 'same-origin',
    headers: {'X-ResearchY-Bootstrap': token}});
  if (response.ok) location.replace('/');
  else document.getElementById('status').textContent = 'Launch authentication failed.';
})().catch(() => {document.getElementById('status').textContent = 'Launch failed.';});
</script>'''

SENSITIVE_HEADERS = {b'host', b'origin', b'cookie', b'sec-fetch-site',
                     b'x-researchy-bootstrap', b'content-length', b'transfer-encoding'}
ASSET_PREFIXES = tuple('/_nicegui/3.18.0/' + name + '/' for name in
                       ('static', 'components', 'libraries', 'resources', 'esm'))
SOCKET_PATH = '/_nicegui_ws/socket.io/'


class LaunchSession:
    def __init__(self, port: int, launch_token: str, *, clock=time.monotonic):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('invalid_port')
        if type(launch_token) is not str or not re.fullmatch('[a-f0-9]{64}', launch_token):
            raise ValueError('invalid_launch_token')
        self.host = f'127.0.0.1:{port}'
        self.origin = f'http://{self.host}'
        self.cookie_name = f'researchy_probe_{port}'
        self._launch = launch_token
        self._cookie = secrets.token_hex(32)
        self._clock = clock
        self._expires = clock() + 60
        self._lock = threading.Lock()
        self._used = False
        self._closed = False
        # Only safe stage names, never tokens, cookies, paths or request data.
        self._startup_stages = {
            'native_http_ready': False, 'bootstrap_served': False, 'session_attempted': False,
            'session_redeemed': False, 'page_accepted': False,
            'socket_allowed': False,
        }

    def note_startup_stage(self, stage: str) -> None:
        """Trusted guard records bounded session handshake progress only."""
        with self._lock:
            if stage not in self._startup_stages:
                raise ValueError('unknown_startup_stage')
            self._startup_stages[stage] = True

    def startup_stages(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._startup_stages)

    @property
    def redeemed(self):
        with self._lock:
            return self._used and not self._closed

    def redeem(self, token: bytes) -> bytes | None:
        with self._lock:
            if self._closed or self._used or self._clock() >= self._expires:
                return None
            if not compare_digest(token, self._launch.encode('ascii')):
                return None
            self._used = True
            self._launch = ''
            return (f'{self.cookie_name}={self._cookie}; Path=/; HttpOnly; SameSite=Strict').encode('ascii')

    def authorized(self, cookie: bytes) -> bool:
        with self._lock:
            if not self._used or self._closed:
                return False
            matches = []
            for field in cookie.split(b';'):
                key, sep, value = field.strip().partition(b'=')
                if sep and key == self.cookie_name.encode('ascii'):
                    matches.append(value)
            return len(matches) == 1 and compare_digest(matches[0], self._cookie.encode('ascii'))

    def revoke(self):
        with self._lock:
            self._closed = True
            self._launch = self._cookie = ''


class PrototypeGuard:
    def __init__(self, app, *, session: LaunchSession):
        self.app, self.session = app, session

    async def __call__(self, scope, receive, send):
        kind = scope.get('type')
        if kind == 'lifespan':
            return await self.app(scope, receive, send)
        if kind not in ('http', 'websocket'):
            raise ValueError('unsupported_scope')
        headers = {}
        for key, value in scope.get('headers', []):
            key = key.lower()
            if key in SENSITIVE_HEADERS and key in headers:
                return await self._reject(kind, send)
            headers[key] = value
        host = self.session.host.encode('ascii')
        origin = self.session.origin.encode('ascii')
        client = scope.get('client')
        path = scope.get('path', '')
        raw = scope.get('raw_path', path.encode('utf-8'))
        method = scope.get('method', 'GET')
        socket = kind == 'websocket' or path == SOCKET_PATH
        if (not client or client[0] != '127.0.0.1' or headers.get(b'host') != host
                or headers.get(b'origin', origin) != origin
                or headers.get(b'sec-fetch-site', b'none') not in (b'none', b'same-origin')
                or b'%' in raw or b'\\' in raw or '\\' in path
                or any(part in ('.', '..') for part in path.split('/'))
                or (scope.get('query_string') and path != SOCKET_PATH
                    and not path.startswith(ASSET_PREFIXES))):
            return await self._reject(kind, send)
        if (socket or method not in ('GET', 'HEAD')) and headers.get(b'origin') != origin:
            return await self._reject(kind, send)
        if kind == 'http' and path == '/bootstrap' and method == 'GET':
            # Test-only native readiness uses the same unauthenticated page
            # without consuming the launch secret or mimicking a browser load.
            self.session.note_startup_stage(
                'native_http_ready' if headers.get(b'x-researchy-native-readiness') == b'1'
                else 'bootstrap_served')
            return await self._reply(send, 200, BOOTSTRAP_HTML, content_type=b'text/html; charset=utf-8')
        if kind == 'http' and path == '/session' and method == 'POST':
            self.session.note_startup_stage('session_attempted')
            # A fixed empty request, not a general JSON/path endpoint.
            if headers.get(b'content-length', b'0') != b'0' or b'transfer-encoding' in headers:
                return await self._reject(kind, send)
            try:
                message = await asyncio.wait_for(receive(), timeout=2)
            except TimeoutError:
                return await self._reject(kind, send)
            if (message.get('type') != 'http.request' or message.get('body')
                    or message.get('more_body', False)):
                return await self._reject(kind, send)
            cookie = self.session.redeem(headers.get(b'x-researchy-bootstrap', b''))
            if cookie is None:
                return await self._reject(kind, send)
            self.session.note_startup_stage('session_redeemed')
            return await self._reply(send, 204, b'', extra=[(b'set-cookie', cookie)])
        if not self.session.authorized(headers.get(b'cookie', b'')):
            return await self._reject(kind, send)
        allowed = (
            (socket and path == SOCKET_PATH and method in ('GET', 'POST'))
            or (kind == 'http' and method in ('GET', 'HEAD') and
                (path in ('/', '/favicon.ico', '/_probe/state') or path.startswith(ASSET_PREFIXES)))
            or (kind == 'http' and method == 'POST' and path in ('/_probe/start', '/_probe/stop'))
        )
        if not allowed:
            return await self._reject(kind, send)
        if socket and path == SOCKET_PATH:
            self.session.note_startup_stage('socket_allowed')
        if kind == 'http' and path == '/' and method in ('GET', 'HEAD'):
            self.session.note_startup_stage('page_accepted')
        if path in ('/_probe/start', '/_probe/stop'):
            if headers.get(b'content-length', b'0') != b'0' or b'transfer-encoding' in headers:
                return await self._reject(kind, send)
            try:
                message = await asyncio.wait_for(receive(), timeout=2)
            except TimeoutError:
                return await self._reject(kind, send)
            if message.get('type') != 'http.request' or message.get('body') or message.get('more_body', False):
                return await self._reject(kind, send)
            async def empty_receive():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            receive = empty_receive
        async def safe_send(message):
            if message['type'] == 'http.response.start':
                excluded = {b'access-control-allow-origin', b'access-control-allow-credentials',
                            b'cache-control', b'content-security-policy'}
                original = [(k, v) for k, v in message.get('headers', []) if k.lower() not in excluded]
                message = {**message, 'headers': original + self._security_headers()}
            await send(message)
        await self.app(scope, receive, safe_send)

    def _security_headers(self):
        # NiceGUI's runtime needs inline scripts/styles and Vue expression eval.
        # This bounds subresources; it is NOT a native navigation veto or XSS proof.
        csp = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
               "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
               f"connect-src 'self' ws://{self.session.host}; "
               "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; frame-src 'none'; form-action 'none'")
        return [(b'cache-control', b'no-store'), (b'referrer-policy', b'no-referrer'),
                (b'x-content-type-options', b'nosniff'), (b'x-frame-options', b'DENY'),
                (b'content-security-policy', csp.encode('ascii'))]

    async def _reply(self, send, status, body, *, content_type=b'text/plain', extra=()):
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', content_type), (b'content-length', str(len(body)).encode())]
                               + self._security_headers() + list(extra)})
        await send({'type': 'http.response.body', 'body': body})

    async def _reject(self, kind, send):
        if kind == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
        else:
            await self._reply(send, 403, b'Forbidden')
