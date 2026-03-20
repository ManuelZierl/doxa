import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import Builtin
from doxa.core.constraint import Constraint, goal_from_doxa
from doxa.core.goal import (
    AtomGoal,
    BuiltinGoal,
    EntityArg,
    LiteralArg,
    VarArg,
    goal_arg_from_doxa,
)
from doxa.core.goal_kinds import GoalKind
from doxa.core.literal_type import LiteralType
from doxa.core.var import Var


def test_constraint_var_arg_from_doxa() -> None:
    arg = VarArg.from_doxa("X")

    assert arg.kind == BaseKind.goal_arg
    assert arg.term_kind == "var"
    assert arg.pos == 0
    assert arg.var == Var.from_doxa("X")
    assert arg.to_doxa() == "X"


def test_constraint_entity_arg_from_doxa() -> None:
    arg = EntityArg.from_doxa("zeus")

    assert arg.kind == BaseKind.goal_arg
    assert arg.term_kind == "ent"
    assert arg.pos == 0
    assert arg.ent_name == "zeus"
    assert arg.to_doxa() == "zeus"


def test_constraint_literal_arg_from_doxa_string() -> None:
    arg = LiteralArg.from_doxa('"hello world"')

    assert arg.kind == BaseKind.goal_arg
    assert arg.term_kind == "lit"
    assert arg.pos == 0
    assert arg.lit_type == LiteralType.str
    assert arg.value == "hello world"
    assert arg.to_doxa() == '"hello world"'


def test_constraint_literal_arg_from_doxa_int() -> None:
    arg = LiteralArg.from_doxa("42")

    assert arg.lit_type == LiteralType.int
    assert arg.value == 42
    assert arg.to_doxa() == "42"


def test_constraint_literal_arg_from_doxa_float() -> None:
    arg = LiteralArg.from_doxa("3.14")

    assert arg.lit_type == LiteralType.float
    assert arg.value == 3.14
    assert arg.to_doxa() == "3.14"


def test_constraint_literal_arg_rejects_invalid_literal() -> None:
    with pytest.raises(ValueError, match="Invalid literal argument"):
        LiteralArg.from_doxa("not_a_literal")


def test_constraint_literal_arg_rejects_wrong_type_for_int() -> None:
    with pytest.raises(ValidationError):
        LiteralArg(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="lit",
            lit_type=LiteralType.int,
            value="42",
        )


def test_constraint_literal_arg_rejects_wrong_type_for_float() -> None:
    with pytest.raises(ValidationError):
        LiteralArg(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="lit",
            lit_type=LiteralType.float,
            value=3,
        )


def test_constraint_goal_arg_dispatch_var() -> None:
    arg = goal_arg_from_doxa("X")
    assert isinstance(arg, VarArg)
    assert arg.var == Var.from_doxa("X")


def test_constraint_goal_arg_dispatch_entity() -> None:
    arg = goal_arg_from_doxa("zeus")
    assert isinstance(arg, EntityArg)
    assert arg.ent_name == "zeus"


def test_constraint_goal_arg_dispatch_literal_string() -> None:
    arg = goal_arg_from_doxa('"abc"')
    assert isinstance(arg, LiteralArg)
    assert arg.lit_type == LiteralType.str
    assert arg.value == "abc"


def test_constraint_goal_arg_dispatch_literal_int() -> None:
    arg = goal_arg_from_doxa("10")
    assert isinstance(arg, LiteralArg)
    assert arg.lit_type == LiteralType.int
    assert arg.value == 10


def test_constraint_goal_arg_dispatch_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="Invalid goal argument"):
        goal_arg_from_doxa("")


def test_constraint_atom_goal_from_doxa() -> None:
    goal = AtomGoal.from_doxa("parent(X, zeus)")

    assert goal.kind == BaseKind.goal
    assert goal.goal_kind == GoalKind.atom
    assert goal.idx == 0
    assert goal.pred_name == "parent"
    assert goal.pred_arity == 2
    assert goal.negated is False
    assert len(goal.goal_args) == 2
    assert isinstance(goal.goal_args[0], VarArg)
    assert isinstance(goal.goal_args[1], EntityArg)
    assert goal.goal_args[0].pos == 0
    assert goal.goal_args[1].pos == 1
    assert goal.to_doxa() == "parent(X, zeus)"


def test_constraint_atom_goal_from_doxa_negated() -> None:
    goal = AtomGoal.from_doxa("not parent(X, zeus)")

    assert goal.negated is True
    assert goal.to_doxa() == "not parent(X, zeus)"


def test_constraint_atom_goal_rejects_builtin_input() -> None:
    with pytest.raises(ValueError, match="Builtin goal cannot be parsed as AtomGoal"):
        AtomGoal.from_doxa("eq(X, Y)")


def test_constraint_atom_goal_rejects_wrong_arity() -> None:
    with pytest.raises(ValidationError):
        AtomGoal(
            kind=BaseKind.goal,
            goal_kind=GoalKind.atom,
            idx=0,
            pred_name="parent",
            pred_arity=2,
            negated=False,
            goal_args=[
                VarArg.from_doxa("X"),
            ],
        )


def test_constraint_builtin_goal_from_doxa() -> None:
    goal = BuiltinGoal.from_doxa("eq(X, Y)")

    assert goal.kind == BaseKind.goal
    assert goal.goal_kind == GoalKind.builtin
    assert goal.idx == 0
    assert goal.builtin_name == Builtin.eq
    assert len(goal.goal_args) == 2
    assert isinstance(goal.goal_args[0], VarArg)
    assert isinstance(goal.goal_args[1], VarArg)
    assert goal.goal_args[0].pos == 0
    assert goal.goal_args[1].pos == 1
    assert goal.to_doxa() == "eq(X, Y)"


