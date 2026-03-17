import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import (
    BeliefEntityArg,
    BeliefLiteralArg,
    BeliefRecord,
    belief_arg_from_ax,
)
from doxa.core.literal_type import LiteralType
from doxa.core.term_kinds import TermKind


def test_belief_entity_arg_from_ax() -> None:
    arg = BeliefEntityArg.from_ax("thomas")

    assert arg.kind == BaseKind.belief_arg
    assert arg.term_kind == TermKind.ent
    assert arg.ent_name == "thomas"
    assert arg.to_ax() == "thomas"


def test_belief_literal_arg_from_ax_string() -> None:
    arg = BeliefLiteralArg.from_ax('"hello world"')

    assert arg.kind == BaseKind.belief_arg
    assert arg.term_kind == TermKind.lit
    assert arg.lit_type == LiteralType.str
    assert arg.value == "hello world"
    assert arg.to_ax() == '"hello world"'


def test_belief_literal_arg_from_ax_int() -> None:
    arg = BeliefLiteralArg.from_ax("42")

    assert arg.lit_type == LiteralType.int
    assert arg.value == 42
    assert arg.to_ax() == "42"


def test_belief_literal_arg_from_ax_float() -> None:
    arg = BeliefLiteralArg.from_ax("3.14")

    assert arg.lit_type == LiteralType.float
    assert arg.value == 3.14
    assert arg.to_ax() == "3.14"


def test_belief_literal_arg_from_ax_bool_true() -> None:
    arg = BeliefLiteralArg.from_ax("true")

    assert arg.lit_type == LiteralType.bool
    assert arg.value is True
    assert arg.to_ax() == "true"


def test_belief_literal_arg_from_ax_bool_false() -> None:
    arg = BeliefLiteralArg.from_ax("false")

    assert arg.lit_type == LiteralType.bool
    assert arg.value is False
    assert arg.to_ax() == "false"


def test_belief_literal_arg_rejects_invalid_literal() -> None:
    with pytest.raises(ValueError, match="Invalid belief literal argument"):
        BeliefLiteralArg.from_ax("not_a_literal")


def test_belief_literal_arg_rejects_wrong_type_for_int() -> None:
    with pytest.raises(ValidationError):
        BeliefLiteralArg(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.lit,
            lit_type=LiteralType.int,
            value="42",
        )


def test_belief_literal_arg_rejects_wrong_type_for_float() -> None:
    with pytest.raises(ValidationError):
        BeliefLiteralArg(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.lit,
            lit_type=LiteralType.float,
            value=3,
        )


def test_belief_literal_arg_rejects_wrong_type_for_bool() -> None:
    with pytest.raises(ValidationError):
        BeliefLiteralArg(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.lit,
            lit_type=LiteralType.bool,
            value=1,
        )


def test_belief_arg_dispatch_entity() -> None:
    arg = belief_arg_from_ax("thomas")
    assert isinstance(arg, BeliefEntityArg)
    assert arg.ent_name == "thomas"


def test_belief_arg_dispatch_literal_string() -> None:
    arg = belief_arg_from_ax('"abc"')
    assert isinstance(arg, BeliefLiteralArg)
    assert arg.lit_type == LiteralType.str
    assert arg.value == "abc"


def test_belief_arg_dispatch_literal_int() -> None:
    arg = belief_arg_from_ax("10")
    assert isinstance(arg, BeliefLiteralArg)
    assert arg.lit_type == LiteralType.int
    assert arg.value == 10


def test_belief_arg_dispatch_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="Invalid belief argument"):
        belief_arg_from_ax("")


def test_belief_record_from_ax_simple() -> None:
    rec = BeliefRecord.from_ax("parent(thomas, manuel)")

    assert rec.kind == BaseKind.belief_record
    assert rec.pred_name == "parent"
    assert rec.pred_arity == 2
    assert len(rec.args) == 2
    assert isinstance(rec.args[0], BeliefEntityArg)
    assert isinstance(rec.args[1], BeliefEntityArg)
    assert rec.args[0].ent_name == "thomas"
    assert rec.args[1].ent_name == "manuel"
    assert rec.to_ax() == "parent(thomas, manuel)"


