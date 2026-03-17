import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import Builtin
from doxa.core.goal_kinds import GoalKind
from doxa.core.literal_type import LiteralType
from doxa.core.rule import (
    Rule,
    RuleAtomGoal,
    RuleBuiltinGoal,
    RuleGoalEntityArg,
    RuleGoalLiteralArg,
    RuleGoalVarArg,
    RuleHeadEntityArg,
    RuleHeadLiteralArg,
    RuleHeadVarArg,
    rule_goal_arg_from_ax,
    rule_goal_from_ax,
    rule_head_arg_from_ax,
)
from doxa.core.term_kinds import TermKind
from doxa.core.var import Var


def test_rule_head_var_arg_from_ax() -> None:
    arg = RuleHeadVarArg.from_ax("X")

    assert arg.kind == BaseKind.rule_head_arg
    assert arg.term_kind == TermKind.var
    assert arg.pos == 0
    assert arg.var == Var.from_ax("X")
    assert arg.to_ax() == "X"


def test_rule_head_entity_arg_from_ax() -> None:
    arg = RuleHeadEntityArg.from_ax("thomas")

    assert arg.kind == BaseKind.rule_head_arg
    assert arg.term_kind == TermKind.ent
    assert arg.pos == 0
    assert arg.ent_name == "thomas"
    assert arg.to_ax() == "thomas"


def test_rule_head_literal_arg_from_ax_string() -> None:
    arg = RuleHeadLiteralArg.from_ax('"hello world"')

    assert arg.kind == BaseKind.rule_head_arg
    assert arg.term_kind == TermKind.lit
    assert arg.pos == 0
    assert arg.lit_type == LiteralType.str
    assert arg.value == "hello world"
    assert arg.to_ax() == '"hello world"'


def test_rule_head_literal_arg_from_ax_int() -> None:
    arg = RuleHeadLiteralArg.from_ax("42")

    assert arg.lit_type == LiteralType.int
    assert arg.value == 42
    assert arg.to_ax() == "42"


def test_rule_head_literal_arg_from_ax_float() -> None:
    arg = RuleHeadLiteralArg.from_ax("3.14")

    assert arg.lit_type == LiteralType.float
    assert arg.value == 3.14
    assert arg.to_ax() == "3.14"


def test_rule_head_literal_arg_rejects_invalid_literal() -> None:
    with pytest.raises(ValueError, match="Invalid rule head literal argument"):
        RuleHeadLiteralArg.from_ax("not_a_literal")


def test_rule_head_literal_arg_rejects_wrong_type_for_int() -> None:
    with pytest.raises(ValidationError):
        RuleHeadLiteralArg(
            kind=BaseKind.rule_head_arg,
            pos=0,
            term_kind=TermKind.lit,
            lit_type=LiteralType.int,
            value="42",
        )


def test_rule_head_literal_arg_rejects_wrong_type_for_float() -> None:
    with pytest.raises(ValidationError):
        RuleHeadLiteralArg(
            kind=BaseKind.rule_head_arg,
            pos=0,
            term_kind=TermKind.lit,
            lit_type=LiteralType.float,
            value=3,
        )


def test_rule_head_arg_dispatch_var() -> None:
    arg = rule_head_arg_from_ax("X")
    assert isinstance(arg, RuleHeadVarArg)
    assert arg.var == Var.from_ax("X")


def test_rule_head_arg_dispatch_entity() -> None:
    arg = rule_head_arg_from_ax("thomas")
    assert isinstance(arg, RuleHeadEntityArg)
    assert arg.ent_name == "thomas"


def test_rule_head_arg_dispatch_literal_string() -> None:
    arg = rule_head_arg_from_ax('"abc"')
    assert isinstance(arg, RuleHeadLiteralArg)
    assert arg.lit_type == LiteralType.str
    assert arg.value == "abc"


def test_rule_head_arg_dispatch_literal_int() -> None:
    arg = rule_head_arg_from_ax("10")
    assert isinstance(arg, RuleHeadLiteralArg)
    assert arg.lit_type == LiteralType.int
    assert arg.value == 10


def test_rule_head_arg_dispatch_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="Invalid rule head argument"):
        rule_head_arg_from_ax("")


def test_rule_goal_var_arg_from_ax() -> None:
    arg = RuleGoalVarArg.from_ax("X")

    assert arg.kind == BaseKind.rule_goal_arg
    assert arg.term_kind == TermKind.var
    assert arg.pos == 0
    assert arg.var == Var.from_ax("X")
    assert arg.to_ax() == "X"


