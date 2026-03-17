import pytest
from pydantic import ValidationError

from doxa.core.base_kinds import BaseKind
from doxa.core.literal import Literal
from doxa.core.literal_type import LiteralType


@pytest.mark.parametrize(
    "inp, datatype, value",
    [
        ('"hello"', LiteralType.str, "hello"),
        ('"foo bar"', LiteralType.str, "foo bar"),
        ('""', LiteralType.str, ""),
        (
            '"a\\\\b"',
            LiteralType.str,
            r"a\\b",
        ),  # NOTE: your from_doxa does NOT unescape; it keeps backslashes
        ('"a\\"b"', LiteralType.str, r"a\"b"),  # NOTE: keeps backslash+quote sequence
        ("0", LiteralType.int, 0),
        ("-12", LiteralType.int, -12),
        ("+12", LiteralType.int, 12),
        ("3.14", LiteralType.float, 3.14),
        ("-0.5", LiteralType.float, -0.5),
        ("1e3", LiteralType.float, 1000.0),
        ("1E-3", LiteralType.float, 0.001),
        (".5", LiteralType.float, 0.5),
        ("2.", LiteralType.float, 2.0),
    ],
)
def test_literal_from_doxa_valid(inp, datatype, value):
    lit = Literal.from_doxa(inp)
    assert lit.kind == BaseKind.literal
    assert lit.datatype == datatype
    assert lit.value == value


@pytest.mark.parametrize(
    "inp",
    [
        "",  # empty
        " ",  # whitespace-only (your from_doxa doesn't strip)
        "True",  # case-sensitive bools
        "FALSE",
        '"unterminated',  # missing closing quote
        'unterminated"',  # missing opening quote
        '"line\nbreak"',  # newline not allowed by regex
        '"line\rbreak"',  # CR not allowed
        "abc",  # not a literal (likely entity/var in language)
        "1_000",  # underscore not allowed in number regex: todo: should we allow?
        "--1",  # invalid number
        "1.2.3",  # invalid float
        "nan",  # not accepted by your parser (float regex won't match)
        "inf",  # todo: should we allow? -> then also -inf
    ],
)
def test_literal_from_doxa_invalid(inp):
    with pytest.raises(ValueError):
        Literal.from_doxa(inp)


def test_literal_to_doxa_string_wraps_double_quotes():
    lit = Literal(kind=BaseKind.literal, datatype=LiteralType.str, value="hello")
    assert lit.to_doxa() == '"hello"'


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, "0"),
        (-2, "-2"),
        (3.14, "3.14"),
        (2.0, "2.0"),
    ],
)
def test_literal_to_doxa_numeric(value, expected):
    datatype = (
        LiteralType.int
        if isinstance(value, int) and not isinstance(value, bool)
        else LiteralType.float
    )
    if isinstance(value, float):
        datatype = LiteralType.float
    lit = Literal(kind=BaseKind.literal, datatype=datatype, value=value)
    assert lit.to_doxa() == expected


@pytest.mark.parametrize(
    "inp",
    [
        '"hello"',
        '"foo bar"',
        "123",
        "-7",
        "3.14",
        "1e3",
        ".5",
    ],
)
def test_literal_roundtrip_from_to_from(inp):
    lit1 = Literal.from_doxa(inp)
    out = lit1.to_doxa()
    lit2 = Literal.from_doxa(out)

    assert lit2.datatype == lit1.datatype
    assert lit2.value == lit1.value


def test_literal_kind_required():
    with pytest.raises(ValidationError):
        Literal(datatype=LiteralType.int, value=1)  # type: ignore[call-arg]


def test_literal_kind_must_be_literal():
    with pytest.raises(ValidationError):
        Literal(kind=BaseKind.rule, datatype=LiteralType.int, value=1)  # wrong kind


def test_literal_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Literal.model_validate(
            {"kind": "literal", "datatype": "int", "value": 1, "extra": 123}
        )


def test_literal_string_does_escape_quotes_current_impl():
    lit = Literal(kind=BaseKind.literal, datatype=LiteralType.str, value='a"b')
    assert lit.to_doxa() == '"a\\"b"'


def test_literal_string_does_escape_backslash_current_impl():
    lit = Literal(kind=BaseKind.literal, datatype=LiteralType.str, value=r"a\b")
    assert lit.to_doxa() == '"a\\\\b"'
