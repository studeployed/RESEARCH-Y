"""Generate blind prompts and score local biomedical candidate responses."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import unicodedata

CORPUS = Path(__file__).resolve().parents[1] / "tools/benchmarks/biomedical-v1.jsonl"
PROMPT_VERSION = "biomedical-v1"
DIMENSIONS = ("original_research", "design", "format", "population")
DESIGNS = ("RCT", "non-randomised interventional study", "prospective cohort", "retrospective cohort",
           "case-control", "cross-sectional", "case series", "case report", "diagnostic study",
           "qualitative study", "systematic review", "meta-analysis", "SRMA", "scoping review",
           "narrative review", "guideline", "consensus statement", "protocol", "editorial/commentary",
           "other", "unclear")
FORMATS = ("full journal article", "conference abstract", "conference paper", "journal supplement item",
           "society web document", "preprint", "book/chapter", "other")
POPULATIONS = ("human", "non-human", "mixed human/non-human", "not applicable", "unclear")


def digest(value):
    return sha256(value.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def corpus():
    cases = [json.loads(line, object_pairs_hook=unique_object)
             for line in CORPUS.read_text(encoding="utf-8").splitlines()]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate benchmark case")
    return cases


def prompt(case):
    if case["task"] == "terms":
        instructions = 'Return only a JSON object with one field "terms", a list of distinct atomic strings.'
    else:
        instructions = (
            'Return only a JSON object with the following four independent fields. '
            'original_research is yes, no or unclear. A new analysis counts as original research. '
            'A protocol without results or a synthesis of published studies does not. '
            'design is a list of all supported labels chosen from ' + ", ".join(DESIGNS) + '. '
            'format is one label from ' + ", ".join(FORMATS) + '. '
            'population is one label from ' + ", ".join(POPULATIONS) + '. '
            'Use unclear where the evidence is insufficient.'
        )
    return instructions + "\n\n" + case["input"]


def normalized(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError("Invalid benchmark label")
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def labels(values):
    if not isinstance(values, list) or len(values) > 96:
        raise ValueError("Expected a bounded label list")
    return {normalized(value) for value in values}


def score_case(case, response):
    answer = json.loads(response, object_pairs_hook=unique_object)
    if not isinstance(answer, dict):
        raise ValueError("Expected a JSON object")
    if case["task"] == "terms":
        if set(answer) != {"terms"}:
            raise ValueError("Expected only the terms field")
        expected, forbidden, proposed = labels(case["expected"]), labels(case["forbidden"]), labels(answer["terms"])
        return dict(recovered=len(proposed & expected), prohibited=len(proposed & forbidden),
                    unlisted=len(proposed - expected - forbidden))
    if set(answer) != set(DIMENSIONS):
        raise ValueError("Incomplete study response")
    design = labels(answer["design"])
    if not design or not design <= labels(list(DESIGNS)):
        raise ValueError("Unknown study design")
    expected = case["expected"]
    # The specification defines SRMA as the combination of these two tags.
    # Preserve exact-set scoring for every other study design.
    def expand_srma(values):
        if "srma" in values:
            return (values - {"srma"}) | {"systematic review", "meta-analysis"}
        return values
    matches = {"design": expand_srma(design) == expand_srma(labels(expected["design"]))}
    for key, allowed in (("original_research", ("yes", "no", "unclear")),
                         ("format", FORMATS), ("population", POPULATIONS)):
        value = normalized(answer[key])
        if value not in allowed:
            raise ValueError("Unknown study label")
        matches[key] = value == expected[key]
    return dict(matches=matches)


def evaluate(cases, responses):
    if not isinstance(responses, dict) or set(responses) != {case["id"] for case in cases}:
        raise ValueError("One response per benchmark case is required")
    totals = Counter()
    matched = Counter(dict.fromkeys(DIMENSIONS, 0))
    rows = []
    for case in cases:
        response = responses[case["id"]]
        if not isinstance(response, str) or len(response) > 65536:
            raise ValueError("Expected bounded raw response text")
        row = dict(id=case["id"], task=case["task"], prompt_sha256=digest(prompt(case)),
                   response_sha256=digest(response))
        if case["task"] == "terms":
            totals["term_cases"] += 1
            totals["expected_terms"] += len(labels(case["expected"]))
        else:
            totals["study_cases"] += 1
        try:
            result = score_case(case, response)
        except (ValueError, RecursionError):
            row["status"] = "invalid_output"
            totals["invalid_outputs"] += 1
        else:
            row.update(result, status="scored")
            if case["task"] == "terms":
                totals.update(result)
            else:
                matched.update(result["matches"])
                totals["all_dimensions_correct"] += all(result["matches"].values())
        rows.append(row)
    return dict(version=PROMPT_VERSION, corpus_sha256=digest(canonical(cases)), cases=rows,
                counts={key: totals[key] for key in ("term_cases", "expected_terms", "recovered",
                        "prohibited", "unlisted", "study_cases", "all_dimensions_correct", "invalid_outputs")},
                correct_by_dimension=dict(matched))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prompts")
    commands.add_parser("score").add_argument("responses", type=Path)
    args = parser.parse_args(argv)
    cases = corpus()
    if args.command == "prompts":
        result = {case["id"]: prompt(case) for case in cases}
    else:
        with args.responses.open("rb") as stream:
            raw = stream.read(4_000_001)
        if len(raw) > 4_000_000:
            parser.error("Response file exceeds 4 MB")
        try:
            responses = json.loads(raw, object_pairs_hook=unique_object)
            result = evaluate(cases, responses)
        except (ValueError, RecursionError):
            parser.error("Invalid response inventory or response file")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
