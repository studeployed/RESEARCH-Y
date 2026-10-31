"""Narrow equivalence for an internal PubMed Create Date partition.

P1-04i: the observed source spelling [Date - Create] is equivalent to [crdt]
only when an explicit caller has established internal partition context.
This is not a general query optimiser and never rewrites submitted text.
"""

from __future__ import annotations

from datetime import date
import re

# Exact literal/All Fields spelling is retained, including case, punctuation,
# spacing and term order. Quotes, escapes and wildcards are outside the approved
# compiler's atomic-term grammar. Operators within literals are NOT operators.
_LITERAL = re.compile(r'"([^"\\*?$\x00-\x1f\x7f]+)"\[All Fields\]')
_DATE_RANGE = re.compile(
    r'([0-9]{4}/[0-9]{2}/[0-9]{2}):([0-9]{4}/[0-9]{2}/[0-9]{2})'
    r'\[(crdt|Date - Create)\]'
)
_OPERATOR = re.compile(r'(AND|OR)\b')


def _tokens(expression: str) -> list[tuple[str, object]] | None:
    """Tokenise the restricted grammar without replacing text inside quotes."""
    if not isinstance(expression, str) or not expression.strip():
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in expression):
        return None
    tokens: list[tuple[str, object]] = []
    offset = 0
    while offset < len(expression):
        char = expression[offset]
        if char == " ":
            offset += 1
            continue
        if char in "()":
            tokens.append((char, char))
            offset += 1
            continue
        literal = _LITERAL.match(expression, offset)
        if literal:
            value = literal.group(1)
            if not value.strip() or value != value.strip():
                return None
            tokens.append(("literal", value))
            offset = literal.end()
            continue
        interval = _DATE_RANGE.match(expression, offset)
        if interval:
            start, end, field = interval.groups()
            try:
                lower = date.fromisoformat(start.replace("/", "-"))
                upper = date.fromisoformat(end.replace("/", "-"))
            except ValueError:
                return None
            if lower > upper:
                return None
            tokens.append(("date", (start, end, field)))
            offset = interval.end()
            continue
        operator = _OPERATOR.match(expression, offset)
        if operator:
            tokens.append((operator.group(1), operator.group(1)))
            offset = operator.end()
            continue
        return None
    return tokens or None


def _signature(expression: str, *, submitted: bool) -> tuple | None:
    """Accept only (OR-only All Fields clause) AND (one fixed date range).

    Balanced groups are inspected iteratively, not recursively. Mixed OR/AND
    at one level is rejected rather than guessing the provider's precedence.
    """
    tokens = _tokens(expression)
    if tokens is None:
        return None
    stack: list[int] = []
    closing: dict[int, int] = {}
    for index, (kind, _) in enumerate(tokens):
        if kind == "(":
            stack.append(index)
        elif kind == ")":
            if not stack:
                return None
            closing[stack.pop()] = index
    if stack:
        return None

    def unwrap(first: int, last: int) -> tuple[int, int]:
        while first < last and closing.get(first) == last:
            first += 1
            last -= 1
        return first, last

    first, last = unwrap(0, len(tokens) - 1)
    # Exactly one administrative conjunction, never a new concept restriction.
    conjunctions = [i for i, (kind, _) in enumerate(tokens) if kind == "AND"]
    if len(conjunctions) != 1:
        return None
    split = conjunctions[0]
    depth = 0
    for index in range(first, last + 1):
        kind = tokens[index][0]
        if kind == "(":
            depth += 1
        elif kind == ")":
            depth -= 1
        elif index == split and depth != 0:
            return None
        elif kind == "OR" and depth == 0:
            return None
    if not first < split < last:
        return None

    date_first, date_last = unwrap(split + 1, last)
    if date_first != date_last or tokens[date_first][0] != "date":
        return None
    start, end, field = tokens[date_first][1]
    # The actual generator submits [crdt]. Only the RESPONSE may use its
    # documented long name. Root/user dates never gain implicit permission.
    if submitted and field != "crdt":
        return None

    literals: list[str] = []
    depth = 0
    need_operand = True
    for kind, value in tokens[first:split]:
        if kind == "(":
            if not need_operand:
                return None
            depth += 1
        elif kind == ")":
            if need_operand or depth == 0:
                return None
            depth -= 1
        elif kind == "literal":
            if not need_operand:
                return None
            literals.append(value)
            need_operand = False
        elif kind == "OR":
            if need_operand:
                return None
            need_operand = True
        else:
            return None
    if depth or need_operand or not literals:
        return None
    return tuple(literals), start, end


def internal_create_date_equivalent(submitted: str, accepted: str) -> bool:
    """Compare proven partition grammar, preserving every term and date bound.

    The caller MUST supply internal partition context separately. Source
    warnings remain an independent rejection condition in the source parser.
    No set/sort/casefold or arbitrary parenthesis removal is used.
    """
    expected = _signature(submitted, submitted=True)
    actual = _signature(accepted, submitted=False)
    return expected is not None and actual is not None and expected == actual
