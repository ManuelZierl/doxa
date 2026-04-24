"""Shared parsing utilities for AX language constructs."""

import re
from datetime import date, datetime, timedelta
from typing import List

_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?(?:\d+\.\d*|\d*\.\d+)")
_PRED_REF_RE = re.compile(r"^[a-z][A-Za-z0-9_]*/[0-9]+$")
_DATE_LIT_RE = re.compile(r'^d"([^"]+)"$')
_DATETIME_LIT_RE = re.compile(r'^dt"([^"]+)"$')
_DURATION_LIT_RE = re.compile(r'^dur"([^"]+)"$')

# ISO 8601 duration pattern: P[nY][nM][nD][T[nH][nM][nS]]
_ISO_DURATION_RE = re.compile(
    r"^P"
    r"(?:(?P<years>\d+)Y)?"
    r"(?:(?P<months>\d+)M)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?"
    r")?$"
)
_GOAL_CALL_RE = re.compile(
    r"""
    ^\s*
    (?P<name>[a-z][A-Za-z0-9_]*)
    \s*
    \(
    (?P<args>.*)
    \)
    \s*$
    """,
    re.VERBOSE | re.DOTALL,
)


def split_top_level(inp: str, sep: str = ",") -> List[str]:
    """Split input string at top-level separators, respecting nested structures.

    Args:
        inp: Input string to split
        sep: Separator character (default: comma)

    Returns:
        List of split parts

    Raises:
        ValueError: If parentheses/braces are unbalanced or strings are unterminated
    """
    parts: List[str] = []
    buf: List[str] = []

    depth_paren = 0
    depth_brace = 0
    in_single = False
    in_double = False
    escape = False

    for ch in inp:
        if escape:
            buf.append(ch)
            escape = False
            continue

        if ch == "\\" and in_double:
            buf.append(ch)
            escape = True
            continue

        if ch == "'" and not in_double:
            buf.append(ch)
            in_single = not in_single
            continue

        if ch == '"' and not in_single:
            buf.append(ch)
            in_double = not in_double
            continue

        if in_single or in_double:
            buf.append(ch)
            continue

        if ch == "(":
            depth_paren += 1
            buf.append(ch)
            continue

        if ch == ")":
            depth_paren -= 1
            if depth_paren < 0:
                raise ValueError("Unbalanced parentheses.")
            buf.append(ch)
            continue

        if ch == "{":
            depth_brace += 1
            buf.append(ch)
            continue

        if ch == "}":
            depth_brace -= 1
            if depth_brace < 0:
                raise ValueError("Unbalanced braces.")
            buf.append(ch)
            continue

        if ch == sep and depth_paren == 0 and depth_brace == 0:
            part = "".join(buf).strip()
            if not part:
                raise ValueError("Empty item in comma-separated list.")
            parts.append(part)
            buf = []
            continue

        buf.append(ch)

    if in_single or in_double:
        raise ValueError("Unterminated quoted string.")
    if depth_paren != 0:
        raise ValueError("Unbalanced parentheses.")
    if depth_brace != 0:
        raise ValueError("Unbalanced braces.")

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)

    return parts


def split_annotation_suffix(inp: str) -> tuple[str, str | None]:
    """Split input into main content and annotation suffix.

    Args:
        inp: Input string potentially containing annotation suffix

    Returns:
        Tuple of (main_content, annotation_string_or_none)

    Raises:
        ValueError: If parentheses are unbalanced
    """
    s = inp.strip()
    in_single = False
    in_double = False
    escape = False
    depth_paren = 0

    i = 0
    while i < len(s):
        ch = s[i]

        if escape:
            escape = False
            i += 1
            continue

        if ch == "\\" and in_double:
            escape = True
            i += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if in_single or in_double:
            i += 1
            continue

        if ch == "(":
            depth_paren += 1
            i += 1
            continue

        if ch == ")":
            depth_paren -= 1
            if depth_paren < 0:
                raise ValueError("Unbalanced parentheses.")
            i += 1
            continue

        if depth_paren == 0 and s.startswith("@{", i):
            return s[:i].strip(), s[i:].strip()

        i += 1

    return s, None


