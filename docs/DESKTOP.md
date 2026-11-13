# Local Windows application

The owner approved NiceGUI 3.18.0 and pywebview 6.2.1 as optional Phase 1
application dependencies on 12 November 2026. [Decision on issue #43](https://github.com/studeployed/RESEARCH-Y/issues/43#issuecomment-6835050119)

## Start the application

In a Windows development environment with Python 3.12 or 3.13 and Microsoft
Edge WebView2 Runtime, install the desktop package from the repository.

```powershell
python -m pip install ".[desktop]"
research-y
```

The launcher opens an integrated window. Choose **Open project folder**, or
enter a new project name and choose **Create project in folder**. The Windows
folder picker supplies the location. Recent projects appear on each launch.
Select the project and run explicitly. After moving a project, open its new
folder to update the local history. The usual research setup, preflight,
supervised source stages, results review and workbook controls use the same
trusted worker and SQLite services as the isolated graphical tests.

## Term variant review

In Research Setup, **Suggest term variants** proposes lexical changes to an
enabled atomic term. The draft shows each candidate and its reason. Edit
the wording before accepting or reject it. Only accepted terms appear in
the exact source-query preview. The separate strategy approval freezes the
term, deterministic origin, rule version, seed and rationale. Editing or
removing a seed withdraws its pending suggestions. This path works offline.

## Reviewed master results

Refresh the run board after recording publication comparisons. When the
current decisions connect every retained source in each publication and
distinguish every pair of separate publications, the board shows the group
counts, their arithmetic sum and the union across all retained groups. The
reconciled primary-run total also requires every approved primary query to
have reconciled identifiers and acquired metadata. An unstarted run has an
unknown total. A fully enumerated empty primary run has zero.

**Prepare reviewed master workbook** freezes the selected revision into a
separate export. Each publication row links to its original source and group
memberships. The workbook also carries the internal audit references for the
comparisons that establish its counts. It excludes provider titles,
accessions and abstracts. Use the existing save and file-inspection actions
to publish and verify it. **Prepare strategy workbook** continues to issue
the original strategy and count format.

Reversing an association or changing its evidence can withdraw a current
count. Previously issued workbooks preserve their original captured inputs.
Candidate discovery, unresolved pairs and abstract extraction keep their
own denominators. The calculation examines existing decisions and adds no
automatic matching rule or new review requirement.

## Source settings

Offline project inspection and workbook operations work with empty source
settings. For live work, create the following **Generic Credentials** using
Windows Credential Manager under your own Windows account, then restart the
application. PubMed uses the entry named `RESEARCH-Y/PubMed`, with the NCBI
contact email as its username and the optional API key as its password.
Starter uses `RESEARCH-Y/WoS-Starter` with the institutional API key as its
password. Only these two named entries are read. Source actions retain their
individual preview and confirmation controls.

## Acceptance evidence

`tests/test_desktop_launcher.py` checks the empty startup, explicit project
selection, scoped source settings and authenticated HTTP boundary. The
**Installed Windows desktop application** workflow installs the package and
exercises native creation, explicit run selection, workbook consent, save,
shutdown, folder relocation and inspection in a second process. The driver
provides the folder choice on the host in place of a person selecting it in
the OS dialog. The browser buttons, research workers, original SQLite files
and Excel readback are real. No provider requests occur in this workflow.
The isolated lifecycle suite continues to exercise native failure and recovery.
