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

### Optional Windows local assistant

The approved local package contains Qwen3-1.7B Q8_0 (1,834,426,016 bytes)
and the Windows x64 CPU build of llama.cpp b12360. Inference uses six CPU
threads. Allow about 1.9 GB for the installed package, plus space for the
downloaded files during installation. The supplied model is Apache-2.0
licensed. See the [model and licence](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/tree/90862c4b9d2787eaed51d12237eafdfe7c5f6077)
and the [official engine release](https://github.com/ggml-org/llama.cpp/releases/tag/b12360).

Use the official `llama-b12360-bin-win-cpu-x64.zip` and
`Qwen3-1.7B-Q8_0.gguf` with the installed Python package:

```text
python -m research_y.install_local_assistant --archive llama-b12360-bin-win-cpu-x64.zip --model Qwen3-1.7B-Q8_0.gguf
```

The installer verifies the archive, extracted native files and weights,
then installs the package under the user's local application data. Restart
the app after installation. **Ask local AI for terms** uses only the
selected seed. Review the wording of each returned proposal. **Use no AI**
turns inference off for this session. Core search and export are available
without the optional package. The model can suggest a related condition or
an overly broad term. A researcher decides which proposals enter the draft
and separately approves the exact query.

Each generation receipt retains the model and engine versions, weights and
prompt hashes, settings, proposed terms and UTC timestamp. Decisions link
to that receipt. The acceptance test can be run on a machine with the package
installed by setting `RESEARCHY_TEST_INSTALLED_MODEL=1` and running
`tests/test_optional_local_assistant.py` and `tests/test_local_study_review.py`.

In a selected publication's detail view, **Review study classifications**
shows the source-backed rules, original field references and the current
researcher decisions. Choose **Ask local AI** for a specific retained source
to request provisional design, original-research, format and population
labels. The project keeps the source paths, input hash, result and generation
settings. The model can misclassify original research even when it identifies
an RCT. Confirm or correct each dimension individually and provide the
supporting evidence. A model proposal alone leaves the classifications
untouched.

### Optional cloud term suggestions

For the Anthropic Messages provider, create a generic credential in Windows
Credential Manager named `RESEARCH-Y/Anthropic`. Its username is your chosen
provider model ID and its password is your API key. Restart the app.
Cloud mode starts disabled. **Choose optional cloud AI** enables previews
for the current project session. **Preview cloud term request** shows the
provider, model, exact seed-only JSON payload and potential token charges.
Only **Authorize and send this request** submits it. Each request needs a
fresh preview and confirmation. Opening another project resets the mode.
Returned suggestions use the normal individual researcher approval controls.
An offline transport fixture verifies this path. The [Messages API](https://platform.claude.com/docs/en/api/messages/create)
is the first supported cloud provider.

### Deterministic variants

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

## Specialist sources

The selected run's **Master results** panel captures a local snapshot of its
publication identities. Use **Search, filters and columns** to search original
titles, citation fields, identifiers or available abstract text. Combine
source, group and classification filters, sort by title, year or ID and
choose the displayed columns. Save an applied view by name to reuse it
after reopening the project. Results distinguish the number matched, the
entire snapshot and a separate bulk selection.

**Open source evidence** displays locally retained abstract text, original
citations, source hashes, group memberships and specialist evidence for the
chosen record. Refresh the snapshot after editing the project.

Select a run and open **Professional society sources** to suggest a library
from topic terms or add an official site. Record the pages and dates examined,
the outcome, and any limitations. A visit with a guidance discovery can be
used to save the document, its version and its explicitly stated society roles.

In a publication's detail view, **Conference abstract review** opens the
Windows file picker for a local JATS document. Select its original collection
source first. The preview lists twenty blocks per page, shows unresolved
blocks, and displays an individual abstract's text on request. Enter any
verified PDF page mapping independently of the printed page. Confirm the
selected blocks and local text retention before saving.
The optional PDF reader also accepts an individual passage on a selected
file page. See [conference extraction](CONFERENCE_EXTRACTION.md) for setup,
printed labels, exact text selection and supported documents.

**Crossref metadata** first inspects the DOI and cached evidence. A work
lookup requires a contact email and an explicit click. Missing or ambiguous
DOIs remain visible. Source records and primary counts keep their original
values when a lookup succeeds or fails.

## Source settings

Offline project inspection and workbook operations work with empty source
settings. For live work, create the following **Generic Credentials** using
Windows Credential Manager under your own Windows account, then restart the
application. PubMed uses the entry named `RESEARCH-Y/PubMed`, with the NCBI
contact email as its username and the optional API key as its password.
Starter uses `RESEARCH-Y/WoS-Starter` with the institutional API key as its
password. The optional cloud assistant separately reads its named Anthropic
entry as described above. Source actions retain their
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
