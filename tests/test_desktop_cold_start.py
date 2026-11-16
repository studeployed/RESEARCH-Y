import json
import asyncio
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from research_y.desktop.app import HOME_STARTUP, recover_missing_home


@pytest.mark.parametrize("redeemed, accepted, calls", [(True, False, 2), (True, True, 0), (False, False, 0)])
def test_missing_home_only_retries_after_redemption(redeemed, accepted, calls):
    window = Mock()
    session = SimpleNamespace(origin="http://127.0.0.1:42001", startup_stages=lambda: {
        "session_redeemed": redeemed, "page_accepted": accepted})
    asyncio.run(recover_missing_home(window, session, delay=0))
    assert window.load_url.call_count == calls
    if calls:
        window.load_url.assert_called_with(session.origin + "/")


@pytest.mark.parametrize("button, connected, interacted, attempts, reloads", [
    (False, True, False, 0, 1), (True, False, False, 1, 1),
    (True, True, False, 0, 0), (False, False, True, 0, 0),
    (False, False, False, 2, 0),
])
def test_authenticated_home_recovery(button, connected, interacted, attempts, reloads):
    node = shutil.which("node")
    if node is None:
        pytest.skip("JavaScript interpreter unavailable; native Windows acceptance runs separately")
    script = """
        const [button, connected, interacted, attempts] = JSON.parse(process.argv[1]);
        let callback, count = String(attempts), reloads = 0;
        const handlers = {};
        const setTimeout = fn => { callback = fn; };
        const document = {
            addEventListener: (name, fn) => { handlers[name] = fn; },
            querySelector: selector => button && selector === '[data-testid=desktop-open]' ?
                {getClientRects: () => [1], disabled: false} : null,
        };
        const window = {did_handshake: true, socket: {connected}};
        const location = {reload: () => { reloads++; }};
        const sessionStorage = {getItem: () => count, setItem: (_, v) => { count = v; }};
    """ + HOME_STARTUP + """;
        if (interacted) handlers.click({target: {closest: () => true}});
        callback();
        console.log(JSON.stringify([reloads, Number(count)]));
    """
    result = subprocess.run([node, "-e", script, json.dumps([button, connected, interacted, attempts])],
                            check=True, text=True, capture_output=True, timeout=10)
    assert json.loads(result.stdout) == [reloads, attempts + reloads]
