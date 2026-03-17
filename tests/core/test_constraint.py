import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import Builtin
from doxa.core.constraint import (
    Constraint,
    ConstraintAtomGoal,
    ConstraintBuiltinGoal,
    ConstraintEntityArg,
    ConstraintLiteralArg,
    ConstraintVarArg,
    constraint_goal_arg_from_ax,
    constraint_goal_from_ax,
)
from doxa.core.goal_kinds import GoalKind
from doxa.core.literal_type import LiteralType
from doxa.core.var import Var


def test_constraint_var_arg_from_ax() -> None:
    arg = ConstraintVarArg.from_ax("X")

    assert arg.kind == BaseKind.goal_arg
    assert arg.term_kind == "var"
    assert arg.pos == 0
    assert arg.var == Var.from_ax("X")
    assert arg.to_ax() == "X"


def test_constraint_entity_arg_from_ax() -> None:
    arg = ConstraintEntityArg.from_ax("thomas")

    assert arg.kind == BaseKind.goal_arg
    assert arg.term_kind == "ent"
    assert arg.pos == 0
    assert arg.ent_name == "thomas"
    assert arg.to_ax() == "thomas"


def test_constraint_literal_arg_from_ax_string() -> None:
    arg = ConstraintLiteralArg.from_ax('"hello world"')

    assert arg.kind == BaseKind.goal_arg
    assert arg.term_kind == "lit"
    assert arg.pos == 0
    assert arg.lit_type == LiteralType.str
    assert arg.value == "hello world"
    assert arg.to_ax() == '"hello world"'


def test_constraint_literal_arg_from_ax_int() -> None:
    arg = ConstraintLiteralArg.from_ax("42")

    assert arg.lit_type == LiteralType.int
    assert arg.value == 42
    assert arg.to_ax() == "42"


def test_constraint_literal_arg_from_ax_float() -> None:
    arg = ConstraintLiteralArg.from_ax("3.14")

    assert arg.lit_type == LiteralType.float
    assert arg.value == 3.14
    assert arg.to_ax() == "3.14"


def test_constraint_literal_arg_rejects_invalid_literal() -> None:
    with pytest.raises(ValueError, match="Invalid literal argument"):
        ConstraintLiteralArg.from_ax("not_a_literal")


def test_constraint_literal_arg_rejects_wrong_type_for_int() -> None:
    with pytest.raises(ValidationError):
        ConstraintLiteralArg(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="lit",
            lit_type=LiteralType.int,
            value="42",
        )


def test_constraint_literal_arg_rejects_wrong_type_for_float() -> None:
    with pytest.raises(ValidationError):
        ConstraintLiteralArg(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="lit",
            lit_type=LiteralType.float,
            value=3,
        )


def test_constraint_goal_arg_dispatch_var() -> None:
    arg = constraint_goal_arg_from_ax("X")
    assert isinstance(arg, ConstraintVarArg)
    assert arg.var == Var.from_ax("X")


def test_constraint_goal_arg_dispatch_entity() -> None:
    arg = constraint_goal_arg_from_ax("thomas")
    assert isinstance(arg, ConstraintEntityArg)
    assert arg.ent_name == "thomas"


def test_constraint_goal_arg_dispatch_literal_string() -> None:
    arg = constraint_goal_arg_from_ax('"abc"')
    assert isinstance(arg, ConstraintLiteralArg)
    assert arg.lit_type == LiteralType.str
    assert arg.value == "abc"


def test_constraint_goal_arg_dispatch_literal_int() -> None:
    arg = constraint_goal_arg_from_ax("10")
    assert isinstance(arg, ConstraintLiteralArg)
    assert arg.lit_type == LiteralType.int
    assert arg.value == 10


def test_constraint_goal_arg_dispatch_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="Invalid goal argument"):
        constraint_goal_arg_from_ax("")


def test_constraint_atom_goal_from_ax() -> None:
    goal = ConstraintAtomGoal.from_ax("parent(X, thomas)")

    assert goal.kind == BaseKind.goal
    assert goal.goal_kind == GoalKind.atom
    assert goal.idx == 0
    assert goal.pred_name == "parent"
    assert goal.pred_arity == 2
    assert goal.negated is False
    assert len(goal.goal_args) == 2
    assert isinstance(goal.goal_args[0], ConstraintVarArg)
    assert isinstance(goal.goal_args[1], ConstraintEntityArg)
    assert goal.goal_args[0].pos == 0
    assert goal.goal_args[1].pos == 1
    assert goal.to_ax() == "parent(X, thomas)"


def test_constraint_atom_goal_from_ax_negated() -> None:
    goal = ConstraintAtomGoal.from_ax("not parent(X, thomas)")

    assert goal.negated is True
    assert goal.to_ax() == "not parent(X, thomas)"


def test_constraint_atom_goal_rejects_builtin_input() -> None:
    with pytest.raises(ValueError, match="Builtin goal cannot be parsed as AtomGoal"):
        ConstraintAtomGoal.from_ax("eq(X, Y)")


def test_constraint_atom_goal_rejects_wrong_arity() -> None:
    with pytest.raises(ValidationError):
        ConstraintAtomGoal(
            kind=BaseKind.goal,
            goal_kind=GoalKind.atom,
            idx=0,
            pred_name="parent",
            pred_arity=2,
            negated=False,
            goal_args=[
                ConstraintVarArg.from_ax("X"),
            ],
        )


