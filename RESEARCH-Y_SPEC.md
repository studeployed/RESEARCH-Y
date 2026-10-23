# RESEARCH-Y
## Software requirements and technical specification

| Document control | Value |
|---|---|
| Version | **1.0.0-draft.1** |
| Date | **23 October 2026** |
| Status | **Approved initial implementation baseline — 23 October 2026** |
| Canonical file | `RESEARCH-Y_SPEC.md` |
| Initial platform | Locally installed Windows desktop application |
| Scope | Literature discovery, retrieval, deduplication, classification, exploration and reporting |

> **Document authority.** This document consolidates the RESEARCH-Y requirements agreed during planning. It supersedes earlier draft wording wherever a subsequent decision changed the design. Implementation was authorised on 23 October 2026 after approval of version `1.0.0-draft.1`. This Markdown file is the version-controlled source of truth for development.

### Requirement terminology

**MUST** denotes a mandatory requirement for the completed initial product unless expressly phased below. **SHOULD** denotes the preferred implementation where feasible; any departure requires documentation. **MAY** denotes a future or optional capability. Numbered requirements are intended for traceability to implementation issues and tests.

### Acronyms

Application programming interface (API); artificial intelligence (AI); graphical user interface (GUI); large language model (LLM); Medical Subject Headings (MeSH); Preferred Reporting Items for Systematic Reviews and Meta-Analyses literature search extension (PRISMA-S); Peer Review of Electronic Search Strategies (PRESS); randomised controlled trial (RCT); systematic review and meta-analysis (SRMA); Web of Science (WoS); digital object identifier (DOI); PubMed identifier (PMID); PubMed Central identifier (PMCID); International Standard Serial Number (ISSN); International Standard Book Number (ISBN); Portable Document Format (PDF); Extensible Markup Language (XML); JavaScript Object Notation (JSON); Structured Query Language (SQL); Microsoft Excel Open XML Workbook (XLSX).

---

# 1. Purpose and scope

**RESEARCH-Y** is a locally operated, general-purpose literature discovery system for investigators undertaking broad searches of biomedical and related scholarly literature. It MUST accept a research theme and any number of researcher-supplied terms; help generate comprehensive terminology permutations; present the strategy for approval; retrieve results through authorised information sources; resolve duplicate records; capture accessible bibliographic metadata; classify retrieved publications; and provide an interactive master list and publication-ready reporting outputs.

The primary objective is **retrieval sensitivity and breadth**, not early precision. Search terms and concept groups are combined with Boolean **OR**. The system MUST NOT silently narrow an approved search by introducing Boolean AND, NOT, language/species restrictions, publication-type exclusions or controlled-vocabulary expansions.

The project MUST be designed independently of any previous literature-search software or codebase. Its architecture, terminology and requirements derive from this specification, not from another project's assumptions.

## 1.1 In scope for the completed initial product

1. Windows desktop installation with integrated local browser-style GUI; no manual Python/R/RStudio setup.
2. New/open/recent project interface, persistent local project directory and portable project archive.
3. Research theme entry; editable search groups and atomic terms; AI-assisted term generation, review and approval.
4. Broad OR-only searches in PubMed and WoS through the user's existing API credentials.
5. Professional society guidance discovery, including material available only on official society websites.
6. Individual conference abstract identification and bibliographic links to journal supplements or proceedings.
7. Retrieval integrity checks, resumability, metadata acquisition and optional free Crossref enrichment.
8. Auditable deduplication and a unique-publication master list.
9. Independent classifications for study design, original research, publication format, language and study population.
10. Interactive, filterable result tables; record inspection and manual review/correction.
11. Excel publication/reporting workbooks, bibliographic exchange export and documented reproducibility.
12. Local database durability, backups, project import/export, security safeguards and automated verification.

## 1.2 Explicitly out of scope for the initial product

- Structured AND/NOT relationships between concept groups, advanced proximity strategy builders or other precision-oriented search modes.
- Dedicated MeSH searches, vocabulary explosion or other controlled-vocabulary expansion.
- Automated determination that a conference abstract reports the same study as a later full paper.
- Eligibility screening, risk-of-bias appraisal, formal evidence extraction, meta-analysis or collaborative multi-reviewer workflows.
- Mandatory full-text acquisition, paid metadata services or promises of exhaustive searching on society websites that do not support it.
- Hosting the application as a shared cloud service or simultaneous multi-computer editing of the same live project.

The schema SHOULD allow later extension, without implementing these capabilities now.

# 2. Governing scientific principles

**METH-01 — PRISMA-S.** RESEARCH-Y MUST preserve information needed to report a search under PRISMA-S: named databases and other sources, exact executed strategies, limits (including confirmation when none were applied), search dates, per-source record counts, update methods, and deduplication methods.

**METH-02 — PRESS.** The strategy review interface MUST incorporate appropriate PRESS checks for the research objective, terminology coverage, logical operators, syntax, spelling, fields and limits. A checklist can be completed by the researcher; an optional named independent reviewer and review date SHOULD be recordable. Software validation MUST NOT be misrepresented as formal external peer review.

