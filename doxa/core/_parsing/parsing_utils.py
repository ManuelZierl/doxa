"""Shared parsing utilities for AX language constructs."""

import re
from typing import List

_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?(?:\d+\.\d*|\d*\.\d+)")
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
