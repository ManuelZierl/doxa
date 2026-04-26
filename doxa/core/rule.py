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
    get_float_regex,
    get_goal_call_regex,
    get_int_regex,
    get_pred_ref_regex,
    split_annotation_suffix,
    split_top_level,
)
from doxa.core.annotate_mixin import AnnotateMixin
from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import BUILTIN_ARITY, Builtin
from doxa.core.goal_kinds import GoalKind
from doxa.core.literal_type import LiteralType
from doxa.core.term_args import (
    parse_entity_name,
    parse_pred_ref,
    parse_with_fallback,
    render_pred_ref,
)
from doxa.core.term_kinds import TermKind
from doxa.core.var import Var

_GOAL_CALL_RE = get_goal_call_regex()
_INT_RE = get_int_regex()
_FLOAT_RE = get_float_regex()
_PRED_REF_RE = get_pred_ref_regex()

_RULE_RE = re.compile(
    r"""
    ^\s*
    (?P<head>.+?)
    \s*:-\s*
    (?P<body>.+)
    \s*$
    """,
    re.VERBOSE | re.DOTALL,
)

_INT_RE = get_int_regex()
_FLOAT_RE = get_float_regex()


def _builtin_names() -> set[str]:
    return {b.value for b in Builtin}


def rule_head_arg_from_doxa(inp: str) -> RuleHeadArg:
    return parse_with_fallback(
        inp,
        (
            RuleHeadLiteralArg.from_doxa,
            RuleHeadPredRefArg.from_doxa,
            RuleHeadVarArg.from_doxa,
            RuleHeadEntityArg.from_doxa,
        ),
        invalid_message=f"Invalid rule head argument: {inp!r}",
    )


def rule_goal_arg_from_doxa(inp: str) -> RuleGoalArg:
    return parse_with_fallback(
        inp,
        (
            RuleGoalLiteralArg.from_doxa,
            RuleGoalPredRefArg.from_doxa,
            RuleGoalVarArg.from_doxa,
            RuleGoalEntityArg.from_doxa,
        ),
        invalid_message=f"Invalid rule goal argument: {inp!r}",
    )


def rule_goal_from_doxa(inp: str) -> RuleGoal:
    s = inp.strip()
    if not s:
        raise ValueError("Rule goal input must not be empty.")

    negated = False
    core = s

    if core.startswith("not "):
        negated = True
        core = core[4:].strip()
    elif core.startswith("not(") and core.endswith(")"):
        negated = True
        core = core[4:-1].strip()

    m = _GOAL_CALL_RE.fullmatch(core)
    if not m:
        raise ValueError(f"Invalid rule goal syntax: {inp!r}")

    name = m.group("name")
    if name in _builtin_names():
        if negated:
            raise ValueError("Builtin goals cannot be negated.")
        return RuleBuiltinGoal.from_doxa(core)

    return RuleAtomGoal.from_doxa(s)