**METH-03 — No automatic narrowing.** The default search includes all languages, all species, all publication types and all dates unless the researcher explicitly chooses otherwise. No implicit exclusion may be applied to make a search smaller or faster.

**METH-04 — Transparent limits.** If a source does not support the requested field coverage, its actual search fields and limitation MUST be disclosed in the method and export. Indexed-record searching MUST NOT be described as searching full article text.

**METH-05 — Evidentiary integrity.** Unknown metadata, a failed retrieval and a genuinely negative search result are different states. Neither AI nor deterministic code may invent missing identifiers, page numbers, abstract text, links, classifications or source counts.

# 3. High-level technical architecture

| Component | Proposed architecture | Design rule |
|---|---|---|
| Language and processing | Python | No R/RStudio dependency |
| GUI | NiceGUI or equivalently capable Python browser-based interface | Native Windows launch, integrated lifecycle |
| Interactive tables | AG Grid or equivalent | Sorting, multi-filtering, selection, large-table usability |
| Persistence | SQLite with versioned migrations | Single authoritative local project database |
| Search jobs | Independently managed Python worker/service within application | Resumable, observable stages; GUI must remain responsive |
| Metadata and transformation | Python libraries; pandas/Polars where appropriate | Deterministic, tested transformations |
| Excel output | openpyxl or equivalent | Actual `.xlsx`, not renamed comma-separated data |
| Local LLM | Bundled llama.cpp-compatible inference component | No Ollama dependency or separate user-managed model server |
| Optional cloud LLM | Configurable provider API | Explicit opt-in, credentials and cost visibility |
| Packaging | Windows application with bundled runtime | No command-line setup required |

**ARCH-01.** Search connectors, query generation, processing, classifications and exports MUST be separated from GUI code. The application must be testable without launching the GUI.

**ARCH-02.** Network work and local model inference MUST NOT freeze or crash the interface. Jobs persist progress and intermediate checkpoints.

**ARCH-03.** The completed application MUST function without an LLM for basic search execution, metadata processing, deduplication, filtering and exports; AI assistance is additive rather than an operational dependency.

**ARCH-04.** Named products and frameworks are preferred technologies, not an instruction to commit before technical feasibility testing. Replacements must preserve requirements and be documented in a design decision record.

# 4. Project creation, storage and portability

**PROJ-01.** On launch, show **New Project**, **Open Project**, **Recent Projects** and **Import Archive**. New Project asks for project name and parent directory; Open Project accepts the project directory or index file.

**PROJ-02.** Projects are self-contained folders with a small human-readable index and separately stored data and documents. Proposed layout:

```text
ResearchProject/
├── project.ryproj            # JSON manifest: project UUID, name, format version
├── data/
│   ├── researchy.sqlite3     # Authoritative structured project database
│   └── raw/                  # Permitted original search payloads/checkpoints
├── documents/                # Permitted guidelines, supplements, files
├── exports/                  # Excel, bibliographic and method outputs
├── logs/                     # Diagnostics, with secrets redacted
└── backups/                  # Recoverable local snapshots
```

**PROJ-03.** Every project MUST have an immutable unique identifier, a versioned manifest, and project-relative file paths. Paths must remain valid after moving the entire project folder between computers.

**PROJ-04.** Structured data MUST be stored transactionally with automatic save and schema migrations. Interrupted or failed operations must not corrupt completed data.

**PROJ-05.** A **Project Archive** operation MUST create one portable `.researchy` file, containing a consistent SQLite snapshot, manifest and permitted supporting files. The archive is a transfer/backup snapshot, **not** a live edited database. On import, validate structure, version, checksums and safe extraction paths before creating a new working folder.

**PROJ-06.** The project MUST support recoverable backups and detection/prevention of multiple concurrent writers. Live databases SHOULD NOT be edited from multiple machines over synchronised cloud folders; users should transfer complete project archives instead.

**PROJ-07.** The application MUST show the current project, project location, most recent successful checkpoint and any pending or incomplete jobs.

# 5. Research question and search strategy

## 5.1 Input and term expansion

**SEARCH-01.** The researcher MUST be able to enter an overarching topic/theme, optional objectives and an unrestricted practical number of initial search groups and search terms. A specific question framework may be offered but cannot be mandatory.

**SEARCH-02.** Terms MUST be stored as **atomic terms** within named groups; groups are a reporting and organisational structure, not an instruction to intersect them. Terms can be added, edited, disabled, removed and reordered before approval.

**SEARCH-03.** An assisted expansion stage MUST propose appropriate synonyms, abbreviations, spelling, hyphenation and spacing variants, inflections and variants of multi-component expressions. For example, *right ventricle / right-ventricle* and *venovenous / veno-venous / veno venous*, combined where scientifically appropriate with *extracorporeal membrane oxygenation* and its variants.

