"""Shared answer post-processing for query engines."""

from __future__ import annotations

from typing import Any, List, Tuple

from doxa.core.query import Query, QueryFocus
from doxa.query.engine import QueryAnswer


def sort_answers(answers: List[QueryAnswer], order_by: List[str]) -> List[QueryAnswer]:
    if not order_by:
        return answers

    def _sort_key(answer: QueryAnswer) -> Tuple[Any, ...]:
        parts = []
        for key in order_by:
            value = answer.bindings.get(key)
            if value is None:
                parts.append((1, "", ""))
            else:
                parts.append((0, type(value).__name__, value))
        return tuple(parts)

    return sorted(answers, key=_sort_key)


def apply_focus(answers: List[QueryAnswer], focus: QueryFocus) -> List[QueryAnswer]:
    if focus == QueryFocus.all:
        return answers

    eps = 1e-12

    if focus == QueryFocus.support:
        filtered = [a for a in answers if a.b > eps]
        return sorted(filtered, key=lambda a: a.b, reverse=True)

    if focus == QueryFocus.disbelief:
        filtered = [a for a in answers if a.d > eps]
        return sorted(filtered, key=lambda a: a.d, reverse=True)

    if focus == QueryFocus.contradiction:
        filtered = [a for a in answers if a.b > eps and a.d > eps]
        return sorted(filtered, key=lambda a: min(a.b, a.d), reverse=True)

    if focus == QueryFocus.ignorance:
        return [a for a in answers if a.b <= eps and a.d <= eps]

    return answers


def finalize_answers(
    answers: List[QueryAnswer],
    query: Query,
    *,
    is_closed_query: bool,
    closed_query_fallback: QueryAnswer | None,
) -> List[QueryAnswer]:
    out = list(answers)

    if is_closed_query and not out and closed_query_fallback is not None:
        out = [closed_query_fallback]

    out = apply_focus(out, query.options.focus)
    out = sort_answers(out, query.options.order_by)

    if query.options.offset:
        out = out[query.options.offset :]

    if query.options.limit is not None:
        out = out[: query.options.limit]

    return out
