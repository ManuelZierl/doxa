"""Tests for the InMemoryQueryEngine fixes:

- eq as variable binder
- add / sub / mul / div / between builtins
- Temporal validity window [vf, vt]
- offset / order_by / distinct post-processing
- Configurable max_depth
- Policy alignment: report / credulous / skeptical
"""

from __future__ import annotations

from datetime import datetime

import pytest

from doxa.core.branch import Branch
from doxa.core.query import Query, QueryOptions
from doxa.query.memory import InMemoryQueryEngine

engine = InMemoryQueryEngine()


# ── helpers ───────────────────────────────────────────────────────────────────


def _run(kb: str, q: str) -> list[dict]:
    branch = Branch.from_doxa(kb)
    query = Query.from_doxa(q)
    result = engine.evaluate(branch, query)
    return [b.values for b in result.bindings]


def _run_opts(kb: str, q: str, **opts) -> list[dict]:
    """Run with explicit QueryOptions keyword args merged into the query."""
    branch = Branch.from_doxa(kb)
    query = Query.from_doxa(q)
    query = query.model_copy(update={"options": QueryOptions(**opts)})
    result = engine.evaluate(branch, query)
    return [b.values for b in result.bindings]


# ─────────────────────────────────────────────────────────────────────────────
# eq: variable binding
# ─────────────────────────────────────────────────────────────────────────────


class TestEqBinder:
    KB = "pred val/1.\nval(a).\nval(b)."

    def test_eq_binds_left_var(self):
        rows = _run(self.KB, "?- eq(X, 42)")
        assert rows == [{"X": 42}]

    def test_eq_binds_right_var(self):
        rows = _run(self.KB, "?- eq(99, Y)")
        assert rows == [{"Y": 99}]

    def test_eq_binds_string_literal(self):
        rows = _run(self.KB, '?- eq(Name, "hello")')
        assert rows == [{"Name": "hello"}]

    def test_eq_filters_true(self):
        rows = _run(self.KB, "?- eq(5, 5)")
        assert rows == [{}]

    def test_eq_filters_false(self):
        rows = _run(self.KB, "?- eq(5, 6)")
        assert rows == []

    def test_eq_propagates_from_fact(self):
        # val(X), eq(X, a)  → X must equal entity "a"
        rows = _run(self.KB, "?- val(X), eq(X, a)")
        assert rows == [{"X": "a"}]

    def test_eq_same_var_trivial(self):
        rows = _run(self.KB, "?- val(X), eq(X, X)")
        assert len(rows) == 2  # both val facts pass


# ─────────────────────────────────────────────────────────────────────────────
# Arithmetic builtins: add / sub / mul / div
# ─────────────────────────────────────────────────────────────────────────────

ARITH_KB = "p(x)."  # minimal KB so Branch.from_doxa is happy


class TestAddBuiltin:
    def test_forward(self):
        rows = _run(ARITH_KB, "?- add(3, 4, R)")
        assert rows == [{"R": 7}]

    def test_solve_c(self):
        rows = _run(ARITH_KB, "?- add(10, 5, R)")
        assert rows == [{"R": 15}]

    def test_solve_a(self):
        rows = _run(ARITH_KB, "?- add(A, 4, 7)")
        assert rows == [{"A": 3}]

    def test_solve_b(self):
        rows = _run(ARITH_KB, "?- add(3, B, 7)")
        assert rows == [{"B": 4}]

    def test_check_true(self):
        rows = _run(ARITH_KB, "?- add(3, 4, 7)")
        assert rows == [{}]

    def test_check_false(self):
        rows = _run(ARITH_KB, "?- add(3, 4, 8)")
        assert rows == []


class TestSubBuiltin:
    def test_forward(self):
        rows = _run(ARITH_KB, "?- sub(10, 3, R)")
        assert rows == [{"R": 7}]

    def test_solve_a(self):
        rows = _run(ARITH_KB, "?- sub(A, 3, 7)")
        assert rows == [{"A": 10}]

    def test_solve_b(self):
        rows = _run(ARITH_KB, "?- sub(10, B, 7)")
        assert rows == [{"B": 3}]


