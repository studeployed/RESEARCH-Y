"""Single confirmed seed-only request to the Claude Messages API; disabled by default."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.client import HTTPException
import json
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

from research_y.local_assistant import LocalAssistantError, _checked_text, _hash_text

ENDPOINT = "https://api.anthropic.com/v1/messages"
TEMPLATE = "cloud-reviewed-atomic-terms/1"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(request):
    with build_opener(_NoRedirect()).open(request, timeout=45) as response:
        data = response.read(131073)
    if len(data) > 131072:
        raise LocalAssistantError("cloud_response_too_large")
    return data


@dataclass(frozen=True)
class CloudTerms:
    model: str
    key: str = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.model, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", self.model)
                or not isinstance(self.key, str) or not 1 <= len(self.key) <= 4096
                or any(not 33 <= ord(c) <= 126 for c in self.key)):
            raise LocalAssistantError("cloud_profile_invalid")

    def preview(self, seed):
        seed = _checked_text(seed, 512)
        instruction = ('Suggest at most eight alternative atomic biomedical search terms for the supplied seed. '
                       'Preserve its scientific meaning. Reply with a JSON object containing a list of strings '
                       'in the field "terms". Seed: '+json.dumps(seed, ensure_ascii=False))
        body = {"model":self.model, "max_tokens":256, "messages":[{"role":"user","content":instruction}]}
        encoded = json.dumps(body, ensure_ascii=False, separators=(",",":"))
        return dict(provider="Anthropic", endpoint=ENDPOINT, model=self.model, seed=seed, payload=encoded,
                    revision=_hash_text(encoded), cost_notice="Your provider may charge for input and output tokens.")

    def generate(self, seed, *, expected_revision, confirmed, transport=_post):
        preview = self.preview(seed)
        if confirmed is not True or expected_revision != preview["revision"]:
            raise LocalAssistantError("cloud_transfer_confirmation_required")
        body = preview["payload"].encode("utf-8")
        req = Request(ENDPOINT, method="POST", data=body, headers={"Content-Type":"application/json",
                      "x-api-key":self.key, "anthropic-version":"2023-06-01"})
        try:
            raw = transport(req)
            if type(raw) is not bytes or len(raw) > 131072:
                raise ValueError
            reply = json.loads(raw)
            if reply.get("type") != "message" or reply.get("role") != "assistant" or reply.get("stop_reason") != "end_turn":
                raise ValueError
            actual_model = _checked_text(reply["model"], 128)
            blocks = reply["content"]
            if not isinstance(blocks,list) or not blocks or any(b.get("type") != "text" for b in blocks):
                raise ValueError
            text = "".join(b["text"] for b in blocks)
            out = json.loads(text)
            if set(out) != {"terms"} or not isinstance(out["terms"],list) or len(out["terms"]) > 8:
                raise ValueError
            terms, seen = [], {seed.casefold()}
            for value in out["terms"]:
                term = _checked_text(value, 256)
                if term.casefold() not in seen:
                    terms.append(term)
                    seen.add(term.casefold())
        except (ValueError, KeyError, TypeError, AttributeError, OSError, HTTPException, RecursionError):
            raise LocalAssistantError("cloud_response_unavailable") from None
        return dict(terms=terms, provider="Anthropic", model=actual_model, requested_model=self.model,
                    template=TEMPLATE, parameters={"max_tokens":256}, input_sha256=_hash_text(seed),
                    prompt_sha256=preview["revision"], response_sha256=_hash_text(text),
                    generated_at_utc=datetime.now(timezone.utc).isoformat())
