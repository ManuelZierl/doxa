import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.var import Var


@pytest.mark.parametrize(
    "name",
    ["X", "_", "_X", "X1", "X_1", "X__Y__9", "_lower"],
)
def test_var_name_valid(name: str):
    v = Var(kind=BaseKind.var, name=name)
    assert v.name == name
    assert v.kind == BaseKind.var
    assert v.to_doxa() == name


@pytest.mark.parametrize(
    "name",
    [
        "",  # empty
        " ",  # whitespace
        "x",  # unquoted lowercase start not allowed
        "foo",  # unquoted lowercase start not allowed
        "1X",  # digit first not allowed
        "X-",  # invalid char
        "X.Y",  # invalid char
        "X Y",  # space
        "X\tY",  # whitespace
        "'1x'",  # quoted: digit first not allowed
        "'foo-bar'",  # invalid char inside quotes
        '"Foo"',  # double quotes not allowed
        "'foo",  # missing closing quote
        "foo'",  # missing opening quote
        "''",  # empty inner
    ],
)
def test_var_name_invalid(name: str):
    with pytest.raises(ValidationError):
        Var(kind=BaseKind.var, name=name)


def test_var_name_rejects_non_string():
    with pytest.raises(ValidationError):
        Var(kind=BaseKind.var, name=123)  # type: ignore[arg-type]


def test_var_to_doxa_returns_name():
    v = Var(kind=BaseKind.var, name="X")
    assert v.to_doxa() == "X"


def test_var_from_doxa_sets_kind_and_name():
    v = Var.from_doxa("X")
    assert v.kind == BaseKind.var
    assert v.name == "X"


def test_var_roundtrip_dict():
    v1 = Var(kind=BaseKind.var, name="X_1")
    payload = v1.model_dump()
    v2 = Var.model_validate(payload)
    assert v2 == v1


def test_var_roundtrip_json():
    v1 = Var(kind=BaseKind.var, name="Foo_1")
    payload_json = v1.model_dump_json()
    v2 = Var.model_validate_json(payload_json)
    assert v2 == v1


def test_var_kind_required():
    with pytest.raises(ValidationError):
        Var(name="X")  # type: ignore[call-arg]


def test_var_kind_must_be_var():
    with pytest.raises(ValidationError):
        Var(kind=BaseKind.rule, name="X")  # wrong kind


def test_var_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Var.model_validate({"kind": "var", "name": "X", "extra": 1})