class TestMulBuiltin:
    def test_forward(self):
        rows = _run(ARITH_KB, "?- mul(3, 4, R)")
        assert rows == [{"R": 12}]

    def test_solve_a(self):
        rows = _run(ARITH_KB, "?- mul(A, 4, 12)")
        assert rows == [{"A": 3}]

    def test_solve_b(self):
        rows = _run(ARITH_KB, "?- mul(3, B, 12)")
        assert rows == [{"B": 4}]

    def test_mul_by_zero_all_ground(self):
        # 0 * 5 = 0  → should hold
        rows = _run(ARITH_KB, "?- mul(0, 5, 0)")
        assert rows == [{}]

    def test_mul_by_zero_solve_a_undefined(self):
        # A * 0 = 12 has no solution
        rows = _run(ARITH_KB, "?- mul(A, 0, 12)")
        assert rows == []


class TestDivBuiltin:
    def test_forward(self):
        rows = _run(ARITH_KB, "?- div(10, 2, R)")
        assert rows == [{"R": 5}]

    def test_solve_a(self):
        rows = _run(ARITH_KB, "?- div(A, 2, 5)")
        assert rows == [{"A": 10}]

    def test_solve_b(self):
        rows = _run(ARITH_KB, "?- div(10, B, 5)")
        assert rows == [{"B": 2}]

    def test_div_by_zero(self):
        rows = _run(ARITH_KB, "?- div(10, 0, R)")
        assert rows == []

    def test_float_result(self):
        rows = _run(ARITH_KB, "?- div(7, 2, R)")
        assert len(rows) == 1
        assert abs(rows[0]["R"] - 3.5) < 1e-9

    def test_arith_in_rule(self):
        """Arithmetic builtins should also work inside rule bodies."""
        kb = """
pred score/2.
pred double/2.

score(alice, 5).
score(bob, 8).

double(X, D) :- score(X, S), mul(S, 2, D).
"""
        rows = _run(kb, "?- double(X, D)")
        vals = {r["X"]: r["D"] for r in rows}
        assert vals == {"alice": 10, "bob": 16}


# ─────────────────────────────────────────────────────────────────────────────
# between
# ─────────────────────────────────────────────────────────────────────────────


class TestBetweenBuiltin:
    def test_in_range(self):
        rows = _run(ARITH_KB, "?- between(5, 1, 10)")
        assert rows == [{}]

    def test_at_lower_bound(self):
        rows = _run(ARITH_KB, "?- between(1, 1, 10)")
        assert rows == [{}]

    def test_at_upper_bound(self):
        rows = _run(ARITH_KB, "?- between(10, 1, 10)")
        assert rows == [{}]

    def test_below_range(self):
        rows = _run(ARITH_KB, "?- between(0, 1, 10)")
        assert rows == []

    def test_above_range(self):
        rows = _run(ARITH_KB, "?- between(11, 1, 10)")
        assert rows == []

    def test_between_with_var(self):
        kb = """
pred score/2.
score(alice, 5).
score(bob, 15).
"""
        rows = _run(kb, "?- score(X, S), between(S, 1, 10)")
        assert rows == [{"X": "alice", "S": 5}]

    def test_between_in_rule(self):
        kb = """
pred score/2.
pred eligible/1.

score(alice, 70).
score(bob, 45).
score(carol, 85).

eligible(X) :- score(X, S), between(S, 60, 100).
"""
        rows = _run(kb, "?- eligible(X)")
        names = {r["X"] for r in rows}
        assert names == {"alice", "carol"}


# ─────────────────────────────────────────────────────────────────────────────
# Temporal validity window [vf, vt]
# ─────────────────────────────────────────────────────────────────────────────


