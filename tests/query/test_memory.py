# tests/query/test_in_memory_query_engine.py
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from doxa.core.base_kinds import BaseKind
from doxa.core.branch import Branch
from doxa.core.epistemic_semantics import (
    BodyFalsitySemantics,
    BodyTruthSemantics,
    ConstraintApplicabilitySemantics,
    EpistemicSemanticsConfig,
    RuleApplicabilitySemantics,
    SupportAggregationSemantics,
)
from doxa.core.query import Query, QueryFocus, QueryOptions
from doxa.query.engine import BelnapStatus

# Adjust only this import if your file/module name differs.
from doxa.query.memory import InMemoryQueryEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


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


def make_branch(ax: str) -> Branch:
    ax = ax.strip()
    if not ax:
        return make_empty_branch()
    return Branch.from_doxa(ax)


def make_query(ax: str, **option_overrides) -> Query:
    q = Query.from_doxa(ax)
    if not option_overrides:
        return q

    data = q.options.model_dump()
    sem = data.pop("epistemic_semantics")

    semantic_keys = set(EpistemicSemanticsConfig.model_fields.keys())
    for key in list(option_overrides.keys()):
        if key in semantic_keys:
            sem[key] = option_overrides.pop(key)

    data["epistemic_semantics"] = sem
    data.update(option_overrides)

    return q.model_copy(update={"options": QueryOptions(**data)})


def evaluate(branch: Branch, query: Query):
    engine = InMemoryQueryEngine()
    public_evaluate = getattr(engine, "evaluate", None)
    if callable(public_evaluate):
        return public_evaluate(branch, query)
    return engine._evaluate(branch, query)


def run(branch_ax: str, query_ax: str, **options):
    return evaluate(make_branch(branch_ax), make_query(query_ax, **options))


def assert_single_answer(result):
    assert len(result.answers) == 1
    return result.answers[0]


def answers_by_var(result, var_name: str) -> dict[object, object]:
    return {answer.bindings[var_name]: answer for answer in result.answers}


# ---------------------------------------------------------------------------
# Basic facts / closed queries / Belnap status
# ---------------------------------------------------------------------------