**SEARCH-04.** The LLM MAY propose related scientific terminology, but each proposal MUST have a visible origin and concise rationale, and MUST be manually accepted, edited or rejected before becoming an approved search term. Deterministic lexical expansions must be separately identifiable from LLM-generated proposals. Duplicate/equivalent variants SHOULD be consolidated without losing provenance.

**SEARCH-05.** A publisher-friendly **search term strategy table** MUST display the group, initial term, approved expansions, individual atomic terms, status and any notes. No hidden expansion can enter an executed search.

## 5.2 Boolean logic and fields

**SEARCH-06.** The initial strategy MUST combine all active terms *within* each group using **OR**, and the union of groups using **OR**. Each group MUST be independently executable and countable. No user-facing or automatic AND/NOT option is required initially.

**SEARCH-07.** PubMed queries SHOULD use an explicitly tagged **All Fields** query for every approved literal/search expression, avoiding unwanted automatic search-term mapping, and must inspect the query translation actually accepted by PubMed. Phrase matching, quoting and punctuation behaviour MUST be tested; equivalent-looking terms must not be assumed equivalent without verification.

**SEARCH-08.** WoS Starter API queries MUST use the broadest supported suitable field: **Topic (`TS`)**, including title, abstract and indexed keyword fields. The interface/report MUST explicitly note that Starter Topic is narrower than WoS web-interface All Fields and does not search article full text.

**SEARCH-09.** The query compiler MUST escape terms appropriately, respect source syntax/length restrictions, generate the complete exact executable query per source/group, and show the query to the user before execution. Splitting a query due to provider size limits must preserve its logical union and be auditable.

**SEARCH-10.** No dedicated MeSH/controlled vocabulary search, expansion, publication-language exclusion, species exclusion or study-type filter is to be applied by default.

**SEARCH-11.** A pre-run verification screen MUST show terms and group counts, full source-specific queries, source coverage, user-selected limitations (or explicitly *none*), known-relevant-item checks where provided, and warnings about ambiguous/very broad terms and anticipated workload. Large results are grounds for warning and consent, **not** silent narrowing.

## 5.3 Run versioning

**SEARCH-12.** An approved search strategy is frozen as a versioned immutable snapshot when executed. Later edits create a new version, preserving the previous term set, queries, results and outputs.

**SEARCH-13.** For each source query, record execution date/time in Coordinated Universal Time (UTC), local display time, source/API, exact query string, parameters/limits, reported hit count, retrieval status, fetched record count and warnings/errors. Record API/client versions when material to reproducibility.

**SEARCH-14.** Pilot/count-only queries are explicitly distinguished from final retrievals. An unexecuted group cannot acquire a fictional count.

# 6. Primary and supplementary information sources

## 6.1 PubMed

**SRC-01.** Support National Center for Biotechnology Information (NCBI) PubMed E-utilities using the researcher's existing key where applicable. Configuration MUST include credentials, identifiable tool/user contact details where required, connection test, request pacing, retries and source-specific logging.

**SRC-02.** PubMed ESearch retrieval has an effective approximately 10,000-identifier window for a single query. For larger hit sets, the engine MUST automatically partition into non-overlapping reproducible subqueries (e.g., indexed-date intervals), recursively subdivide as needed, and verify the deduplicated identifier union against the intended result set. Implement defensively below the documented ceiling and detect backend variations.

**SRC-03.** Each split MUST retain its rationale, exact subquery, boundaries and counts. If the complete result set cannot be proven retrieved, mark the source/group **Incomplete** rather than **Complete**. Do not infer that a reported count has all been downloaded.

**SRC-04.** Fetch detailed accessible PubMed bibliographic metadata and abstracts, including identifiers, publication types, languages and species indexing when available. PubMed indexing can inform *classification* even though MeSH is not used to *construct searches*.

## 6.2 Web of Science

**SRC-05.** Use the user's institutional **WoS Starter API** access (5,000 requests/day tier, not 50/day trial) and validate actual entitlement/quota at connection time. Avoid assuming that an authorised API provides all fields shown in the WoS website.

**SRC-06.** Use `TS=` queries; paginate at the documented maximum of 50 records per request where supported. Estimate required requests, show quota consumption, pace requests, and resume over multiple days when necessary without re-fetching successful pages unnecessarily.

**SRC-07.** Record the WoS accession number and every available field. Where Starter does not return abstract text or other requested fields, use permitted enrichment from PubMed, Crossref or original publication pages. Mark residual gaps; never invent them.

**SRC-08.** If source-side paging/limits or collection changes make exhaustive retrieval impossible, clearly label the dataset incomplete or reconciliation required. Preserve the count and available results rather than declaring success.

## 6.3 Professional society sources

**SRC-09.** RESEARCH-Y MUST help identify relevant professional societies and permit researcher confirmation, editing and addition to a per-project society directory.

**SRC-10.** Search documented official guideline/document libraries and other accessible society pages. Capture guidance published only on a society website, published in an affiliated journal/supplement, published in an unrelated journal, or jointly issued by multiple societies.

