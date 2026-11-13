"""Curated deterministic lexical variants for researcher review."""
from __future__ import annotations

import re
from itertools import product
from math import prod

VERSION = "clinical-lexical-variants/1"
FAMILIES = (
    (("venovenous", "veno-venous", "veno venous"), "Venovenous spacing and hyphenation"),
    (("venoarterial", "veno-arterial", "veno arterial"), "Venoarterial spacing and hyphenation"),
    (("extracorporeal membrane oxygenation", "ECMO"), "Modality abbreviation and expanded form"),
    (("right ventricle", "right-ventricle"), "Chamber phrase spelling"),
    (("right ventricular", "right-ventricular"), "Adjectival phrase spelling"),
    (("hemoglobin", "haemoglobin"), "American and British spelling"),
    (("randomized", "randomised"), "American and British spelling"),
    (("intensive care unit", "intensive care units", "ICU"), "Singular, plural and unit abbreviation"),
)
PATTERNS = tuple((re.compile(r"(?<!\w)(?:" + "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
                              + r")(?!\w)", re.I), variants, reason) for variants, reason in FAMILIES)


def lexical_variants(term):
    """Substitute one recognised component per family, including combinations across families."""
    applicable = [(pattern, variants, reason) for pattern, variants, reason in PATTERNS if pattern.search(term)]
    choices = []
    for pattern, variants, _ in applicable:
        choices.append([None, *(v for v in variants if pattern.sub(v, term).casefold() != term.casefold())])
    if prod(map(len, choices)) > 129:
        raise ValueError("Too many lexical combinations; review smaller atomic expressions")
    unique = {term.casefold()}
    result = []
    for combination in product(*choices):
        text, reasons = term, []
        for (pattern, _, reason), variant in zip(applicable, combination, strict=True):
            if variant is not None:
                text = pattern.sub(variant, text)
                reasons.append(reason)
        if text.casefold() not in unique and len(text) <= 2048:
            unique.add(text.casefold())
            result.append((text, "; ".join(reasons)))
    return result