def test_rule_goal_entity_arg_from_ax() -> None:
    arg = RuleGoalEntityArg.from_ax("thomas")

    assert arg.kind == BaseKind.rule_goal_arg
    assert arg.term_kind == TermKind.ent
    assert arg.pos == 0
    assert arg.ent_name == "thomas"
    assert arg.to_ax() == "thomas"


def test_rule_goal_literal_arg_from_ax_string() -> None:
    arg = RuleGoalLiteralArg.from_ax('"hello world"')

    assert arg.kind == BaseKind.rule_goal_arg
    assert arg.term_kind == TermKind.lit
    assert arg.pos == 0
    assert arg.lit_type == LiteralType.str
    assert arg.value == "hello world"
    assert arg.to_ax() == '"hello world"'


def test_rule_goal_literal_arg_from_ax_int() -> None:
    arg = RuleGoalLiteralArg.from_ax("42")

    assert arg.lit_type == LiteralType.int
    assert arg.value == 42
    assert arg.to_ax() == "42"


def test_rule_goal_literal_arg_from_ax_float() -> None:
    arg = RuleGoalLiteralArg.from_ax("3.14")

    assert arg.lit_type == LiteralType.float
    assert arg.value == 3.14
    assert arg.to_ax() == "3.14"


def test_rule_goal_literal_arg_rejects_invalid_literal() -> None:
    with pytest.raises(ValueError, match="Invalid rule goal literal argument"):
        RuleGoalLiteralArg.from_ax("not_a_literal")


def test_rule_goal_literal_arg_rejects_wrong_type_for_int() -> None:
    with pytest.raises(ValidationError):
        RuleGoalLiteralArg(
            kind=BaseKind.rule_goal_arg,
            pos=0,
            term_kind=TermKind.lit,
            lit_type=LiteralType.int,
            value="42",
        )


def test_rule_goal_literal_arg_rejects_wrong_type_for_float() -> None:
    with pytest.raises(ValidationError):
        RuleGoalLiteralArg(
            kind=BaseKind.rule_goal_arg,
            pos=0,
            term_kind=TermKind.lit,
            lit_type=LiteralType.float,
            value=3,
        )


def test_rule_goal_arg_dispatch_var() -> None:
    arg = rule_goal_arg_from_ax("X")
    assert isinstance(arg, RuleGoalVarArg)
    assert arg.var == Var.from_ax("X")


def test_rule_goal_arg_dispatch_entity() -> None:
    arg = rule_goal_arg_from_ax("thomas")
    assert isinstance(arg, RuleGoalEntityArg)
    assert arg.ent_name == "thomas"


def test_rule_goal_arg_dispatch_literal_string() -> None:
    arg = rule_goal_arg_from_ax('"abc"')
    assert isinstance(arg, RuleGoalLiteralArg)
    assert arg.lit_type == LiteralType.str
    assert arg.value == "abc"


def test_rule_goal_arg_dispatch_literal_int() -> None:
    arg = rule_goal_arg_from_ax("10")
    assert isinstance(arg, RuleGoalLiteralArg)
    assert arg.lit_type == LiteralType.int
    assert arg.value == 10


def test_rule_goal_arg_dispatch_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="Invalid rule goal argument"):
        rule_goal_arg_from_ax("")


def test_rule_atom_goal_from_ax() -> None:
    goal = RuleAtomGoal.from_ax("parent(X, thomas)")

    assert goal.kind == BaseKind.rule_goal
    assert goal.goal_kind == GoalKind.atom
    assert goal.idx == 0
    assert goal.pred_name == "parent"
    assert goal.pred_arity == 2
    assert goal.negated is False
    assert len(goal.goal_args) == 2
    assert isinstance(goal.goal_args[0], RuleGoalVarArg)
    assert isinstance(goal.goal_args[1], RuleGoalEntityArg)
    assert goal.goal_args[0].pos == 0
    assert goal.goal_args[1].pos == 1
    assert goal.to_ax() == "parent(X, thomas)"


def test_rule_atom_goal_from_ax_negated() -> None:
    goal = RuleAtomGoal.from_ax("not parent(X, thomas)")

    assert goal.negated is True
    assert goal.to_ax() == "not parent(X, thomas)"


def test_rule_atom_goal_rejects_builtin_input() -> None:
    with pytest.raises(
        ValueError, match="Builtin goal cannot be parsed as RuleAtomGoal"
    ):
        RuleAtomGoal.from_ax("eq(X, Y)")


