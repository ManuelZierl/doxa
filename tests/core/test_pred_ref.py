"""Tests for first-class predicate reference values (name/arity)."""

import pytest

from doxa.core import Branch
from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import (
    BeliefPredRefArg,
    belief_arg_from_doxa,
)
from doxa.core.goal import PredRefArg, goal_arg_from_doxa
from doxa.core.rule import (
    RuleGoalPredRefArg,
    RuleHeadPredRefArg,
    rule_goal_arg_from_doxa,
    rule_head_arg_from_doxa,
)
from doxa.core.term_kinds import TermKind


# ── BeliefPredRefArg parsing ────────────────────────────────────────────────


def test_belief_pred_ref_arg_from_doxa() -> None:
    arg = BeliefPredRefArg.from_doxa("parent/2")

    assert arg.kind == BaseKind.belief_arg
    assert arg.term_kind == TermKind.pred_ref
    assert arg.pred_ref_name == "parent"
    assert arg.pred_ref_arity == 2


def test_belief_pred_ref_arg_to_doxa() -> None:
    arg = BeliefPredRefArg.from_doxa("alive/1")
    assert arg.to_doxa() == "alive/1"


def test_belief_pred_ref_arg_round_trip() -> None:
    original = "ancestor/3"
    arg = BeliefPredRefArg.from_doxa(original)
    assert arg.to_doxa() == original


def test_belief_arg_dispatch_recognizes_pred_ref() -> None:
    """belief_arg_from_doxa should correctly dispatch to BeliefPredRefArg."""
    arg = belief_arg_from_doxa("foo/2")
    assert isinstance(arg, BeliefPredRefArg)
    assert arg.pred_ref_name == "foo"
    assert arg.pred_ref_arity == 2


def test_belief_pred_ref_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid predicate reference"):
        BeliefPredRefArg.from_doxa("Foo/2")

    with pytest.raises(ValueError, match="Invalid predicate reference"):
        BeliefPredRefArg.from_doxa("foo/")

    with pytest.raises(ValueError, match="Invalid predicate reference"):
        BeliefPredRefArg.from_doxa("/2")

    with pytest.raises(ValueError, match="Invalid predicate reference"):
        BeliefPredRefArg.from_doxa("foo")


# ── PredRefArg (goal) parsing ───────────────────────────────────────────────


def test_goal_pred_ref_arg_from_doxa() -> None:
    arg = PredRefArg.from_doxa("parent/2")

    assert arg.kind == BaseKind.goal_arg
    assert arg.term_kind == "pred_ref"
    assert arg.pred_ref_name == "parent"
    assert arg.pred_ref_arity == 2


def test_goal_pred_ref_arg_to_doxa() -> None:
    arg = PredRefArg.from_doxa("alive/1")
    assert arg.to_doxa() == "alive/1"


def test_goal_arg_dispatch_recognizes_pred_ref() -> None:
    arg = goal_arg_from_doxa("bar/3")
    assert isinstance(arg, PredRefArg)
    assert arg.pred_ref_name == "bar"
    assert arg.pred_ref_arity == 3


# ── RuleHeadPredRefArg parsing ──────────────────────────────────────────────


def test_rule_head_pred_ref_arg_from_doxa() -> None:
    arg = RuleHeadPredRefArg.from_doxa("parent/2")

    assert arg.kind == BaseKind.rule_head_arg
    assert arg.term_kind == TermKind.pred_ref
    assert arg.pred_ref_name == "parent"
    assert arg.pred_ref_arity == 2


def test_rule_head_pred_ref_arg_to_doxa() -> None:
    arg = RuleHeadPredRefArg.from_doxa("alive/1")
    assert arg.to_doxa() == "alive/1"


def test_rule_head_arg_dispatch_recognizes_pred_ref() -> None:
    arg = rule_head_arg_from_doxa("baz/4")
    assert isinstance(arg, RuleHeadPredRefArg)


# ── RuleGoalPredRefArg parsing ──────────────────────────────────────────────


def test_rule_goal_pred_ref_arg_from_doxa() -> None:
    arg = RuleGoalPredRefArg.from_doxa("parent/2")

    assert arg.kind == BaseKind.rule_goal_arg
    assert arg.term_kind == TermKind.pred_ref
    assert arg.pred_ref_name == "parent"
    assert arg.pred_ref_arity == 2


def test_rule_goal_pred_ref_arg_to_doxa() -> None:
    arg = RuleGoalPredRefArg.from_doxa("alive/1")
    assert arg.to_doxa() == "alive/1"


def test_rule_goal_arg_dispatch_recognizes_pred_ref() -> None:
    arg = rule_goal_arg_from_doxa("qux/1")
    assert isinstance(arg, RuleGoalPredRefArg)


# ── Branch-level integration (facts with pred refs) ────────────────────────


