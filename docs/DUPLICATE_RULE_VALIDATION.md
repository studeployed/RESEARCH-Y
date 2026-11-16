# Repeated journal-pair review

The desktop can suggest **high confidence** for two newly retrieved journal
records when the researcher previously confirmed the same PubMed and Web of
Science record keys. The rule `unchanged-reviewed-journal-pair/1` requires the
latest receipt to remain current and both provider records to recur unchanged.
It checks journal article types, source identifiers, PMID and author agreement,
and an exact normalised DOI, title, publication year, journal and pages. A
missing field, conflicting comparison, container warning, historical reversal,
or previous rejection prevents the suggestion. The researcher sees the prior
audit and records a new decision before either identity or count can change.

## Independent bibliographic evaluation

We evaluated the five-field portion on all five published ASySD adjudicated CSVs.
The unit was an unordered pair within one dataset. Equal `duplicateid` labels
defined the reference match. All records, including those missing a comparison
field, contributed to the reference denominator. No records were pooled across
libraries. The script reads the local CSV and emits counts and its SHA-256.
[Study](https://doi.org/10.1186/s12915-023-01686-z) · [Published labels](https://osf.io/2b8uq/)

| Library | Records | All pairs | True positives | False positives | False negatives | True negatives |
|---|---:|---:|---:|---:|---:|---:|
| Diabetes | 1,845 | 1,701,090 | 1,067 | 0 | 1,488 | 1,698,535 |
| Neuroimaging | 3,438 | 5,908,203 | 1,039 | 0 | 773 | 5,906,391 |
| Cardiac | 8,948 | 40,028,878 | 380 | 0 | 3,442 | 40,025,056 |
| Preclinical reviews (SRSR) | 53,001 | 1,404,526,500 | 7,163 | 1 | 15,537 | 1,404,503,799 |
| Depression | 79,880 | 3,190,367,260 | 2,600 | 0 | 12,602 | 3,190,352,058 |

The first three libraries yielded 2,486 true matches and zero false matches.
We then applied the unchanged rule to the two larger libraries. One pair in
SRSR agreed on all five fields despite having distinct adjudicated group IDs.
Overall the comparison proposed 12,250 pairs and correctly identified 12,249
of 46,091 labelled duplicate pairs. The application therefore requires a
current prior researcher confirmation even for a read-only suggestion.
These exports do not include the application's prior decision
receipts. The figures measure the five-field condition only. They do not
estimate performance on conference supplements or generalise to unseen data.
The application exercises its additional exclusions and prior-decision checks
with disk-backed regression fixtures in `tests/test_publication_candidates.py`.
The synthetic collision in `tests/test_duplicate_rule_evaluation.py` shows how
distinct adjudicated groups can agree on all five fields.

Run `python tools/evaluate_duplicate_rule.py FILE` in the project environment.
Use `--encoding latin-1` for the Diabetes export. The publication's file
checksums matched the locally evaluated inputs.

| Download | SHA-256 |
|---|---|
| [Diabetes](https://osf.io/download/5zmbr/) | `55abf08312b6da338d7f5c57466573604aa32da0c1a224fa25b031b17dd3aef7` |
| [Neuroimaging](https://osf.io/download/g9qf7/) | `46ef8c7d8149acc522c0d3f82725c2b8d55cd234938a063d6e6be4395a0e37bc` |
| [Cardiac](https://osf.io/download/9a48v/) | `037f06b3cd7b457a08b29e721ebdfbf73ac17b16a6230c5810430bd9004ea2eb` |
| [Preclinical reviews](https://osf.io/download/z3m4d/) | `93ccc1007c9ad7c3793db03473aab4a4fbbfb292fcabbd981be8c98a97ab8e36` |
| [Depression](https://osf.io/download/cvnfj/) | `85392814cb4bbba2bad155e8a25c24b1bb223f5f17c0439285fcc162a72d7cea` |