**SRC-11.** Record each site's URL, search/browse method, terms, pages/dates examined, retrieval date, discovery outcome, and completeness/limitations. Where automated search is unavailable, offer a **manual review/import task**; never claim a complete automated society search without evidence.

## 6.4 Free metadata enrichment and manual import

**SRC-12.** Crossref's free public/polite REST API MAY be used for targeted DOI metadata enrichment if implementation remains straightforward and without fees. Cache results, provide a configured contact email, honour published response rate/concurrency headers, and preserve the original metadata and provenance. Do not use a paid tier.

**SRC-13.** Crossref enrichment alone MUST NOT silently add search-result publications or alter database hit counts. It enriches existing records; a distinct discoverable record can be added only through a documented source/import workflow.

**SRC-14.** Support manual entry and common bibliographic export formats for additional sources or recovery from API limitations. All manually imported records must retain distinct provenance and should be eligible for normal deduplication and classification.

# 7. Retrieval reliability, progress and recovery

**RUN-01.** Searching MUST run as a persistent job with clearly shown stages: query validation, count retrieval, record pagination, metadata fetching, enrichment, source reconciliation, deduplication, classification and export preparation.

**RUN-02.** Every job and component query MUST have explicit statuses, at minimum: `pending`, `running`, `paused`, `completed_verified`, `completed_with_warnings`, `incomplete`, `failed` and `cancelled` where applicable.

**RUN-03.** An accurate progress display MUST show available reported counts, records actually retrieved, pages or batches completed, retries, quota headroom and failure reason. Estimated total work can be displayed but must be identified as an estimate.

**RUN-04.** Respect retryable network errors, backoff headers, quotas and provider terms. Prevent unbounded retry loops. Persist checkpoints so an interrupted run resumes from the last verified point.

**RUN-05.** Do not mark a search completed/verified solely on an HTTP success response. Required checks include retrieval count reconciliation, uniqueness, pagination coverage, source errors and any provider-specific completeness checks.

**RUN-06.** A query can be paused without discarding fetched results. Users can close and reopen the application and resume; continued unattended processing while the application is closed is **not** required initially.

**RUN-07.** Original API payloads or a sufficiently complete, legally retained representation SHOULD be stored for reprocessing, along with error and audit logs, without embedding credentials.

# 8. Core record model and metadata

## 8.1 Distinct entities

**DATA-01.** The database MUST distinguish:

1. **Project** — research theme, configuration and settings.
2. **Strategy Version** — approved groups, terms and compiled queries.
3. **Search Run** — dated execution of an approved strategy version.
4. **Source Retrieval** — a database hit or imported source record, with its original metadata.
5. **Publication** — the unique bibliographic item appearing as one row in the master results.
6. **Source/Group Membership** — many-to-many associations showing all sources, search groups and runs in which a publication occurred.
7. **Container** — journal supplement, proceedings volume or other publication housing one or more abstracts.
8. **Organisation** — society issuing, collaborating on or endorsing a guideline.
9. **Classification** — original-research status, designs, format, language/species, and decision provenance.
10. **Document/Attachment** — original permitted source file or link, with location and provenance.
11. **Audit Event** — merges, splits, metadata edits, AI use, overrides, imports, exports and migrations.

**DATA-02.** The master table MUST represent **unique publications**, not unique studies. Multiple retrieval records for the same publication link to one publication. Distinct publications are not merged merely because they appear to address the same study or share a container.

## 8.2 Bibliographic fields

**DATA-03.** Gather all accessible/publicly available and lawfully retainable bibliographic metadata, including where available:

- Complete title; authors and contributor identifiers; affiliations; publication dates and year.
- Journal/publisher/source title, ISSN/ISBN, volume, issue, supplement, pages, electronic article identifier.
- DOI, PMID, PMCID, WoS accession number and other source-specific identifiers.
- Full available abstract text, language, author/indexer keywords and database-supplied document-type tags.
- Conference title/date, abstract/poster/presentation number, proceedings or supplement link and page locator.
- Guideline authoring organisations, document version/status, society page and publication links.
- Source record identifiers, date first retrieved, metadata updates, available full-text/document URLs and rights restrictions.

**DATA-04.** Keep original source values, normalised chosen display values and enrichment values separate. Each derived/chosen value MUST be traceable to a source, method, timestamp and (where relevant) user or model.

**DATA-05.** Missing, not available from source, not yet queried, extraction failed, and conflicted metadata MUST be distinguishable. A title or DOI conflict is not resolved by silently discarding a source value.

**DATA-06.** Source URLs are not proof of downloadable/openly licensed content. Retain abstracts/documents and export them only as allowed by source terms; otherwise retain location, citation and availability status.

# 9. Deduplication

**DUP-01.** Deduplicate a publication across PubMed, WoS, society sites, imports and repeated groups/runs while preserving every contributing source retrieval and group membership.

