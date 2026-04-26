from __future__ import annotations

from typing import Annotated, List, Literal, Union

from pydantic import Field, model_validator

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
    split_top_level,
)
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
from doxa.core.var import Var

_GOAL_CALL_RE = get_goal_call_regex()
_INT_RE = get_int_regex()
_FLOAT_RE = get_float_regex()
_PRED_REF_RE = get_pred_ref_regex()


def _builtin_names() -> set[str]:
    return {b.value for b in Builtin}


def goal_from_doxa(inp: str) -> "Goal":
    s = inp.strip()
    if not s:
        raise ValueError("Goal input must not be empty.")

    if s.startswith("assume(") and s.endswith(")"):
        return AssumeGoal.from_doxa(s)

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
        raise ValueError(f"Invalid goal syntax: {inp!r}")

    name = m.group("name")
    if name in _builtin_names():
        if negated:
            raise ValueError("Builtin goals cannot be negated.")
        return BuiltinGoal.from_doxa(core)

    return AtomGoal.from_doxa(s)


def goal_arg_from_doxa(inp: str) -> "GoalArg":
    return parse_with_fallback(
        inp,
        (
            LiteralArg.from_doxa,
            PredRefArg.from_doxa,
            VarArg.from_doxa,
            EntityArg.from_doxa,
        ),
        invalid_message=f"Invalid goal argument: {inp!r}",
    )


class GoalBase(Base):
    kind: Literal[BaseKind.goal] = Field(...)
    goal_kind: GoalKind = Field(...)
    idx: int = Field(..., ge=0, description="Goal order index in body (0-based).")


class AtomGoal(GoalBase):
    goal_kind: Literal[GoalKind.atom] = Field(GoalKind.atom)
    pred_name: str = Field(..., description="Predicate name when goal_kind='atom'.")
    pred_arity: int = Field(..., ge=0, description="Predicate arity.")
    negated: bool = Field(False, description="Negated atom.")
    goal_args: List["GoalArg"] = Field(...)

    @model_validator(mode="after")
    def validate_arity(self) -> "AtomGoal":
        if len(self.goal_args) != self.pred_arity:
            raise ValueError(
                f"Atom goal arg count ({len(self.goal_args)}) does not match "
                f"predicate arity ({self.pred_arity}) for '{self.pred_name}'."
            )
        return self

    def to_doxa(self) -> str:
        args = ", ".join(arg.to_doxa() for arg in self.goal_args)
        atom = f"{self.pred_name}({args})"
        return f"not {atom}" if self.negated else atom

    @classmethod
    def from_doxa(cls, inp: str) -> "AtomGoal":
        if not isinstance(inp, str):
            raise TypeError("Atom goal input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Atom goal input must not be empty.")

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
            raise ValueError(f"Invalid atom goal syntax: {inp!r}")

        name = m.group("name")
        if name in _builtin_names():
            raise ValueError("Builtin goal cannot be parsed as AtomGoal.")

        arg_str = m.group("args").strip()
        arg_parts = [] if not arg_str else split_top_level(arg_str)

        args: List[GoalArg] = []
        for i, part in enumerate(arg_parts):
            arg = goal_arg_from_doxa(part)
            args.append(arg.model_copy(update={"pos": i}))

        return cls(
            kind=BaseKind.goal,
            goal_kind=GoalKind.atom,
            idx=0,
            pred_name=name,
            pred_arity=len(arg_parts),
            negated=negated,
            goal_args=args,
        )


class AssumeGoal(GoalBase):
    goal_kind: Literal[GoalKind.assume] = Field(GoalKind.assume)
    assumptions: List["AtomGoal"] = Field(
        ...,
        description="List of ground atom goals treated as temporary facts.",
    )

    def to_doxa(self) -> str:
        inner = ", ".join(a.to_doxa() for a in self.assumptions)
        return f"assume({inner})"

    @classmethod
    def from_doxa(cls, inp: str) -> "AssumeGoal":
        if not isinstance(inp, str):
            raise TypeError("AssumeGoal input must be a string.")

        s = inp.strip()
        if not s.startswith("assume(") or not s.endswith(")"):
            raise ValueError(f"Invalid assume goal syntax: {inp!r}")

        inner = s[len("assume(") : -1].strip()
        if not inner:
            raise ValueError("assume() must contain at least one assumption.")

        parts = split_top_level(inner)
        assumptions: List[AtomGoal] = []
        for i, part in enumerate(parts):
            atom = AtomGoal.from_doxa(part)
            assumptions.append(atom.model_copy(update={"idx": i}))

        return cls(
            kind=BaseKind.goal,
            goal_kind=GoalKind.assume,
            idx=0,
            assumptions=assumptions,
        )


