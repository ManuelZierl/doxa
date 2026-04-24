from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Literal, Union

from pydantic import Field, model_validator

from doxa.core._parsing.annotation_utils import (
    extract_annotation_kwargs,
    is_default_annotation,
)
from doxa.core._parsing.parsing_utils import (
    get_date_lit_regex,
    get_datetime_lit_regex,
    get_duration_lit_regex,
    get_float_regex,
    get_int_regex,
    get_pred_ref_regex,
    parse_date_literal,
    parse_datetime_literal,
    parse_duration_literal,
    parse_python_string_literal,
    render_date_literal,
    render_datetime_literal,
    render_duration_literal,
    split_annotation_suffix,
    split_top_level,
)
from doxa.core.annotate_mixin import AnnotateMixin
from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.entity import Entity
from doxa.core.literal_type import LiteralType
from doxa.core.term_kinds import TermKind

_INT_RE = get_int_regex()
_FLOAT_RE = get_float_regex()
_PRED_REF_RE = get_pred_ref_regex()
_DATE_LIT_RE = get_date_lit_regex()
_DATETIME_LIT_RE = get_datetime_lit_regex()
_DURATION_LIT_RE = get_duration_lit_regex()


def belief_arg_from_doxa(inp: str) -> BeliefArg:
    last_error: ValueError | None = None

    for cls in (BeliefLiteralArg, BeliefPredRefArg, BeliefEntityArg):
        try:
            return cls.from_doxa(inp)
        except ValueError as exc:
            last_error = exc

    raise ValueError(f"Invalid belief argument: {inp!r}") from last_error


class BeliefEntityArg(Base):
    kind: Literal[BaseKind.belief_arg] = Field(...)
    term_kind: Literal[TermKind.ent] = Field(...)
    ent_name: str = Field(
        ...,
        description="Entity name reference.",
    )

    def to_doxa(self) -> str:
        return self.ent_name

    @classmethod
    def from_doxa(cls, inp: str) -> "BeliefEntityArg":
        ent = Entity.from_doxa(inp)
        return cls(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.ent,
            ent_name=ent.name,
        )


class BeliefLiteralArg(Base):
    kind: Literal[BaseKind.belief_arg] = Field(...)
    term_kind: Literal[TermKind.lit] = Field(...)
    lit_type: LiteralType = Field(
        ...,
        description="Literal type tag.",
    )
    value: object = Field(
        ...,
        description="Literal value.",
    )

    model_config = {"arbitrary_types_allowed": True}

    def to_doxa(self) -> str:
        if self.lit_type == LiteralType.str:
            return f'"{self.value}"'
        if self.lit_type == LiteralType.int:
            return str(self.value)
        if self.lit_type == LiteralType.float:
            return str(self.value)
        if self.lit_type == LiteralType.date:
            return render_date_literal(self.value)
        if self.lit_type == LiteralType.datetime:
            return render_datetime_literal(self.value)
        if self.lit_type == LiteralType.duration:
            return render_duration_literal(self.value)
        raise ValueError(f"Unsupported literal type: {self.lit_type}")

    @classmethod
    def from_doxa(cls, inp: str) -> "BeliefLiteralArg":
        s = inp.strip()

        if _DATETIME_LIT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.datetime,
                value=parse_datetime_literal(s),
            )

        if _DATE_LIT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.date,
                value=parse_date_literal(s),
            )

        if _DURATION_LIT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.duration,
                value=parse_duration_literal(s),
            )

        if s.startswith('"') and s.endswith('"'):
            return cls(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.str,
                value=parse_python_string_literal(s),
            )

        if _INT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.int,
                value=int(s),
            )

        if _FLOAT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.lit,
                lit_type=LiteralType.float,
                value=float(s),
            )

        raise ValueError(f"Invalid belief literal argument: {inp!r}")

    @model_validator(mode="after")
    def validate_value_matches_type(self) -> "BeliefLiteralArg":
        import datetime as _dt

        if self.lit_type == LiteralType.str and not isinstance(self.value, str):
            raise ValueError(
                "BeliefLiteralArg with lit_type='str' must use a string value."
            )
        if self.lit_type == LiteralType.int and type(self.value) is not int:
            raise ValueError(
                "BeliefLiteralArg with lit_type='int' must use an int value."
            )
        if self.lit_type == LiteralType.float and type(self.value) is not float:
            raise ValueError(
                "BeliefLiteralArg with lit_type='float' must use a float value."
            )
        if self.lit_type == LiteralType.date and type(self.value) is not _dt.date:
            raise ValueError(
                "BeliefLiteralArg with lit_type='date' must use a date value."
            )
        if self.lit_type == LiteralType.datetime and not isinstance(
            self.value, _dt.datetime
        ):
            raise ValueError(
                "BeliefLiteralArg with lit_type='datetime' must use a datetime value."
            )
        if self.lit_type == LiteralType.duration and not isinstance(
            self.value, _dt.timedelta
        ):
            raise ValueError(
                "BeliefLiteralArg with lit_type='duration' must use a timedelta value."
            )
        return self


