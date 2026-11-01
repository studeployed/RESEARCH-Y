# Graphical dependency decision — proposed, not adopted

Date: 1 November 2026. Scope: #43 under #41. Authority: ARCH-01–04, PROJ-01,
UI-01/05/06/10 and SEC-01–05. This document does not amend the specification or
approve dependencies. No GUI package, lockfile, installer or network server is
introduced by the accompanying worker increment.

## Recommendation

Evaluate NiceGUI **3.18.0** with pywebview **6.2.1** for the first local graphical
adapter. The upstream latest-release endpoints returned these non-prerelease
versions during this assessment: NiceGUI released 7 October 2026 and pywebview
released 15 April 2026. They are concrete candidates, not a claim that an arbitrary
future latest release is accepted. Recheck releases/advisories before installation.

NiceGUI is already the specification's preferred Python browser-style framework.
Its native extra supports pywebview. Keeping the business/inspection/export services
independent, with the new supervised worker, avoids tying durable operations to
page callbacks or framework-specific background pools. This is the recommended
approach, not approval to adopt the framework on main.

## Reviewed facts and dependencies

The candidate NiceGUI package declares the MIT licence and Python >=3.10,<4;
pywebview declares a BSD licence and Python >=3.8. These declarations are compatible
with the project's Python 3.12/3.13 targets, but do not demonstrate actual native
runtime compatibility. Windows pywebview declares pythonnet; its documentation
also describes .NET and WebView2 runtime requirements. These need a clean Windows
packaging/launch test with all prerequisites bundled or installed appropriately.

NiceGUI is not a small single-package addition: its declared Python dependencies
include FastAPI/Starlette/Uvicorn, Socket.IO, template/markup/JSON components and
network libraries. Its native extra accepts pywebview >=5.0.1,<7. pywebview brings
pythonnet on Windows plus bottle, proxy_tools and typing_extensions. Frontend
bundles and platform-specific/transitive licences must also be inventoried.

**Not yet verified:** a resolved complete dependency graph for each supported
platform/Python version, package-file hashes, full transitive licence inventory,
installed vulnerability audit, offline asset loading, frozen build or native
window interaction. No exact transitive pins are invented from broad upstream
ranges. Resolve and record these in an isolated feasibility environment before
proposing a production lockfile. Browser tooling, packaging tooling and optional
plot/table enterprise extras are not implicitly authorised by this proposal.

## Security implications

NiceGUI's run documentation/source defaults to loopback in native mode but all
interfaces in ordinary browser mode. Configure `host='127.0.0.1'` explicitly,
disable reload/remote sharing, and restrict every read/write/socket boundary by
session, origin, host and request authorisation. A local web server and a native
window are not, by themselves, authentication. pywebview documents session tokens
for protecting local request handlers against cross-site request forgery.

The latest NiceGUI release specifically fixes uploads being accepted through
disabled/hidden upload elements. The previous release series also fixed predictable
unauthenticated single-use downloads. Therefore hiding a control is not a security
boundary. The first adapter should expose no upload/static-directory/download
surface, use trusted native path selection and plain-text rendering, and test the
actual routes/socket protocol rather than assuming safety from UI configuration.
The pywebview security page currently lists no published advisories; this is NOT
proof of no vulnerabilities. Its support policy covers the latest release only.

## Approval boundary and objective next work

Owner approval requested: use these frameworks for an isolated, pinned feasibility
prototype and, if its gates pass, propose the optional GUI dependencies and thin
adapter in a separately reviewed pull request. Production adoption and merge are
not authorised by this document. No hosted service, separate end-user Python setup
or new AI/model dependency is proposed.

The feasibility must resolve/audit dependencies, verify local-only assets and
listener settings, enforce forged-session/origin/path rejection, and demonstrate
Windows launch/close/server-worker cleanup. Then wire real new/open, explicit run
selection, honest counts/strategy and stable-ID export prepare/resume/observe/cancel
through the existing services. New/open and framework security remain unfinished;
the worker is not a substitute for them. Keep #43/#41 open until evidence supports
their full acceptance contract.

## Primary sources consulted

- https://api.github.com/repos/zauberzeug/nicegui/releases/latest
- https://api.github.com/repos/r0x0r/pywebview/releases/latest
- https://raw.githubusercontent.com/zauberzeug/nicegui/v3.18.0/pyproject.toml
- https://raw.githubusercontent.com/r0x0r/pywebview/6.2.1/pyproject.toml
- https://raw.githubusercontent.com/zauberzeug/nicegui/main/nicegui/ui_run.py
- https://github.com/zauberzeug/nicegui/security
- https://github.com/r0x0r/pywebview/security
- https://pywebview.flowrl.com/guide/installation.html
- https://pywebview.flowrl.com/guide/security.html

Release endpoints were checked through the live repository connector because
cached package/search pages disagreed about the latest NiceGUI release. Upstream
metadata inspection is not a completed dependency-resolution/security audit.