**DUP-02.** Use stable identifiers (e.g., exact verified DOI, PMID, WoS accession mapping) with conservative normalisation and bibliographic comparison of title, authors, date, source and pagination. A DOI or supplement identifier is not automatically the identifier of an individual contained abstract.

**DUP-03.** Distinguish `automatic_high_confidence`, `review_required`, `confirmed_match` and `rejected_match`; no irreversible silent merge. Reviewable evidence and confidence/rule MUST be exposed to the user.

**DUP-04.** Users MUST be able to merge, split or reverse a proposed deduplication, with all original source records preserved. Subsequent runs must respect previously confirmed decisions unless new conflicting evidence requires review.

**DUP-05.** Never merge two distinct abstracts because they share supplement DOI, title, journal, first page or container. Never infer that a conference abstract and a full paper are duplicates merely because they describe the same study; linking these as study reports is outside initial scope.

# 10. Conference abstracts and containing supplements

**CONF-01.** Identify individual conference abstracts and separate them from generic proceedings or supplement collection records, where accessible metadata/source material permits.

**CONF-02.** If one collection contains multiple matching abstracts, create distinct individual abstract records. Terms distributed across *different* abstracts MUST NOT be combined to claim that any one abstract meets a search query. Preserve the original collection-level retrieval and disclose the number of extracted individual abstracts.

**CONF-03.** For every identified abstract, capture available exact title, authors, text, conference name/date, abstract/poster/presentation number, published pages and direct individual link. For a PDF, capture the **printed page reference** and separately the **PDF file page index** where they differ; generate a page-link when supported.

**CONF-04.** Independently identify the **containing journal supplement/proceedings**: journal title, year, volume, issue, supplement designation, title, DOI/identifier where applicable, table-of-contents/landing-page link and full-supplement link where available.

**CONF-05.** Individual abstract identifiers MUST NOT be confused with supplement identifiers. An unresolved abstract identity, page, link or text must be flagged rather than guessed.

**CONF-06.** The extraction process SHOULD provide confidence/evidence, a review queue for uncertain identifications, and a source-document locator sufficient for a researcher to find and verify the abstract.

# 11. Professional society guidance

**GUIDE-01.** Identify and explicitly classify **professional society guidelines**, including documents available outside indexed journals.

**GUIDE-02.** Preserve distinctions among clinical practice guidelines, consensus statements, position statements, practice recommendations and related document types; a guideline can carry multiple relevant labels but should not be indiscriminately relabelled as original research.

**GUIDE-03.** Record issuing/authoring societies separately from collaborating societies and endorsing societies. Do not infer endorsement from publication in a society-affiliated journal.

**GUIDE-04.** Capture title, authors/body, edition/version, issue date, update/supersession statements, society landing page, document link, journal citation (if any), supplement details and all accessible identifiers.

**GUIDE-05.** One guideline version available from the society and a journal is one unique publication where bibliographically warranted, with multiple source/manifestation links. Distinct guideline revisions and companion summaries remain distinct but can be related explicitly.

# 12. Publication classifications and review

## 12.1 Independent dimensions

**CLASS-01.** Every publication MUST support separate classification dimensions:

| Dimension | Examples / accepted values |
|---|---|
| **Original research** | `yes`, `no`, `unclear` |
| **Study design / document type** | RCT; non-randomised interventional study; prospective/retrospective cohort; case-control; cross-sectional; case series; case report; diagnostic study; qualitative study; systematic review; meta-analysis; SRMA; scoping review; narrative review; guideline; consensus statement; protocol; editorial/commentary; other; unclear |
| **Publication format** | Full journal article; conference abstract; conference paper; journal supplement item; society web document; preprint; book/chapter; other |
| **Publication language** | English; non-English; multilingual; unknown; with actual language code/name where available |
| **Population** | Human; non-human; mixed human/non-human; not applicable; unclear, with `explicit_non_human_only` derived conservatively |
| **Review status** | Machine-provisional; requires review; user-confirmed; user-corrected |

**CLASS-02.** “Original research” means reporting primary empirical observations or a new analysis of existing data. A study reporting a genuinely new secondary data analysis qualifies; reviews and meta-analyses remain evidence synthesis and are **not** tagged as original research under this operational definition. Study protocols without study findings require their own document-type label and should not be assigned original-research status without evidence of results.

**CLASS-03.** Study design and document-type tags MAY be multiple. Format is separate from design: an RCT reported as a conference abstract retains **RCT** as design and **conference abstract** as format.

**CLASS-04.** Language and species exclusions are **post-retrieval filters only**. Explicitly non-English or exclusively non-human records may be hidden from a filtered view or selected export; ambiguous records must remain unless explicitly filtered. These actions MUST NOT change original database counts or delete master records.

## 12.2 Automated and manual classifications

**CLASS-05.** Use explicit source metadata and deterministic rules first. Local/optional cloud LLM interpretation MAY supplement uncertain study-design/original-research classifications from titles and abstracts, but cannot invent evidence. Show provenance, model/rule, explanation or supporting text where available, and uncertainty.

