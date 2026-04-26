"""Shared helpers for term-argument parsing and rendering.

This module centralises common logic used by belief, goal, and rule argument
models (entity/predicate-ref parsing and fallback parse-order handling).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import TypeVar

from doxa.core.entity import Entity

T = TypeVar("T")


def parse_with_fallback(
    inp: str,
    parsers: Sequence[Callable[[str], T]],
    *,
    invalid_message: str,
) -> T:
    last_error: ValueError | None = None
    for parse in parsers:
        try:
            return parse(inp)
        except ValueError as exc:
            last_error = exc
    raise ValueError(invalid_message) from last_error


def parse_entity_name(inp: str) -> str:
    return Entity.from_doxa(inp).name


def parse_pred_ref(
    inp: str, pred_ref_re: re.Pattern, *, error_prefix: str
) -> tuple[str, int]:
    s = inp.strip()
    if not pred_ref_re.fullmatch(s):
        raise ValueError(f"{error_prefix}: {inp!r}")
    name, arity_str = s.rsplit("/", 1)
    return name, int(arity_str)


def render_pred_ref(name: str, arity: int) -> str:
    return f"{name}/{arity}"
