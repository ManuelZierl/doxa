from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal, List, Annotated, Union, Dict

from pydantic import Field, model_validator

from doxa.core.annotate_mixin import AnnotateMixin
from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.entity import Entity
from doxa.core.literal_type import LiteralType
from doxa.core.term_kinds import TermKind
from doxa.core._parsing.annotation_utils import (
    extract_annotation_kwargs,
    is_default_annotation,
)
from doxa.core._parsing.parsing_utils import (
    get_float_regex,
    get_int_regex,
    parse_python_string_literal,
    render_string_literal,
    split_annotation_suffix,
    split_top_level,
)

_INT_RE = get_int_regex()
_FLOAT_RE = get_float_regex()


def belief_arg_from_ax(inp: str) -> BeliefArg:
    last_error: ValueError | None = None

    for cls in (BeliefLiteralArg, BeliefEntityArg):
        try:
            return cls.from_ax(inp)
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

    def to_ax(self) -> str:
        return self.ent_name

    @classmethod
    def from_ax(cls, inp: str) -> "BeliefEntityArg":
        ent = Entity.from_ax(inp)
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
    value: str | int | float = Field(
        ...,
        description="Literal value.",
    )

    def to_ax(self) -> str:
        if self.lit_type == LiteralType.str:
            return f'"{self.value}"'
        if self.lit_type == LiteralType.int:
            return str(self.value)
        if self.lit_type == LiteralType.float:
            return str(self.value)
        raise ValueError(f"Unsupported literal type: {self.lit_type}")

    @classmethod
    def from_ax(cls, inp: str) -> "BeliefLiteralArg":
        s = inp.strip()

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
        return self


BeliefArg = Annotated[
    Union[BeliefEntityArg, BeliefLiteralArg],
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

    def to_ax(self) -> str:
        args_str = ", ".join(arg.to_ax() for arg in self.args)
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

        return f"{atom} {ann.to_ax_annotation()}"

    @classmethod
    def from_ax(cls, inp: str) -> "BeliefRecord":
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

        args = [belief_arg_from_ax(part) for part in arg_parts]

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
