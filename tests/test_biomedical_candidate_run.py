from pathlib import Path
import json
import subprocess

import pytest

from scripts import run_biomedical_candidate as run


def test_local_evaluation_uses_exact_inputs_and_retains_raw_predictions(tmp_path, monkeypatch):
    engine = tmp_path / "evaluation.exe"
    model = tmp_path / "model.gguf"
    engine.write_bytes(b"engine fixture")
    model.write_bytes(b"weights fixture")
    cases = run.corpus()
    calls = []

    def invoke(args, **kwargs):
        case = cases[len(calls)]
        assert args[0] == str(engine) and kwargs["stdin"] == subprocess.DEVNULL
        assert "HF_TOKEN" not in kwargs["env"]
        assert "LLAMA_ARG_CTX_SIZE" not in kwargs["env"]
        actual = Path(args[args.index("-f")+1]).read_bytes()
        assert actual.decode() == run.render(run.prompt(case))
        calls.append(actual)
        answer = {"terms": case["expected"]} if case["task"] == "terms" else case["expected"]
        return subprocess.CompletedProcess(args, 0, json.dumps(answer).encode("utf-8"), b"")

    monkeypatch.setenv("HF_TOKEN", "fixture")
    monkeypatch.setenv("LLAMA_ARG_CTX_SIZE", "1")
    monkeypatch.setattr(run, "run_process", invoke)
    report = run.run(engine, model, expected_engine=run.file_hash(engine),
                     expected_model=run.file_hash(model), model_revision="fixture")
    assert len(calls) == len(report["responses"]) == 20
    assert report["scores"]["counts"]["all_dimensions_correct"] == 12
    for row, score in zip(report["responses"], report["scores"]["cases"], strict=True):
        assert score["response_sha256"] == run.digest(row["output"])


def test_wrong_file_digest_stops_before_engine_execution(tmp_path, monkeypatch):
    fake = tmp_path / "weights"
    fake.write_bytes(b"fixture")
    monkeypatch.setattr(run, "run_process", lambda *args, **kwargs: pytest.fail("Unexpected execution"))
    with pytest.raises(ValueError, match="checksum"):
        run.run(fake, fake, expected_engine="a"*64, expected_model=run.file_hash(fake), model_revision="fixture")


def test_only_runtime_trailer_is_removed_and_candidate_formatting_is_preserved():
    answer = '```json\r\n{"terms":["[end of text]"]}\r\n```'
    assert run.response_text(answer+" [end of text]\r\n\r\n") == answer
    assert run.response_text(answer) == answer


def test_windows_evidence_reproduces_all_four_measured_scores():
    evidence = Path(__file__).resolve().parents[1] / "docs/evidence/biomedical-windows-20261113.json"
    report = json.loads(evidence.read_text(encoding="utf-8"))
    observed = {}
    cases = run.corpus()
    for result in report["runs"]:
        assert result["os"] == "Windows"
        assert result["engine_options"] == list(run.OPTIONS)
        responses = {row["id"]: row for row in result["responses"]}
        assert len(responses) == len(cases) == len(result["responses"])
        for case in cases:
            row = responses[case["id"]]
            assert row["rendered_sha256"] == run.digest(run.render(run.prompt(case)))
            expected = run.digest(run.canonical(run.output_schema(case["task"]))) if result["structured"] else None
            assert row["schema_sha256"] == expected
        scores = run.evaluate(cases, {key: row["output"] for key, row in responses.items()})
        assert scores == result["scores"]
        observed[result["model"], result["structured"]] = tuple(scores["counts"][key] for key in
                                                     ("recovered", "all_dimensions_correct", "invalid_outputs"))
    assert observed == {
        ("Qwen3-0.6B-Q8_0.gguf", False): (0, 0, 13), ("Qwen3-1.7B-Q8_0.gguf", False): (1, 1, 16),
        ("Qwen3-0.6B-Q8_0.gguf", True): (3, 0, 0), ("Qwen3-1.7B-Q8_0.gguf", True): (4, 2, 0),
    }