def render_string_literal(value: str) -> str:
    """Render a Python string as an AX string literal.

    Args:
        value: String value to render

    Returns:
        Quoted and escaped string literal
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_python_string_literal(inp: str) -> str:
    """Parse an AX string literal to a Python string.

    Args:
        inp: String literal with quotes

    Returns:
        Unescaped string value

    Raises:
        ValueError: If input is not a valid string literal
    """
    s = inp.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape")
    raise ValueError(f"Invalid string literal: {inp!r}")


def get_int_regex() -> re.Pattern:
    """Get compiled regex pattern for integer literals."""
    return _INT_RE


def get_float_regex() -> re.Pattern:
    """Get compiled regex pattern for float literals."""
    return _FLOAT_RE


def get_goal_call_regex() -> re.Pattern:
    """Get compiled regex pattern for goal call syntax."""
    return _GOAL_CALL_RE


def get_pred_ref_regex() -> re.Pattern:
    """Get compiled regex pattern for predicate reference literals (name/arity)."""
    return _PRED_REF_RE


def get_date_lit_regex() -> re.Pattern:
    """Get compiled regex pattern for date literals d"..."."""
    return _DATE_LIT_RE


def get_datetime_lit_regex() -> re.Pattern:
    """Get compiled regex pattern for datetime literals dt"..."."""
    return _DATETIME_LIT_RE


def get_duration_lit_regex() -> re.Pattern:
    """Get compiled regex pattern for duration literals dur"..."."""
    return _DURATION_LIT_RE


def parse_date_literal(s: str) -> date:
    """Parse a date literal d"YYYY-MM-DD" and return a Python date."""
    m = _DATE_LIT_RE.fullmatch(s.strip())
    if not m:
        raise ValueError(f'Invalid date literal: {s!r}. Expected d"YYYY-MM-DD".')
    iso = m.group(1).strip()
    try:
        return date.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(f"Invalid date value in literal {s!r}: {exc}") from exc


def parse_datetime_literal(s: str) -> datetime:
    """Parse a datetime literal dt"..." and return a Python datetime."""
    m = _DATETIME_LIT_RE.fullmatch(s.strip())
    if not m:
        raise ValueError(
            f'Invalid datetime literal: {s!r}. Expected dt"YYYY-MM-DDTHH:MM:SSZ".'
        )
    iso = m.group(1).strip()
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime value in literal {s!r}: {exc}") from exc


def parse_duration_literal(s: str) -> timedelta:
    """Parse a duration literal dur"P..." and return a Python timedelta."""
    m = _DURATION_LIT_RE.fullmatch(s.strip())
    if not m:
        raise ValueError(
            f'Invalid duration literal: {s!r}. Expected dur"P..." (ISO 8601 duration).'
        )
    iso = m.group(1).strip()
    return parse_iso_duration(iso)


def parse_iso_duration(s: str) -> timedelta:
    """Parse an ISO 8601 duration string into a timedelta.

    Supports [-]P[nY][nM][nD][T[nH][nM][nS]].
    An optional leading '-' produces a negative duration.
    Years are converted to 365 days, months to 30 days (fixed-unit, not calendar-aware).
    """
    stripped = s.strip()
    negative = stripped.startswith("-")
    if negative:
        stripped = stripped[1:]
    m = _ISO_DURATION_RE.fullmatch(stripped)
    if not m:
        raise ValueError(f"Invalid ISO 8601 duration: {s!r}")

    years = int(m.group("years") or 0)
    months = int(m.group("months") or 0)
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds_str = m.group("seconds")
    seconds = float(seconds_str) if seconds_str else 0.0

    if (
        years == 0
        and months == 0
        and days == 0
        and hours == 0
        and minutes == 0
        and seconds == 0.0
    ):
        # "P" alone or "PT" alone with no components is invalid
        if stripped == "P" or stripped == "PT":
            raise ValueError(f"Invalid ISO 8601 duration: {s!r} (no components)")

    total_days = years * 365 + months * 30 + days
    total_seconds = hours * 3600 + minutes * 60 + seconds

    result = timedelta(days=total_days, seconds=total_seconds)
    return -result if negative else result


def render_date_literal(d: date) -> str:
    """Render a Python date as a Doxa date literal."""
    return f'd"{d.isoformat()}"'


def render_datetime_literal(dt: datetime) -> str:
    """Render a Python datetime as a Doxa datetime literal."""
    iso = dt.isoformat()
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    return f'dt"{iso}"'


def render_duration_literal(td: timedelta) -> str:
    """Render a Python timedelta as a Doxa duration literal (ISO 8601)."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        sign = "-"
        total_seconds = -total_seconds
    else:
        sign = ""

    days = total_seconds // 86400
    remainder = total_seconds % 86400
    hours = remainder // 3600
    remainder = remainder % 3600
    minutes = remainder // 60
    seconds = remainder % 60

    parts = [f"{sign}P"]
    if days:
        parts.append(f"{days}D")
    if hours or minutes or seconds:
        parts.append("T")
        if hours:
            parts.append(f"{hours}H")
        if minutes:
            parts.append(f"{minutes}M")
        if seconds:
            parts.append(f"{seconds}S")
    if len(parts) == 1:
        # Zero duration
        parts.append("T0S")

    return f'dur"{"".join(parts)}"'
