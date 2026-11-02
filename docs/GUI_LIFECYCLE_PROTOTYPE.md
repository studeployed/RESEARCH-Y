# P1-06e2c — isolated graphical lifecycle prototype

2 November 2026. Continues issue #43 / #41 after owner-merged PR #45 at
`c94da2b8f038a4cb6e7dd30d0e2873921c296332`. The owner approved the
NiceGUI 3.18.0 / pywebview 6.2.1 feasibility experiment on 2 November.
That approval is not outstanding. Production adoption and merging remain
separate approvals. The authoritative specification is unchanged.

## What this experiment does

The optional files under `tools/gui_feasibility/` launch the approved frameworks
in disposable environments and temporary working directories. They import the
existing `ApplicationWorker` and `ApplicationCommand` from the checkout; they do
not change either module. The worker service is deliberately replaced **only in
the disposable experiment host** with a fixed, slow synthetic operation. No real
project, source query, retained report, export, credential or provider is opened.
The page says INCOMPLETE and never presents a synthetic operation as a search.

This creates an actual NiceGUI page and runs the actual supervised worker, but is
NOT the real project/open/run/export adapter. It is not an installer or release.
It explores ARCH-01/02/04, UI-05/06/10 and SEC-01/04/05 without claiming their
full acceptance or AT-22's 100,000-record performance requirement.

## Local request boundary

- Explicit IPv4 loopback listener, exact host and origin including port, reload
  and remote sharing disabled, proxy-header trust disabled, no access logging.
- A random one-use launch secret is supplied to the native window in a fragment,
  never an HTTP query. Bootstrap removes the fragment before redeeming it in an
  empty same-origin POST. It expires after 60 seconds; competing redemptions have
  one winner. No token is printed or included in uploaded evidence.
- An independent HttpOnly, SameSite=Strict session cookie authorizes the owner.
  Duplicate sensitive headers/cookies, incorrect/missing socket or mutation
  origins, cross-site/same-site fetch contexts and unowned requests are refused
  before NiceGUI routing or synthetic worker submission. Cookie names are
  port-specific; cookies themselves are not an operating-system security boundary.
- Only fixed synthetic actions, the page, and required framework asset/socket
  routes are allowed. No browser-selected filesystem path, upload, general file
  download, document route or static project directory exists. Mutation bodies
  must be empty. Paths with encoded traversal/backslashes are refused.
- Fixed security headers prevent caching, framing and nonlocal subresources.
  NiceGUI requires inline script/style support and Vue expression evaluation, so
  this is not represented as a strict script-content security policy. The native
  probe checks a malicious-looking **label** remains literal and unexecuted.

Upstream `nicegui/nicegui.py` at v3.18.0 configures permissive Socket.IO origins;
native mode alone is therefore not the application's origin/session guard.
The experiment guards both HTTP and WebSocket requests ahead of the framework.
This does not establish protection against hostile native code under the same
operating-system account or same-origin script execution.

## Executable scenarios and evidence

The dedicated workflow preserves all four core test configurations and the
existing four dependency probes. Its separate four-configuration matrix repeats
the approved dependency-resolution/hash-bound installation checks before launch.
No new direct framework, browser-driver or packaging dependency is introduced.
Each run's experimental transitive lock and release observations are recorded;
these are not reviewed production dependency locks.

**Transport on Windows/Linux, Python 3.12/3.13:** real HTTP requests and WebSocket
upgrade requests verify positive owner access, rejected forged access, one-use
bootstrap and no service calls from rejected requests. Two valid submissions
coalesce. A live server heartbeat is sampled during slow spawned work. Completion,
explicit service failure and interruption have separate expected final outcomes.

**Native on Windows, Python 3.12/3.13:** pywebview's Edge Chromium backend actually
loads the authenticated page. The probe uses pywebview's existing evaluation
facility, not an additional browser automation package, to inspect the document
and click a real NiceGUI button twice. It verifies the callbacks arrive through
the real framework connection, coalesce, and the rendered heartbeat advances
while work runs. It then closes the actual native window, both after completion
or failure and while work remains active.