def test_ground_fact_query_returns_true_answer():
    result = run(
        """
        p(a).
        """,
        "?- p(a)",
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.true


def test_variable_fact_query_returns_all_bindings():
    result = run(
        """
        p(a).
        p(b).
        """,
        '?- p(X) @{order_by:"X"}',
    )

    assert [a.bindings["X"] for a in result.answers] == ["a", "b"]
    for answer in result.answers:
        assert answer.b == pytest.approx(1.0)
        assert answer.d == pytest.approx(0.0)
        assert answer.belnap_status is BelnapStatus.true


def test_closed_unsupported_query_returns_single_neither_answer():
    result = run("", "?- p(a)")

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(0.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.neither


@pytest.mark.parametrize(
    ("fact_src", "expected_status", "expected_b", "expected_d"),
    [
        ('p(a) @{b:1.0, d:0.0}.', BelnapStatus.true, 1.0, 0.0),
        ('p(a) @{b:0.0, d:1.0}.', BelnapStatus.false, 0.0, 1.0),
        ('p(a) @{b:0.7, d:0.2}.', BelnapStatus.both, 0.7, 0.2),
    ],
)
def test_belnap_statuses_from_visible_evidence(
    fact_src,
    expected_status,
    expected_b,
    expected_d,
):
    result = run(fact_src, "?- p(a)")

    answer = assert_single_answer(result)
    assert answer.b == pytest.approx(expected_b)
    assert answer.d == pytest.approx(expected_d)
    assert answer.belnap_status is expected_status


def test_anonymous_variables_are_not_projected():
    result = run(
        """
        p(a).
        p(b).
        """,
        "?- p(_)",
    )

    # Both matches collapse into the same projected row {}
    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Temporal visibility
# ---------------------------------------------------------------------------


def test_record_visibility_respects_known_at_and_valid_interval():
    result = run(
        """
        p(visible) @{et:"2025-01-01T00:00:00Z", vf:"2025-01-01T00:00:00Z", vt:"2025-12-31T00:00:00Z"}.
        p(future_known) @{et:"2025-07-01T00:00:00Z", vf:"2025-01-01T00:00:00Z", vt:"2025-12-31T00:00:00Z"}.
        p(expired) @{et:"2025-01-01T00:00:00Z", vf:"2025-01-01T00:00:00Z", vt:"2025-05-01T00:00:00Z"}.
        """,
        '?- p(X) @{order_by:"X"}',
        query_time=utc(2025, 6, 1),
        valid_at=utc(2025, 6, 1),
        known_at=utc(2025, 6, 1),
    )

    assert [a.bindings["X"] for a in result.answers] == ["visible"]
    assert result.effective_query_time == utc(2025, 6, 1)
    assert result.effective_valid_at == utc(2025, 6, 1)
    assert result.effective_known_at == utc(2025, 6, 1)


# ---------------------------------------------------------------------------
# Builtins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query_ax", "expected_bindings"),
    [
        ('?- eq(X, a)', {"X": "a"}),
        ('?- add(2, 3, X)', {"X": 5}),
        ('?- add(X, 3, 5)', {"X": 2}),
        ('?- sub(7, X, 4)', {"X": 3}),
        ('?- mul(3, 4, X)', {"X": 12}),
        ('?- mul(X, 4, 12)', {"X": 3}),
        ('?- div(8, 2, X)', {"X": 4}),
        ('?- div(X, 2, 4)', {"X": 8}),
    ],
)
def test_arithmetic_and_eq_builtins_bind_single_unknown(query_ax, expected_bindings):
    result = run("", query_ax)

    answer = assert_single_answer(result)
    assert answer.bindings == expected_bindings
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.true


def test_division_by_zero_produces_no_open_query_answers():
    result = run("", "?- div(1, 0, X)")
    assert result.answers == ()


def test_comparison_and_between_builtins_filter_rows():
    result = run(
        """
        age(alice, 30).
        age(bob, 16).
        age(carol, 18).
        """,
        '?- age(X, A), geq(A, 18), leq(A, 30), between(A, 18, 30) @{order_by:"X"}',
    )

    assert [a.bindings["X"] for a in result.answers] == ["alice", "carol"]


@pytest.mark.parametrize(
    ("query_ax", "expected_bindings"),
    [
        ('?- eq(X, 3), int(X)', {"X": 3}),
        ('?- eq(X, 3.5), float(X)', {"X": 3.5}),
        ('?- eq(X, "hi"), string(X)', {"X": "hi"}),
        ('?- eq(X, alice), entity(X)', {"X": "alice"}),
    ],
)
def test_type_builtins_accept_matching_values(query_ax, expected_bindings):
    result = run("", query_ax)

    answer = assert_single_answer(result)
    assert answer.bindings == expected_bindings
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)


def test_builtin_inside_rule_body_filters_rule_applicability():
    result = run(
        """
        age(alice, 30).
        age(bob, 14).

        adult(X) :- age(X, A), geq(A, 18).
        """,
        '?- adult(X) @{order_by:"X"}',
    )

    assert [a.bindings["X"] for a in result.answers] == ["alice"]


# ---------------------------------------------------------------------------
# Body truth / falsity semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body_truth", "expected_b"),
    [
        (BodyTruthSemantics.product, 0.8 * 0.6),
        (BodyTruthSemantics.minimum, 0.6),
    ],
)
def test_body_truth_semantics_change_combined_support(body_truth, expected_b):
    result = run(
        """
        p(a) @{b:0.8, d:0.0}.
        q(a) @{b:0.6, d:0.0}.
        """,
        "?- p(a), q(a)",
        body_truth=body_truth,
    )

    answer = assert_single_answer(result)
    assert answer.b == pytest.approx(expected_b)
    assert answer.d == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("body_falsity", "expected_d"),
    [
        (BodyFalsitySemantics.maximum, 0.3),
        (BodyFalsitySemantics.noisy_or, 1.0 - (1.0 - 0.2) * (1.0 - 0.3)),
    ],
)
def test_body_falsity_semantics_change_combined_falsity(body_falsity, expected_d):
    result = run(
        """
        p(a) @{b:1.0, d:0.2}.
        q(a) @{b:1.0, d:0.3}.
        """,
        "?- p(a), q(a)",
        body_falsity=body_falsity,
    )

    answer = assert_single_answer(result)
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(expected_d)