def test_belief_record_from_ax_with_mixed_args() -> None:
    rec = BeliefRecord.from_ax('label(thomas, "hello")')

    assert rec.pred_name == "label"
    assert rec.pred_arity == 2
    assert isinstance(rec.args[0], BeliefEntityArg)
    assert isinstance(rec.args[1], BeliefLiteralArg)
    assert rec.args[1].lit_type == LiteralType.str
    assert rec.args[1].value == "hello"
    assert rec.to_ax() == 'label(thomas, "hello")'


def test_belief_record_from_ax_with_annotation() -> None:
    rec = BeliefRecord.from_ax(
        'parent(thomas, manuel) @{name:"registry_fact", description:"from registry", b:0.9, d:0.01}'
    )

    assert rec.name == "registry_fact"
    assert rec.description == "from registry"
    assert rec.b == 0.9
    assert rec.d == 0.01
    assert rec.to_ax().strip("parent(thomas, manuel)")
    assert "@{" in rec.to_ax()
    assert rec.to_ax().endswith("}")
    assert 'name:"registry_fact"' in rec.to_ax()
    assert 'description:"from registry"' in rec.to_ax()
    assert "b:0.9" in rec.to_ax()
    assert "d:0.01" in rec.to_ax()


def test_belief_record_from_ax_sets_created_at() -> None:
    rec = BeliefRecord.from_ax("parent(thomas, manuel)")
    assert rec.created_at is not None


def test_belief_record_to_ax_omits_default_annotation() -> None:
    rec = BeliefRecord.from_ax("parent(thomas, manuel)")
    assert rec.to_ax() == "parent(thomas, manuel)"


def test_belief_record_from_ax_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        BeliefRecord.from_ax(None)  # type: ignore[arg-type]


def test_belief_record_from_ax_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        BeliefRecord.from_ax("")


@pytest.mark.parametrize(
    "inp",
    [
        "parent",
        "parent(",
        "parent)",
        "parent thomas, manuel",
        "Parent(thomas, manuel)",
        "9parent(thomas, manuel)",
    ],
)
def test_belief_record_from_ax_rejects_invalid_syntax(inp: str) -> None:
    with pytest.raises(ValueError):
        BeliefRecord.from_ax(inp)


def test_belief_record_validate_arity_rejects_wrong_arg_count() -> None:
    with pytest.raises(ValidationError):
        BeliefRecord(
            kind=BaseKind.belief_record,
            created_at=BeliefRecord.from_ax("parent(thomas, manuel)").created_at,
            pred_name="parent",
            pred_arity=2,
            args=[BeliefEntityArg.from_ax("thomas")],
        )


def test_belief_record_round_trip_simple() -> None:
    original = BeliefRecord.from_ax("parent(thomas, manuel)")
    reparsed = BeliefRecord.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.pred_name == original.pred_name
    assert reparsed.pred_arity == original.pred_arity
    assert reparsed.args == original.args


def test_belief_record_round_trip_with_annotation() -> None:
    original = BeliefRecord.from_ax(
        'parent(thomas, manuel) @{name:"registry_fact", description:"from registry", b:0.9, d:0.01}'
    )
    reparsed = BeliefRecord.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.pred_name == original.pred_name
    assert reparsed.pred_arity == original.pred_arity
    assert reparsed.args == original.args
    assert reparsed.name == original.name
    assert reparsed.description == original.description
    assert reparsed.b == original.b
    assert reparsed.d == original.d


def test_belief_record_string_literal_round_trip() -> None:
    original = BeliefRecord.from_ax('label(thomas, "hello world")')
    reparsed = BeliefRecord.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.args == original.args


def test_belief_record_bool_literal_round_trip() -> None:
    original = BeliefRecord.from_ax("active(thomas, true)")
    reparsed = BeliefRecord.from_ax(original.to_ax())

    assert reparsed.to_ax() == original.to_ax()
    assert reparsed.args == original.args
