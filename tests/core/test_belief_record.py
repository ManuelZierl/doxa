import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import (
    BeliefEntityArg,
    BeliefLiteralArg,
    BeliefRecord,
    belief_arg_from_doxa,
)
from doxa.core.literal_type import LiteralType
from doxa.core.term_kinds import TermKind


def test_belief_entity_arg_from_doxa() -> None:
    arg = BeliefEntityArg.from_doxa("zeus")

    assert arg.kind == BaseKind.belief_arg
    assert arg.term_kind == TermKind.ent
    assert arg.ent_name == "zeus"
    assert arg.to_doxa() == "zeus"


def test_belief_literal_arg_from_doxa_string() -> None:
    arg = BeliefLiteralArg.from_doxa('"hello world"')

    assert arg.kind == BaseKind.belief_arg
    assert arg.term_kind == TermKind.lit
    assert arg.lit_type == LiteralType.str
    assert arg.value == "hello world"
    assert arg.to_doxa() == '"hello world"'


def test_belief_literal_arg_from_doxa_int() -> None:
    arg = BeliefLiteralArg.from_doxa("42")

    assert arg.lit_type == LiteralType.int
    assert arg.value == 42
    assert arg.to_doxa() == "42"


def test_belief_literal_arg_from_doxa_float() -> None:
    arg = BeliefLiteralArg.from_doxa("3.14")

    assert arg.lit_type == LiteralType.float
    assert arg.value == 3.14
    assert arg.to_doxa() == "3.14"


def test_belief_literal_arg_rejects_invalid_literal() -> None:
    with pytest.raises(ValueError, match="Invalid belief literal argument"):
        BeliefLiteralArg.from_doxa("not_a_literal")


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


def test_belief_arg_dispatch_entity() -> None:
    arg = belief_arg_from_doxa("zeus")
    assert isinstance(arg, BeliefEntityArg)
    assert arg.ent_name == "zeus"


def test_belief_arg_dispatch_literal_string() -> None:
    arg = belief_arg_from_doxa('"abc"')
    assert isinstance(arg, BeliefLiteralArg)
    assert arg.lit_type == LiteralType.str
    assert arg.value == "abc"


def test_belief_arg_dispatch_literal_int() -> None:
    arg = belief_arg_from_doxa("10")
    assert isinstance(arg, BeliefLiteralArg)
    assert arg.lit_type == LiteralType.int
    assert arg.value == 10


def test_belief_arg_dispatch_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="Invalid belief argument"):
        belief_arg_from_doxa("")


def test_belief_record_from_doxa_simple() -> None:
    rec = BeliefRecord.from_doxa("parent(zeus, heracles)")

    assert rec.kind == BaseKind.belief_record
    assert rec.pred_name == "parent"
    assert rec.pred_arity == 2
    assert len(rec.args) == 2
    assert isinstance(rec.args[0], BeliefEntityArg)
    assert isinstance(rec.args[1], BeliefEntityArg)
    assert rec.args[0].ent_name == "zeus"
    assert rec.args[1].ent_name == "heracles"
    assert rec.to_doxa().startswith("parent(zeus, heracles) @{b:1.0, d:0.0, et:")
    assert rec.to_doxa().endswith('"}')


def test_belief_record_from_doxa_with_mixed_args() -> None:
    rec = BeliefRecord.from_doxa('label(zeus, "hello")')

    assert rec.pred_name == "label"
    assert rec.pred_arity == 2
    assert isinstance(rec.args[0], BeliefEntityArg)
    assert isinstance(rec.args[1], BeliefLiteralArg)
    assert rec.args[1].lit_type == LiteralType.str
    assert rec.args[1].value == "hello"
    assert rec.to_doxa().startswith('label(zeus, "hello") @{b:1.0, d:0.0, et:"')
    assert rec.to_doxa().endswith('"}')