# ---------------------------------------------------------------------------
# Rules / aggregation / max depth
# ---------------------------------------------------------------------------


def test_rule_derivation_propagates_rule_weights():
    result = run(
        """
        human(alice).

        mortal(X) :- human(X) @{b:0.6, d:0.2}.
        """,
        "?- mortal(alice)",
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(0.6)
    assert answer.d == pytest.approx(0.2)
    assert answer.belnap_status is BelnapStatus.both


def test_rule_applicability_can_discount_body_truth_by_body_falsity():
    result = run(
        """
        human(alice) @{b:0.8, d:0.25}.

        mortal(X) :- human(X) @{b:0.9, d:0.2}.
        """,
        "?- mortal(alice)",
        rule_applicability=(
            RuleApplicabilitySemantics.body_truth_discounted_by_body_falsity
        ),
    )

    answer = assert_single_answer(result)

    applicability = 0.8 * (1.0 - 0.25)
    assert answer.b == pytest.approx(applicability * 0.9)
    assert answer.d == pytest.approx(applicability * 0.2)
    assert answer.belnap_status is BelnapStatus.both


@pytest.mark.parametrize(
    ("support_aggregation", "expected_b"),
    [
        (SupportAggregationSemantics.maximum, 0.5),
        (SupportAggregationSemantics.capped_sum, 0.9),
        (SupportAggregationSemantics.noisy_or, 1.0 - (1.0 - 0.4) * (1.0 - 0.5)),
    ],
)
def test_multiple_rule_derivations_are_aggregated_per_binding(
    support_aggregation,
    expected_b,
):
    result = run(
        """
        p(a).

        r(X) :- p(X) @{b:0.4, d:0.0}.
        r(X) :- p(X) @{b:0.5, d:0.0}.
        """,
        "?- r(a)",
        support_aggregation=support_aggregation,
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(expected_b)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.true


def test_recursive_rule_chain_respects_max_depth():
    branch_ax = """
    p(a).
    q(X) :- p(X).
    r(X) :- q(X).
    """

    shallow = run(branch_ax, "?- r(a)", max_depth=1)
    shallow_answer = assert_single_answer(shallow)
    assert shallow_answer.b == pytest.approx(0.0)
    assert shallow_answer.d == pytest.approx(0.0)
    assert shallow_answer.belnap_status is BelnapStatus.neither

    deep_enough = run(branch_ax, "?- r(a)", max_depth=2)
    deep_answer = assert_single_answer(deep_enough)
    assert deep_answer.b == pytest.approx(1.0)
    assert deep_answer.d == pytest.approx(0.0)
    assert deep_answer.belnap_status is BelnapStatus.true


# ---------------------------------------------------------------------------
# Negation
# ---------------------------------------------------------------------------


def test_negated_atom_acts_as_crisp_filter():
    result = run(
        """
        p(a).
        q(a).
        q(b).
        """,
        '?- q(X), not p(X) @{order_by:"X"}',
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {"X": "b"}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.true


def test_negation_succeeds_if_positive_atom_has_only_disbelief_and_no_support():
    result = run(
        """
        p(a) @{b:0.0, d:0.9}.
        """,
        "?- not p(a)",
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.true


def test_negation_in_rule_body_works():
    result = run(
        """
        human(alice).
        human(bob).
        friend(alice).

        lonely(X) :- human(X), not friend(X).
        """,
        '?- lonely(X) @{order_by:"X"}',
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {"X": "bob"}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


def test_constraint_adds_violation_to_successful_derivation():
    result = run(
        """
        p(a).
        q(a).

        !:- p(X), q(X) @{b:0.7}.
        """,
        "?- p(a), q(a)",
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.7)
    assert answer.belnap_status is BelnapStatus.both


def test_constraint_does_not_apply_if_derivation_footprint_is_too_small():
    result = run(
        """
        p(a).
        q(a).

        !:- p(X), q(X) @{b:0.7}.
        """,
        "?- p(a)",
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.true


def test_constraint_applicability_can_discount_by_body_falsity():
    result = run(
        """
        p(a) @{b:1.0, d:0.25}.
        q(a) @{b:1.0, d:0.0}.

        !:- p(X), q(X) @{b:0.8}.
        """,
        "?- p(a), q(a)",
        constraint_applicability=(
            ConstraintApplicabilitySemantics.body_truth_discounted_by_body_falsity
        ),
    )

    answer = assert_single_answer(result)

    # Query body falsity from p(a), q(a):
    # current_falsity = noisy_or(0.25, 0.0) = 0.25
    # constraint applicability = 1.0 * (1 - 0.25) = 0.75
    # violation = 0.75 * 0.8 = 0.6
    # final falsity = noisy_or(0.25, 0.6) = 1 - (0.75 * 0.4) = 0.7
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.7)
    assert answer.belnap_status is BelnapStatus.both


# ---------------------------------------------------------------------------
# Focus / sorting / slicing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("focus", "expected_order"),
    [
        (QueryFocus.support, ["a", "c"]),
        (QueryFocus.disbelief, ["b", "c"]),
        (QueryFocus.contradiction, ["c"]),
    ],
)
def test_focus_filters_and_ranks_answers(focus, expected_order):
    result = run(
        """
        p(a) @{b:0.9, d:0.0}.
        p(b) @{b:0.0, d:0.8}.
        p(c) @{b:0.4, d:0.3}.
        """,
        "?- p(X)",
        focus=focus,
    )

    assert [a.bindings["X"] for a in result.answers] == expected_order


def test_ignorance_focus_keeps_closed_neither_answer():
    result = run("", "?- missing(a)", focus=QueryFocus.ignorance)

    answer = assert_single_answer(result)
    assert answer.bindings == {}
    assert answer.b == pytest.approx(0.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.neither


def test_order_by_offset_and_limit_are_applied_after_answer_construction():
    result = run(
        """
        p(3).
        p(1).
        p(2).
        """,
        '?- p(X) @{order_by:"X"}',
        offset=1,
        limit=1,
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {"X": 2}


# ---------------------------------------------------------------------------
# Explain output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("explain_mode", ["true", "human"])
def test_explain_modes_enable_explain_collection(explain_mode):
    result = run(
        """
        p(a).
        q(X) :- p(X) @{b:0.6, d:0.1}.
        """,
        "?- q(a)",
        explain=explain_mode,
    )

    assert result.explain is not None
    assert len(result.explain) >= 1
    event_types = {event["type"] for event in result.explain}
    assert "fact_support" in event_types
    assert "rule_applicability" in event_types
    assert "rule_support" in event_types


def test_explain_false_disables_explain_collection():
    result = run(
        """
        p(a).
        """,
        "?- p(a)",
        explain="false",
    )

    assert result.explain is None


# ---------------------------------------------------------------------------
# Inline assumptions / skolemization
# ---------------------------------------------------------------------------


def test_skolemized_inline_assumption_bridges_edb_goal_to_idb_goal():
    result = run(
        """
        chosen(X) :- edge(root, X).
        """,
        "?- edge(root, X), chosen(X)",
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {"X": "_hyp_X"}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)
    assert answer.belnap_status is BelnapStatus.true


def test_existing_visible_facts_prevent_inline_assumption_injection():
    result = run(
        """
        edge(root, a).
        chosen(X) :- edge(root, X).
        """,
        "?- edge(root, X), chosen(X)",
    )

    answer = assert_single_answer(result)
    assert answer.bindings == {"X": "a"}
    assert answer.b == pytest.approx(1.0)
    assert answer.d == pytest.approx(0.0)


def test_single_goal_query_does_not_inline_assume_missing_edb_fact():
    result = run(
        "",
        "?- edge(root, X)",
    )

    # Important: assumption injection is deliberately disabled for single-goal queries.
    assert result.answers == ()