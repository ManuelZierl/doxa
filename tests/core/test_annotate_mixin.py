from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from doxa.core.annotate_mixin import AnnotateMixin


def test_from_doxa_annotation_parses_full_annotation() -> None:
    ann = AnnotateMixin.from_doxa_annotation(
        '@{b:0.9, d:0.01, src:registry_2020, et:"2026-02-27T10:00:00Z", '
        'vf:"2026-01-01T00:00:00Z", vt:"2026-12-31T23:59:59Z", '
        'name:"parent fact", description:"from registry"}'
    )

    assert ann.b == 0.9
    assert ann.d == 0.01
    assert ann.src == "registry_2020"
    assert ann.et == datetime(2026, 2, 27, 10, 0, 0, tzinfo=timezone.utc)
    assert ann.vf == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert ann.vt == datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    assert ann.name == "parent fact"
    assert ann.description == "from registry"


def test_from_doxa_annotation_accepts_bare_body_without_wrapper() -> None:
    ann = AnnotateMixin.from_doxa_annotation("b:0.9, d:0.1, src:registry_2020")

    assert ann.b == 0.9
    assert ann.d == 0.1
    assert ann.src == "registry_2020"


def test_from_doxa_annotation_accepts_brace_wrapper() -> None:
    ann = AnnotateMixin.from_doxa_annotation("{b:0.9, d:0.1, src:registry_2020}")

    assert ann.b == 0.9
    assert ann.d == 0.1
    assert ann.src == "registry_2020"


def test_from_doxa_annotation_empty_block_returns_defaults() -> None:
    ann = AnnotateMixin.from_doxa_annotation("@{}")

    assert ann.b == 1.0
    assert ann.d == 0.0
    assert ann.src is None
    assert ann.et is not None
    assert ann.vf is None
    assert ann.vt is None
    assert ann.name is None
    assert ann.description is None


def test_from_doxa_annotation_maps_note_to_description() -> None:
    ann = AnnotateMixin.from_doxa_annotation('@{note:"derived from source"}')

    assert ann.description == "derived from source"


def test_from_doxa_annotation_parses_quoted_strings_with_commas_and_colons() -> None:
    ann = AnnotateMixin.from_doxa_annotation(
        '@{name:"alpha, beta", description:"x:y, z"}'
    )

    assert ann.name == "alpha, beta"
    assert ann.description == "x:y, z"


def test_from_doxa_annotation_parses_escaped_quotes() -> None:
    ann = AnnotateMixin.from_doxa_annotation('@{description:"say \\"hello\\""}')

    assert ann.description == 'say "hello"'


def test_from_doxa_annotation_parses_datetime_with_z_suffix() -> None:
    ann = AnnotateMixin.from_doxa_annotation('@{et:"2026-02-27T10:00:00Z"}')

    assert ann.et == datetime(2026, 2, 27, 10, 0, 0, tzinfo=timezone.utc)


def test_from_doxa_annotation_parses_datetime_with_explicit_offset() -> None:
    ann = AnnotateMixin.from_doxa_annotation('@{et:"2026-02-27T11:00:00+01:00"}')

    assert ann.et == datetime.fromisoformat("2026-02-27T11:00:00+01:00")


def test_from_doxa_annotation_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate annotation key"):
        AnnotateMixin.from_doxa_annotation("@{b:0.9, b:0.8}")


def test_from_doxa_annotation_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="not allow keys"):
        AnnotateMixin.from_doxa_annotation('@{policy:"strict"}')


def test_from_doxa_annotation_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        AnnotateMixin.from_doxa_annotation("")


def test_from_doxa_annotation_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        AnnotateMixin.from_doxa_annotation(None)  # type: ignore[arg-type]


def test_from_doxa_annotation_rejects_unterminated_wrapper() -> None:
    with pytest.raises(ValueError, match="must be closed by"):
        AnnotateMixin.from_doxa_annotation("@{b:0.9")


