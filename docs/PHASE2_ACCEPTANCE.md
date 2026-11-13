# Phase 2 specialist processing

Section 20 of the specification sets the gate at specialist extraction and
source provenance. The four roadmap units cover the eight scenarios below.
The evidence uses original synthetic research material, a real local model
benchmark and the installed Windows desktop. [Phase 2 tracking issue](https://github.com/studeployed/RESEARCH-Y/issues/121)

| Unit | Observed result | Tests and delivery |
|---|---|---|
| P2-01 · AT-04, AT-15, AT-20 | Two local models each answered 20 blind tasks in two output modes on Windows. The researcher can accept, edit or reject proposed terms. Only accepted terms reach the frozen query. With the model absent and cloud disabled the sample search produces a reviewed workbook with two publications and six memberships. | [Benchmark and results](BIOMEDICAL_BENCHMARK.md), [local integration](https://github.com/studeployed/RESEARCH-Y/pull/133), [cloud consent](https://github.com/studeployed/RESEARCH-Y/pull/135), `test_optional_local_assistant.py`, `test_cloud_terms.py`, `test_phase2_acceptance.py` |
| P2-02 · AT-11, AT-12 | Two abstracts in one supplement retain separate identities and within-abstract matches. XML positions, document checksums, printed pages and file-page links survive reopening. The PDF test admits two different passages on file page 2, printed S3. An unresolved XML block can be queued, examined and given a dated decision. | [Researcher workflow](CONFERENCE_EXTRACTION.md), [desktop](https://github.com/studeployed/RESEARCH-Y/pull/139), [PDF reader](https://github.com/studeployed/RESEARCH-Y/pull/140), `test_conference_jats.py`, `test_conference_project.py`, `test_conference_pdf.py` |
| P2-03 · AT-13 | A guideline without a DOI or journal citation reopens under its own title with official-site evidence and organisational roles. The native Windows test saves a society and reads the same entry after relocating the project. Version and companion links and explicitly confirmed journal manifestations have separate tests. | [Society sources](SOCIETY_SOURCES.md), [relationships](https://github.com/studeployed/RESEARCH-Y/pull/136), `test_society_sources.py`, `test_society_guidance_review.py`, `test_desktop_specialist_workbench.py`, `tools/desktop_lifecycle.py` |
| P2-04 · AT-14, AT-15, AT-16 | Design, original research, format, language and population keep independent evidence. Saved decisions survive reopening and can flag later conflicts. Filters retain uncertain cases and preserve source records. Missing DOI, missing Crossref fields, unavailable responses and interruptions retain the original and its query counts. | [Classification queue](https://github.com/studeployed/RESEARCH-Y/pull/137), [Crossref evidence](CROSSREF_ENRICHMENT.md), `test_study_classification.py`, `test_study_review_queue.py`, `test_crossref_metadata.py` |

## Combined project evidence

A single project begins with two reviewed primary publications. Adding two
individual conference abstracts and one society-only guideline produces five
inspectable publications after reopen. The primary count stays at two and the
same reviewed workbook revision remains valid. The whole-run count separately
reports the two retained abstracts. The integrated feature commit passed twelve
pull-request workflows and the merged commit passed the four Windows/Linux
Python jobs. [Integration review](https://github.com/studeployed/RESEARCH-Y/pull/138) · [Merged tests](https://github.com/studeployed/RESEARCH-Y/actions/runs/43489142552)

## Interpretation and coverage

The selected Qwen3-1.7B Q8_0 structured run recovered 4 of 17 expected terms
and all four classification dimensions in 2 of 12 cases. Local suggestions
require researcher review. The cloud consent path and Crossref failover were
tested with controlled transports. No paid cloud invocation was used.

Structured XML extraction handles explicit JATS sub-articles. Direct PDF
verification handles researcher-selected text on one page. Image-only and
multi-page abstracts require manual examination. These tests exercise a known,
permitted sample and do not establish the coverage of a live search.

Windows release packaging, broader end-to-end acceptance and the full export
scope remain in Phase 3. Issue #119 separately tracks the live cross-day
Web of Science observation. [Development roadmap](ROADMAP.md)