class TestTemporalValidityWindow:
    KB = """
pred event/1.
event(a) @{vf:"2020-01-01T00:00:00Z", vt:"2021-12-31T23:59:59Z"}.
event(b) @{vf:"2022-01-01T00:00:00Z", vt:"2023-12-31T23:59:59Z"}.
event(c) @{vf:"2021-06-01T00:00:00Z"}.
"""

    def test_asof_matches_first_window(self):
        rows = _run_opts(
            self.KB, "?- event(X)", asof="2020-06-01T00:00:00Z", policy="report"
        )
        names = {r["X"] for r in rows}
        assert names == {"a"}

    def test_asof_matches_second_window(self):
        rows = _run_opts(
            self.KB, "?- event(X)", asof="2022-06-01T00:00:00Z", policy="report"
        )
        names = {r["X"] for r in rows}
        assert names == {"b", "c"}

    def test_asof_between_windows(self):
        # gap between 2022-01-01 and end of b; a has expired
        rows = _run_opts(
            self.KB, "?- event(X)", asof="2021-01-01T00:00:00Z", policy="report"
        )
        names = {r["X"] for r in rows}
        assert names == {"a"}

    def test_no_asof_returns_all(self):
        rows = _run_opts(self.KB, "?- event(X)", policy="report")
        assert len(rows) == 3

    def test_asof_before_all_windows(self):
        rows = _run_opts(
            self.KB, "?- event(X)", asof="2019-12-31T00:00:00Z", policy="report"
        )
        assert rows == []

    def test_vt_only_fact_expires(self):
        kb = """
pred ev/1.
ev(x) @{vt:"2020-12-31T23:59:59Z"}.
"""
        rows = _run_opts(kb, "?- ev(X)", asof="2021-01-01T00:00:00Z", policy="report")
        assert rows == []

    def test_vf_only_fact_not_yet_valid(self):
        kb = """
pred ev/1.
ev(x) @{vf:"2025-01-01T00:00:00Z"}.
"""
        rows = _run_opts(kb, "?- ev(X)", asof="2024-06-01T00:00:00Z", policy="report")
        assert rows == []

    def test_no_vf_vt_always_active(self):
        kb = "pred ev/1.\nev(x)."
        rows = _run_opts(kb, "?- ev(X)", asof="2020-01-01T00:00:00Z", policy="report")
        assert rows == [{"X": "x"}]


# ─────────────────────────────────────────────────────────────────────────────
# Post-processing: distinct, order_by, offset, limit
# ─────────────────────────────────────────────────────────────────────────────

POSTPROC_KB = """
pred item/2.
item(a, 3).
item(b, 1).
item(c, 2).
item(d, 1).
"""


class TestDistinct:
    def test_distinct_removes_duplicates(self):
        # Query only for the numeric value – will produce duplicates (1 appears twice)
        rows = _run_opts(POSTPROC_KB, "?- item(_, V)", distinct=True)
        values = sorted(r["V"] for r in rows)
        # Anonymous var is not projected, so distinct deduplicates on V alone
        assert values == [1, 2, 3]

    def test_distinct_on_single_var(self):
        kb = """
pred tag/2.
tag(a, x).
tag(b, x).
tag(c, y).
"""
        # Query only T to expose the duplicate
        rows = _run_opts(kb, "?- tag(_, T)", distinct=True, policy="report")
        # Anonymous var is not projected, so distinct deduplicates on T alone
        assert len(rows) == 2
        tags = sorted(r["T"] for r in rows)
        assert tags == ["x", "y"]

    def test_distinct_on_projected_result(self):
        kb = """
pred tag/1.
tag(x).
tag(x).
tag(y).
"""
        rows = _run_opts(kb, "?- tag(T)", distinct=True, policy="report")
        tags = [r["T"] for r in rows]
        assert sorted(tags) == ["x", "y"]


