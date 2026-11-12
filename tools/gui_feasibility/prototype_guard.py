"""Additional fixed test routes for the disposable graphical lifecycle harness."""
from research_y.desktop.session import BOOTSTRAP_HTML, SOCKET_PATH, DesktopGuard, LaunchSession


class PrototypeGuard(DesktopGuard):
    get_paths = DesktopGuard.get_paths | {'/_probe/state'}
    empty_post_paths = frozenset(('/_probe/start', '/_probe/stop'))
