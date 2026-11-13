import json

import pytest

from scripts import biomedical_benchmark as benchmark


def answers(cases):
    return {c["id"]: json.dumps({"terms": c["expected"]} if c["task"] == "terms" else c["expected"])
            for c in cases}


def test_reference_answers_reconcile_all_cases_without_answer_keys_in_prompts():
    cases = benchmark.corpus()
    predictions = answers(cases)
    report = benchmark.evaluate(cases, predictions)
    totals = report["counts"]
    assert totals["term_cases"] == 8 and totals["study_cases"] == 12
    assert totals["expected_terms"] == totals["recovered"] == 17
    assert totals["all_dimensions_correct"] == 12 and totals["invalid_outputs"] == 0
    assert set(report["correct_by_dimension"].values()) == {12}
    assert len(report["cases"]) == len(cases)
    for case, row in zip(cases, report["cases"], strict=True):
        assert benchmark.prompt(case) == benchmark.prompt({**case, "expected": None, "forbidden": ["different"]})
        assert row["response_sha256"] == benchmark.digest(predictions[case["id"]])


def test_incorrect_abstaining_and_malformed_responses_remain_in_denominators():
    cases = benchmark.corpus()
    predicted = answers(cases)
    predicted["t01"] = '{"terms":["ECMO","mechanical ventilation","Mechanical Ventilation"]}'
    predicted["t02"] = "I cannot answer"
    predicted["s05"] = '{"design":["retrospective cohort"],"format":"full journal article","population":"human","original_research":"no"}'
    predicted["s06"] = '{"original_research":"yes","original_research":"no"}'
    report = benchmark.evaluate(cases, predicted)
    assert report["counts"] == dict(term_cases=8, expected_terms=17, recovered=13,
                                     prohibited=1, unlisted=1, study_cases=12,
                                     all_dimensions_correct=10, invalid_outputs=2)
    assert report["correct_by_dimension"] == dict(original_research=10, design=11, format=11, population=11)
    assert next(r for r in report["cases"] if r["id"] == "s05")["matches"]["design"]


def test_preserves_spacing_hyphenation_and_distinct_case_inventory():
    cases = benchmark.corpus()
    response = json.dumps({"terms": ["veno-venous ECMO", "VENO-VENOUS ECMO", "veno venous ECMO"]})
    assert benchmark.score_case(cases[1], response) == dict(recovered=2, prohibited=0, unlisted=0)
    with pytest.raises(ValueError, match="One response"):
        benchmark.evaluate(cases, {})


def test_cli_roundtrip_preserves_raw_output_hashes_and_refuses_duplicate_ids(tmp_path, capsys):
    benchmark.main(["prompts"])
    prompts = json.loads(capsys.readouterr().out)
    cases = benchmark.corpus()
    assert set(prompts) == {c["id"] for c in cases}
    path = tmp_path / "raw.json"
    predicted = answers(cases)
    path.write_text(json.dumps(predicted), encoding="utf-8")
    benchmark.main(["score", str(path)])
    assert json.loads(capsys.readouterr().out) == benchmark.evaluate(cases, predicted)
    path.write_text('{"t01":"x","t01":"y"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        benchmark.main(["score", str(path)])