class TestOrderBy:
    def test_order_by_ascending(self):
        rows = _run_opts(POSTPROC_KB, "?- item(N, V)", order_by="V", policy="report")
        values = [r["V"] for r in rows]
        assert values == sorted(values)

    def test_order_by_name_ascending(self):
        rows = _run_opts(POSTPROC_KB, "?- item(N, V)", order_by="N", policy="report")
        names = [r["N"] for r in rows]
        assert names == sorted(names)

    def test_order_by_multi(self):
        rows = _run_opts(POSTPROC_KB, "?- item(N, V)", order_by="V, N", policy="report")
        # Primary: V ascending, secondary: N ascending
        assert rows[0]["V"] <= rows[1]["V"] <= rows[2]["V"] <= rows[3]["V"]
        # Within same V=1: b before d
        v1_rows = [r for r in rows if r["V"] == 1]
        assert [r["N"] for r in v1_rows] == ["b", "d"]


class TestOffsetLimit:
    def test_limit(self):
        rows = _run_opts(
            POSTPROC_KB, "?- item(N, V)", order_by="N", limit=2, policy="report"
        )
        assert len(rows) == 2

    def test_offset(self):
        all_rows = _run_opts(
            POSTPROC_KB, "?- item(N, V)", order_by="N", policy="report"
        )
        offset_rows = _run_opts(
            POSTPROC_KB, "?- item(N, V)", order_by="N", offset=2, policy="report"
        )
        assert offset_rows == all_rows[2:]

    def test_limit_and_offset(self):
        all_rows = _run_opts(
            POSTPROC_KB, "?- item(N, V)", order_by="N", policy="report"
        )
        page = _run_opts(
            POSTPROC_KB,
            "?- item(N, V)",
            order_by="N",
            offset=1,
            limit=2,
            policy="report",
        )
        assert page == all_rows[1:3]

    def test_offset_beyond_results(self):
        rows = _run_opts(POSTPROC_KB, "?- item(N, V)", offset=100, policy="report")
        assert rows == []

    def test_limit_zero(self):
        rows = _run_opts(POSTPROC_KB, "?- item(N, V)", limit=0, policy="report")
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Configurable max_depth
# ─────────────────────────────────────────────────────────────────────────────


class TestMaxDepth:
    # A recursive predicate: nat(N) holds for all natural numbers.
    # Deriving nat(N) requires N rule applications.
    KB = """
pred nat/1.
nat(0).
nat(S) :- nat(P), add(P, 1, S).
"""

    def test_depth_1_derives_nat_1(self):
        # nat(1) requires 1 rule application → succeeds at max_depth=1
        rows = _run_opts(self.KB, "?- nat(1)", max_depth=1, distinct=True)
        assert rows == [{}]

    def test_depth_1_cannot_derive_nat_2(self):
        # nat(2) requires 2 rule applications → cut at max_depth=1
        rows = _run_opts(self.KB, "?- nat(2)", max_depth=1, distinct=True)
        assert rows == []

    def test_depth_2_derives_nat_2(self):
        # nat(2) requires 2 rule applications → succeeds at max_depth=2
        rows = _run_opts(self.KB, "?- nat(2)", max_depth=2, distinct=True)
        assert rows == [{}]

    def test_max_depth_from_query_annotation(self):
        branch = Branch.from_doxa(self.KB)
        query = Query.from_doxa("?- nat(1) @{max_depth:5}")
        result = engine.evaluate(branch, query)
        assert result.success


# ─────────────────────────────────────────────────────────────────────────────
# Policy: report / credulous / skeptical
# ─────────────────────────────────────────────────────────────────────────────

POLICY_KB = """
pred fact/1.
fact(believed) @{b:0.9, d:0.1}.
fact(disbelieved) @{b:0.1, d:0.9}.
fact(contradicted) @{b:0.5, d:0.5}.
fact(unknown) @{b:0.0, d:0.0}.
fact(certain) @{b:1.0, d:0.0}.
"""


