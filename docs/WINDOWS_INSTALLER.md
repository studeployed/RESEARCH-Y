# Windows installer

Open **RESEARCH-Y-Setup.exe** and choose **OK** to install or update the
application for the current user. Setup offers to open the application and
adds **RESEARCH-Y** to the Windows Start menu. The application uses the
Windows WebView2 runtime. The build carries its own x64 CPython, GUI libraries,
Excel and PDF readers, licence files and component inventory. The optional model
has a separate first-use download and confirmation.

Setup verifies its embedded image before extraction and switches the active
version only after extraction completes. Application versions are stored
under the user's local Programs folder. Projects, model files and Windows
credentials have separate locations. Running an earlier installer switches
back to its version. The same installer can be run again.

The Windows build uses the supported CPython interpreter on the build
machine and the .NET Framework compiler provided by Windows. Run
`python tools/windows_distribution/build.py build/RESEARCH-Y-Setup.exe`.
The Windows CI job tests clean installation and reinstallation. In a second
location it installs the Phase 3 baseline, creates a project with two approved
source queries, and upgrades that installation with the candidate. It compares
the project identity, strategy, run and both queries after opening them with
the upgraded application. The bundled native project/workbook lifecycle runs
on both installation paths.

Run **Windows standalone installer** on the final integrated revision. Its
artifact contains the tested executable and `verification.json`, including
the source commit, baseline commit, image identifiers, file size and SHA-256.
