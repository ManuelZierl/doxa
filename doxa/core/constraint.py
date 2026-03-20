from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Dict

from pydantic import Field, model_validator

from doxa.core.annotate_mixin import AnnotateMixin
from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.goal import (
    AtomGoal,
    BuiltinGoal,
    EntityArg,
    Goal,
    GoalArg,
    GoalBase,
    LiteralArg,
    VarArg,
    goal_arg_from_doxa,
    goal_from_doxa,
)
from doxa.core.goal_kinds import GoalKind
from doxa.core.var import Var
from doxa.core._parsing.annotation_utils import (
    extract_annotation_kwargs,
)
from doxa.core._parsing.parsing_utils import (
    split_annotation_suffix,
    split_top_level,
)
import re

# Backward-compatible aliases
ConstraintGoalBase = GoalBase
ConstraintAtomGoal = AtomGoal
ConstraintBuiltinGoal = BuiltinGoal
ConstraintGoal = Goal
ConstraintVarArg = VarArg
ConstraintEntityArg = EntityArg
ConstraintLiteralArg = LiteralArg
ConstraintGoalArg = GoalArg
constraint_goal_from_doxa = goal_from_doxa
constraint_goal_arg_from_doxa = goal_arg_from_doxa


class Constraint(Base, AuditMixin, AnnotateMixin):
    kind: Literal[BaseKind.constraint] = Field(...)
    goals: List["ConstraintGoal"] = Field(
        ...,
        description="Ordered constraint body goals evaluated left-to-right.",
    )

    @model_validator(mode="after")
    def validate_goal_indices(self) -> "Constraint":
        indices = [g.idx for g in self.goals]
        if indices != list(range(len(self.goals))):
            raise ValueError(
                f"Constraint goal indices must be contiguous and ordered from 0; got {indices}."
            )
        return self

    def to_doxa(self) -> str:
        body = ", ".join(goal.to_doxa() for goal in self.goals)

        parts: List[str] = []

        if self.name is not None:
            escaped = self.name.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'name:"{escaped}"')

        if self.description is not None:
            escaped = self.description.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'description:"{escaped}"')

        parts.append(f"b:{self.b}")

        parts.append(f"d:{self.d}")

        if self.src is not None:
            parts.append(f"src:{self.src}")

        if self.et is not None:
            iso = self.et.isoformat()
            if iso.endswith("+00:00"):
                iso = iso[:-6] + "Z"
            parts.append(f'et:"{iso}"')

        if self.vf is not None:
            iso = self.vf.isoformat()
            if iso.endswith("+00:00"):
                iso = iso[:-6] + "Z"
            parts.append(f'vf:"{iso}"')

        if self.vt is not None:
            iso = self.vt.isoformat()
            if iso.endswith("+00:00"):
                iso = iso[:-6] + "Z"
            parts.append(f'vt:"{iso}"')

        if not parts:
            return f"!:- {body}"

        return f"!:- {body} @{{{', '.join(parts)}}}"

    @classmethod
    def from_doxa(cls, inp: str) -> "Constraint":
        """Parse a single constraint from AX syntax."""
        if not isinstance(inp, str):
            raise TypeError("Constraint input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Constraint input must not be empty.")

        if not s.startswith("!:-"):
            raise ValueError("Constraint must start with '!:-'.")

        rest = s[3:].strip()
        if not rest:
            raise ValueError("Constraint body must not be empty.")

        body_str, annotation_str = split_annotation_suffix(rest)
        goal_parts = split_top_level(body_str)
        if not goal_parts:
            raise ValueError("Constraint body must contain at least one goal.")

        goals: List[ConstraintGoal] = []
        for i, part in enumerate(goal_parts):
            goal = constraint_goal_from_doxa(part)
            goals.append(goal.model_copy(update={"idx": i}))

        kwargs: Dict[str, object] = {
            "kind": BaseKind.constraint,
            "created_at": datetime.now(timezone.utc),
            "goals": goals,
        }

        if annotation_str:
            kwargs.update(extract_annotation_kwargs(annotation_str))

        return cls(**kwargs)
