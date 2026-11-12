"""Windows WebView2 startup and guarded local navigation."""
from __future__ import annotations

import http.client
import multiprocessing
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit

from research_y.desktop.session import BOOTSTRAP_HTML, server_proof


def _record_stage(directory, name, value):
    if directory is not None:
        (directory / name).write_text(value, encoding='ascii')


def navigation_allowed(url: str, origin: str) -> bool:
    """Allow the exact local HTTP origin; never allow arbitrary URL fragments."""
    if url == 'about:blank':
        return True
    if type(url) is not str or type(origin) is not str:
        return False
    try:
        target, owner = urlsplit(url), urlsplit(origin)
    except (TypeError, ValueError):
        return False
    return (target.scheme == owner.scheme == 'http' and target.netloc == owner.netloc
            and target.username is None and target.password is None and not target.fragment)


def valid_initial_bootstrap(url: str, origin: str) -> bool:
    """Permit only a well-formed, one-use launch URL at the trusted local origin."""
    if type(url) is not str or type(origin) is not str:
        return False
    try:
        target, owner = urlsplit(url), urlsplit(origin)
    except (TypeError, ValueError):
        return False
    return (target.scheme == owner.scheme == 'http' and target.netloc == owner.netloc
            and target.username is None and target.password is None
            and target.path == '/bootstrap' and not target.query
            and re.fullmatch(r'[a-f0-9]{64}', target.fragment) is not None)


def wait_for_native_http_ready(origin: str, *, expected_proof: str | None = None, seconds: float = 8) -> None:
    """Verify the bootstrap HTTP route before the first WebView2 navigation.

    The pinned NiceGUI 3.18.0 native launcher checks only that a TCP socket is
    accepting connections. A cold Windows WebView2 can navigate before the
    application route actually responds; an internal browser error page does
    not automatically retry. This bounded local HTTP-only preflight never
    transmits the launch token, cookies or project data and does not redeem
    any session. It raises rather than masking a non-ready server.
    """
    target = urlsplit(origin)
    if (target.scheme != 'http' or target.hostname != '127.0.0.1'
            or target.username is not None or target.password is not None
            or target.path or target.query or target.fragment
            or target.port is None or not 1024 <= target.port <= 65535):
        raise ValueError('native_readiness_origin_invalid')
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        connection = http.client.HTTPConnection('127.0.0.1', target.port,
                                                timeout=min(1, max(0.1, remaining)))
        try:
            connection.request('GET', '/bootstrap',
                               headers={'X-ResearchY-Native-Readiness': '1'})
            response = connection.getresponse()
            body = response.read(8192)
            if (response.status == 200 and body == BOOTSTRAP_HTML and
                    (expected_proof is None or response.getheader('X-ResearchY-Server') == expected_proof)):
                return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(min(.05, max(0, deadline - time.monotonic())))
    raise RuntimeError('native_http_bootstrap_unavailable')


def install_native_navigation_veto(window, allowed_origin: str, marker_dir: Path | None,
                                   trusted_bootstrap: str) -> None:
    """Attach the actual WebView2 pre-navigation gate; fail if it is unavailable."""
    form = window.native
    browser = getattr(form, 'browser', None)
    control = getattr(browser, 'webview', None)
    if control is None or not hasattr(control, 'NavigationStarting'):
        raise RuntimeError('native_navigation_boundary_unavailable')
    pending_bootstrap = True

    def on_navigation_start(_, event):
        nonlocal pending_bootstrap
        uri = str(event.Uri)
        if uri == 'about:blank':
            return
        if pending_bootstrap:
            pending_bootstrap = False
            if uri == trusted_bootstrap:
                _record_stage(marker_dir, 'native-bootstrap-navigated', '1')
                return
        if navigation_allowed(uri, allowed_origin) and uri == allowed_origin + '/':
            _record_stage(marker_dir, 'native-home-navigated', '1')
        if not navigation_allowed(uri, allowed_origin):
            event.Cancel = True
            _record_stage(marker_dir, 'navigation-blocked', 'blocked')

    control.NavigationStarting += on_navigation_start


def create_guarded_window(real_create_window, allowed_origin: str, marker_dir: Path | None,
                          *window_args, **window_kwargs):
    """Use pywebview's zero-argument before_show callback contract.

    The initial authenticated bootstrap fragment is allowed exactly once, for
    the exact known URL only. All later fragment/navigation attempts are gated.
    """
    initial_url = window_kwargs.get('url')
    if not valid_initial_bootstrap(initial_url, allowed_origin):
        raise RuntimeError('unexpected_native_bootstrap')
    window = real_create_window(*window_args, **window_kwargs)
    _record_stage(marker_dir, 'native-window-created', '1')

    def before_show():
        _record_stage(marker_dir, 'native-before-show', '1')
        install_native_navigation_veto(window, allowed_origin, marker_dir, initial_url)

    window.events.before_show += before_show
    return window


def open_desktop_window(protocol, host, port, *args, **kwargs):
    """Windows spawn entry. Check the host before handing the launch fragment to WebView2."""
    from nicegui.native import native_mode
    import webview

    if protocol != 'http' or host != '127.0.0.1':
        raise RuntimeError('native_origin_invalid')
    origin = f'http://127.0.0.1:{port}'
    original = webview.create_window

    def create_window(*window_args, **window_kwargs):
        url = window_kwargs.get('url')
        if not valid_initial_bootstrap(url, origin):
            raise RuntimeError('unexpected_native_bootstrap')
        wait_for_native_http_ready(origin, expected_proof=server_proof(urlsplit(url).fragment))
        return create_guarded_window(original, origin, None, *window_args, **window_kwargs)

    def parent_watch():
        parent = multiprocessing.parent_process()
        if parent is not None:
            parent.join()
            os._exit(75)

    threading.Thread(target=parent_watch, daemon=True, name='researchy-native-parent-watch').start()
    webview.create_window = create_window
    try:
        return native_mode._open_window(protocol, host, port, *args, **kwargs)
    finally:
        webview.create_window = original
