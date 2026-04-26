from __future__ import annotations

import pytest

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.evaluator import InMemoryQueryEngine


def _has_native() -> bool:
    try:
        from doxa import _native  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _has_native(), reason="doxa._native not installed")
def test_native_honors_rule_applicability_override() -> None:
    from doxa.query.native import NativeQueryEngine

    branch = Branch.from_doxa("p(a) @{b:1.0, d:0.8}. q(X) :- p(X).")
    query = Query.from_doxa("?- q(X) @{rule_applicability:body_truth_only}")

    mem = InMemoryQueryEngine().evaluate(branch, query).answers
    nat = NativeQueryEngine().evaluate(branch, query).answers

    assert len(mem) == 1
    assert len(nat) == 1
    assert mem[0].bindings == nat[0].bindings
    assert nat[0].b == pytest.approx(mem[0].b, abs=1e-9)
    assert nat[0].d == pytest.approx(mem[0].d, abs=1e-9)


@pytest.mark.skipif(not _has_native(), reason="doxa._native not installed")
def test_native_supports_type_builtins_in_rule_body() -> None:
    from doxa.query.native import NativeQueryEngine

    branch = Branch.from_doxa("p(1). q(X) :- p(X), int(X).")
    query = Query.from_doxa("?- q(X)")

    mem = InMemoryQueryEngine().evaluate(branch, query).answers
    nat = NativeQueryEngine().evaluate(branch, query).answers

    assert len(mem) == 1
    assert len(nat) == 1
    assert nat[0].bindings == mem[0].bindings


@pytest.mark.skipif(not _has_native(), reason="doxa._native not installed")
def test_native_aggregates_duplicate_projected_bindings_like_memory() -> None:
    from doxa.query.native import NativeQueryEngine

    branch = Branch.from_doxa("p(a, b) @{b:0.6}. p(a, c) @{b:0.6}.")
    query = Query.from_doxa("?- p(X, _)")

    mem = InMemoryQueryEngine().evaluate(branch, query).answers
    nat = NativeQueryEngine().evaluate(branch, query).answers

    assert len(mem) == 1
    assert len(nat) == 1
    assert nat[0].bindings == mem[0].bindings
    assert nat[0].b == pytest.approx(mem[0].b, abs=1e-9)


@pytest.mark.skipif(not _has_native(), reason="doxa._native not installed")
def test_native_matches_memory_for_multi_rule_support_aggregation_default() -> None:
    from doxa.query.native import NativeQueryEngine

    branch = Branch.from_doxa(
        "s1(x). s2(x). d(X) :- s1(X) @{b:0.6}. d(X) :- s2(X) @{b:0.4}."
    )
    query = Query.from_doxa("?- d(X)")

    mem = InMemoryQueryEngine().evaluate(branch, query).answers
    nat = NativeQueryEngine().evaluate(branch, query).answers

    assert len(mem) == 1
    assert len(nat) == 1
    assert nat[0].bindings == mem[0].bindings
    assert nat[0].b == pytest.approx(mem[0].b, abs=1e-9)
