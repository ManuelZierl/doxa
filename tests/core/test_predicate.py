import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.predicate import Predicate


def test_predicate_from_ax_parses_without_annotation() -> None:
    pred = Predicate.from_ax("pred parent/2")

    assert pred.kind == BaseKind.predicate
    assert pred.name == "parent"
    assert pred.arity == 2
    assert pred.description is None


def test_predicate_from_ax_parses_with_description_annotation() -> None:
    pred = Predicate.from_ax(
        'pred source_document/1 @{description:"source_document(S): provenance source entity"}'
    )

    assert pred.kind == BaseKind.predicate
    assert pred.name == "source_document"
    assert pred.arity == 1
    assert pred.description == "source_document(S): provenance source entity"


def test_predicate_from_ax_parses_description_with_escaped_quotes() -> None:
    pred = Predicate.from_ax('pred quoted/1 @{description:"say \\"hello\\""}')

    assert pred.name == "quoted"
    assert pred.arity == 1
    assert pred.description == 'say "hello"'


def test_predicate_from_ax_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Predicate.from_ax("")


def test_predicate_from_ax_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        Predicate.from_ax(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "inp",
    [
        "parent/2",
        "pred",
        "pred parent",
        "pred parent/",
        "pred /2",
        "pred Parent/2",
        "pred _parent/2",
        "pred 9parent/2",
        "pred parent/-1",
        "pred parent/2.",
    ],
)
def test_predicate_from_ax_rejects_invalid_declarations(inp: str) -> None:
    with pytest.raises(ValueError, match="Invalid predicate declaration"):
        Predicate.from_ax(inp)


def test_predicate_from_ax_rejects_unsupported_annotation_keys() -> None:
    with pytest.raises(ValueError, match="only allow"):
        Predicate.from_ax("pred parent/2 @{b:0.9}")


def test_predicate_from_ax_rejects_mixed_supported_and_unsupported_annotation_keys() -> (
    None
):
    with pytest.raises(ValueError, match="unsupported keys"):
        Predicate.from_ax(
            'pred parent/2 @{description:"Parent relation", src:registry_2020}'
        )


def test_predicate_to_ax_without_description() -> None:
    pred = Predicate(
        kind=BaseKind.predicate,
        name="parent",
        arity=2,
    )

    assert pred.to_ax() == "pred parent/2"


def test_predicate_to_ax_with_description() -> None:
    pred = Predicate(
        kind=BaseKind.predicate,
        name="source_document",
        arity=1,
        description="source_document(S): provenance source entity",
    )

    assert (
        pred.to_ax()
        == 'pred source_document/1 @{description:"source_document(S): provenance source entity"}'
    )


def test_predicate_to_ax_escapes_quotes_and_backslashes() -> None:
    pred = Predicate(
        kind=BaseKind.predicate,
        name="quoted",
        arity=1,
        description='path C:\\tmp says "hi"',
    )

    assert pred.to_ax() == 'pred quoted/1 @{description:"path C:\\\\tmp says \\"hi\\""}'


def test_predicate_round_trip_without_description() -> None:
    original = Predicate(
        kind=BaseKind.predicate,
        name="parent",
        arity=2,
    )

    reparsed = Predicate.from_ax(original.to_ax())

    assert reparsed == original


def test_predicate_round_trip_with_description() -> None:
    original = Predicate(
        kind=BaseKind.predicate,
        name="source_document",
        arity=1,
        description='source_document(S): provenance source entity for "facts"',
    )

    reparsed = Predicate.from_ax(original.to_ax())

    assert reparsed == original


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Parent",
        "_parent",
        "9parent",
        "parent-name",
        "parent name",
    ],
)
def test_predicate_direct_model_rejects_invalid_name(name: str) -> None:
    with pytest.raises(ValidationError):
        Predicate(
            kind=BaseKind.predicate,
            name=name,
            arity=2,
        )


def test_predicate_direct_model_rejects_negative_arity() -> None:
    with pytest.raises(ValidationError):
        Predicate(
            kind=BaseKind.predicate,
            name="parent",
            arity=-1,
        )
