"""Type-constraint generation helpers for predicates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import BUILTIN_ARITY, Builtin
from doxa.core.constraint import Constraint
from doxa.core.goal import AtomGoal, VarArg
from doxa.core.goal_kinds import GoalKind
from doxa.core.var import Var


def generate_predicate_type_constraints(
    pred_name: str,
    pred_arity: int,
    type_list: List[str] | None,
) -> List[Constraint]:
    """Generate type-checking constraints for a predicate signature."""
    if type_list is None:
        return []

    constraints: List[Constraint] = []
    builtin_type_predicates = {b.value for b in Builtin if BUILTIN_ARITY[b] == 1}

    for arg_idx, type_name in enumerate(type_list):
        if type_name in builtin_type_predicates:
            continue

        pred_args: List[VarArg] = []
        for i in range(pred_arity):
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
            pred_arity=pred_arity,
            negated=False,
            goal_args=pred_args,
        )

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

        constraints.append(
            Constraint(
                kind=BaseKind.constraint,
                created_at=datetime.now(timezone.utc),
                goals=[pred_goal, type_goal],
            )
        )

    return constraints
