import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.entity import Entity


@pytest.mark.parametrize(
    "name",
    [
        "x",
        "foo",
        "foo1",
        "foo_bar",
        "'foo'",
        "'foo bar'",
        "'_Bar 9'",
        "'9abc'",
        "''",
        "'   '",
    ],
)
def test_entity_accepts_valid_names(name: str) -> None:
    ent = Entity(kind=BaseKind.entity, name=name)
    assert ent.name == name
    assert ent.kind == BaseKind.entity


@pytest.mark.parametrize(
    "name",
    [
        "",
        "X",
        "_x",
        "9abc",
        "foo-bar",
        "foo bar",
        "'foo",
        "foo'",
        '"foo"',
        "'foo-bar'",
        "'foo\nbar'",
    ],
)
def test_entity_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Entity(kind=BaseKind.entity, name=name)

    msg = str(exc_info.value)
    assert "Entity.name" in msg


def test_entity_to_ax_returns_name() -> None:
    ent = Entity(kind=BaseKind.entity, name="foo_bar")
    assert ent.to_ax() == "foo_bar"


def test_entity_from_ax_builds_entity() -> None:
    ent = Entity.from_ax("foo_bar")
    assert ent.kind == BaseKind.entity
    assert ent.name == "foo_bar"


def test_entity_requires_kind() -> None:
    with pytest.raises(ValidationError):
        Entity(name="foo_bar")  # type: ignore[call-arg]
