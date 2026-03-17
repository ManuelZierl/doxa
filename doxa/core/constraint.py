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
    goal_arg_from_ax,
    goal_from_ax,
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
constraint_goal_from_ax = goal_from_ax
constraint_goal_arg_from_ax = goal_arg_from_ax

_SIG_RE = re.compile(
    r"""^
    \s*sig\s*\(
    \s*(?P<pred_name>[a-z][A-Za-z0-9_]*)
    \s*,\s*
    \[(?P<types>[^\]]+)\]
    (?P<rest>.*)
    \)\s*$
    """,
    re.VERBOSE | re.DOTALL,
)


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

    def to_ax(self) -> str:
        body = ", ".join(goal.to_ax() for goal in self.goals)

        parts: List[str] = []

        if self.name is not None:
            escaped = self.name.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'name:"{escaped}"')

        if self.description is not None:
            escaped = self.description.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'description:"{escaped}"')

        if self.b != 1.0:
            parts.append(f"b:{self.b}")

        if self.d != 0.0:
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
    def from_ax(cls, inp: str) -> "Constraint":
        """Parse a single constraint from AX syntax.

        Note: This does NOT handle sig() syntax, which expands to multiple constraints.
        Use from_ax_multi() for that.
        """
        if not isinstance(inp, str):
            raise TypeError("Constraint input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Constraint input must not be empty.")

        # Check for sig syntactic sugar - this is an error in from_ax
        if _SIG_RE.match(s):
            raise ValueError(
                "sig() syntax expands to multiple constraints. "
                "Use Constraint.from_ax_multi() or parse at the Branch level."
            )

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
            goal = constraint_goal_from_ax(part)
            goals.append(goal.model_copy(update={"idx": i}))

        kwargs: Dict[str, object] = {
            "kind": BaseKind.constraint,
            "created_at": datetime.now(timezone.utc),
            "goals": goals,
        }

        if annotation_str:
            kwargs.update(extract_annotation_kwargs(annotation_str))

        return cls(**kwargs)

    @classmethod
    def from_ax_multi(cls, inp: str) -> List["Constraint"]:
        """Parse constraint(s) from AX syntax.

        Handles both regular constraints and sig() syntax which expands to multiple constraints.
        Returns a list of constraints (single item for regular constraints, multiple for sig).
        """
        if not isinstance(inp, str):
            raise TypeError("Constraint input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Constraint input must not be empty.")

        # Check for sig syntactic sugar
        sig_match = _SIG_RE.match(s)
        if sig_match:
            return cls._from_sig_syntax(sig_match)

        # Regular constraint - return single-item list
        return [cls.from_ax(s)]

    @classmethod
    def _from_sig_syntax(cls, match: re.Match) -> List["Constraint"]:
        """Parse sig(pred_name, [type1, type2, ...], ...) syntax.

        This is syntactic sugar that expands to multiple type-checking constraints.
        For example: sig(parent, [person, person]) expands to:
        !:- parent(X0, X1), not person(X0).
        !:- parent(X0, X1), not person(X1).

        Returns a list of constraints, one for each argument type.
        """
        pred_name = match.group("pred_name")
        types_str = match.group("types").strip()
        rest = match.group("rest").strip()

        # Parse the type list
        type_parts = split_top_level(types_str)
        types = [t.strip() for t in type_parts]

        if not types:
            raise ValueError(
                "sig() syntax requires at least one type in the type list."
            )

        # Parse optional annotation from rest
        annotation_str = None
        if rest:
            # rest might contain additional parameters like view="..."
            # For now, we'll check if there's an @{...} annotation
            if "@{" in rest:
                _, annotation_str = split_annotation_suffix(rest)

        arity = len(types)
        constraints: List[Constraint] = []

        # Generate one constraint for each argument position
        for arg_idx, type_name in enumerate(types):
            # Create the main predicate goal: pred_name(X0, X1, ...)
            pred_args: List[GoalArg] = []
            for i in range(arity):
                var = Var(kind=BaseKind.var, name=f"X{i}")
                pred_args.append(
                    VarArg(
                        kind=BaseKind.goal_arg,
                        pos=i,
                        term_kind="var",
                        var=var,
                    )
                )

            pred_goal = AtomGoal(
                kind=BaseKind.goal,
                goal_kind=GoalKind.atom,
                idx=0,
                pred_name=pred_name,
                pred_arity=arity,
                negated=False,
                goal_args=pred_args,
            )

            # Create the type-checking goal: not type_name(X{arg_idx})
            type_var = Var(kind=BaseKind.var, name=f"X{arg_idx}")
            type_arg = VarArg(
                kind=BaseKind.goal_arg,
                pos=0,
                term_kind="var",
                var=type_var,
            )

            type_goal = AtomGoal(
                kind=BaseKind.goal,
                goal_kind=GoalKind.atom,
                idx=1,
                pred_name=type_name,
                pred_arity=1,
                negated=True,
                goal_args=[type_arg],
            )

            goals = [pred_goal, type_goal]

            kwargs: Dict[str, object] = {
                "kind": BaseKind.constraint,
                "created_at": datetime.now(timezone.utc),
                "goals": goals,
            }

            if annotation_str:
                kwargs.update(extract_annotation_kwargs(annotation_str))

            constraints.append(cls(**kwargs))

        return constraints
