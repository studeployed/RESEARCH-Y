# Inspecting a JATS conference supplement

Use a locally permitted UTF-8 JATS article document without a DTD, with direct
`sub-article` children explicitly typed as abstracts. Each child keeps
its own title, authors, abstract text, source identifiers and printed page
range. The parent retains its own bibliographic information. The source
SHA-256 and positional XML locator identify the exact input and block.
The supported structure follows the [JATS sub-article element](https://jats.nlm.nih.gov/publishing/tag-library/1.3/element/sub-article.html).

```text
python -m scripts.inspect_conference_jats supplement.xml --term ECMO --term "right ventricle"
```

Supply the known supplement landing page and PDF URL with `--landing-url`
and `--pdf-url`. Each `--pdf-page XML_ID ONE_BASED_PAGE` maps a unique
abstract XML ID to an explicitly verified PDF file page. A file page of
8 results in a link ending in `#page=8`. Printed labels such as S3 are
retained independently. Links are stored locally without a network request.

The preview prints JSON to standard output and may include the original
abstract text. Use it locally within the document's access conditions.
The preview lists every supported child and its own literal term matches.
Missing text or locators, repeated identifiers and unclassified sub-articles
are exposed for review. An XML ID identifies a location within that file.
A DOI shared with the parent stays in the original identifiers. The extracted
list carries no final publication count.

Add `--project PROJECT --original-retrieval UUID` to tie the preview to an
existing retained collection source. Confirm permissions and each selected
block by repeating the command with its original options, `--admit-locator`
for each locator, `--actor`, `--revision`, `--confirm` and
`--allow-local-retention`. All selected individual source records, tentative
publication identities, the shared container and audit receipts are written
in one transaction. Exact retries return the same identities. The original
provider source and its query memberships remain available. The import
reports selected, extracted and unclassified counts separately.

In the Windows app, open the collection publication and expand **Conference
abstract review**. Choose the original source and the local XML file. Inspect
each abstract, confirm text retention permissions and select the blocks to
retain. The whole-run count covers distinct retained blocks with admission
receipts. The primary reviewed workbook continues to use the original
query records.

Use **Save block for follow-up** for an unclassified block. The project saves
its document checksum, original retrieval, exact locator and reason.
**Open saved block reviews** lists tasks after relaunch. Record the outcome
and source observation there. Recording an observation creates an audit
entry and leaves the publication count unchanged.
