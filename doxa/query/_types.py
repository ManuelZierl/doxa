"""Compiled internal types shared across the query evaluator submodules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple, Union

from doxa.core.belief_record import BeliefRecord
from doxa.core.builtins import Builtin
from doxa.core.constraint import Constraint
from doxa.core.query import Query
from doxa.core.rule import Rule

Subst = Dict[str, Any]


@dataclass(frozen=True)
class _VarTerm:
    name: str


@dataclass(frozen=True)
class _GroundTerm:
    value: Any


_Term = Union[_VarTerm, _GroundTerm]


@dataclass(frozen=True)
class _Atom:
    pred: str
    negated: bool
    args: Tuple[_Term, ...]


@dataclass(frozen=True)
class _BuiltinGoal:
    op: Builtin
    args: Tuple[_Term, ...]


@dataclass(frozen=True)
class _AssumeGoal:
    atoms: Tuple[_Atom, ...]


_Goal = Union[_Atom, _BuiltinGoal, _AssumeGoal]


@dataclass(frozen=True)
class _EvidenceRow:
    """
    One grounded support row for a positive atom or derived head.

    b/d are support contributions for the grounded atom under subst.
    """

    subst: Subst
    b: float
    d: float


@dataclass(frozen=True)
class _CompiledRule:
    head_terms: Tuple[_Term, ...]
    body_goals: Tuple[_Goal, ...]


@dataclass(frozen=True)
class _MemoEvidenceRow:
    args: Tuple[Any, ...]
    b: float
    d: float


GroundAtomKey = Tuple[str, Tuple[Any, ...]]

# Sentinel for unbound argument positions in call-pattern keys.
_FREE: Any = "__doxa_free__"

CallPatternKey = Tuple[str, Tuple[Any, ...]]


@dataclass(frozen=True)
class _TruthRow:
    """
    One grounded body-success row.

    support:
        Positive truth-support for the successful body.

    falsity:
        Falsity-support for the successful body.

    atoms:
        Grounded positive atoms used in this successful derivation.
    """

    subst: Subst
    support: float
    falsity: float
    atoms: Tuple[GroundAtomKey, ...] = ()


@dataclass(frozen=True)
class _Context:
    fact_index: Dict[Tuple[str, int], List[BeliefRecord]]
    rules: Tuple[Rule, ...]
    constraints: Tuple[Constraint, ...]
    query: Query
    effective_query_time: datetime
    effective_valid_at: datetime
    effective_known_at: datetime
    max_depth: int
    explain_enabled: bool
    # Tabling: memoisation + cycle detection.
    memo: Dict[CallPatternKey, List[_MemoEvidenceRow]] = field(default_factory=dict)
    in_progress: Set[CallPatternKey] = field(default_factory=set)
    rules_by_head: Dict[Tuple[str, int], Tuple[Tuple[int, Rule], ...]] = field(
        init=False
    )
    compiled_rule_cache: Dict[Tuple[int, int], _CompiledRule] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        grouped: Dict[Tuple[str, int], List[Tuple[int, Rule]]] = {}
        for rule_idx, rule in enumerate(self.rules):
            key = (rule.head_pred_name, rule.head_pred_arity)
            grouped.setdefault(key, []).append((rule_idx, rule))
        object.__setattr__(
            self,
            "rules_by_head",
            {key: tuple(items) for key, items in grouped.items()},
        )


class ExplainCollector:
    __slots__ = ("enabled", "events")

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.events: List[Dict[str, Any]] = []

    def record(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.enabled:
            self.events.append({"type": event_type, **payload})
