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

The current rules cover explicit PubMed publication type, language and
population metadata and supported Starter document-type tags. Language codes
outside the recognised set remain unknown. Broader inference, desktop review
queues and enrichment are tracked in [issue #126](https://github.com/studeployed/RESEARCH-Y/issues/126).
