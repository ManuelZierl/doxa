"""Shared helpers for literal value validation, rendering, and parsing.

Used by :class:`BeliefLiteralArg`, :class:`LiteralArg`,
:class:`RuleHeadLiteralArg`, and :class:`RuleGoalLiteralArg` to avoid
repeating the same ``lit_type``/``value`` logic in every class.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Tuple

from doxa.core._parsing.parsing_utils import (
    get_date_lit_regex,
    get_datetime_lit_regex,
    get_duration_lit_regex,
    parse_date_literal,
    parse_datetime_literal,
    parse_duration_literal,
    parse_python_string_literal,
    render_date_literal,
    render_datetime_literal,
    render_duration_literal,
    render_string_literal,
)
from doxa.core.literal_type import LiteralType

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")
_DATE_LIT_RE = get_date_lit_regex()
_DATETIME_LIT_RE = get_datetime_lit_regex()
_DURATION_LIT_RE = get_duration_lit_regex()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_literal_value(lit_type: LiteralType, value: object) -> None:
    """Validate that *value* is compatible with *lit_type*.

    Raises :class:`ValueError` with a generic message on mismatch.
    Callers that need class-specific error text should catch and re-raise.
    """
    if lit_type == LiteralType.str and not isinstance(value, str):
        raise ValueError("Literal with lit_type='str' must use a string value.")
    if lit_type == LiteralType.int and type(value) is not int:
        raise ValueError("Literal with lit_type='int' must use an int value.")
    if lit_type == LiteralType.float and type(value) is not float:
        raise ValueError("Literal with lit_type='float' must use a float value.")
    if lit_type == LiteralType.date and type(value) is not _dt.date:
        raise ValueError("Literal with lit_type='date' must use a date value.")
    if lit_type == LiteralType.datetime and not isinstance(value, _dt.datetime):
        raise ValueError("Literal with lit_type='datetime' must use a datetime value.")
    if lit_type == LiteralType.duration and not isinstance(value, _dt.timedelta):
        raise ValueError("Literal with lit_type='duration' must use a timedelta value.")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_literal_value(
    lit_type: LiteralType, value: object, *, escape_strings: bool = True
) -> str:
    """Render a typed literal value as AX source text.

    Args:
        lit_type: The literal type tag.
        value: The Python value to render.
        escape_strings: When ``True``, string values are escaped via
            :func:`render_string_literal`.  When ``False``, they are
            wrapped in double quotes without escaping.
    """
    if lit_type == LiteralType.str:
        if escape_strings:
            return render_string_literal(value)  # type: ignore[arg-type]
        return f'"{value}"'
    if lit_type == LiteralType.int:
        return str(value)
    if lit_type == LiteralType.float:
        return str(value)
    if lit_type == LiteralType.date:
        return render_date_literal(value)  # type: ignore[arg-type]
    if lit_type == LiteralType.datetime:
        return render_datetime_literal(value)  # type: ignore[arg-type]
    if lit_type == LiteralType.duration:
        return render_duration_literal(value)  # type: ignore[arg-type]
    raise ValueError(f"Unsupported literal type: {lit_type}")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_literal_value(
    s: str, *, error_prefix: str = "Invalid literal argument"
) -> Tuple[LiteralType, object]:
    """Parse an AX literal string and return ``(lit_type, value)``.

    Raises :class:`ValueError` if the input is not a recognised literal form.
    """
    s = s.strip()

    if _DATETIME_LIT_RE.fullmatch(s):
        return LiteralType.datetime, parse_datetime_literal(s)

    if _DATE_LIT_RE.fullmatch(s):
        return LiteralType.date, parse_date_literal(s)

    if _DURATION_LIT_RE.fullmatch(s):
        return LiteralType.duration, parse_duration_literal(s)

    if s.startswith('"') and s.endswith('"'):
        return LiteralType.str, parse_python_string_literal(s)

    if _INT_RE.fullmatch(s):
        return LiteralType.int, int(s)

    if _FLOAT_RE.fullmatch(s):
        return LiteralType.float, float(s)

    raise ValueError(f"{error_prefix}: {s!r}")