def test_rule_atom_goal_rejects_wrong_arity() -> None:
    with pytest.raises(ValidationError):
        RuleAtomGoal(
            kind=BaseKind.rule_goal,
            goal_kind=GoalKind.atom,
            idx=0,
            pred_name="parent",
            pred_arity=2,
            negated=False,
            goal_args=[RuleGoalVarArg.from_ax("X")],
        )


def test_rule_builtin_goal_from_ax() -> None:
    goal = RuleBuiltinGoal.from_ax("eq(X, Y)")

    assert goal.kind == BaseKind.rule_goal
    assert goal.goal_kind == GoalKind.builtin
    assert goal.idx == 0
    assert goal.builtin_name == Builtin.eq
    assert len(goal.goal_args) == 2
    assert isinstance(goal.goal_args[0], RuleGoalVarArg)
    assert isinstance(goal.goal_args[1], RuleGoalVarArg)
    assert goal.goal_args[0].pos == 0
    assert goal.goal_args[1].pos == 1
    assert goal.to_ax() == "eq(X, Y)"


def test_rule_builtin_goal_rejects_negation() -> None:
    with pytest.raises(ValueError, match="Builtin goals cannot be negated"):
        RuleBuiltinGoal.from_ax("not eq(X, Y)")


def test_rule_builtin_goal_rejects_unknown_builtin() -> None:
    with pytest.raises(ValueError, match="Unknown builtin goal"):
        RuleBuiltinGoal.from_ax("foo(X, Y)")


def test_rule_builtin_goal_rejects_wrong_arity() -> None:
    with pytest.raises(ValidationError):
        RuleBuiltinGoal(
            kind=BaseKind.rule_goal,
            goal_kind=GoalKind.builtin,
            idx=0,
            builtin_name=Builtin.eq,
            goal_args=[RuleGoalVarArg.from_ax("X")],
        )


def test_rule_goal_dispatch_atom() -> None:
    goal = rule_goal_from_ax("parent(X, Y)")
    assert isinstance(goal, RuleAtomGoal)


def test_rule_goal_dispatch_builtin() -> None:
    goal = rule_goal_from_ax("eq(X, Y)")
    assert isinstance(goal, RuleBuiltinGoal)


def test_rule_goal_dispatch_negated_atom() -> None:
    goal = rule_goal_from_ax("not parent(X, Y)")
    assert isinstance(goal, RuleAtomGoal)
    assert goal.negated is True


def test_rule_goal_dispatch_rejects_negated_builtin() -> None:
    with pytest.raises(ValueError, match="Builtin goals cannot be negated"):
        rule_goal_from_ax("not eq(X, Y)")


def test_rule_from_ax_simple() -> None:
    rule = Rule.from_ax("ancestor(X, Y) :- parent(X, Y)")

    assert rule.kind == BaseKind.rule
    assert rule.head_pred_name == "ancestor"
    assert rule.head_pred_arity == 2
    assert len(rule.head_args) == 2
    assert isinstance(rule.head_args[0], RuleHeadVarArg)
    assert isinstance(rule.head_args[1], RuleHeadVarArg)
    assert len(rule.goals) == 1
    assert isinstance(rule.goals[0], RuleAtomGoal)
    assert rule.goals[0].idx == 0
    assert rule.to_ax() == "ancestor(X, Y) :- parent(X, Y)"


def test_rule_from_ax_with_builtin_goal() -> None:
    rule = Rule.from_ax("ok(X) :- risk_score(X, S), geq(S, 0)")

    assert rule.head_pred_name == "ok"
    assert rule.head_pred_arity == 1
    assert len(rule.goals) == 2
    assert isinstance(rule.goals[0], RuleAtomGoal)
    assert isinstance(rule.goals[1], RuleBuiltinGoal)
    assert rule.goals[1].builtin_name == Builtin.geq
    assert rule.to_ax() == "ok(X) :- risk_score(X, S), geq(S, 0)"


def test_rule_from_ax_with_head_literal() -> None:
    rule = Rule.from_ax('answer("yes") :- ready(true)')

    assert rule.head_pred_name == "answer"
    assert rule.head_pred_arity == 1
    assert isinstance(rule.head_args[0], RuleHeadLiteralArg)
    assert rule.head_args[0].lit_type == LiteralType.str
    assert rule.head_args[0].value == "yes"
    assert rule.to_ax() == 'answer("yes") :- ready(true)'


