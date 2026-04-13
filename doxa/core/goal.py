from __future__ import annotations

from typing import Annotated, List, Literal, Union

from pydantic import Field, model_validator

from doxa.core._parsing.parsing_utils import (
    get_date_lit_regex,
    get_datetime_lit_regex,
    get_duration_lit_regex,
    get_float_regex,
    get_goal_call_regex,
    get_int_regex,
    get_pred_ref_regex,
    parse_date_literal,
    parse_datetime_literal,
    parse_duration_literal,
    parse_python_string_literal,
    render_date_literal,
    render_datetime_literal,
    render_duration_literal,
    split_top_level,
)
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import BUILTIN_ARITY, Builtin
from doxa.core.entity import Entity
from doxa.core.goal_kinds import GoalKind
from doxa.core.literal_type import LiteralType
from doxa.core.var import Var

_GOAL_CALL_RE = get_goal_call_regex()
_INT_RE = get_int_regex()
_FLOAT_RE = get_float_regex()
_PRED_REF_RE = get_pred_ref_regex()
_DATE_LIT_RE = get_date_lit_regex()
_DATETIME_LIT_RE = get_datetime_lit_regex()
_DURATION_LIT_RE = get_duration_lit_regex()


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
    last_error: ValueError | None = None

    for cls in (LiteralArg, PredRefArg, VarArg, EntityArg):
        try:
            return cls.from_doxa(inp)
        except ValueError as exc:
            last_error = exc

    raise ValueError(f"Invalid goal argument: {inp!r}") from last_error


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
        ent = Entity.from_doxa(inp)
        return cls(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="ent",
            ent_name=ent.name,
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
        import datetime as _dt

        if self.lit_type == LiteralType.str and not isinstance(self.value, str):
            raise ValueError("Literal with lit_type='str' must use a string value.")
        if self.lit_type == LiteralType.int and type(self.value) is not int:
            raise ValueError("Literal with lit_type='int' must use an int value.")
        if self.lit_type == LiteralType.float and type(self.value) is not float:
            raise ValueError("Literal with lit_type='float' must use a float value.")
        if self.lit_type == LiteralType.date and not isinstance(self.value, _dt.date):
            raise ValueError("Literal with lit_type='date' must use a date value.")
        if self.lit_type == LiteralType.datetime and not isinstance(self.value, _dt.datetime):
            raise ValueError("Literal with lit_type='datetime' must use a datetime value.")
        if self.lit_type == LiteralType.duration and not isinstance(self.value, _dt.timedelta):
            raise ValueError("Literal with lit_type='duration' must use a timedelta value.")
        return self

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
    def from_doxa(cls, inp: str) -> "LiteralArg":
        s = inp.strip()

        if _DATETIME_LIT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.goal_arg,
                pos=0,
                term_kind="lit",
                lit_type=LiteralType.datetime,
                value=parse_datetime_literal(s),
            )

        if _DATE_LIT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.goal_arg,
                pos=0,
                term_kind="lit",
                lit_type=LiteralType.date,
                value=parse_date_literal(s),
            )

        if _DURATION_LIT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.goal_arg,
                pos=0,
                term_kind="lit",
                lit_type=LiteralType.duration,
                value=parse_duration_literal(s),
            )

        if s.startswith('"') and s.endswith('"'):
            return cls(
                kind=BaseKind.goal_arg,
                pos=0,
                term_kind="lit",
                lit_type=LiteralType.str,
                value=parse_python_string_literal(s),
            )

        if _INT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.goal_arg,
                pos=0,
                term_kind="lit",
                lit_type=LiteralType.int,
                value=int(s),
            )

        if _FLOAT_RE.fullmatch(s):
            return cls(
                kind=BaseKind.goal_arg,
                pos=0,
                term_kind="lit",
                lit_type=LiteralType.float,
                value=float(s),
            )

        raise ValueError(f"Invalid literal argument: {inp!r}")


class PredRefArg(Base):
    kind: Literal[BaseKind.goal_arg] = Field(...)
    pos: int = Field(..., ge=0, description="Argument position in goal (0-based).")
    term_kind: Literal["pred_ref"] = Field(...)
    pred_ref_name: str = Field(..., description="Referenced predicate name.")
    pred_ref_arity: int = Field(..., ge=0, description="Referenced predicate arity.")

    def to_doxa(self) -> str:
        return f"{self.pred_ref_name}/{self.pred_ref_arity}"

    @classmethod
    def from_doxa(cls, inp: str) -> "PredRefArg":
        s = inp.strip()
        if not _PRED_REF_RE.fullmatch(s):
            raise ValueError(f"Invalid predicate reference argument: {inp!r}")
        name, arity_str = s.rsplit("/", 1)
        return cls(
            kind=BaseKind.goal_arg,
            pos=0,
            term_kind="pred_ref",
            pred_ref_name=name,
            pred_ref_arity=int(arity_str),
        )


GoalArg = Annotated[
    Union[VarArg, EntityArg, LiteralArg, PredRefArg],
    Field(discriminator="term_kind"),
]