**CLASS-06.** Provide a review queue for ambiguous classifications, missing abstracts, apparently conflicting source tags and likely deduplication errors. All categories must be editable or confirmable by the user, with audit history.

**CLASS-07.** User-confirmed values persist through reclassification and search updates; new evidence may flag a conflict, never silently overwrite them.

# 13. Integrated AI and terminology assistance

**AI-01.** The GUI MUST offer three operating modes: **Built-in local AI (default when installed)**, **Optional cloud AI**, and **No AI**.

**AI-02.** The preferred local inference component is a directly integrated llama.cpp-compatible engine managed by RESEARCH-Y. No Ollama process, terminal command, separate user-managed runtime or independently launched model service is required.

**AI-03.** The installation MUST manage model availability gracefully: model bundled or downloaded during setup/first use, with clear storage requirement, licence information, origin and checksum verification. Hardware detection SHOULD choose supported acceleration when present and fall back to the central processing unit.

**AI-04.** Local model selection is **not yet fixed**; benchmark candidate models against a curated biomedical synonym/term-permutation set and study-type classification test set on target Windows hardware. Prioritise accuracy and reproducibility over general conversational performance.

**AI-05.** Cloud mode is explicit opt-in, configured with the user's credentials. Display what data would be transmitted, provider and model, potential usage costs and the active project mode. No cloud transmission without the user's authorisation.

**AI-06.** Retain model name/version, prompt template and version, parameters where material, input/response hashes or permitted texts, proposed terms, approvals and timestamps. AI suggestions are never incorporated into an approved executed query without researcher action.

**AI-07.** AI MUST NOT independently issue final database searches, determine final counts, mark incomplete retrieval as complete, invent metadata, or silently merge publications. Those operations are performed by validated deterministic logic, with explicit user review where uncertain.

# 14. User interface and workflow

**UI-01 — Project Launcher.** Create, open, recent and import project; application/settings access.

**UI-02 — Research Setup.** Theme/objectives, search groups and initial terms, selected sources, society list and any user-chosen limits.

**UI-03 — Terminology Review.** Group/term/variant table; AI and rule suggestions; accept/edit/reject; exact original versus generated term provenance.

**UI-04 — Strategy Preview.** Display exact PubMed/WoS queries per group, pilot counts, PRESS checks, anticipated source workload and approval control.

**UI-05 — Execution Monitor.** Persistent staged jobs, source/group counts, pages fetched, quota, status, warnings, pause/resume/retry.

**UI-06 — Results Summary.** Per-source and per-group counts, retrieval and deduplication reconciliations, clear overall unique result count, society search coverage and warnings.

**UI-07 — Master Results.** One row per unique publication; combined text search, sorting, faceted filters, saved views, visible-column selection, bulk selection and export of complete versus filtered results.

**UI-08 — Record Detail.** Full abstract and metadata; identifiers; click-through links; group memberships and source records; classification status; supplemental conference/guideline data; manual correction; audit provenance.

**UI-09 — Review Queues.** Potential duplicates, incomplete conference extraction, unresolved society source tasks, uncertain classifications and metadata conflicts.

**UI-10 — Export Centre.** Publication-ready Excel outputs, bibliographic file export, run version selection, logs and full project archive.

The interface MUST avoid fake controls: each exposed action is implemented or clearly disabled with explanation. Important operations MUST communicate actual success/failure rather than optimistically reporting success.

# 15. Counting and reconciliation model

**COUNT-01.** Counts must use explicitly named denominators. The following are separate:

- `reported_matches(source, group, run)` — count reported by the source for that group's approved query (or equivalent partitioned union).
- `retrieved_source_records(source, group, run)` — unique retrieved provider identifiers, regardless of duplicate appearances in API pages or query partitions.
- `group_unique_publications(group, run)` — publications deduplicated across sources within that group.
- `source_unique_records(source, run)` — distinct source records across *all groups* for that source.
- `global_unique_publications(run)` — unique publications across *all groups and all sources* in that run.
- `extracted_individual_abstracts(run)` — separately identifiable abstracts recovered from container-level records, without pretending they were original independent API hits.

**COUNT-02.** The sum of group-level counts may exceed the global unique publication count because one paper may match several groups. Never label the sum as the final deduplicated result. Provide both the arithmetic sum (clearly labelled) and the global union.

**COUNT-03.** For each source/group, compare reported matches to retrieved identifiers and expose unmatched discrepancies. Partitioned searches must count the **unique union**, not double-count overlapping partition calls. Society sources with no total-hit count should report `not available`, not zero.

**COUNT-04.** The results summary MUST show at minimum group, PubMed reported/retrieved, WoS reported/retrieved, unique publications within group, and flags for incomplete sources. Separate subtables describe society-site findings and manually imported material. A clearly labelled footer gives unique per-source totals, group-count sums and the final global unique-publication count.

**COUNT-05.** A final run can be labelled **Verified Complete** only if all mandatory source/group retrievals have passed reconciliation and material source limitations are disclosed. A partial run remains exportable but all reports/exports must prominently state that it is incomplete.

