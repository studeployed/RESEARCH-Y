"""Optional, offline local inference. Model suggestions never execute project actions."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from zipfile import ZipFile

from research_y.local_model_manifest import (ARCHIVE_SHA256, ENGINE_BUILD, MODEL_BYTES, MODEL_NAME,
                                             MODEL_REVISION, MODEL_SHA256, NATIVE_FILES)
from research_y.study_classification import LABELS

PACKAGE = "qwen3-1.7b-b12360-v1"
PROMPT_VERSION = "reviewed-atomic-terms/1"
PARAMETERS = ("--offline", "--no-conversation", "--no-display-prompt", "--no-escape", "--no-warmup",
              "--no-perf", "--simple-io", "-ngl", "0", "-t", "6", "-c", "2048", "-n", "256",
              "--temp", "0", "--seed", "19")
TERM_SCHEMA = {"type": "object", "properties": {"terms": {"type": "array", "maxItems": 8,
               "items": {"type": "string"}}}, "required": ["terms"], "additionalProperties": False}


class LocalAssistantError(ValueError):
    """Static operator-facing error code."""


def _digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _linked(path):
    return path.is_symlink() or path.is_junction()


def _validate(root):
    native = root / "runtime"
    if any(_linked(p) for p in (root.parent, root, native)) or not native.is_dir():
        raise LocalAssistantError("local_assistant_unavailable")
    if {p.name for p in native.iterdir()} != set(NATIVE_FILES):
        raise LocalAssistantError("local_assistant_runtime_changed")
    for name, expected in NATIVE_FILES.items():
        path = native / name
        if _linked(path) or not path.is_file() or _digest(path) != expected:
            raise LocalAssistantError("local_assistant_runtime_changed")
    model = root / MODEL_NAME
    if _linked(model) or not model.is_file() or model.stat().st_size != MODEL_BYTES or _digest(model) != MODEL_SHA256:
        raise LocalAssistantError("local_assistant_model_changed")


def install_local_package(parent, *, archive, model):
    """Install verified local release files with an atomic directory rename."""
    parent, archive, model = Path(parent), Path(archive), Path(model)
    parent.mkdir(parents=True, exist_ok=True)
    if _linked(parent):
        raise LocalAssistantError("local_assistant_install_location_invalid")
    target = parent / PACKAGE
    if target.exists():
        _validate(target)
        return target
    if archive.stat().st_size != 25_097_627 or _digest(archive) != ARCHIVE_SHA256 or model.stat().st_size != MODEL_BYTES:
        raise LocalAssistantError("local_assistant_asset_mismatch")
    with tempfile.TemporaryDirectory(dir=parent, prefix=".install-") as tmp:
        stage = Path(tmp) / PACKAGE
        native = stage / "runtime"
        native.mkdir(parents=True)
        with ZipFile(archive) as z:
            for name in NATIVE_FILES:
                with z.open(name) as src, (native / name).open("xb") as dst:
                    shutil.copyfileobj(src, dst)
        shutil.copyfile(model, stage / MODEL_NAME)
        _validate(stage)
        try:
            stage.rename(target)
        except FileExistsError:
            _validate(target)
    return target


def _hash_text(text):
    return sha256(text.encode("utf-8")).hexdigest()


def _checked_text(value, limit):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value) or "<|" in value or "|>" in value):
        raise LocalAssistantError("local_assistant_invalid_text")
    return value.strip()


class LocalAssistant:
    def __init__(self, root):
        self.root = Path(root)

    @property
    def installed(self):
        return (self.root / MODEL_NAME).is_file() and (self.root / "runtime/llama-completion.exe").is_file()

    def propose_terms(self, seed):
        seed = _checked_text(seed, 512)
        task = ("Suggest up to eight alternate atomic literature search terms for the seed below. "
                "Use synonyms, abbreviations or lexical variants that preserve its biomedical meaning. "
                'Return JSON with one field "terms" containing strings. Omit the original seed.\n'
                "Seed: " + json.dumps(seed, ensure_ascii=False))
        result, receipt = self._generate(task, seed, TERM_SCHEMA, PROMPT_VERSION)
        if set(result) != {"terms"} or type(result["terms"]) is not list or len(result["terms"]) > 8:
            raise LocalAssistantError("local_assistant_invalid_output")
        terms, seen = [], {seed.casefold()}
        for candidate in result["terms"]:
            term = _checked_text(candidate, 256)
            if term.casefold() not in seen:
                terms.append(term)
                seen.add(term.casefold())
        return dict(terms=terms, **receipt)

    def propose_study(self, source_text):
        evidence = _checked_text(source_text, 5000)
        dimensions = ("original_research", "design", "format", "population")
        fields = {k: {"enum": sorted(LABELS[k])} for k in dimensions}
        fields["design"] = {"type": "array", "minItems": 1, "maxItems": 6, "items": fields["design"]}
        schema = {"type": "object", "properties": fields, "required": list(dimensions), "additionalProperties": False}
        task = ("Propose provisional study classifications using only the quoted evidence. "
                "New empirical analyses are original research. Protocols without results and reviews are not. "
                "Evaluate publication format separately from study design. Choose unclear for insufficient evidence. "
                "Use the supplied JSON schema. Evidence: " + json.dumps(evidence, ensure_ascii=False))
        result, receipt = self._generate(task, evidence, schema, "reviewed-study-labels/1")
        if set(result) != set(dimensions):
            raise LocalAssistantError("local_assistant_invalid_output")
        proposals = {}
        for key in dimensions:
            values = result[key] if key == "design" else [result[key]]
            if (type(values) is not list or not 1 <= len(values) <= 6
                    or any(type(v) is not str or v not in LABELS[key] for v in values)):
                raise LocalAssistantError("local_assistant_invalid_output")
            proposals[key] = sorted(set(values))
        return dict(proposals=proposals, **receipt)

    def _generate(self, task, input_text, schema, template):
        rendered = "<|im_start|>user\n" + task + "\n/no_think<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        try:
            _validate(self.root)
            runtime = self.root / "runtime"
            env = {k: v for k, v in os.environ.items() if k.upper() in
                   {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "SYSTEMDRIVE"}}
            if "SystemRoot" in os.environ:
                env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            with tempfile.TemporaryDirectory(prefix="research-y-local-") as tmp:
                input_path = Path(tmp) / "input.txt"
                input_path.write_bytes(rendered.encode("utf-8"))
                proc = subprocess.run([str(runtime / "llama-completion.exe"), "-m", str(self.root / MODEL_NAME),
                        *PARAMETERS, "--json-schema", json.dumps(schema), "-f", str(input_path)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                        cwd=runtime, env=env, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            response = re.sub(r" \[end of text\](?:\r?\n)+\Z", "", proc.stdout.decode("utf-8"))
            result = json.loads(response)
            if type(result) is not dict:
                raise LocalAssistantError("local_assistant_invalid_output")
        except LocalAssistantError:
            raise
        except (OSError, ValueError, RecursionError, subprocess.SubprocessError):
            raise LocalAssistantError("local_assistant_inference_failed") from None
        return result, dict(model=MODEL_NAME, revision=MODEL_REVISION, model_sha256=MODEL_SHA256,
                    engine=ENGINE_BUILD, template=template, parameters=list(PARAMETERS),
                    schema_sha256=_hash_text(json.dumps(schema)), input_sha256=_hash_text(input_text),
                    prompt_sha256=_hash_text(rendered), response_sha256=_hash_text(response),
                    generated_at_utc=datetime.now(timezone.utc).isoformat())