class Rule(Base, AuditMixin, AnnotateMixin):
    kind: Literal[BaseKind.rule] = Field(...)
    head_pred_name: str = Field(
        ...,
        description="Predicate name used in rule head.",
    )
    head_pred_arity: int = Field(
        ...,
        ge=0,
        description="Predicate arity.",
    )
    head_args: List["RuleHeadArg"] = Field(
        ...,
        description="Ordered rule head arguments.",
    )
    goals: List["RuleGoal"] = Field(
        ...,
        description="Ordered rule body goals evaluated left-to-right.",
    )

    @model_validator(mode="after")
    def validate_structure(self) -> "Rule":
        if len(self.head_args) != self.head_pred_arity:
            raise ValueError(
                f"Rule head arg count ({len(self.head_args)}) does not match "
                f"predicate arity ({self.head_pred_arity}) for '{self.head_pred_name}'."
            )

        indices = [g.idx for g in self.goals]
        if indices != list(range(len(self.goals))):
            raise ValueError(
                f"Rule goal indices must be contiguous and ordered from 0; got {indices}."
            )

        return self

    def to_doxa(self) -> str:
        head_args_str = ", ".join(arg.to_doxa() for arg in self.head_args)
        head = f"{self.head_pred_name}({head_args_str})"
        body = ", ".join(goal.to_doxa() for goal in self.goals)

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
            return f"{head} :- {body}"

        return f"{head} :- {body} {ann.to_doxa_annotation()}"

    @classmethod
    def from_doxa(cls, inp: str) -> "Rule":
        if not isinstance(inp, str):
            raise TypeError("Rule input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Rule input must not be empty.")

        rule_str, annotation_str = split_annotation_suffix(s)

        m_rule = _RULE_RE.fullmatch(rule_str)
        if not m_rule:
            raise ValueError(
                "Invalid rule syntax. Expected '<head> :- <body>' optionally followed by annotation."
            )

        head_str = m_rule.group("head").strip()
        body_str = m_rule.group("body").strip()

        m_head = _GOAL_CALL_RE.fullmatch(head_str)
        if not m_head:
            raise ValueError(f"Invalid rule head syntax: {head_str!r}")

        head_name = m_head.group("name")
        head_arg_str = m_head.group("args").strip()
        head_arg_parts = [] if not head_arg_str else split_top_level(head_arg_str)

        head_args: List[RuleHeadArg] = []
        for i, part in enumerate(head_arg_parts):
            arg = rule_head_arg_from_doxa(part)
            head_args.append(arg.model_copy(update={"pos": i}))

        goal_parts = split_top_level(body_str)
        if not goal_parts:
            raise ValueError("Rule body must contain at least one goal.")

        goals: List[RuleGoal] = []
        for i, part in enumerate(goal_parts):
            goal = rule_goal_from_doxa(part)
            goals.append(goal.model_copy(update={"idx": i}))

        kwargs: Dict[str, object] = {
            "kind": BaseKind.rule,
            "created_at": datetime.now(timezone.utc),
            "head_pred_name": head_name,
            "head_pred_arity": len(head_arg_parts),
            "head_args": head_args,
            "goals": goals,
        }

        if annotation_str:
            kwargs.update(extract_annotation_kwargs(annotation_str))

        return cls(**kwargs)