class BeliefPredRefArg(Base):
    kind: Literal[BaseKind.belief_arg] = Field(...)
    term_kind: Literal[TermKind.pred_ref] = Field(...)
    pred_ref_name: str = Field(
        ...,
        description="Referenced predicate name.",
    )
    pred_ref_arity: int = Field(
        ...,
        ge=0,
        description="Referenced predicate arity.",
    )

    def to_doxa(self) -> str:
        return f"{self.pred_ref_name}/{self.pred_ref_arity}"

    @classmethod
    def from_doxa(cls, inp: str) -> "BeliefPredRefArg":
        s = inp.strip()
        if not _PRED_REF_RE.fullmatch(s):
            raise ValueError(f"Invalid predicate reference argument: {inp!r}")
        name, arity_str = s.rsplit("/", 1)
        return cls(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.pred_ref,
            pred_ref_name=name,
            pred_ref_arity=int(arity_str),
        )


BeliefArg = Annotated[
    Union[BeliefEntityArg, BeliefLiteralArg, BeliefPredRefArg],
    Field(discriminator="term_kind"),
]


class BeliefRecord(Base, AuditMixin, AnnotateMixin):
    kind: Literal[BaseKind.belief_record] = Field(...)
    pred_name: str = Field(
        ...,
        description="Predicate name reference.",
    )
    pred_arity: int = Field(
        ...,
        ge=0,
        description="Predicate arity.",
    )
    args: List[BeliefArg] = Field(
        ...,
        description="Ground arguments of the asserted atom, ordered by predicate position.",
    )

    def to_doxa(self) -> str:
        args_str = ", ".join(arg.to_doxa() for arg in self.args)
        atom = f"{self.pred_name}({args_str})"

        ann = AnnotateMixin(
            b=self.b,
            d=self.d,
            src=self.src,
            et=self.et,
            vf=self.vf,
            vt=self.vt,
            name=self.name,
            description=self.description,
        )

        if is_default_annotation(ann):
            return atom

        return f"{atom} {ann.to_doxa_annotation()}"

    @classmethod
    def from_doxa(cls, inp: str) -> "BeliefRecord":
        if not isinstance(inp, str):
            raise TypeError("BeliefRecord input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("BeliefRecord input must not be empty.")

        atom_str, annotation_str = split_annotation_suffix(s)

        m = re.fullmatch(
            r"""
            ^\s*
            (?P<name>[a-z][A-Za-z0-9_]*)
            \s*
            \(
            (?P<args>.*)
            \)
            \s*$
            """,
            atom_str,
            re.VERBOSE | re.DOTALL,
        )
        if not m:
            raise ValueError(
                "Invalid belief record syntax. Expected '<pred>(<args>)' optionally followed by annotation."
            )

        pred_name = m.group("name")
        arg_str = m.group("args").strip()
        arg_parts = [] if not arg_str else split_top_level(arg_str)

        args = [belief_arg_from_doxa(part) for part in arg_parts]

        kwargs: Dict[str, object] = {
            "kind": BaseKind.belief_record,
            "created_at": datetime.now(timezone.utc),
            "pred_name": pred_name,
            "pred_arity": len(arg_parts),
            "args": args,
        }

        if annotation_str:
            kwargs.update(extract_annotation_kwargs(annotation_str))

        return cls(**kwargs)

    @model_validator(mode="after")
    def validate_arity(self) -> "BeliefRecord":
        if len(self.args) != self.pred_arity:
            raise ValueError(
                f"BeliefRecord.args length ({len(self.args)}) does not match "
                f"predicate arity ({self.pred_arity}) for predicate '{self.pred_name}'."
            )
        return self
