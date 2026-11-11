# P1-06k4d5 — Native Windows GUI action acceptance with 100,000 retained original sources

**Authority:** version-controlled `RESEARCH-Y_SPEC.md` (unchanged). **Baseline:** owner-merged PR #87, main merge commit `1eb06a47485c6aa700883a4c03edee05d0b991c0` (11 November 2026).

## Gap and bounded scope

PRs #83–85 measured the original 100,000-record SQLite and supervised worker paths **without actual native graphical clicks**. PR #87 confirmed native Windows Graphical User Interface (GUI) actions on **132 original retained source records**. This increment joins these two separately proven boundaries: the *same* supervised GUI offer, explicit actor-entry and confirmation, lost-reply handling and read-only inspection operate on a genuine **100,000-original-source project**. This is a larger fixture for the previously approved experimental NiceGUI/pywebview adapter, not a change to production search, processing, source filtering, or research methods.

## Exact controlled fixture

The original `scripts.benchmark_original_project._seed` inserts **100,000 original retained source retrievals** and **100,000 original query/group memberships** into a versioned real SQLite project, with both PubMed and Web of Science representations. It creates **128 already independently audited provisional identities**, using the existing fixture-only writer. Those identities remain original baseline evidence and are not counted as GUI approvals.

For each of two **separate** disposable projects, the native Windows test clicks original host-selected, researcher-visible buttons; the Linux test exercises the existing guarded loopback test transport:

1. Open the original project and explicitly select the synthetic run. Preview exactly **128 new original source identities** in two original 64-record transactions while **99,872** remain unmaterialised.
2. Enter a synthetic researcher label and explicitly click **CONFIRM**. The original `ApplicationWorker` executes the production write-locked scope validator and commits 128 independent, review-required provisional identities; no title/digital-object-identifier candidate is automatically merged.
3. In the normal case, inspect the original source ledger **read-only**, showing **256 total provisional identities** and **99,744 remaining**.
4. In the separate lost-reply case, simulate loss of the worker reply **only after both original transactions commit**; assert no false successful receipt, a visible recovery-required notice, no silent replay and a separate read-only inspection showing the same durable totals.

The test runner independently reopens the SQLite project and verifies unchanged original source and membership SHA-256 digests; 100,000 original rows in each table; 256 distinct provisional identities, links and audit receipts; exact original linked source IDs; no implicit merging; `PRAGMA integrity_check` and foreign key integrity. It writes only bounded aggregate JSON evidence; no source text, bibliographic payload, credentials, project paths, database or browser logs are published.

`python -m tools.gui_feasibility.run_materialisation_window --directory <local-test-dir> --large` exercises the Linux guarded transport, while `--native --large` exercises native Windows; `--large` is a fixed **test-process-only** option, never a browser-selectable project size, source, worker fault, approval or ID. The existing 132-record PR #87 workflow and assertions are retained unchanged. Dedicated Python 3.12 Windows/Linux test jobs also run actual installed pinned experimental GUI candidates, with existing project Excel extras and environment checks.

## Important scientific and product limitations

**This is not AT-22 acceptance.** Only 128 **additional** original records undergo GUI confirmation, not all 100,000; the application does not paint or interactively paginate 100,000 publication *rows* in this test, and no representative usability/latency threshold for the full interface is established. Provisional identities are **not** proven globally unique publications; candidate decisions, deduplication, full-source retrieval, scientific classification, reporting completeness and search verification remain partial. No installer, product accessibility acceptance, external live provider calls, unattended materialisation, new dependencies, specification revision or implicit researcher permission is claimed.

The lost-reply experiment remains an intentionally disposable host-side fault injection and cannot be invoked by a browser or an ordinary user workflow. Automatic tests cannot substitute for real human researcher usability testing.

## Merge gate

The new Linux loopback and native Windows 100k workflow, the original Linux/Windows finite-window workflow, four Windows/Linux Python 3.12/3.13 core checks, graphical dependency/lifecycle checks, **definitive code review and then security review for the exact current HEAD** and every substantive finding must be verified. The owner alone authorises merging.