def test_constraint_builtin_goal_from_ax() -> None:
    goal = ConstraintBuiltinGoal.from_ax("eq(X, Y)")

    assert goal.kind == BaseKind.goal
    assert goal.goal_kind == GoalKind.builtin
    assert goal.idx == 0
    assert goal.builtin_name == Builtin.eq
    assert len(goal.goal_args) == 2
    assert isinstance(goal.goal_args[0], ConstraintVarArg)
    assert isinstance(goal.goal_args[1], ConstraintVarArg)
    assert goal.goal_args[0].pos == 0
    assert goal.goal_args[1].pos == 1
    assert goal.to_ax() == "eq(X, Y)"


def test_constraint_builtin_goal_rejects_negation() -> None:
    with pytest.raises(ValueError, match="Builtin goals cannot be negated"):
        ConstraintBuiltinGoal.from_ax("not eq(X, Y)")


def test_constraint_builtin_goal_rejects_unknown_builtin() -> None:
    with pytest.raises(ValueError, match="Unknown builtin goal"):
        ConstraintBuiltinGoal.from_ax("foo(X, Y)")


def test_constraint_builtin_goal_rejects_wrong_arity() -> None:
    with pytest.raises(ValidationError):
        ConstraintBuiltinGoal(
            kind=BaseKind.goal,
            goal_kind=GoalKind.builtin,
            idx=0,
            builtin_name=Builtin.eq,
            goal_args=[ConstraintVarArg.from_ax("X")],
        )


def test_constraint_goal_dispatch_atom() -> None:
    goal = constraint_goal_from_ax("parent(X, Y)")
    assert isinstance(goal, ConstraintAtomGoal)


def test_constraint_goal_dispatch_builtin() -> None:
    goal = constraint_goal_from_ax("eq(X, Y)")
    assert isinstance(goal, ConstraintBuiltinGoal)


def test_constraint_goal_dispatch_negated_atom() -> None:
    goal = constraint_goal_from_ax("not parent(X, Y)")
    assert isinstance(goal, ConstraintAtomGoal)
    assert goal.negated is True


def test_constraint_goal_dispatch_rejects_negated_builtin() -> None:
    with pytest.raises(ValueError, match="Builtin goals cannot be negated"):
        constraint_goal_from_ax("not eq(X, Y)")


def test_constraint_from_ax_simple() -> None:
    c = Constraint.from_ax("!:- parent(X, Y), not person(X)")

    assert c.kind == BaseKind.constraint
    assert len(c.goals) == 2
    assert isinstance(c.goals[0], ConstraintAtomGoal)
    assert isinstance(c.goals[1], ConstraintAtomGoal)
    assert c.goals[0].idx == 0
    assert c.goals[1].idx == 1
    assert c.goals[1].negated is True
    assert c.to_ax() == "!:- parent(X, Y), not person(X)"


def test_constraint_from_ax_with_builtin() -> None:
    c = Constraint.from_ax("!:- risk_score(X, S), lt(S, 0)")

    assert len(c.goals) == 2
    assert isinstance(c.goals[0], ConstraintAtomGoal)
    assert isinstance(c.goals[1], ConstraintBuiltinGoal)
    assert c.goals[1].builtin_name == Builtin.lt
    assert c.to_ax() == "!:- risk_score(X, S), lt(S, 0)"


def test_constraint_from_ax_with_annotation() -> None:
    c = Constraint.from_ax(
        '!:- ancestor(X, X) @{name:"no_self_ancestor", description:"integrity check"}'
    )

    assert c.name == "no_self_ancestor"
    assert c.description == "integrity check"
    assert c.to_ax() == (
        '!:- ancestor(X, X) @{name:"no_self_ancestor", description:"integrity check"}'
    )


def test_constraint_to_ax_omits_default_annotation() -> None:
    c = Constraint.from_ax("!:- parent(X, Y)")
    assert c.to_ax() == "!:- parent(X, Y)"


def test_constraint_from_ax_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        Constraint.from_ax(None)  # type: ignore[arg-type]


def test_constraint_from_ax_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Constraint.from_ax("")


def test_constraint_from_ax_rejects_missing_prefix() -> None:
    with pytest.raises(ValueError, match="must start with '!:-'"):
        Constraint.from_ax("parent(X, Y)")


def test_constraint_from_ax_rejects_empty_body() -> None:
    with pytest.raises(ValueError, match="body must not be empty"):
        Constraint.from_ax("!:-")


def test_constraint_goal_indices_must_be_contiguous() -> None:
    g0 = ConstraintAtomGoal.from_ax("parent(X, Y)")
    g1 = ConstraintAtomGoal.from_ax("person(X)")

    with pytest.raises(ValidationError):
        Constraint(
            kind=BaseKind.constraint,
            goals=[
                g0.model_copy(update={"idx": 0}),
                g1.model_copy(update={"idx": 2}),
            ],
        )


def test_constraint_round_trip_simple() -> None:
    original = Constraint.from_ax("!:- parent(X, Y), not person(X)")
    reparsed = Constraint.from_ax(original.to_ax())

    assert reparsed.model_dump(exclude={"created_at", "updated_at"}) == (
        original.model_dump(exclude={"created_at", "updated_at"})
    )


def test_constraint_round_trip_with_annotation() -> None:
    original = Constraint.from_ax(
        '!:- ancestor(X, X) @{description:"integrity check", name:"no_self_ancestor"}'
    )
    reparsed = Constraint.from_ax(original.to_ax())

    assert reparsed.model_dump(exclude={"created_at", "updated_at"}) == (
        original.model_dump(exclude={"created_at", "updated_at"})
    )


def test_constraint_string_literal_round_trip() -> None:
    original = Constraint.from_ax('!:- label(X, "hello world"), eq("a", "a")')
    reparsed = Constraint.from_ax(original.to_ax())

    assert reparsed.model_dump(exclude={"created_at", "updated_at"}) == (
        original.model_dump(exclude={"created_at", "updated_at"})
    )