def test_fact_with_pred_ref_arg() -> None:
    """A fact like bar(foo/2). should parse correctly."""
    branch = Branch.from_doxa("bar(foo/2).")

    assert len(branch.belief_records) == 1
    rec = branch.belief_records[0]
    assert rec.pred_name == "bar"
    assert rec.pred_arity == 1
    assert isinstance(rec.args[0], BeliefPredRefArg)
    assert rec.args[0].pred_ref_name == "foo"
    assert rec.args[0].pred_ref_arity == 2


def test_fact_with_multiple_pred_ref_args() -> None:
    """subpredicate(child_of/2, parent_like/2). should parse correctly."""
    branch = Branch.from_doxa("subpredicate(child_of/2, parent_like/2).")

    assert len(branch.belief_records) == 1
    rec = branch.belief_records[0]
    assert rec.pred_name == "subpredicate"
    assert rec.pred_arity == 2
    assert isinstance(rec.args[0], BeliefPredRefArg)
    assert rec.args[0].pred_ref_name == "child_of"
    assert rec.args[0].pred_ref_arity == 2
    assert isinstance(rec.args[1], BeliefPredRefArg)
    assert rec.args[1].pred_ref_name == "parent_like"
    assert rec.args[1].pred_ref_arity == 2


def test_fact_mixing_pred_ref_and_entity_args() -> None:
    """registry(parent/2, alice). mixes pred ref and entity."""
    branch = Branch.from_doxa("registry(parent/2, alice).")

    rec = branch.belief_records[0]
    assert rec.pred_arity == 2
    assert isinstance(rec.args[0], BeliefPredRefArg)
    assert rec.args[0].pred_ref_name == "parent"
    from doxa.core.belief_record import BeliefEntityArg

    assert isinstance(rec.args[1], BeliefEntityArg)
    assert rec.args[1].ent_name == "alice"


def test_fact_mixing_pred_ref_and_literal_args() -> None:
    """info(parent/2, "a relation", 42). mixes pred ref, string, and int."""
    branch = Branch.from_doxa('info(parent/2, "a relation", 42).')

    rec = branch.belief_records[0]
    assert rec.pred_arity == 3
    assert isinstance(rec.args[0], BeliefPredRefArg)
    from doxa.core.belief_record import BeliefLiteralArg

    assert isinstance(rec.args[1], BeliefLiteralArg)
    assert rec.args[1].value == "a relation"
    assert isinstance(rec.args[2], BeliefLiteralArg)
    assert rec.args[2].value == 42


def test_fact_with_pred_ref_round_trip() -> None:
    """A fact with pred ref should survive to_doxa/from_doxa round trip."""
    branch = Branch.from_doxa("bar(foo/2).")

    doxa_output = branch.to_doxa()
    assert "bar(foo/2)" in doxa_output

    reparsed = Branch.from_doxa(doxa_output)
    assert len(reparsed.belief_records) == 1
    rec = reparsed.belief_records[0]
    assert isinstance(rec.args[0], BeliefPredRefArg)
    assert rec.args[0].pred_ref_name == "foo"
    assert rec.args[0].pred_ref_arity == 2


# ── Rule with pred ref args ─────────────────────────────────────────────────


def test_rule_with_pred_ref_in_head() -> None:
    """A rule head can contain pred ref values."""
    branch = Branch.from_doxa(
        """
        documented(parent/2).
        documented_type(X, "predicate") :- documented(X).
        """
    )

    assert len(branch.rules) == 1


def test_rule_with_pred_ref_in_body() -> None:
    """A rule body goal can contain pred ref values."""
    branch = Branch.from_doxa(
        """
        registry(parent/2).
        registry(ancestor/2).
        is_registered(parent/2).
        is_registered(X) :- registry(X).
        """
    )

    assert len(branch.rules) == 1
    assert len(branch.belief_records) == 3


# ── pred_ref does not require existing predicate ────────────────────────────


def test_pred_ref_forward_reference() -> None:
    """foo/2 in a fact does not require foo/2 to be declared or used."""
    branch = Branch.from_doxa("meta(foo/2).")

    assert len(branch.belief_records) == 1
    rec = branch.belief_records[0]
    assert isinstance(rec.args[0], BeliefPredRefArg)
    assert rec.args[0].pred_ref_name == "foo"
    # foo/2 is NOT auto-created as a predicate
    pred_names = {p.name for p in branch.predicates}
    assert "meta" in pred_names
    # foo should NOT be in predicates (it's just a value, not a usage)
    assert "foo" not in pred_names


# ── predicate_ref is a valid builtin type name ──────────────────────────────


def test_predicate_ref_builtin_in_type_list() -> None:
    """predicate_ref can be used in a pred type_list."""
    branch = Branch.from_doxa(
        """
        pred registry/1 [predicate_ref].
        registry(parent/2).
        """
    )

    assert len(branch.predicates) >= 1
    reg_pred = next(p for p in branch.predicates if p.name == "registry")
    assert reg_pred.type_list == ["predicate_ref"]
