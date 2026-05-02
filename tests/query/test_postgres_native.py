from __future__ import annotations

import os

import pytest

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.postgres_native import try_evaluate_native

_PG_URL = os.environ.get("DOXA_POSTGRES_TEST_URL", "")

try:
    import psycopg  # noqa: F401

    _HAS_PSYCOPG = True
except ImportError:
    _HAS_PSYCOPG = False


def _can_connect() -> bool:
    if not _PG_URL or not _HAS_PSYCOPG:
        return False
    try:
        conn = psycopg.connect(_PG_URL, autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _can_connect(),
    reason="PostgreSQL not available (set DOXA_POSTGRES_TEST_URL)",
)


@pytest.fixture()
def pg_repo():
    from doxa.persistence.postgres import PostgresBranchRepository

    repo = PostgresBranchRepository(_PG_URL)
    yield repo
    repo.close()


def test_native_recursive_cycle_does_not_self_reinforce(pg_repo) -> None:
    branch = Branch.from_doxa(
        """
        q(a) @{b:0.2, d:0.0}.
        q(X) :- q(X) @{b:1.0, d:0.0}.
        """
    )
    pg_repo.save(branch)

    shallow = Query.from_doxa(
        '?- q(a) @{rule_applicability:"body_truth_only", support_aggregation:"capped_sum", max_depth:3}'
    )
    shallow_result = try_evaluate_native(pg_repo._conn, branch, shallow)
    assert shallow_result is not None
    assert len(shallow_result.answers) == 1
    assert shallow_result.answers[0].b == pytest.approx(0.2)
    assert shallow_result.answers[0].d == pytest.approx(0.0)

    deeper = Query.from_doxa(
        '?- q(a) @{rule_applicability:"body_truth_only", support_aggregation:"capped_sum", max_depth:5}'
    )
    deeper_result = try_evaluate_native(pg_repo._conn, branch, deeper)
    assert deeper_result is not None
    assert len(deeper_result.answers) == 1
    assert deeper_result.answers[0].b == pytest.approx(0.2)
    assert deeper_result.answers[0].d == pytest.approx(0.0)


def test_native_mutual_cycle_does_not_feed_support_back_into_seed(pg_repo) -> None:
    branch = Branch.from_doxa(
        """
        p(a) @{b:0.3, d:0.0}.
        q(X) :- p(X) @{b:1.0, d:0.0}.
        p(X) :- q(X) @{b:1.0, d:0.0}.
        """
    )
    pg_repo.save(branch)

    p_query = Query.from_doxa(
        '?- p(a) @{rule_applicability:"body_truth_only", support_aggregation:"capped_sum", max_depth:5}'
    )
    p_result = try_evaluate_native(pg_repo._conn, branch, p_query)
    assert p_result is not None
    assert len(p_result.answers) == 1
    assert p_result.answers[0].b == pytest.approx(0.3)
    assert p_result.answers[0].d == pytest.approx(0.0)

    q_query = Query.from_doxa(
        '?- q(a) @{rule_applicability:"body_truth_only", support_aggregation:"capped_sum", max_depth:5}'
    )
    q_result = try_evaluate_native(pg_repo._conn, branch, q_query)
    assert q_result is not None
    assert len(q_result.answers) == 1
    assert q_result.answers[0].b == pytest.approx(0.3)
    assert q_result.answers[0].d == pytest.approx(0.0)


def test_native_recursive_chain_expands_with_each_round(pg_repo) -> None:
    branch = Branch.from_doxa(
        """
        q(a) @{b:0.6, d:0.0}.
        succ(a, b) @{b:1.0, d:0.0}.
        succ(b, c) @{b:1.0, d:0.0}.
        q(Y) :- q(X), succ(X, Y) @{b:1.0, d:0.0}.
        """
    )
    pg_repo.save(branch)

    shallow = Query.from_doxa(
        '?- q(X) @{rule_applicability:"body_truth_only", support_aggregation:"maximum", max_depth:1}'
    )
    shallow_result = try_evaluate_native(pg_repo._conn, branch, shallow)
    assert shallow_result is not None
    assert {answer.bindings["X"] for answer in shallow_result.answers} == {"a", "b"}

    deeper = Query.from_doxa(
        '?- q(X) @{rule_applicability:"body_truth_only", support_aggregation:"maximum", max_depth:2}'
    )
    deeper_result = try_evaluate_native(pg_repo._conn, branch, deeper)
    assert deeper_result is not None
    assert {answer.bindings["X"] for answer in deeper_result.answers} == {"a", "b", "c"}


def test_native_rejects_discounted_recursive_applicability(pg_repo) -> None:
    branch = Branch.from_doxa(
        """
        p(a) @{b:1.0, d:0.0}.
        p(X) :- p(X) @{b:0.8, d:0.0}.
        """
    )
    pg_repo.save(branch)

    query = Query.from_doxa("?- p(a)")
    assert try_evaluate_native(pg_repo._conn, branch, query) is None