def test_rule_from_ax_with_annotation() -> None:
    rule = Rule.from_ax(
        'ancestor(X, Y) :- parent(X, Y) @{name:"transitive_seed", description:"seed rule", b:0.9, d:0.01}'
    )

    assert rule.name == "transitive_seed"
    assert rule.description == "seed rule"
    assert rule.b == 0.9
    assert rule.d == 0.01
    assert rule.to_ax() == (
        'ancestor(X, Y) :- parent(X, Y) @{description:"seed rule", b:0.9, d:0.01, name:"transitive_seed"}'
    )


def test_rule_to_ax_omits_default_annotation() -> None:
    rule = Rule.from_ax("ancestor(X, Y) :- parent(X, Y)")
    assert rule.to_ax() == "ancestor(X, Y) :- parent(X, Y)"


def test_rule_from_ax_sets_created_at() -> None:
    rule = Rule.from_ax("ancestor(X, Y) :- parent(X, Y)")
    assert rule.created_at is not None


def test_rule_from_ax_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        Rule.from_ax(None)  # type: ignore[arg-type]


def test_rule_from_ax_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Rule.from_ax("")


@pytest.mark.parametrize(
    "inp",
    [
        "ancestor(X, Y)",
        "ancestor(X, Y) parent(X, Y)",
        ":- parent(X, Y)",
        "ancestor(X, Y) :-",
        "Ancestor(X, Y) :- parent(X, Y)",
        "9ancestor(X, Y) :- parent(X, Y)",
    ],
)
def test_rule_from_ax_rejects_invalid_syntax(inp: str) -> None:
    with pytest.raises(ValueError):
        Rule.from_ax(inp)


def test_rule_validate_head_arity_rejects_wrong_arg_count() -> None:
    with pytest.raises(ValidationError):
        Rule(
            kind=BaseKind.rule,
            created_at=Rule.from_ax("ancestor(X, Y) :- parent(X, Y)").created_at,
            head_pred_name="ancestor",
            head_pred_arity=2,
            head_args=[RuleHeadVarArg.from_ax("X")],
            goals=[RuleAtomGoal.from_ax("parent(X, Y)")],
        )


def test_rule_validate_goal_indices_rejects_non_contiguous_indices() -> None:
    g0 = RuleAtomGoal.from_ax("parent(X, Y)")
    g1 = RuleAtomGoal.from_ax("person(X)")

    with pytest.raises(ValidationError):
        Rule(
            kind=BaseKind.rule,
            created_at=Rule.from_ax("ancestor(X, Y) :- parent(X, Y)").created_at,
            head_pred_name="ancestor",
            head_pred_arity=2,
            head_args=[
                RuleHeadVarArg.from_ax("X").model_copy(update={"pos": 0}),
                RuleHeadVarArg.from_ax("Y").model_copy(update={"pos": 1}),
            ],
            goals=[
                g0.model_copy(update={"idx": 0}),
                g1.model_copy(update={"idx": 2}),
            ],
        )


def test_rule_round_trip_simple() -> None:
    original = Rule.from_ax("ancestor(X, Y) :- parent(X, Y)")
    reparsed = Rule.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.head_pred_name == original.head_pred_name
    assert reparsed.head_pred_arity == original.head_pred_arity
    assert reparsed.head_args == original.head_args
    assert reparsed.goals == original.goals


def test_rule_round_trip_with_annotation() -> None:
    original = Rule.from_ax(
        'ancestor(X, Y) :- parent(X, Y) @{name:"transitive_seed", description:"seed rule", b:0.9, d:0.01}'
    )
    reparsed = Rule.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.head_pred_name == original.head_pred_name
    assert reparsed.head_pred_arity == original.head_pred_arity
    assert reparsed.head_args == original.head_args
    assert reparsed.goals == original.goals
    assert reparsed.name == original.name
    assert reparsed.description == original.description
    assert reparsed.b == original.b
    assert reparsed.d == original.d


def test_rule_string_literal_round_trip() -> None:
    original = Rule.from_ax('label_out(X, "hello") :- label_in(X, "hello")')
    reparsed = Rule.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.head_args == original.head_args
    assert reparsed.goals == original.goals


def test_rule_bool_literal_round_trip() -> None:
    original = Rule.from_ax("active_out(X, true) :- active_in(X, true)")
    reparsed = Rule.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.head_args == original.head_args
    assert reparsed.goals == original.goals