def test_constraint_builtin_goal_rejects_negation() -> None:
    with pytest.raises(ValueError, match="Builtin goals cannot be negated"):
        BuiltinGoal.from_doxa("not eq(X, Y)")


def test_constraint_builtin_goal_rejects_unknown_builtin() -> None:
    with pytest.raises(ValueError, match="Unknown builtin goal"):
        BuiltinGoal.from_doxa("foo(X, Y)")


def test_constraint_builtin_goal_rejects_wrong_arity() -> None:
    with pytest.raises(ValidationError):
        BuiltinGoal(
            kind=BaseKind.goal,
            goal_kind=GoalKind.builtin,
            idx=0,
            builtin_name=Builtin.eq,
            goal_args=[VarArg.from_doxa("X")],
        )


def test_constraint_goal_dispatch_atom() -> None:
    goal = goal_from_doxa("parent(X, Y)")
    assert isinstance(goal, AtomGoal)


def test_constraint_goal_dispatch_builtin() -> None:
    goal = goal_from_doxa("eq(X, Y)")
    assert isinstance(goal, BuiltinGoal)


def test_constraint_goal_dispatch_negated_atom() -> None:
    goal = goal_from_doxa("not parent(X, Y)")
    assert isinstance(goal, AtomGoal)
    assert goal.negated is True


def test_constraint_goal_dispatch_rejects_negated_builtin() -> None:
    with pytest.raises(ValueError, match="Builtin goals cannot be negated"):
        goal_from_doxa("not eq(X, Y)")


def test_constraint_from_doxa_simple() -> None:
    c = Constraint.from_doxa("!:- parent(X, Y), not person(X)")

    assert c.kind == BaseKind.constraint
    assert len(c.goals) == 2
    assert isinstance(c.goals[0], AtomGoal)
    assert isinstance(c.goals[1], AtomGoal)
    assert c.goals[0].idx == 0
    assert c.goals[1].idx == 1
    assert c.goals[1].negated is True
    assert c.to_doxa().startswith("!:- parent(X, Y), not person(X)")


def test_constraint_from_doxa_with_builtin() -> None:
    c = Constraint.from_doxa("!:- risk_score(X, S), lt(S, 0)")

    assert len(c.goals) == 2
    assert isinstance(c.goals[0], AtomGoal)
    assert isinstance(c.goals[1], BuiltinGoal)
    assert c.goals[1].builtin_name == Builtin.lt
    assert c.to_doxa().startswith("!:- risk_score(X, S), lt(S, 0)")


def test_constraint_from_doxa_with_annotation() -> None:
    c = Constraint.from_doxa(
        '!:- ancestor(X, X) @{name:"no_self_ancestor", description:"integrity check"}'
    )

    assert c.name == "no_self_ancestor"
    assert c.description == "integrity check"
    d = c.to_doxa()
    assert d.startswith("!:- ancestor(X, X)")
    assert 'name:"no_self_ancestor"' in d
    assert 'description:"integrity check"' in d


def test_constraint_to_doxa_omits_default_annotation() -> None:
    c = Constraint.from_doxa("!:- parent(X, Y)")
    assert c.to_doxa().startswith("!:- parent(X, Y)")


def test_constraint_from_doxa_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        Constraint.from_doxa(None)  # type: ignore[arg-type]


def test_constraint_from_doxa_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Constraint.from_doxa("")


def test_constraint_from_doxa_rejects_missing_prefix() -> None:
    with pytest.raises(ValueError, match="must start with '!:-'"):
        Constraint.from_doxa("parent(X, Y)")


def test_constraint_from_doxa_rejects_empty_body() -> None:
    with pytest.raises(ValueError, match="body must not be empty"):
        Constraint.from_doxa("!:-")


def test_constraint_goal_indices_must_be_contiguous() -> None:
    g0 = AtomGoal.from_doxa("parent(X, Y)")
    g1 = AtomGoal.from_doxa("person(X)")

    with pytest.raises(ValidationError):
        Constraint(
            kind=BaseKind.constraint,
            goals=[
                g0.model_copy(update={"idx": 0}),
                g1.model_copy(update={"idx": 2}),
            ],
        )


def test_constraint_round_trip_simple() -> None:
    original = Constraint.from_doxa("!:- parent(X, Y), not person(X)")
    reparsed = Constraint.from_doxa(original.to_doxa())

    assert reparsed.model_dump(exclude={"created_at", "updated_at"}) == (
        original.model_dump(exclude={"created_at", "updated_at"})
    )


def test_constraint_round_trip_with_annotation() -> None:
    original = Constraint.from_doxa(
        '!:- ancestor(X, X) @{description:"integrity check", name:"no_self_ancestor"}'
    )
    reparsed = Constraint.from_doxa(original.to_doxa())

    assert reparsed.model_dump(exclude={"created_at", "updated_at"}) == (
        original.model_dump(exclude={"created_at", "updated_at"})
    )


def test_constraint_string_literal_round_trip() -> None:
    original = Constraint.from_doxa('!:- label(X, "hello world"), eq("a", "a")')
    reparsed = Constraint.from_doxa(original.to_doxa())

    assert reparsed.model_dump(exclude={"created_at", "updated_at"}) == (
        original.model_dump(exclude={"created_at", "updated_at"})
    )
