import pytest

from tools.evaluate_duplicate_rule import evaluate


def test_counts_every_pair_and_keeps_missing_records_in_the_denominator():
    base = dict(doi="10.1234/example", title="Title", year="2020", journal="Journal", pages="4")
    rows = [dict(base, record_id=str(i), duplicateid=g, pages=p) for i, (g, p) in enumerate((
        ("1", "4"), ("1", "4"), ("2", "4"), ("1", "NA"), ("2", "NA")))]
    assert evaluate(rows) == dict(records=5, adjudicated_groups=2, total_pairs=10,
                                  comparable_records=3, proposed_pairs=3, true_positives=1,
                                  false_positives=2, false_negatives=3, true_negatives=4)
    with pytest.raises(ValueError):
        evaluate(rows + rows)
