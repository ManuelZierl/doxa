from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Literal, Union

from pydantic import Field, model_validator

from doxa.core._parsing.annotation_utils import (
    extract_annotation_kwargs,
    is_default_annotation,
)
from doxa.core._parsing.literal_value import (
    parse_literal_value,
    render_literal_value,
    validate_literal_value,
)
from doxa.core._parsing.parsing_utils import (
    get_pred_ref_regex,
    split_annotation_suffix,
    split_top_level,
)
from doxa.core.annotate_mixin import AnnotateMixin
from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.literal_type import LiteralType
from doxa.core.term_args import (
    parse_entity_name,
    parse_pred_ref,
    parse_with_fallback,
    render_pred_ref,
)
from doxa.core.term_kinds import TermKind

_PRED_REF_RE = get_pred_ref_regex()


def belief_arg_from_doxa(inp: str) -> BeliefArg:
    return parse_with_fallback(
        inp,
        (
            BeliefLiteralArg.from_doxa,
            BeliefPredRefArg.from_doxa,
            BeliefEntityArg.from_doxa,
        ),
        invalid_message=f"Invalid belief argument: {inp!r}",
    )


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
        return cls(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.ent,
            ent_name=parse_entity_name(inp),
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
        return render_literal_value(self.lit_type, self.value, escape_strings=False)

    @classmethod
    def from_doxa(cls, inp: str) -> "BeliefLiteralArg":
        lit_type, value = parse_literal_value(
            inp,
            error_prefix="Invalid belief literal argument",
        )
        return cls(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.lit,
            lit_type=lit_type,
            value=value,
        )

    @model_validator(mode="after")
    def validate_value_matches_type(self) -> "BeliefLiteralArg":
        try:
            validate_literal_value(self.lit_type, self.value)
        except ValueError as exc:
            raise ValueError(f"BeliefLiteralArg {exc}") from exc
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
        return render_pred_ref(self.pred_ref_name, self.pred_ref_arity)

    @classmethod
    def from_doxa(cls, inp: str) -> "BeliefPredRefArg":
        name, arity = parse_pred_ref(
            inp,
            _PRED_REF_RE,
            error_prefix="Invalid predicate reference argument",
        )
        return cls(
            kind=BaseKind.belief_arg,
            term_kind=TermKind.pred_ref,
            pred_ref_name=name,
            pred_ref_arity=arity,
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