# 16. Search history, provenance and reproducibility

**AUDIT-01.** Preserve an immutable history of each approved strategy version and executed run: exact submitted query text, source parameters, source/platform, dates, reported counts, retrieved IDs, errors, processing versions, manual changes and source-coverage decisions.

**AUDIT-02.** A rerun/update MUST preserve its earlier version and allow a comparison: newly discovered publications, retained publications, absent-from-new-run publications (not necessarily withdrawn), metadata changes, and prior annotations carried forward.

**AUDIT-03.** Record every deduplication merge/split/override, classification correction, document attachment, society-site search and manual import. Logs MUST support a human-readable audit view and machine-readable export.

**AUDIT-04.** PRISMA-S output MUST distinguish items actually complied with from items not applicable, not undertaken or awaiting verification. PRESS completion must likewise distinguish programmatic checks from actual peer review.

# 17. Exports and reporting

**EXPORT-01.** The primary export MUST be a formatted `.xlsx` workbook, with these proposed worksheets:

1. **Search Summary** — group/source counts and reconciled totals.
2. **Search Terms** — theme, groups, initial terms, accepted atomic expansions and provenance.
3. **Executed Queries** — full exact strategy for each source/group/partition, parameters, dates and outcomes.
4. **Master Results** — unique-publication rows, identifiers, abstracts (where permitted), classification, metadata, links and memberships.
5. **Conference Abstracts** — abstract identifiers, source text/location and full containing-supplement reference/link.
6. **Society Guidelines** — issuing societies, document type/version, official links and journal references.
7. **Deduplication Audit** — contributing source records, decisions, confidence and review status.
8. **Search Log** — execution and exceptions, including incomplete/unavailable sources.
9. **Data Dictionary / Methods** — field definitions, status codes, software/method versions and PRISMA-S reporting notes.

**EXPORT-02.** Provide a separately selectable **publication-ready search strategy and count workbook** with concise, clean tables suitable for manuscript supplementary materials.

**EXPORT-03.** Exports MUST distinguish entire master dataset from currently filtered subset and clearly label run/version, status, dates, denominators and filtering criteria. Filtering must not mutate search counts.

**EXPORT-04.** Excel exports SHOULD include readable typography, consistent styles, table filters, frozen headers, sensible widths and clickable valid hyperlinks. Very large data must be divided across sheets/files where required by Excel row/cell limits rather than silently truncated. Untrusted cell text must be escaped to avoid spreadsheet formula injection.

**EXPORT-05.** Support a suitable reference-manager exchange format (e.g., Research Information Systems [RIS] and/or BibTeX), while documenting metadata that cannot be represented and retaining the native database as the complete record.

**EXPORT-06.** Outputs should be sufficiently detailed to reproduce and audit searches, without falsely claiming that standard spreadsheet exports constitute completion of a full PRISMA systematic review.

# 18. Security, privacy, licensing and recoverability

**SEC-01.** Default to local data storage and local AI processing. Credentials are machine/user settings, not project data; store via operating-system secure credential storage where supported, and redact from project logs, diagnostic bundles and archives.

**SEC-02.** Cloud AI is opt-in with a clear data-transfer notice. The app MUST not transmit full project contents unnecessarily.

**SEC-03.** Respect source terms, website access controls, licence restrictions, download permissions, rate limits and robots guidance where applicable. Do not bypass paywalls or represent inaccessible material as extracted.

**SEC-04.** Archive import, link handling and downloaded files MUST defend against path traversal, unsafe filenames and untrusted content. Project migrations create a recoverable pre-migration snapshot and fail safely.

**SEC-05.** Provide understandable network/authentication error messages, recoverable job checkpoints and a diagnostic report without secrets.

# 19. Quality gates and acceptance tests

The following scenarios are **mandatory acceptance tests for the completed initial product**. Deterministic tests use controlled fixtures; real-source smoke tests are used to verify external integration under permitted credentials. Pass/fail, expected/actual outcomes and evidence must be recorded.