class RuleHeadVarArg(Base):
    kind: Literal[BaseKind.rule_head_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in rule head (0-based).")
    term_kind: Literal[TermKind.var] = Field(...)
    var: Var = Field(..., description="Variable value.")

    def to_doxa(self) -> str:
        return self.var.to_doxa()

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleHeadVarArg":
        return cls(
            kind=BaseKind.rule_head_arg,
            pos=0,
            term_kind=TermKind.var,
            var=Var.from_doxa(inp),
        )


class RuleHeadEntityArg(Base):
    kind: Literal[BaseKind.rule_head_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in rule head (0-based).")
    term_kind: Literal[TermKind.ent] = Field(...)
    ent_name: str = Field(..., description="Entity name reference.")

    def to_doxa(self) -> str:
        return self.ent_name

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleHeadEntityArg":
        return cls(
            kind=BaseKind.rule_head_arg,
            pos=0,
            term_kind=TermKind.ent,
            ent_name=parse_entity_name(inp),
        )


class RuleHeadLiteralArg(Base):
    kind: Literal[BaseKind.rule_head_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in rule head (0-based).")
    term_kind: Literal[TermKind.lit] = Field(...)
    lit_type: LiteralType = Field(..., description="Literal type tag.")
    value: object = Field(..., description="Literal value.")

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def validate_value_matches_type(self) -> "RuleHeadLiteralArg":
        try:
            validate_literal_value(self.lit_type, self.value)
        except ValueError as exc:
            raise ValueError(f"RuleHeadLiteralArg {exc}") from exc
        return self

    def to_doxa(self) -> str:
        return render_literal_value(self.lit_type, self.value)

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleHeadLiteralArg":
        lit_type, value = parse_literal_value(
            inp,
            error_prefix="Invalid rule head literal argument",
        )
        return cls(
            kind=BaseKind.rule_head_arg,
            pos=0,
            term_kind=TermKind.lit,
            lit_type=lit_type,
            value=value,
        )


class RuleHeadPredRefArg(Base):
    kind: Literal[BaseKind.rule_head_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in rule head (0-based).")
    term_kind: Literal[TermKind.pred_ref] = Field(...)
    pred_ref_name: str = Field(..., description="Referenced predicate name.")
    pred_ref_arity: int = Field(..., ge=0, description="Referenced predicate arity.")

    def to_doxa(self) -> str:
        return render_pred_ref(self.pred_ref_name, self.pred_ref_arity)

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleHeadPredRefArg":
        name, arity = parse_pred_ref(
            inp,
            _PRED_REF_RE,
            error_prefix="Invalid predicate reference argument",
        )
        return cls(
            kind=BaseKind.rule_head_arg,
            pos=0,
            term_kind=TermKind.pred_ref,
            pred_ref_name=name,
            pred_ref_arity=arity,
        )


RuleHeadArg = Annotated[
    Union[RuleHeadVarArg, RuleHeadEntityArg, RuleHeadLiteralArg, RuleHeadPredRefArg],
    Field(discriminator="term_kind"),
]


class RuleGoalBase(Base):
    kind: Literal[BaseKind.rule_goal] = Field(...)
    goal_kind: GoalKind = Field(...)
    idx: int = Field(..., ge=0, description="Goal order index in rule body (0-based).")


class RuleAtomGoal(RuleGoalBase):
    goal_kind: Literal[GoalKind.atom] = Field(GoalKind.atom)
    pred_name: str = Field(..., description="Predicate name when goal_kind='atom'.")
    pred_arity: int = Field(..., ge=0, description="Predicate arity.")
    negated: bool = Field(False, description="Negated atom.")
    goal_args: List["RuleGoalArg"] = Field(...)

    @model_validator(mode="after")
    def validate_arity(self) -> "RuleAtomGoal":
        if len(self.goal_args) != self.pred_arity:
            raise ValueError(
                f"Rule atom goal arg count ({len(self.goal_args)}) does not match "
                f"predicate arity ({self.pred_arity}) for '{self.pred_name}'."
            )
        return self

    def to_doxa(self) -> str:
        args = ", ".join(arg.to_doxa() for arg in self.goal_args)
        atom = f"{self.pred_name}({args})"
        return f"not {atom}" if self.negated else atom

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleAtomGoal":
        if not isinstance(inp, str):
            raise TypeError("Rule atom goal input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Rule atom goal input must not be empty.")

        negated = False
        core = s

        if core.startswith("not "):
            negated = True
            core = core[4:].strip()
        elif core.startswith("not(") and core.endswith(")"):
            negated = True
            core = core[4:-1].strip()

        m = _GOAL_CALL_RE.fullmatch(core)
        if not m:
            raise ValueError(f"Invalid rule atom goal syntax: {inp!r}")

        name = m.group("name")
        if name in _builtin_names():
            raise ValueError("Builtin goal cannot be parsed as RuleAtomGoal.")

        arg_str = m.group("args").strip()
        arg_parts = [] if not arg_str else split_top_level(arg_str)

        args: List[RuleGoalArg] = []
        for i, part in enumerate(arg_parts):
            arg = rule_goal_arg_from_doxa(part)
            args.append(arg.model_copy(update={"pos": i}))

        return cls(
            kind=BaseKind.rule_goal,
            goal_kind=GoalKind.atom,
            idx=0,
            pred_name=name,
            pred_arity=len(arg_parts),
            negated=negated,
            goal_args=args,
        )


class RuleBuiltinGoal(RuleGoalBase):
    goal_kind: Literal[GoalKind.builtin] = Field(GoalKind.builtin)
    builtin_name: Builtin = Field(..., description="Builtin when goal_kind='builtin'.")
    goal_args: List["RuleGoalArg"] = Field(...)

    @model_validator(mode="after")
    def validate_builtin_arity(self) -> "RuleBuiltinGoal":
        expected = BUILTIN_ARITY[self.builtin_name]
        if len(self.goal_args) != expected:
            raise ValueError(
                f"Builtin '{self.builtin_name}' expects {expected} arguments, got {len(self.goal_args)}."
            )
        return self

    def to_doxa(self) -> str:
        args = ", ".join(arg.to_doxa() for arg in self.goal_args)
        return f"{self.builtin_name.value}({args})"

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleBuiltinGoal":
        if not isinstance(inp, str):
            raise TypeError("Rule builtin goal input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Rule builtin goal input must not be empty.")

        if s.startswith("not ") or (s.startswith("not(") and s.endswith(")")):
            raise ValueError("Builtin goals cannot be negated.")

        m = _GOAL_CALL_RE.fullmatch(s)
        if not m:
            raise ValueError(f"Invalid rule builtin goal syntax: {inp!r}")

        name = m.group("name")
        if name not in _builtin_names():
            raise ValueError(f"Unknown builtin goal: {name!r}")

        arg_str = m.group("args").strip()
        arg_parts = [] if not arg_str else split_top_level(arg_str)

        args: List[RuleGoalArg] = []
        for i, part in enumerate(arg_parts):
            arg = rule_goal_arg_from_doxa(part)
            args.append(arg.model_copy(update={"pos": i}))

        return cls(
            kind=BaseKind.rule_goal,
            goal_kind=GoalKind.builtin,
            idx=0,
            builtin_name=Builtin(name),
            goal_args=args,
        )


RuleGoal = Annotated[
    Union[RuleAtomGoal, RuleBuiltinGoal],
    Field(discriminator="goal_kind"),
]


class RuleGoalVarArg(Base):
    kind: Literal[BaseKind.rule_goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal[TermKind.var] = Field(...)
    var: Var = Field(..., description="Variable value.")

    def to_doxa(self) -> str:
        return self.var.to_doxa()

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleGoalVarArg":
        return cls(
            kind=BaseKind.rule_goal_arg,
            pos=0,
            term_kind=TermKind.var,
            var=Var.from_doxa(inp),
        )


class RuleGoalEntityArg(Base):
    kind: Literal[BaseKind.rule_goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal[TermKind.ent] = Field(...)
    ent_name: str = Field(..., description="Entity name reference.")

    def to_doxa(self) -> str:
        return self.ent_name

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleGoalEntityArg":
        return cls(
            kind=BaseKind.rule_goal_arg,
            pos=0,
            term_kind=TermKind.ent,
            ent_name=parse_entity_name(inp),
        )


class RuleGoalLiteralArg(Base):
    kind: Literal[BaseKind.rule_goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal[TermKind.lit] = Field(...)
    lit_type: LiteralType = Field(..., description="Literal type tag.")
    value: object = Field(..., description="Literal value.")

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def validate_value_matches_type(self) -> "RuleGoalLiteralArg":
        try:
            validate_literal_value(self.lit_type, self.value)
        except ValueError as exc:
            raise ValueError(f"RuleGoalLiteralArg {exc}") from exc
        return self

    def to_doxa(self) -> str:
        return render_literal_value(self.lit_type, self.value)

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleGoalLiteralArg":
        lit_type, value = parse_literal_value(
            inp,
            error_prefix="Invalid rule goal literal argument",
        )
        return cls(
            kind=BaseKind.rule_goal_arg,
            pos=0,
            term_kind=TermKind.lit,
            lit_type=lit_type,
            value=value,
        )


class RuleGoalPredRefArg(Base):
    kind: Literal[BaseKind.rule_goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal[TermKind.pred_ref] = Field(...)
    pred_ref_name: str = Field(..., description="Referenced predicate name.")
    pred_ref_arity: int = Field(..., ge=0, description="Referenced predicate arity.")

    def to_doxa(self) -> str:
        return render_pred_ref(self.pred_ref_name, self.pred_ref_arity)

    @classmethod
    def from_doxa(cls, inp: str) -> "RuleGoalPredRefArg":
        name, arity = parse_pred_ref(
            inp,
            _PRED_REF_RE,
            error_prefix="Invalid predicate reference argument",
        )
        return cls(
            kind=BaseKind.rule_goal_arg,
            pos=0,
            term_kind=TermKind.pred_ref,
            pred_ref_name=name,
            pred_ref_arity=arity,
        )


RuleGoalArg = Annotated[
    Union[RuleGoalVarArg, RuleGoalEntityArg, RuleGoalLiteralArg, RuleGoalPredRefArg],
    Field(discriminator="term_kind"),
]
