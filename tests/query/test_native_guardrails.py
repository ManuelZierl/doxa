from __future__ import annotations

import pytest

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.postgres import PostgresNativeFallbackError, PostgresQueryEngine


class _DummyRepo:
    def __init__(self) -> None:
        self.connection_requested = False
        self.visible_records_requested = False

    def save(self, branch: Branch) -> None:
        raise AssertionError("test should disable auto-sync")

    def get_connection(self):
        self.connection_requested = True
        raise AssertionError("unsupported native SQL must not request a DB connection")

    def get_visible_belief_records(self, *args, **kwargs):
        self.visible_records_requested = True
        return []


def test_postgres_native_sql_strict_rejects_constraint_fallback(monkeypatch):
    branch = Branch.from_doxa(
        """
        p(a).
        q(a).
        !:- p(X), q(X) @{b:0.7}.
        """
    )
    query = Query.from_doxa('?- p(a), q(a) @{explain:"false"}')
    repo = _DummyRepo()
    engine = PostgresQueryEngine(
        repo,
        native_sql_enabled=True,
        native_sql_strict=True,
        auto_sync_on_evaluate=False,
    )

    def _forbid_python_fallback(*args, **kwargs):
        raise AssertionError("Python evaluator fallback was used")

    monkeypatch.setattr(
        "doxa.query.postgres.evaluate_with_records",
        _forbid_python_fallback,
    )

    with pytest.raises(PostgresNativeFallbackError, match="constraints"):
        engine.evaluate(branch, query)

    assert (
        engine.last_native_fallback_reason
        == "constraints are not supported by native SQL"
    )
    assert repo.connection_requested is False
    assert repo.visible_records_requested is False


def test_postgres_native_sql_records_non_strict_fallback_reason():
    branch = Branch.from_doxa(
        """
        p(a).
        q(a).
        !:- p(X), q(X) @{b:0.7}.
        """
    )
    query = Query.from_doxa('?- p(a), q(a) @{explain:"false"}')
    repo = _DummyRepo()
    engine = PostgresQueryEngine(
        repo,
        native_sql_enabled=True,
        native_sql_strict=False,
        auto_sync_on_evaluate=False,
    )

    result = engine.evaluate(branch, query)

    assert (
        engine.last_native_fallback_reason
        == "constraints are not supported by native SQL"
    )
    assert repo.connection_requested is False
    assert repo.visible_records_requested is True
    assert result.answers
