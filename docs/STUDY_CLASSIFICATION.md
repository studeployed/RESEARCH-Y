# Inspect and review a publication classification

Use a materialised publication ID from the project results. The local
inspection command reads its current source associations in one project
transaction. It returns proposed and current values for design, format,
original research, language and population. Each rule observation identifies
the original retrieval, source hash, exact metadata field and observed value.

```text
python -m scripts.review_publication_classification PROJECT PUBLICATION_ID inspect
python -m scripts.review_publication_classification PROJECT PUBLICATION_ID review --dimension design --label RCT --actor Researcher --rationale "Checked the methods" --revision REVISION --confirm
```

Use the revision returned by inspection. Multiple design labels can be
specified with repeated `--label`. Each confirmed change writes a linked
receipt and classification together. A stale review must be reopened.
Reclassification reads supporting evidence again. An earlier researcher
decision remains current and later disagreements are flagged. Missing
abstracts, inconclusive labels and conflicting metadata remain visible.

Population indexing alone cannot establish exclusively non-human research.
A researcher can explicitly record that conclusion. A filtered view can
then hide the publication while retaining all original records, counts and
group memberships. Explicitly non-English-only language can also be filtered.
Unknown and mixed-language records remain in view.

The desktop run panel includes **Study review queue and filters**. Inspect
one page of materialised publications, choose how to filter it, and open an
individual row for a revision-checked decision. Each page states how many
original identities were examined, hidden by the selected filters and
displayed. A page containing no visible rows can still have a next page.

The current rules cover explicit PubMed publication type, language and
population metadata and supported Starter document-type tags. Language codes
outside the recognised set remain unknown. Model evidence and enrichment
are tracked in [issue #126](https://github.com/studeployed/RESEARCH-Y/issues/126).
