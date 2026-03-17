# src/shared/annotation_parser.py

from __future__ import annotations

from datetime import datetime


def parse_ax_annotation(inp: str) -> dict[str, object]:
    if not isinstance(inp, str):
        raise TypeError("Annotation input must be a string.")

    s = inp.strip()
    if not s:
        raise ValueError("Annotation input must not be empty.")

    if s.startswith("@{"):
        if not s.endswith("}"):
            raise ValueError("Invalid annotation: '@{' must be closed by '}'.")
        s = s[2:-1].strip()
    elif s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()

    if not s:
        return {}

    parts: list[str] = []
    buf: list[str] = []
    in_quotes = False
    escape = False

    for ch in s:
        if escape:
            buf.append(ch)
            escape = False
            continue

        if ch == "\\" and in_quotes:
            buf.append(ch)
            escape = True
            continue

        if ch == '"':
            buf.append(ch)
            in_quotes = not in_quotes
            continue

        if ch == "," and not in_quotes:
            part = "".join(buf).strip()
            if not part:
                raise ValueError("Invalid annotation: empty entry between commas.")
            parts.append(part)
            buf = []
            continue

        buf.append(ch)

    if in_quotes:
        raise ValueError("Invalid annotation: unterminated quoted string.")

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    elif s.endswith(","):
        raise ValueError("Invalid annotation: trailing comma.")

    raw: dict[str, object] = {}

    for pair in parts:
        key, value = _split_key_value(pair)
        parsed_key, parsed_value = _parse_annotation_item(key, value)

        if parsed_key in raw:
            raise ValueError(f"Duplicate annotation key: {parsed_key!r}")

        raw[parsed_key] = parsed_value

    return raw


def _split_key_value(pair: str) -> tuple[str, str]:
    in_quotes = False
    escape = False

    for i, ch in enumerate(pair):
        if escape:
            escape = False
            continue

        if ch == "\\" and in_quotes:
            escape = True
            continue

        if ch == '"':
            in_quotes = not in_quotes
            continue

        if ch == ":" and not in_quotes:
            key = pair[:i].strip()
            value = pair[i + 1 :].strip()
            if not key:
                raise ValueError(f"Invalid annotation entry {pair!r}: missing key.")
            if not value:
                raise ValueError(f"Invalid annotation entry {pair!r}: missing value.")
            return key, value

    raise ValueError(f"Invalid annotation entry {pair!r}: expected 'key:value'.")


def _parse_annotation_item(key: str, value: str) -> tuple[str, object]:
    key = key.strip()

    key_aliases = {
        "note": "description",
    }
    key = key_aliases.get(key, key)

    if key in {"b", "d"}:
        try:
            return key, float(value)
        except ValueError as exc:
            raise ValueError(
                f"Annotation key {key!r} must be a number in [0,1], got {value!r}."
            ) from exc

    if key in {"et", "vf", "vt"}:
        raw = _parse_str_value(value)
        iso = raw.strip()
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"

        try:
            return key, datetime.fromisoformat(iso)
        except ValueError as exc:
            raise ValueError(
                f"Annotation key {key!r} must be an ISO-8601 datetime string, got {raw!r}."
            ) from exc

    return key, _parse_str_value(value)


def _parse_str_value(value: str) -> str:
    value = value.strip()

    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape")

    return value