def test_from_doxa_annotation_rejects_unterminated_quoted_string() -> None:
    with pytest.raises(ValueError, match="unterminated quoted string"):
        AnnotateMixin.from_doxa_annotation('@{name:"abc}')


def test_from_doxa_annotation_rejects_trailing_comma() -> None:
    with pytest.raises(ValueError, match="trailing comma"):
        AnnotateMixin.from_doxa_annotation("@{b:0.9,}")


def test_from_doxa_annotation_rejects_empty_entry_between_commas() -> None:
    with pytest.raises(ValueError, match="empty entry between commas"):
        AnnotateMixin.from_doxa_annotation("@{b:0.9,,d:0.1}")


def test_from_doxa_annotation_rejects_missing_key() -> None:
    with pytest.raises(ValueError, match="missing key"):
        AnnotateMixin.from_doxa_annotation("@{:0.9}")


def test_from_doxa_annotation_rejects_missing_value() -> None:
    with pytest.raises(ValueError, match="missing value"):
        AnnotateMixin.from_doxa_annotation("@{b:}")


def test_from_doxa_annotation_rejects_missing_colon() -> None:
    with pytest.raises(ValueError, match="expected 'key:value'"):
        AnnotateMixin.from_doxa_annotation("@{b}")


def test_from_doxa_annotation_rejects_invalid_float_value() -> None:
    with pytest.raises(ValueError, match="must be a number"):
        AnnotateMixin.from_doxa_annotation("@{b:abc}")


def test_from_doxa_annotation_rejects_invalid_datetime() -> None:
    with pytest.raises(ValueError, match="must be an ISO-8601 datetime string"):
        AnnotateMixin.from_doxa_annotation('@{et:"not-a-date"}')


def test_from_doxa_annotation_rejects_b_out_of_range_via_pydantic() -> None:
    with pytest.raises(ValidationError):
        AnnotateMixin.from_doxa_annotation("@{b:1.5}")


def test_from_doxa_annotation_rejects_d_out_of_range_via_pydantic() -> None:
    with pytest.raises(ValidationError):
        AnnotateMixin.from_doxa_annotation("@{d:-0.1}")


def test_to_doxa_annotation_serializes_simple_fields() -> None:
    ann = AnnotateMixin(
        b=0.9,
        d=0.01,
        src="registry_2020",
    )

    out = ann.to_doxa_annotation()

    assert out.startswith("@{")
    assert out.endswith("}")
    assert "b:0.9" in out
    assert "d:0.01" in out
    assert "src:registry_2020" in out


def test_to_doxa_annotation_serializes_datetime_and_quotes_strings() -> None:
    ann = AnnotateMixin(
        et=datetime(2026, 2, 27, 10, 0, 0, tzinfo=timezone.utc),
        name="parent fact",
        description='say "hello"',
    )

    out = ann.to_doxa_annotation()

    assert 'et:"2026-02-27T10:00:00Z"' in out
    assert 'name:"parent fact"' in out
    assert 'description:"say \\"hello\\""' in out


def test_to_doxa_annotation_omits_none_fields() -> None:
    ann = AnnotateMixin()

    out = ann.to_doxa_annotation()

    assert out.startswith("@{")
    assert out.endswith("}")
    assert "src:" not in out
    assert "et:" in out
    assert "vf:" not in out
    assert "vt:" not in out
    assert "name:" not in out
    assert "description:" not in out


def test_round_trip_parse_then_serialize_then_parse() -> None:
    original = AnnotateMixin.from_doxa_annotation(
        '@{b:0.9, d:0.01, src:registry_2020, et:"2026-02-27T10:00:00Z", '
        'name:"parent fact", description:"from registry"}'
    )

    serialized = original.to_doxa_annotation()
    reparsed = AnnotateMixin.from_doxa_annotation(serialized)

    assert reparsed == original
