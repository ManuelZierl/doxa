# tests/query/test_query_engine_base.py
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from doxa.core.base_kinds import BaseKind
from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.engine import (
    EngineInfo,
    QueryEngine,
    QueryResult,
    UnsupportedEpistemicSemanticsError,
)


def make_empty_branch() -> Branch:
    return Branch(
        kind=BaseKind.branch,
        created_at=datetime.now(timezone.utc),
        name="main",
        ephemeral=False,
        predicates=[],
        entities=[],
        belief_records=[],
        rules=[],
        constraints=[],
    )


class StubEngine(QueryEngine):
    def __init__(self) -> None:
        self.seen_branch = None
        self.seen_query = None
        self.evaluate_calls = 0

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name="stub",
            version="1.0",
        )

    def _evaluate(self, branch: Branch, query: Query) -> QueryResult:
        self.evaluate_calls += 1
        self.seen_branch = branch
        self.seen_query = query
        return QueryResult()


def test_query_engine_is_abstract():
    with pytest.raises(TypeError):
        QueryEngine()


def test_evaluate_delegates_to__evaluate_for_supported_semantics():
    engine = StubEngine()
    branch = make_empty_branch()
    query = Query.from_doxa("?- p(a)")

    result = engine.evaluate(branch, query)

    assert isinstance(result, QueryResult)
    assert engine.evaluate_calls == 1
    assert engine.seen_branch is branch
    assert engine.seen_query is query


def test_validate_epistemic_semantics_accepts_default_query_semantics():
    engine = StubEngine()
    query = Query.from_doxa("?- p(a)")

    # Should not raise
    engine.validate_epistemic_semantics(query)


def test_validate_epistemic_semantics_raises_for_unsupported_body_truth():
    engine = StubEngine()
    query = Query.from_doxa('?- p(a) @{body_truth:"minimum"}')

    with pytest.raises(UnsupportedEpistemicSemanticsError) as exc_info:
        engine.validate_epistemic_semantics(query)

    message = str(exc_info.value)
    assert "stub" in message
    assert "body_truth='minimum'" in message


def test_evaluate_raises_before__evaluate_when_semantics_are_unsupported():
    engine = StubEngine()
    branch = make_empty_branch()
    query = Query.from_doxa('?- p(a) @{body_truth:"minimum"}')

    with pytest.raises(UnsupportedEpistemicSemanticsError):
        engine.evaluate(branch, query)

    assert engine.evaluate_calls == 0


def test_validate_epistemic_semantics_reports_multiple_unsupported_parts():
    engine = StubEngine()
    query = Query.from_doxa(
        '?- p(a) @{body_truth:"minimum", support_aggregation:"maximum"}'
    )

    with pytest.raises(UnsupportedEpistemicSemanticsError) as exc_info:
        engine.validate_epistemic_semantics(query)

    message = str(exc_info.value)
    assert "body_truth='minimum'" in message
    assert "support_aggregation='maximum'" in message