The parent checks the application's final cleanup report and that its listener
is closed. The report must show the supervised worker reaped, supervisor stopped,
session revoked and the correct returned/failed/interrupted result. Timeout,
missing native prerequisites, absent evidence or cleanup failure FAIL the job;
Windows native execution is not silently skipped. The parent bounds runtimes and
cleans up only its owned child process tree after a failure. Private process logs,
launch tokens, packages, fonts, screenshots and temporary directories are not
uploaded. Failure evidence contains exception types and code locations, not
exception messages, source lines or absolute paths.

Local dependency-free tests cover the access gate, replay/concurrency, path and
header rejection, evidence fail-closed rules and child-environment isolation.
They do **not** import NiceGUI or prove native execution. Actual framework and
Windows outcomes must be read from the new workflow, not inferred from unit tests.

## P1-06e2d follow-on safety experiment

After owner-merged PR #46, the approved prototype is extended without changing
production dependencies or application services. On Windows the disposable
NiceGUI native-window spawn target is wrapped so pywebview's underlying WebView2
`NavigationStarting` event can cancel a navigation before it leaves the exact
loopback origin. The wrapper is experiment-only: it does not modify installed
NiceGUI/pywebview files or claim a cross-platform navigation policy.

The native scenarios deliberately attempt an HTTPS navigation to an external
invalid domain. The WebView2 event must set `Cancel=True`, record a bounded marker,
and the current URL must remain on the owner loopback origin before any worker
result is accepted. The initial `/bootstrap#<launch-token>` URL is exempted **once
only**, using exact matching with the trusted launch URL and no other fragment
exception. The initial PR #47 implementation failed on Windows because pywebview
6.2.1 dispatches `before_show` with no arguments unless the callback parameter
is named `window`, and because it rejected this required bootstrap fragment.
The corrected callback takes zero arguments, closes over the created window, and
registers the native veto before normal loading. Contract tests exercise that
real callback signature, exact bootstrap rules and replay/foreign-navigation
rejection. This complements the existing HTTP/Socket.IO guard; it does not make
arbitrary same-origin script execution safe.

A fourth Windows-native scenario starts slow synthetic work and then abruptly
terminates **only the prototype host process**, not its process tree. Immediately
before termination the driver inventories the host's current Windows descendants.
The existing worker parent-death watcher and the experiment's native-window
parent-death watcher must then make every captured descendant disappear without
`taskkill /T`. The listener must also close. Tree-kill is retained only as failure
cleanup after evidence collection, not as the pass mechanism. This observes the
native window, worker and any currently owned WebView2 helpers that are descendants
at the capture point; it is not a universal proof against later PID reuse or every
future packaging topology.

## Still open after this increment

- Full browser session/reconnection adversarial cases and production-grade
  navigation ownership. The Windows WebView2 veto is prototype evidence, not yet
  adopted production code. No real project should be wired in until the evidence
  from this increment has passed review.
- Real trusted new/open/path selection and the complete project/run/workbook flow,
  including retained-ID export recovery and real data/disk failure cases.
- Source-build inputs (including proxy-tools), reproducible built wheels, complete
  licence-file review and embedded frontend/native-runtime advisory inventory.
  A clean release feed or successful prototype does not close those gaps.
- Linux native desktop prerequisites are outside this Windows-native experiment;
  Linux validates the real browser-server transport, not a graphical window.
- Offline installation, complete offline asset enumeration, packaged Windows
  prerequisites, accessibility and representative large-dataset responsiveness.

Continue #43 rather than opening another placeholder issue. After the
navigation/abrupt-exit evidence is accepted, next is the trusted real-project
adapter plus the unresolved dependency/licence review, within the granted prototype approval. New
material dependencies, changed requirements, production adoption and merges remain
gated. Never treat an automatically successful-looking review summary as definitive
without its completion record, matching commit and individual receipt.

## Primary implementation references

- https://github.com/zauberzeug/nicegui/blob/v3.18.0/nicegui/ui_run.py
- https://github.com/zauberzeug/nicegui/blob/v3.18.0/nicegui/nicegui.py
- https://github.com/zauberzeug/nicegui/blob/v3.18.0/nicegui/native/native_mode.py
- https://github.com/zauberzeug/nicegui/blob/v3.18.0/nicegui/native/native.py
- https://pywebview.flowrl.com/guide/security.html
