"""Tests for first-class temporal value support (date, datetime, duration)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from doxa.core._parsing.parsing_utils import (
    parse_date_literal,
    parse_datetime_literal,
    parse_duration_literal,
    parse_iso_duration,
    render_date_literal,
    render_datetime_literal,
    render_duration_literal,
)
from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import BeliefLiteralArg
from doxa.core.builtins import BUILTIN_ARITY, Builtin
from doxa.core.goal import LiteralArg
from doxa.core.literal_type import LiteralType
from doxa.core.rule import RuleGoalLiteralArg, RuleHeadLiteralArg
from doxa.core.term_kinds import TermKind

# ---------------------------------------------------------------------------
# Parsing utilities
# ---------------------------------------------------------------------------


class TestParseDateLiteral:
    def test_basic(self) -> None:
        assert parse_date_literal('d"2024-06-15"') == date(2024, 6, 15)

    def test_whitespace(self) -> None:
        assert parse_date_literal('  d"2024-01-01"  ') == date(2024, 1, 1)

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid date literal"):
            parse_date_literal('"2024-06-15"')

    def test_invalid_date_value(self) -> None:
        with pytest.raises(ValueError, match="Invalid date value"):
            parse_date_literal('d"2024-13-01"')


class TestParseDatetimeLiteral:
    def test_utc_z(self) -> None:
        result = parse_datetime_literal('dt"2024-06-15T10:30:00Z"')
        assert result == datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_with_offset(self) -> None:
        result = parse_datetime_literal('dt"2024-06-15T10:30:00+02:00"')
        assert result.hour == 10
        assert result.utcoffset() == timedelta(hours=2)

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid datetime literal"):
            parse_datetime_literal('"2024-06-15T10:30:00Z"')

    def test_invalid_datetime_value(self) -> None:
        with pytest.raises(ValueError, match="Invalid datetime value"):
            parse_datetime_literal('dt"not-a-datetime"')


class TestParseDurationLiteral:
    def test_days(self) -> None:
        assert parse_duration_literal('dur"P30D"') == timedelta(days=30)

    def test_hours_minutes(self) -> None:
        assert parse_duration_literal('dur"PT2H30M"') == timedelta(hours=2, minutes=30)

    def test_years_months(self) -> None:
        result = parse_duration_literal('dur"P1Y6M"')
        assert result == timedelta(days=365 + 6 * 30)

    def test_complex(self) -> None:
        result = parse_duration_literal('dur"P1Y2M3DT4H5M6S"')
        expected = timedelta(days=365 + 60 + 3, hours=4, minutes=5, seconds=6)
        assert result == expected

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="Invalid duration literal"):
            parse_duration_literal('"P30D"')


class TestParseIsoDuration:
    def test_zero_duration_P_alone(self) -> None:
        with pytest.raises(ValueError, match="no components"):
            parse_iso_duration("P")

    def test_zero_duration_PT_alone(self) -> None:
        with pytest.raises(ValueError, match="no components"):
            parse_iso_duration("PT")

    def test_seconds_with_decimal(self) -> None:
        result = parse_iso_duration("PT1.5S")
        assert result == timedelta(seconds=1.5)

    def test_invalid_string(self) -> None:
        with pytest.raises(ValueError, match="Invalid ISO 8601 duration"):
            parse_iso_duration("not_valid")

    def test_negative_duration(self) -> None:
        assert parse_iso_duration("-P1D") == timedelta(days=-1)

    def test_negative_duration_time(self) -> None:
        assert parse_iso_duration("-PT2H30M") == timedelta(hours=-2, minutes=-30)


# ---------------------------------------------------------------------------
# Rendering utilities
# ---------------------------------------------------------------------------


class TestRenderDateLiteral:
    def test_basic(self) -> None:
        assert render_date_literal(date(2024, 6, 15)) == 'd"2024-06-15"'


class TestRenderDatetimeLiteral:
    def test_utc(self) -> None:
        dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert render_datetime_literal(dt) == 'dt"2024-06-15T10:30:00Z"'

    def test_non_utc(self) -> None:
        tz = timezone(timedelta(hours=2))
        dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=tz)
        result = render_datetime_literal(dt)
        assert result == 'dt"2024-06-15T10:30:00+02:00"'


class TestRenderDurationLiteral:
    def test_days(self) -> None:
        assert render_duration_literal(timedelta(days=30)) == 'dur"P30D"'

    def test_hours_minutes_seconds(self) -> None:
        assert (
            render_duration_literal(timedelta(hours=2, minutes=30, seconds=15))
            == 'dur"PT2H30M15S"'
        )

    def test_zero(self) -> None:
        assert render_duration_literal(timedelta(0)) == 'dur"PT0S"'

    def test_mixed(self) -> None:
        td = timedelta(days=1, hours=12)
        assert render_duration_literal(td) == 'dur"P1DT12H"'


# ---------------------------------------------------------------------------
# Roundtrip: parse → render → parse
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_date_roundtrip(self) -> None:
        original = 'd"2024-06-15"'
        d = parse_date_literal(original)
        assert render_date_literal(d) == original

    def test_datetime_roundtrip(self) -> None:
        original = 'dt"2024-06-15T10:30:00Z"'
        dt = parse_datetime_literal(original)
        assert render_datetime_literal(dt) == original

    def test_duration_roundtrip(self) -> None:
        original = 'dur"P30D"'
        td = parse_duration_literal(original)
        assert render_duration_literal(td) == original

    def test_negative_duration_roundtrip(self) -> None:
        td = timedelta(days=-1)
        rendered = render_duration_literal(td)
        assert parse_iso_duration(rendered[4:-1]) == td


# ---------------------------------------------------------------------------
# BeliefLiteralArg
# ---------------------------------------------------------------------------


class TestBeliefLiteralArgTemporal:
    def test_from_doxa_date(self) -> None:
        arg = BeliefLiteralArg.from_doxa('d"2024-06-15"')
        assert arg.lit_type == LiteralType.date
        assert arg.value == date(2024, 6, 15)
        assert arg.to_doxa() == 'd"2024-06-15"'

    def test_from_doxa_datetime(self) -> None:
        arg = BeliefLiteralArg.from_doxa('dt"2024-06-15T10:30:00Z"')
        assert arg.lit_type == LiteralType.datetime
        assert arg.value == datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert arg.to_doxa() == 'dt"2024-06-15T10:30:00Z"'

    def test_from_doxa_duration(self) -> None:
        arg = BeliefLiteralArg.from_doxa('dur"P30D"')
        assert arg.lit_type == LiteralType.duration
        assert arg.value == timedelta(days=30)
        assert arg.to_doxa() == 'dur"P30D"'

    def test_validator_rejects_wrong_date_value(self) -> None:
        with pytest.raises(ValidationError):
            BeliefLiteralArg(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.date,
                value="not-a-date",
            )

    def test_validator_rejects_datetime_for_date(self) -> None:
        """datetime is a subclass of date; the validator must reject it for lit_type=date."""
        with pytest.raises(ValidationError):
            BeliefLiteralArg(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.date,
                value=datetime(2024, 6, 15, tzinfo=timezone.utc),
            )

    def test_validator_rejects_wrong_datetime_value(self) -> None:
        with pytest.raises(ValidationError):
            BeliefLiteralArg(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.datetime,
                value="not-a-datetime",
            )

    def test_validator_rejects_wrong_duration_value(self) -> None:
        with pytest.raises(ValidationError):
            BeliefLiteralArg(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.duration,
                value="not-a-timedelta",
            )


# ---------------------------------------------------------------------------
# Goal LiteralArg
# ---------------------------------------------------------------------------


class TestGoalLiteralArgTemporal:
    def test_from_doxa_date(self) -> None:
        arg = LiteralArg.from_doxa('d"2024-06-15"')
        assert arg.lit_type == LiteralType.date
        assert arg.value == date(2024, 6, 15)
        assert arg.to_doxa() == 'd"2024-06-15"'

    def test_from_doxa_datetime(self) -> None:
        arg = LiteralArg.from_doxa('dt"2024-06-15T10:30:00Z"')
        assert arg.lit_type == LiteralType.datetime
        assert arg.to_doxa() == 'dt"2024-06-15T10:30:00Z"'

    def test_from_doxa_duration(self) -> None:
        arg = LiteralArg.from_doxa('dur"PT2H30M"')
        assert arg.lit_type == LiteralType.duration
        assert arg.value == timedelta(hours=2, minutes=30)


# ---------------------------------------------------------------------------
# RuleHeadLiteralArg / RuleGoalLiteralArg
# ---------------------------------------------------------------------------


class TestRuleLiteralArgTemporal:
    def test_rule_head_date(self) -> None:
        arg = RuleHeadLiteralArg.from_doxa('d"2024-06-15"')
        assert arg.lit_type == LiteralType.date
        assert arg.value == date(2024, 6, 15)
        assert arg.to_doxa() == 'd"2024-06-15"'

    def test_rule_head_datetime(self) -> None:
        arg = RuleHeadLiteralArg.from_doxa('dt"2024-06-15T10:30:00Z"')
        assert arg.lit_type == LiteralType.datetime

    def test_rule_head_duration(self) -> None:
        arg = RuleHeadLiteralArg.from_doxa('dur"P1D"')
        assert arg.lit_type == LiteralType.duration
        assert arg.value == timedelta(days=1)

    def test_rule_goal_date(self) -> None:
        arg = RuleGoalLiteralArg.from_doxa('d"2024-06-15"')
        assert arg.lit_type == LiteralType.date
        assert arg.to_doxa() == 'd"2024-06-15"'

    def test_rule_goal_datetime(self) -> None:
        arg = RuleGoalLiteralArg.from_doxa('dt"2024-06-15T10:30:00Z"')
        assert arg.lit_type == LiteralType.datetime

    def test_rule_goal_duration(self) -> None:
        arg = RuleGoalLiteralArg.from_doxa('dur"PT30M"')
        assert arg.lit_type == LiteralType.duration
        assert arg.value == timedelta(minutes=30)

    def test_rule_head_rejects_datetime_for_date(self) -> None:
        """datetime is a subclass of date; the validator must reject it for lit_type=date."""
        from doxa.core.base_kinds import BaseKind
        from doxa.core.term_kinds import TermKind

        with pytest.raises(ValidationError):
            RuleHeadLiteralArg(
                kind=BaseKind.rule_head_arg,
                pos=0,
                term_kind=TermKind.lit,
                lit_type=LiteralType.date,
                value=datetime(2024, 6, 15, tzinfo=timezone.utc),
            )

    def test_rule_goal_rejects_datetime_for_date(self) -> None:
        """datetime is a subclass of date; the validator must reject it for lit_type=date."""
        from doxa.core.base_kinds import BaseKind
        from doxa.core.term_kinds import TermKind

        with pytest.raises(ValidationError):
            RuleGoalLiteralArg(
                kind=BaseKind.rule_goal_arg,
                pos=0,
                term_kind=TermKind.lit,
                lit_type=LiteralType.date,
                value=datetime(2024, 6, 15, tzinfo=timezone.utc),
            )


# ---------------------------------------------------------------------------
# Builtins registry
# ---------------------------------------------------------------------------


class TestBuiltinArities:
    def test_date_builtin_exists(self) -> None:
        assert Builtin.date.value == "date"
        assert BUILTIN_ARITY[Builtin.date] == 1

    def test_datetime_builtin_exists(self) -> None:
        assert Builtin.datetime.value == "datetime"
        assert BUILTIN_ARITY[Builtin.datetime] == 1

    def test_duration_builtin_exists(self) -> None:
        assert Builtin.duration.value == "duration"
        assert BUILTIN_ARITY[Builtin.duration] == 1


# ---------------------------------------------------------------------------
# LiteralType enum
# ---------------------------------------------------------------------------


class TestLiteralTypeEnum:
    def test_temporal_members_exist(self) -> None:
        assert LiteralType.date == "date"
        assert LiteralType.datetime == "datetime"
        assert LiteralType.duration == "duration"