class BuiltinGoal(GoalBase):
    goal_kind: Literal[GoalKind.builtin] = Field(GoalKind.builtin)
    builtin_name: Builtin = Field(..., description="Builtin when goal_kind='builtin'.")
    goal_args: List["GoalArg"] = Field(...)

    @model_validator(mode="after")
    def validate_builtin_arity(self) -> "BuiltinGoal":
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
    def from_doxa(cls, inp: str) -> "BuiltinGoal":
        if not isinstance(inp, str):
            raise TypeError("Builtin goal input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Builtin goal input must not be empty.")

        if s.startswith("not ") or (s.startswith("not(") and s.endswith(")")):
            raise ValueError("Builtin goals cannot be negated.")

        m = _GOAL_CALL_RE.fullmatch(s)
        if not m:
            raise ValueError(f"Invalid builtin goal syntax: {inp!r}")

        name = m.group("name")
        if name not in _builtin_names():
            raise ValueError(f"Unknown builtin goal: {name!r}")

        arg_str = m.group("args").strip()
        arg_parts = [] if not arg_str else split_top_level(arg_str)

        args: List[GoalArg] = []
        for i, part in enumerate(arg_parts):
            arg = goal_arg_from_doxa(part)
            args.append(arg.model_copy(update={"pos": i}))

        return cls(
            kind=BaseKind.goal,
            goal_kind=GoalKind.builtin,
            idx=0,
            builtin_name=Builtin(name),
            goal_args=args,
        )


Goal = Annotated[
    Union[AtomGoal, BuiltinGoal, AssumeGoal],
    Field(discriminator="goal_kind"),
]


class VarArg(Base):
    kind: Literal[BaseKind.goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal["var"] = Field(...)
    var: Var = Field(..., description="Variable name.")

    def to_doxa(self) -> str:
        return self.var.to_doxa()

    @classmethod
    def from_doxa(cls, inp: str) -> "VarArg":
        return cls(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="var",
            var=Var.from_doxa(inp),
        )


class EntityArg(Base):
    kind: Literal[BaseKind.goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal["ent"] = Field(...)
    ent_name: str = Field(..., description="Entity name reference.")

    def to_doxa(self) -> str:
        return self.ent_name

    @classmethod
    def from_doxa(cls, inp: str) -> "EntityArg":
        return cls(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="ent",
            ent_name=parse_entity_name(inp),
        )


class LiteralArg(Base):
    kind: Literal[BaseKind.goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal["lit"] = Field(...)
    lit_type: LiteralType = Field(..., description="Literal type tag.")
    value: object = Field(..., description="Literal value.")

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def validate_value_matches_type(self) -> "LiteralArg":
        try:
            validate_literal_value(self.lit_type, self.value)
        except ValueError as exc:
            raise ValueError(f"LiteralArg {exc}") from exc
        return self

    def to_doxa(self) -> str:
        return render_literal_value(self.lit_type, self.value, escape_strings=False)

    @classmethod
    def from_doxa(cls, inp: str) -> "LiteralArg":
        lit_type, value = parse_literal_value(
            inp, error_prefix="Invalid literal argument"
        )
        return cls(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="lit",
            lit_type=lit_type,
            value=value,
        )


class PredRefArg(Base):
    kind: Literal[BaseKind.goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal["pred_ref"] = Field(...)
    pred_ref_name: str = Field(..., description="Referenced predicate name.")
    pred_ref_arity: int = Field(..., ge=0, description="Referenced predicate arity.")

    def to_doxa(self) -> str:
        return render_pred_ref(self.pred_ref_name, self.pred_ref_arity)

    @classmethod
    def from_doxa(cls, inp: str) -> "PredRefArg":
        name, arity = parse_pred_ref(
            inp,
            _PRED_REF_RE,
            error_prefix="Invalid predicate reference argument",
        )
        return cls(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="pred_ref",
            pred_ref_name=name,
            pred_ref_arity=arity,
        )


GoalArg = Annotated[
    Union[VarArg, EntityArg, LiteralArg, PredRefArg],
    Field(discriminator="term_kind"),
]
