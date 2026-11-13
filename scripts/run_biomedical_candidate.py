"""Evaluate one pinned Qwen3 GGUF candidate locally using the benchmark prompts."""
from __future__ import annotations

import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import platform
import re
import subprocess
from subprocess import run as run_process
import sys
import tempfile
import time

from scripts.biomedical_benchmark import DESIGNS, FORMATS, POPULATIONS, canonical, corpus, digest, evaluate, prompt

RENDERER = "qwen3-chatml-no-thinking-v1"
OPTIONS = ("--offline", "--no-conversation", "--no-display-prompt", "--no-escape", "--no-warmup",
           "--no-perf", "--simple-io", "-ngl", "0", "-t", "6", "-c", "2048",
           "-n", "256", "--temp", "0", "--seed", "19")


def file_hash(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def render(user_prompt):
    return ("<|im_start|>user\n" + user_prompt + "\n/no_think<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def response_text(stdout):
    # tools/completion/completion.cpp b12360 appends this line on EOG.
    return re.sub(r" \[end of text\](?:\r?\n)+\Z", "", stdout)


def output_schema(task):
    if task == "terms":
        fields = {"terms": {"type": "array", "items": {"type": "string"}}}
    else:
        fields = {"original_research": {"enum": ["yes", "no", "unclear"]},
                  "design": {"type": "array", "minItems": 1, "items": {"enum": list(DESIGNS)}},
                  "format": {"enum": list(FORMATS)}, "population": {"enum": list(POPULATIONS)}}
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def run(engine, model, *, expected_engine, expected_model, model_revision, structured=False):
    if file_hash(engine) != expected_engine or file_hash(model) != expected_model:
        raise ValueError("Local engine or model checksum differs from the expected file")
    cases = corpus()
    responses = {}
    records = []
    # Ignore ambient LLAMA_ARG_* overrides and external service credentials.
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "SYSTEMDRIVE", "PATH", "LANG", "LC_ALL"}}
    with tempfile.TemporaryDirectory(prefix="research-y-prompts-") as tmp:
        path = Path(tmp) / "prompt.txt"
        for case in cases:
            rendered = render(prompt(case))
            path.write_bytes(rendered.encode("utf-8"))
            start = time.monotonic()
            schema = canonical(output_schema(case["task"])) if structured else None
            extra = ["--json-schema", schema] if structured else []
            result = run_process([str(engine), "-m", str(model), *OPTIONS, *extra, "-f", str(path)],
                                    stdin=subprocess.DEVNULL, capture_output=True, env=env,
                                    timeout=180, check=True, cwd=engine.parent)
            stdout = result.stdout.decode("utf-8")
            output = response_text(stdout)
            responses[case["id"]] = output
            records.append(dict(id=case["id"], rendered_sha256=digest(rendered), stdout_sha256=digest(stdout),
                                schema_sha256=digest(schema) if schema else None,
                                seconds=round(time.monotonic()-start, 3), output=output))
            print("Evaluated", case["id"], file=sys.stderr, flush=True)
    if not any(value.strip() for value in responses.values()):
        raise ValueError("Engine returned no observable model responses; candidate was not evaluated")
    return dict(engine=engine.name, engine_sha256=expected_engine, model=model.name,
                model_sha256=expected_model, model_revision=model_revision, renderer=RENDERER, structured=structured,
                engine_options=list(OPTIONS), os=platform.system(), os_release=platform.release(),
                os_version=platform.version(), architecture=platform.machine(), processor=platform.processor(),
                python=platform.python_version(), responses=records, scores=evaluate(cases, responses))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("engine", "model", "output"):
        parser.add_argument("--" + field, type=Path, required=True)
    for field in ("engine-sha256", "model-sha256", "model-revision"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--structured", action="store_true", help="Constrain JSON output to the public label schema")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new output path")
    report = run(args.engine.resolve(strict=True), args.model.resolve(strict=True),
                 expected_engine=args.engine_sha256, expected_model=args.model_sha256,
                 model_revision=args.model_revision, structured=args.structured)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