def test_belief_record_from_doxa_with_annotation() -> None:
    rec = BeliefRecord.from_doxa(
        'parent(zeus, heracles) @{name:"registry_fact", description:"from registry", b:0.9, d:0.01}'
    )

    assert rec.name == "registry_fact"
    assert rec.description == "from registry"
    assert rec.b == 0.9
    assert rec.d == 0.01
    assert rec.to_doxa().strip("parent(zeus, heracles)")
    assert "@{" in rec.to_doxa()
    assert rec.to_doxa().endswith("}")
    assert 'name:"registry_fact"' in rec.to_doxa()
    assert 'description:"from registry"' in rec.to_doxa()
    assert "b:0.9" in rec.to_doxa()
    assert "d:0.01" in rec.to_doxa()


def test_belief_record_from_doxa_sets_created_at() -> None:
    rec = BeliefRecord.from_doxa("parent(zeus, heracles)")
    assert rec.created_at is not None


def test_belief_record_to_doxa_omits_default_annotation() -> None:
    rec = BeliefRecord.from_doxa("parent(zeus, heracles)")
    assert rec.to_doxa().startswith('parent(zeus, heracles) @{b:1.0, d:0.0, et:"')
    assert rec.to_doxa().endswith('"}')


def test_belief_record_from_doxa_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        BeliefRecord.from_doxa(None)  # type: ignore[arg-type]


def test_belief_record_from_doxa_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        BeliefRecord.from_doxa("")


@pytest.mark.parametrize(
    "inp",
    [
        "parent",
        "parent(",
        "parent)",
        "parent zeus, heracles",
        "Parent(zeus, heracles)",
        "9parent(zeus, heracles)",
    ],
)
def test_belief_record_from_doxa_rejects_invalid_syntax(inp: str) -> None:
    with pytest.raises(ValueError):
        BeliefRecord.from_doxa(inp)


def test_belief_record_validate_arity_rejects_wrong_arg_count() -> None:
    with pytest.raises(ValidationError):
        BeliefRecord(
            kind=BaseKind.belief_record,
            created_at=BeliefRecord.from_doxa("parent(zeus, heracles)").created_at,
            pred_name="parent",
            pred_arity=2,
            args=[BeliefEntityArg.from_doxa("zeus")],
        )


def test_belief_record_round_trip_simple() -> None:
    original = BeliefRecord.from_doxa("parent(zeus, heracles)")
    reparsed = BeliefRecord.from_doxa(original.to_doxa())

    assert reparsed.to_doxa() == original.to_doxa()
    assert reparsed.pred_name == original.pred_name
    assert reparsed.pred_arity == original.pred_arity
    assert reparsed.args == original.args


def test_belief_record_round_trip_with_annotation() -> None:
    original = BeliefRecord.from_doxa(
        'parent(zeus, heracles) @{name:"registry_fact", description:"from registry", b:0.9, d:0.01}'
    )
    reparsed = BeliefRecord.from_doxa(original.to_doxa())

    assert reparsed.to_doxa() == original.to_doxa()
    assert reparsed.pred_name == original.pred_name
    assert reparsed.pred_arity == original.pred_arity
    assert reparsed.args == original.args
    assert reparsed.name == original.name
    assert reparsed.description == original.description
    assert reparsed.b == original.b
    assert reparsed.d == original.d


def test_belief_record_string_literal_round_trip() -> None:
    original = BeliefRecord.from_doxa('label(zeus, "hello world")')
    reparsed = BeliefRecord.from_doxa(original.to_doxa())

    assert reparsed.to_doxa() == original.to_doxa()
    assert reparsed.args == original.args


def test_belief_record_bool_literal_round_trip() -> None:
    original = BeliefRecord.from_doxa("active(zeus, true)")
    reparsed = BeliefRecord.from_doxa(original.to_doxa())

    assert reparsed.to_doxa() == original.to_doxa()
    assert reparsed.args == original.args