| ID | Acceptance scenario | Pass condition |
|---|---|---|
| AT-01 | Create → close → reopen project | All terms, results, annotations and jobs persist |
| AT-02 | Move project folder to a new path | Index, database and relative document links work |
| AT-03 | Export/import `.researchy` | Consistent project snapshot restores without loss |
| AT-04 | Term expansion and approval | Unapproved AI suggestions never enter queries |
| AT-05 | OR query compilation | Exact set union retained within and across groups; no hidden AND/NOT |
| AT-06 | PubMed All Fields translation | Generated query accepted and does not cause unwanted MeSH mapping |
| AT-07 | PubMed >10,000-hit fixture/live verification | Partitions reconcile; no silent truncation |
| AT-08 | WoS 50-record pagination and quota | No skipped page, quota-aware pause/resume and verified counts |
| AT-09 | Interrupted retrieval | Resume from checkpoint with no data loss/false completion |
| AT-10 | Same publication found in two sources and groups | One master row; all memberships retained |
| AT-11 | Different abstracts in one supplement | Separate abstract rows; no false deduplication |
| AT-12 | Abstract locator | Printed page, PDF page and supplement URL distinct when available |
| AT-13 | Society-only guideline | Captured, labelled and linked despite no journal/DOI |
| AT-14 | Language/species classification | Explicitly non-English/non-human-only filterable without deletion |
| AT-15 | Study-design/original-research classification | Independent labels, uncertainty and user overrides persist |
| AT-16 | Crossref missing/unavailable metadata | Original record preserved, gap flagged, counts unchanged |
| AT-17 | Repeated search version | Historical runs immutable; differences and statuses clear |
| AT-18 | Excel export | Correct counts, full rows, functioning filters/links; no silent truncation |
| AT-19 | Partial/failing source | Cannot be displayed as verified complete |
| AT-20 | Local model unavailable/cloud disabled | Core search and export features still function |
| AT-21 | Error and security tests | Keys absent from logs/archive, hostile archive blocked, migrations recoverable |
| AT-22 | Performance test | Representative 100,000-record fixture can be processed and explored without interface lock-up or data loss; timing results documented |

The initial model must also be evaluated against a curated biomedical test set. Model choice and classification quality thresholds must be documented **before** turning automated classifications into default unreviewed outputs; unverified predictions remain provisional.

# 20. Delivery sequence and release gates

The final scope above should be developed incrementally. A phase may expose an incomplete feature internally, but the completed initial product cannot be claimed until all mandatory acceptance criteria are met.

**Phase 0 — Specification and verification plan.** Approve this file; establish repository conventions, requirement-to-test mapping, source access smoke tests and representative fixtures. No implementation has been started as part of drafting this specification.

**Phase 1 — Durable foundation.** Windows application shell, project launcher and storage, SQLite schema, audit trail, PubMed/WoS connectors, robust retrieval and counts, basic master list, conservative deduplication and initial Excel export. Gate: core retrieval/recovery tests.

**Phase 2 — Research-specific processing.** AI assistance and benchmarking, rich classification, conference abstract/container handling, professional society sourcing, review queues and metadata enrichment. Gate: source provenance and specialist extraction tests.

**Phase 3 — Polished workflow and release packaging.** Full GUI, Excel/report presentation, archive import/export, accessibility/performance work, installer/update flow, documentation, security review and full regression. Gate: all mandatory acceptance tests and documented exceptions.

## 20.1 Open implementation choices (not blockers to starting)

- Exact bundled LLM and quantisation, selected by biomedical benchmark, hardware and licensing.
- Specific GUI packaging method (embedded browser versus native window), provided the launch/user experience requirements are met.
- Site-specific society search adapters versus guided manual workflows according to access and stability.
- Precise confidence thresholds for automated class assignment and deduplication, based on validation fixtures and error costs.
- Optional automatic downloads of lawful full documents versus linked-only fallback.
- Quantified UI latency and memory targets after realistic large-data benchmarking; **no** performance claim is accepted merely from a small demonstration dataset.

Changes to the approved broad-OR search philosophy, use of MeSH, required sources, primary output format or publication identity model would be **scope changes** requiring explicit approval and a document version update.

# 21. Authoritative reference points

The following are external methodological and interface references for implementation verification; URLs should be rechecked at build time because provider documentation and API constraints may change.

1. PRISMA-S, 16 reporting items: https://www.prisma-statement.org/prisma-search ; Rethlefsen et al., *Systematic Reviews* (2021), DOI `10.1186/s13643-020-01542-z`.
2. PRESS 2015 Evidence-Based Checklist: https://www.cda-amc.ca/sites/default/files/PRESS_Peer_Review_Electronic_Search_Strate/Table_9-PRESS.pdf ; McGowan et al., *Journal of Clinical Epidemiology* (2016), PMID `27005575`.
3. PubMed search help / field-tag behaviour: https://pubmed.ncbi.nlm.nih.gov/help/ .
4. NCBI E-utilities (including PubMed retrieval limits): https://www.ncbi.nlm.nih.gov/books/NBK25499/ .
5. WoS Starter API plan and entitlement details: https://developer.clarivate.com/apis/wos-starter .
6. Official WoS Starter Python client, supported query fields and pagination: https://github.com/clarivate/wosstarter_python_client .
7. Crossref public/polite access and rate limits: https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/ .
8. Crossref REST API request/caching etiquette: https://github.com/CrossRef/rest-api-doc .

---

## Revision history

| Date | Version | Status / change | Approved by |
|---|---|---|---|
| 23 October 2026 | `1.0.0-draft.1` | Initial consolidated design baseline authored; no implementation begun. | — |
| 23 October 2026 | `1.0.0-draft.1` | **Approved as initial implementation baseline; development authorised.** Document-control status and authority wording updated to record approval. No substantive requirements changed. | Project owner |

**End of approved specification — v1.0.0-draft.1.**