class TestPolicy:
    def test_report_returns_all(self):
        rows = _run_opts(POLICY_KB, "?- fact(X)", policy="report")
        names = {r["X"] for r in rows}
        assert names == {
            "believed",
            "disbelieved",
            "contradicted",
            "unknown",
            "certain",
        }

    def test_skeptical_filters_b_le_d(self):
        rows = _run_opts(POLICY_KB, "?- fact(X)", policy="skeptical")
        names = {r["X"] for r in rows}
        # Only facts where b > d pass
        assert names == {"believed", "certain"}

    def test_credulous_same_as_skeptical(self):
        # Both credulous and skeptical use b > d (aligned with legacy)
        rows_s = _run_opts(POLICY_KB, "?- fact(X)", policy="skeptical")
        rows_c = _run_opts(POLICY_KB, "?- fact(X)", policy="credulous")
        assert {r["X"] for r in rows_s} == {r["X"] for r in rows_c}

    def test_default_policy_is_report(self):
        # Default QueryOptions → policy="report" → no filter
        rows = _run(POLICY_KB, "?- fact(X)")
        assert len(rows) == 5

    def test_policy_from_query_annotation(self):
        branch = Branch.from_doxa(POLICY_KB)
        query = Query.from_doxa('?- fact(X) @{policy:"skeptical"}')
        result = engine.evaluate(branch, query)
        names = {b.values["X"] for b in result.bindings}
        assert names == {"believed", "certain"}


# ─────────────────────────────────────────────────────────────────────────────
# QueryOptions: Pydantic validation
# ─────────────────────────────────────────────────────────────────────────────


class TestQueryOptions:
    def test_default_options(self):
        opts = QueryOptions()
        assert opts.policy == "report"
        assert opts.asof is None
        assert opts.limit is None
        assert opts.offset == 0
        assert opts.order_by == []
        assert opts.distinct is False
        assert opts.max_depth == 24

    def test_invalid_policy_rejected(self):
        with pytest.raises(Exception):
            QueryOptions(policy="invalid")

    def test_negative_limit_rejected(self):
        with pytest.raises(Exception):
            QueryOptions(limit=-1)

    def test_negative_offset_rejected(self):
        with pytest.raises(Exception):
            QueryOptions(offset=-1)

    def test_zero_max_depth_rejected(self):
        with pytest.raises(Exception):
            QueryOptions(max_depth=0)

    def test_unknown_option_rejected(self):
        with pytest.raises(Exception):
            QueryOptions(unknown_key="value")

    def test_asof_coerces_from_string(self):
        opts = QueryOptions(asof="2024-01-15T12:00:00Z")
        assert isinstance(opts.asof, datetime)
        assert opts.asof.year == 2024
        assert opts.asof.tzinfo is not None

    def test_order_by_coerces_from_comma_string(self):
        opts = QueryOptions(order_by="X, Y")
        assert opts.order_by == ["X", "Y"]

    def test_limit_coerces_from_string_int(self):
        opts = QueryOptions(limit="10")
        assert opts.limit == 10

    def test_to_doxa_parts_only_non_defaults(self):
        opts = QueryOptions(policy="skeptical", limit=5)
        parts = opts.to_doxa_parts()
        keys = [p.split(":")[0] for p in parts]
        assert "policy" in keys
        assert "limit" in keys
        assert "offset" not in keys
        assert "distinct" not in keys

    def test_to_doxa_parts_empty_for_defaults(self):
        opts = QueryOptions()
        assert opts.to_doxa_parts() == []

    def test_query_from_doxa_parses_options(self):
        q = Query.from_doxa('?- fact(X) @{policy:"skeptical", limit:10, offset:2}')
        assert q.options.policy == "skeptical"
        assert q.options.limit == 10
        assert q.options.offset == 2

    def test_query_to_doxa_roundtrip(self):
        q = Query.from_doxa('?- fact(X) @{policy:"skeptical", limit:5}')
        ax = q.to_doxa()
        q2 = Query.from_doxa(ax)
        assert q2.options.policy == "skeptical"
        assert q2.options.limit == 5
