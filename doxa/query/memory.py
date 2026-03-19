from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from doxa.core import TermKind, LiteralType
from doxa.core.branch import Branch
from doxa.core.builtins import Builtin
from doxa.core.belief_record import (
    BeliefArg,
    BeliefEntityArg,
    BeliefLiteralArg,
    BeliefRecord,
)
from doxa.core.constraint import Constraint
from doxa.core.epistemic_semantics import (
    BelnapStatusSemantics,
    BodyFalsitySemantics,
    BodyTruthSemantics,
    ConstraintApplicabilitySemantics,
    ConstraintPropagationSemantics,
    EpistemicSemanticsCapabilities,
    NonAtomSemantics,
    RuleApplicabilitySemantics,
    RulePropagationSemantics,
    SupportAggregationSemantics,
)
from doxa.core.goal import AtomGoal, BuiltinGoal, VarArg
from doxa.core.query import Query, QueryFocus
from doxa.core.rule import Rule, RuleAtomGoal, RuleBuiltinGoal
from doxa.query.engine import (
    BelnapStatus,
    EngineInfo,
    QueryAnswer,
    QueryEngine,
    QueryResult,
)

# ---------------------------------------------------------------------------
# Builtins
# ---------------------------------------------------------------------------

_CMP_OPS: Dict[Builtin, Any] = {
    Builtin.ne: operator.ne,
    Builtin.lt: operator.lt,
    Builtin.leq: operator.le,
    Builtin.gt: operator.gt,
    Builtin.geq: operator.ge,
}

# ---------------------------------------------------------------------------
# Lightweight compiled representation
# ---------------------------------------------------------------------------

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


_Goal = Union[_Atom, _BuiltinGoal]


@dataclass(frozen=True)
class _EvidenceRow:
    """
    One grounded support row for a positive atom or derived head.

    b/d are support contributions for the grounded atom under subst.
    """

    subst: Subst
    b: float
    d: float


GroundAtomKey = Tuple[str, Tuple[Any, ...]]


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


# ---------------------------------------------------------------------------
# Explain collector
# ---------------------------------------------------------------------------


class ExplainCollector:
    __slots__ = ("enabled", "events")

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.events: List[Dict[str, Any]] = []

    def record(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.enabled:
            self.events.append({"type": event_type, **payload})


# ---------------------------------------------------------------------------
# Core → internal compilation
# ---------------------------------------------------------------------------

def _strip_prefix(name: str, prefix: str) -> str:
    if name.startswith(prefix):
        return name[len(prefix):]
    return name

def _term(arg: Any) -> _Term:
    if hasattr(arg, "var"):
        return _VarTerm(arg.var.name)
    if hasattr(arg, "ent_name"):
        return _GroundTerm(arg.ent_name)
    if hasattr(arg, "value"):
        return _GroundTerm(arg.value)
    raise TypeError(f"Unsupported arg type for compilation: {type(arg)!r}")


def _prefixed_term(arg: Any, prefix: str) -> _Term:
    if hasattr(arg, "var"):
        return _VarTerm(prefix + arg.var.name)
    if hasattr(arg, "ent_name"):
        return _GroundTerm(arg.ent_name)
    if hasattr(arg, "value"):
        return _GroundTerm(arg.value)
    raise TypeError(f"Unsupported arg type for compilation: {type(arg)!r}")


def _compile_query_goals(query: Query) -> List[_Goal]:
    out: List[_Goal] = []
    for g in query.goals:
        if isinstance(g, AtomGoal):
            out.append(
                _Atom(
                    pred=g.pred_name,
                    negated=g.negated,
                    args=tuple(_term(a) for a in g.goal_args),
                )
            )
        elif isinstance(g, BuiltinGoal):
            out.append(
                _BuiltinGoal(
                    op=g.builtin_name,
                    args=tuple(_term(a) for a in g.goal_args),
                )
            )
        else:
            raise TypeError(f"Unsupported query goal type: {type(g)!r}")
    return out


def _compile_rule_head(rule: Rule, prefix: str) -> Tuple[_Term, ...]:
    return tuple(_prefixed_term(a, prefix) for a in rule.head_args)


def _compile_rule_body(rule: Rule, prefix: str) -> List[_Goal]:
    out: List[_Goal] = []
    for g in rule.goals:
        if isinstance(g, RuleAtomGoal):
            out.append(
                _Atom(
                    pred=g.pred_name,
                    negated=g.negated,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        elif isinstance(g, RuleBuiltinGoal):
            out.append(
                _BuiltinGoal(
                    op=g.builtin_name,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        else:
            raise TypeError(f"Unsupported rule goal type: {type(g)!r}")
    return out


def _compile_constraint_body(constraint: Constraint, prefix: str) -> List[_Goal]:
    out: List[_Goal] = []
    for g in constraint.goals:
        if isinstance(g, AtomGoal):
            out.append(
                _Atom(
                    pred=g.pred_name,
                    negated=g.negated,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        elif isinstance(g, BuiltinGoal):
            out.append(
                _BuiltinGoal(
                    op=g.builtin_name,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        else:
            raise TypeError(f"Unsupported constraint goal type: {type(g)!r}")
    return out


# ---------------------------------------------------------------------------
# Time / visibility
# ---------------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _resolve_effective_times(query: Query) -> Tuple[datetime, datetime, datetime]:
    opts = query.options
    now = datetime.now(timezone.utc)

    query_time = _utc(opts.query_time) if opts.query_time is not None else now
    valid_at = _utc(opts.valid_at) if opts.valid_at is not None else query_time
    known_at = _utc(opts.known_at) if opts.known_at is not None else query_time
    return query_time, valid_at, known_at


def _record_visible(
    record: BeliefRecord,
    *,
    valid_at: datetime,
    known_at: datetime,
) -> bool:
    if _utc(record.et) > known_at:
        return False

    if record.vf is not None and _utc(record.vf) > valid_at:
        return False

    if record.vt is not None and _utc(record.vt) < valid_at:
        return False

    return True


def _build_fact_index(
    records: Sequence[BeliefRecord],
    *,
    valid_at: datetime,
    known_at: datetime,
) -> Dict[Tuple[str, int], List[BeliefRecord]]:
    out: Dict[Tuple[str, int], List[BeliefRecord]] = {}
    for rec in records:
        if not _record_visible(rec, valid_at=valid_at, known_at=known_at):
            continue
        out.setdefault((rec.pred_name, rec.pred_arity), []).append(rec)
    return out


# ---------------------------------------------------------------------------
# Basic substitution / matching
# ---------------------------------------------------------------------------


def _resolve(term: _Term, subst: Subst) -> Optional[Any]:
    if isinstance(term, _GroundTerm):
        return term.value
    return subst.get(term.name)


def _unify(term: _Term, value: Any, subst: Subst) -> Optional[Subst]:
    if isinstance(term, _GroundTerm):
        return subst if term.value == value else None

    if term.name in subst:
        return subst if subst[term.name] == value else None

    return {**subst, term.name: value}


def _belief_arg_value(arg: BeliefArg) -> Any:
    if isinstance(arg, BeliefEntityArg):
        return arg.ent_name
    if isinstance(arg, BeliefLiteralArg):
        return arg.value
    raise TypeError(f"Unsupported belief arg type: {type(arg)!r}")


def _ground_atom_key(atom: _Atom, subst: Mapping[str, Any]) -> Optional[GroundAtomKey]:
    values: List[Any] = []
    for arg in atom.args:
        value = _resolve(arg, dict(subst))
        if value is None:
            return None
        values.append(value)
    return atom.pred, tuple(values)

def _match_rule_head(
    head_terms: Tuple[_Term, ...],
    goal_args: Tuple[_Term, ...],
    query_subst: Subst,
) -> Optional[Tuple[Subst, Subst, List[Tuple[str, str]]]]:
    """
    Match a compiled rule head against a compiled goal under the current query subst.

    Returns:
      (new_query_subst, initial_rule_subst, links)
    where links maps (query_var_name, rule_var_name).
    """
    new_q = dict(query_subst)
    r_subst: Subst = {}
    links: List[Tuple[str, str]] = []

    for h_term, g_term in zip(head_terms, goal_args):
        g_val = _resolve(g_term, new_q)

        if isinstance(h_term, _GroundTerm):
            if g_val is not None:
                if h_term.value != g_val:
                    return None
            else:
                if isinstance(g_term, _VarTerm):
                    if g_term.name in new_q and new_q[g_term.name] != h_term.value:
                        return None
                    new_q[g_term.name] = h_term.value
        else:
            if g_val is not None:
                if h_term.name in r_subst and r_subst[h_term.name] != g_val:
                    return None
                r_subst[h_term.name] = g_val
            else:
                if isinstance(g_term, _VarTerm):
                    links.append((g_term.name, h_term.name))

    return new_q, r_subst, links


# ---------------------------------------------------------------------------
# Epistemic semantics helpers
# ---------------------------------------------------------------------------


def _combine_truth(lhs: float, rhs: float, query: Query) -> float:
    semantics = query.options.epistemic_semantics.body_truth
    if semantics == BodyTruthSemantics.product:
        return lhs * rhs
    if semantics == BodyTruthSemantics.minimum:
        return min(lhs, rhs)
    raise ValueError(f"Unsupported body truth semantics: {semantics!r}")


def _combine_falsity(lhs: float, rhs: float, query: Query) -> float:
    semantics = query.options.epistemic_semantics.body_falsity
    if semantics == BodyFalsitySemantics.noisy_or:
        return 1.0 - ((1.0 - lhs) * (1.0 - rhs))
    if semantics == BodyFalsitySemantics.maximum:
        return max(lhs, rhs)
    raise ValueError(f"Unsupported body falsity semantics: {semantics!r}")


def _rule_applicability(body_b: float, body_d: float, query: Query) -> float:
    semantics = query.options.epistemic_semantics.rule_applicability
    if semantics == RuleApplicabilitySemantics.body_truth_only:
        return body_b
    if semantics == RuleApplicabilitySemantics.body_truth_discounted_by_body_falsity:
        return body_b * (1.0 - body_d)
    raise ValueError(f"Unsupported rule applicability semantics: {semantics!r}")


def _constraint_applicability(body_b: float, body_d: float, query: Query) -> float:
    semantics = query.options.epistemic_semantics.constraint_applicability
    if semantics == ConstraintApplicabilitySemantics.body_truth_only:
        return body_b
    if (
        semantics
        == ConstraintApplicabilitySemantics.body_truth_discounted_by_body_falsity
    ):
        return body_b * (1.0 - body_d)
    raise ValueError(f"Unsupported constraint applicability semantics: {semantics!r}")


def _aggregate_values(values: Sequence[float], query: Query) -> float:
    semantics = query.options.epistemic_semantics.support_aggregation
    vals = [float(v) for v in values if v > 0.0]
    if not vals:
        return 0.0

    if semantics == SupportAggregationSemantics.noisy_or:
        prod = 1.0
        for v in vals:
            prod *= 1.0 - v
        return 1.0 - prod

    if semantics == SupportAggregationSemantics.maximum:
        return max(vals)

    if semantics == SupportAggregationSemantics.capped_sum:
        return min(1.0, sum(vals))

    raise ValueError(f"Unsupported support aggregation semantics: {semantics!r}")


def _derive_belnap_status(b: float, d: float, query: Query) -> BelnapStatus:
    semantics = query.options.epistemic_semantics.belnap_status
    if semantics != BelnapStatusSemantics.nonzero:
        raise ValueError(f"Unsupported Belnap status semantics: {semantics!r}")

    eps = 1e-12
    has_b = b > eps
    has_d = d > eps

    if has_b and has_d:
        return BelnapStatus.both
    if has_b:
        return BelnapStatus.true
    if has_d:
        return BelnapStatus.false
    return BelnapStatus.neither


# ---------------------------------------------------------------------------
# Builtins
# ---------------------------------------------------------------------------


def _numeric(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return None


def _to_number(v: float) -> Union[int, float]:
    if abs(v - round(v)) <= 1e-9:
        return int(round(v))
    return v


def _arith_forward(op: Builtin, a: float, b: float) -> Optional[float]:
    if op == Builtin.add:
        return a + b
    if op == Builtin.sub:
        return a - b
    if op == Builtin.mul:
        return a * b
    if op == Builtin.div:
        return None if abs(b) <= 1e-12 else a / b
    return None


def _arith_solve_a(op: Builtin, b: float, c: float) -> Optional[float]:
    if op == Builtin.add:
        return c - b
    if op == Builtin.sub:
        return c + b
    if op == Builtin.mul:
        return None if abs(b) <= 1e-12 else c / b
    if op == Builtin.div:
        return c * b
    return None


def _arith_solve_b(op: Builtin, a: float, c: float) -> Optional[float]:
    if op == Builtin.add:
        return c - a
    if op == Builtin.sub:
        return a - c
    if op == Builtin.mul:
        return None if abs(a) <= 1e-12 else c / a
    if op == Builtin.div:
        return None if abs(c) <= 1e-12 else a / c
    return None


def _eval_builtin(goal: _BuiltinGoal, subst: Subst) -> Iterator[Subst]:
    op = goal.op

    if op == Builtin.eq:
        a_term, b_term = goal.args
        a_val = _resolve(a_term, subst)
        b_val = _resolve(b_term, subst)

        if a_val is not None and b_val is not None:
            if a_val == b_val:
                yield subst
            return

        if a_val is None and isinstance(a_term, _VarTerm) and b_val is not None:
            new_subst = _unify(a_term, b_val, subst)
            if new_subst is not None:
                yield new_subst
            return

        if b_val is None and isinstance(b_term, _VarTerm) and a_val is not None:
            new_subst = _unify(b_term, a_val, subst)
            if new_subst is not None:
                yield new_subst
            return

        if (
            isinstance(a_term, _VarTerm)
            and isinstance(b_term, _VarTerm)
            and a_term.name == b_term.name
        ):
            yield subst
        return

    if op in (Builtin.add, Builtin.sub, Builtin.mul, Builtin.div):
        a_term, b_term, c_term = goal.args
        a_val = _resolve(a_term, subst)
        b_val = _resolve(b_term, subst)
        c_val = _resolve(c_term, subst)

        na = _numeric(a_val)
        nb = _numeric(b_val)
        nc = _numeric(c_val)

        unbound = sum(1 for n in (na, nb, nc) if n is None)

        if unbound == 0:
            result = _arith_forward(op, na, nb)  # type: ignore[arg-type]
            if result is not None and abs(result - nc) <= 1e-9:  # type: ignore[operator]
                yield subst
            return

        if unbound == 1:
            if nc is None and isinstance(c_term, _VarTerm):
                result = _arith_forward(op, na, nb)  # type: ignore[arg-type]
                if result is not None:
                    new_subst = _unify(c_term, _to_number(result), subst)
                    if new_subst is not None:
                        yield new_subst
                return

            if na is None and isinstance(a_term, _VarTerm):
                result = _arith_solve_a(op, nb, nc)  # type: ignore[arg-type]
                if result is not None:
                    new_subst = _unify(a_term, _to_number(result), subst)
                    if new_subst is not None:
                        yield new_subst
                return

            if nb is None and isinstance(b_term, _VarTerm):
                result = _arith_solve_b(op, na, nc)  # type: ignore[arg-type]
                if result is not None:
                    new_subst = _unify(b_term, _to_number(result), subst)
                    if new_subst is not None:
                        yield new_subst
                return

        return

    if op == Builtin.between:
        x_val = _numeric(_resolve(goal.args[0], subst))
        lo_val = _numeric(_resolve(goal.args[1], subst))
        hi_val = _numeric(_resolve(goal.args[2], subst))
        if (
            x_val is not None
            and lo_val is not None
            and hi_val is not None
            and lo_val <= x_val <= hi_val
        ):
            yield subst
        return

    if op in (Builtin.int, Builtin.string, Builtin.float, Builtin.entity):
        val = _resolve(goal.args[0], subst)
        if val is None:
            return

        if op == Builtin.int and isinstance(val, int) and not isinstance(val, bool):
            yield subst
            return
        if op == Builtin.string and isinstance(val, str):
            yield subst
            return
        if op == Builtin.float and isinstance(val, float):
            yield subst
            return
        if op == Builtin.entity and isinstance(val, str):
            yield subst
            return
        return

    a_val = _resolve(goal.args[0], subst)
    b_val = _resolve(goal.args[1], subst)
    if a_val is None or b_val is None:
        return

    op_fn = _CMP_OPS[op]
    try:
        if op_fn(a_val, b_val):
            yield subst
    except TypeError:
        return


# ---------------------------------------------------------------------------
# Evidence solving
# ---------------------------------------------------------------------------


def _aggregate_evidence_rows(
    rows: Sequence[_EvidenceRow],
    query: Query,
) -> List[_EvidenceRow]:
    grouped: Dict[Tuple[Tuple[str, Any], ...], List[_EvidenceRow]] = {}
    for row in rows:
        key = tuple(sorted(row.subst.items(), key=lambda kv: kv[0]))
        grouped.setdefault(key, []).append(row)

    out: List[_EvidenceRow] = []
    for items, group in grouped.items():
        subst = dict(items)
        b = _aggregate_values([r.b for r in group], query)
        d = _aggregate_values([r.d for r in group], query)
        out.append(_EvidenceRow(subst=subst, b=b, d=d))
    return out


def _positive_atom_evidence(
    goal: _Atom,
    subst: Subst,
    ctx: _Context,
    collector: Optional[ExplainCollector],
    depth: int,
) -> List[_EvidenceRow]:
    if depth > ctx.max_depth:
        return []

    rows: List[_EvidenceRow] = []

    # facts
    for record in ctx.fact_index.get((goal.pred, len(goal.args)), ()):
        new_subst: Optional[Subst] = subst
        for g_term, f_arg in zip(goal.args, record.args):
            new_subst = _unify(g_term, _belief_arg_value(f_arg), new_subst)  # type: ignore[arg-type]
            if new_subst is None:
                break

        if new_subst is not None:
            if collector is not None:
                collector.record(
                    "fact_support",
                    {
                        "pred": goal.pred,
                        "b": record.b,
                        "d": record.d,
                    },
                )
            rows.append(_EvidenceRow(subst=new_subst, b=record.b, d=record.d))

    # rules
    prefix = f"_r{depth}_"
    for rule in ctx.rules:
        if rule.head_pred_name != goal.pred or rule.head_pred_arity != len(goal.args):
            continue

        head_terms = _compile_rule_head(rule, prefix)
        match = _match_rule_head(head_terms, goal.args, subst)
        if match is None:
            continue

        new_query_subst, initial_rule_subst, links = match
        body_goals = _compile_rule_body(rule, prefix)

        for body_row in _solve_body_truth(
            body_goals,
            initial_rule_subst,
            ctx,
            collector,
            depth + 1,
            current_support=1.0,
            current_falsity=0.0,
        ):
            result_subst = dict(new_query_subst)
            conflict = False
            for q_var, r_var in links:
                if r_var in body_row.subst:
                    value = body_row.subst[r_var]
                    if q_var in result_subst and result_subst[q_var] != value:
                        conflict = True
                        break
                    result_subst[q_var] = value
            if conflict:
                continue

            applicability = _rule_applicability(
                body_row.support,
                body_row.falsity,
                ctx.query,
            )
            if applicability <= 0.0:
                continue

            if collector is not None:
                collector.record(
                    "rule_applicability",
                    {
                        "pred": goal.pred,
                        "rule_head": rule.head_pred_name,
                        "body_support": body_row.support,
                        "body_falsity": body_row.falsity,
                        "applicability": applicability,
                    },
                )

            propagation = ctx.query.options.epistemic_semantics.rule_propagation
            if propagation != RulePropagationSemantics.body_times_rule_weights:
                raise ValueError(
                    f"Unsupported rule propagation semantics: {propagation!r}"
                )

            b = applicability * rule.b
            d = applicability * rule.d

            if collector is not None:
                collector.record(
                    "rule_support",
                    {
                        "pred": goal.pred,
                        "rule_head": rule.head_pred_name,
                        "body_support": body_row.support,
                        "body_falsity": body_row.falsity,
                        "applicability": applicability,
                        "b": b,
                        "d": d,
                    },
                )

            rows.append(_EvidenceRow(subst=result_subst, b=b, d=d))

    return _aggregate_evidence_rows(rows, ctx.query)


def _positive_atom_truth_rows(
    goal: _Atom,
    subst: Subst,
    ctx: _Context,
    collector: Optional[ExplainCollector],
    depth: int,
) -> List[_TruthRow]:
    evidence_rows = _positive_atom_evidence(goal, subst, ctx, collector, depth)
    out: List[_TruthRow] = []
    for row in evidence_rows:
        if row.b > 0.0 or row.d > 0.0:
            grounded = _ground_atom_key(goal, row.subst)
            atoms: Tuple[GroundAtomKey, ...] = (grounded,) if grounded is not None else ()
            out.append(
                _TruthRow(
                    subst=row.subst,
                    support=row.b,
                    falsity=row.d,
                    atoms=atoms,
                )
            )
    return out

def _constraint_violation_for_atoms(
    atoms: Tuple[GroundAtomKey, ...],
    ctx: _Context,
    collector: Optional[ExplainCollector],
    depth: int,
) -> float:
    if not atoms or not ctx.constraints:
        return 0.0

    atom_set = set(atoms)
    violations: List[float] = []

    for idx, constraint in enumerate(ctx.constraints):
        prefix = f"_c{depth}_{idx}_"
        body_goals = _compile_constraint_body(constraint, prefix)

        for body_row in _solve_body_truth(
            body_goals,
            {},
            ctx,
            collector,
            depth=depth + 1,
            current_support=1.0,
            current_falsity=0.0,
            current_atoms=(),
            apply_constraints=False,
        ):
            if not body_row.atoms:
                continue

            # Constraint only applies to this derivation if all grounded atoms
            # used by the constraint are contained in the derivation footprint.
            if not set(body_row.atoms).issubset(atom_set):
                continue

            applicability = _constraint_applicability(
                body_row.support,
                body_row.falsity,
                ctx.query,
            )
            if applicability <= 0.0:
                continue

            propagation = ctx.query.options.epistemic_semantics.constraint_propagation
            if (
                propagation
                != ConstraintPropagationSemantics.body_times_constraint_weights_to_violation
            ):
                raise ValueError(
                    f"Unsupported constraint propagation semantics: {propagation!r}"
                )

            violations.append(applicability * constraint.b)

    return _aggregate_values(violations, ctx.query)

def _solve_body_truth(
    goals: Sequence[_Goal],
    subst: Subst,
    ctx: _Context,
    collector: Optional[ExplainCollector],
    depth: int,
    current_support: float,
    current_falsity: float,
    current_atoms: Tuple[GroundAtomKey, ...] = (),
    apply_constraints: bool = True,
) -> Iterator[_TruthRow]:
    if depth > ctx.max_depth:
        return

    if not goals:
        final_falsity = current_falsity

        if apply_constraints:
            violation = _constraint_violation_for_atoms(
                current_atoms,
                ctx,
                collector,
                depth,
            )
            if violation > 0.0:
                final_falsity = _aggregate_values(
                    [final_falsity, violation],
                    ctx.query,
                )

        yield _TruthRow(
            subst=subst,
            support=current_support,
            falsity=final_falsity,
            atoms=current_atoms,
        )
        return

    goal = goals[0]
    rest = goals[1:]

    if isinstance(goal, _BuiltinGoal):
        for new_subst in _eval_builtin(goal, subst):
            yield from _solve_body_truth(
                rest,
                new_subst,
                ctx,
                collector,
                depth,
                current_support,
                current_falsity,
                current_atoms,
                apply_constraints,
            )
        return

    assert isinstance(goal, _Atom)

    if goal.negated:
        positive = _Atom(pred=goal.pred, negated=False, args=goal.args)
        has_any = any(
            row.support > 0.0
            for row in _positive_atom_truth_rows(
                positive,
                subst,
                ctx,
                collector,
                depth + 1,
            )
        )

        non_atom = ctx.query.options.epistemic_semantics.non_atom
        if non_atom != NonAtomSemantics.crisp_filters:
            raise ValueError(f"Unsupported non-atom semantics: {non_atom!r}")

        if not has_any:
            yield from _solve_body_truth(
                rest,
                subst,
                ctx,
                collector,
                depth,
                current_support,
                current_falsity,
                current_atoms,
                apply_constraints,
            )
        return

    for atom_row in _positive_atom_truth_rows(goal, subst, ctx, collector, depth):
        combined_support = _combine_truth(
            current_support,
            atom_row.support,
            ctx.query,
        )
        combined_falsity = _combine_falsity(
            current_falsity,
            atom_row.falsity,
            ctx.query,
        )
        yield from _solve_body_truth(
            rest,
            atom_row.subst,
            ctx,
            collector,
            depth,
            combined_support,
            combined_falsity,
            current_atoms + atom_row.atoms,
            apply_constraints,
        )


# ---------------------------------------------------------------------------
# Answer shaping
# ---------------------------------------------------------------------------


def _query_var_names(query: Query) -> Set[str]:
    names: Set[str] = set()
    for goal in query.goals:
        args = getattr(goal, "goal_args", [])
        for arg in args:
            if isinstance(arg, VarArg):
                names.add(arg.var.name)
    return names - query.anon_vars


def _project_bindings(
    subst: Mapping[str, Any], vars_to_keep: Set[str]
) -> Dict[str, Any]:
    return {k: v for k, v in subst.items() if k in vars_to_keep}

def _should_inline_assume_goal(
    goal: _Goal,
    *,
    compiled_goals: Sequence[_Goal],
    fact_index: Dict[Tuple[str, int], List[BeliefRecord]],
    idb_preds: Set[str],
    query_vars: Set[str],
) -> bool:
    if not isinstance(goal, _Atom):
        return False
    if goal.negated:
        return False
    if goal.pred in idb_preds:
        return False
    if not all(isinstance(arg, _GroundTerm) for arg in goal.args):
        return False

    # Conservative: only allow implicit hypotheticals in exploratory queries
    if not query_vars:
        return False
    if len(compiled_goals) <= 1:
        return False

    # Conservative: if this predicate already has visible facts,
    # do not silently inject new hypothetical facts.
    if (goal.pred, len(goal.args)) in fact_index:
        return False

    return True


def _aggregate_answers_from_evidence(
    rows: Sequence[_EvidenceRow],
    query: Query,
    query_vars: Set[str],
) -> List[QueryAnswer]:
    grouped: Dict[Tuple[Tuple[str, Any], ...], List[_EvidenceRow]] = {}

    for row in rows:
        bindings = _project_bindings(row.subst, query_vars)
        key = tuple(sorted(bindings.items(), key=lambda kv: kv[0]))
        grouped.setdefault(key, []).append(row)

    answers: List[QueryAnswer] = []
    for items, group in grouped.items():
        bindings = dict(items)
        b = _aggregate_values([r.b for r in group], query)
        d = _aggregate_values([r.d for r in group], query)
        answers.append(
            QueryAnswer(
                bindings=bindings,
                b=b,
                d=d,
                belnap_status=_derive_belnap_status(b, d, query),
            )
        )

    return answers


def _aggregate_answers_from_truth(
    rows: Sequence[_TruthRow],
    query: Query,
    query_vars: Set[str],
) -> List[QueryAnswer]:
    grouped: Dict[Tuple[Tuple[str, Any], ...], List[_TruthRow]] = {}

    for row in rows:
        bindings = _project_bindings(row.subst, query_vars)
        key = tuple(sorted(bindings.items(), key=lambda kv: kv[0]))
        grouped.setdefault(key, []).append(row)

    answers: List[QueryAnswer] = []
    for items, group in grouped.items():
        bindings = dict(items)
        b = _aggregate_values([r.support for r in group], query)
        d = _aggregate_values([r.falsity for r in group], query)

        answers.append(
            QueryAnswer(
                bindings=bindings,
                b=b,
                d=d,
                belnap_status=_derive_belnap_status(b, d, query),
            )
        )

    return answers


def _sort_answers(answers: List[QueryAnswer], order_by: List[str]) -> List[QueryAnswer]:
    if not order_by:
        return answers

    def _sort_key(answer: QueryAnswer) -> Tuple[Any, ...]:
        parts = []
        for key in order_by:
            value = answer.bindings.get(key)
            if value is None:
                parts.append((1, "", ""))
            else:
                parts.append((0, type(value).__name__, value))
        return tuple(parts)

    return sorted(answers, key=_sort_key)


def _apply_focus(answers: List[QueryAnswer], focus: QueryFocus) -> List[QueryAnswer]:
    """Filter and rank answers according to the requested QueryFocus.

    all:           keep all answers unchanged
    support:       keep answers with b > 0, rank by b descending
    disbelief:     keep answers with d > 0, rank by d descending
    contradiction: keep answers with both b > 0 and d > 0, rank by min(b, d) descending
    ignorance:     keep answers with both b and d near 0
    """
    if focus == QueryFocus.all:
        return answers

    eps = 1e-12

    if focus == QueryFocus.support:
        filtered = [a for a in answers if a.b > eps]
        return sorted(filtered, key=lambda a: a.b, reverse=True)

    if focus == QueryFocus.disbelief:
        filtered = [a for a in answers if a.d > eps]
        return sorted(filtered, key=lambda a: a.d, reverse=True)

    if focus == QueryFocus.contradiction:
        filtered = [a for a in answers if a.b > eps and a.d > eps]
        return sorted(filtered, key=lambda a: min(a.b, a.d), reverse=True)

    if focus == QueryFocus.ignorance:
        return [a for a in answers if a.b <= eps and a.d <= eps]

    return answers


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class InMemoryQueryEngine(QueryEngine):
    """
    First-pass in-memory epistemic query engine.

    What changed from the old engine:
    - no legacy policy/asof handling
    - time semantics come from query_time / valid_at / known_at
    - results are QueryAnswer rows
    - positive atoms, rules, and body evaluation are separated
    - constraints now have a reusable evaluation hook
    - general query bodies compute both body-level b and d
    - rule/constraint applicability can discount body truth by body falsity
    """

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name="in_memory",
            version="0.1",
            supported_epistemic_semantics=EpistemicSemanticsCapabilities(
                body_truth=(
                    BodyTruthSemantics.product,
                    BodyTruthSemantics.minimum,
                ),
                body_falsity=(
                    BodyFalsitySemantics.noisy_or,
                    BodyFalsitySemantics.maximum,
                ),
                rule_propagation=(RulePropagationSemantics.body_times_rule_weights,),
                constraint_propagation=(
                    ConstraintPropagationSemantics.body_times_constraint_weights_to_violation,
                ),
                support_aggregation=(
                    SupportAggregationSemantics.noisy_or,
                    SupportAggregationSemantics.maximum,
                    SupportAggregationSemantics.capped_sum,
                ),
                belnap_status=(BelnapStatusSemantics.nonzero,),
                non_atom=(NonAtomSemantics.crisp_filters,),
                rule_applicability=(
                    RuleApplicabilitySemantics.body_truth_only,
                    RuleApplicabilitySemantics.body_truth_discounted_by_body_falsity,
                ),
                constraint_applicability=(
                    ConstraintApplicabilitySemantics.body_truth_only,
                    ConstraintApplicabilitySemantics.body_truth_discounted_by_body_falsity,
                ),
            ),
        )

    def _evaluate(self, branch: Branch, query: Query) -> QueryResult:
        effective_query_time, effective_valid_at, effective_known_at = (
            _resolve_effective_times(query)
        )
        fact_index = _build_fact_index(
            branch.belief_records,
            valid_at=effective_valid_at,
            known_at=effective_known_at,
        )

        compiled_goals = _compile_query_goals(query)
        query_vars = _query_var_names(query)

        # ── Skolemize bridging variables ──────────────────────────────────────
        # A variable is skolemized when it appears in:
        #   1. A non-negated EDB assumption-candidate goal (EDB pred, >=1 ground arg)
        #   2. At least one IDB goal (predicate has rules)
        # This allows hypothetical facts to be connected through rule derivations.
        idb_preds: Set[str] = {r.head_pred_name for r in branch.rules}

        vars_in_edb_assumptions: Set[str] = set()
        for goal in compiled_goals:
            if (
                isinstance(goal, _Atom)
                and not goal.negated
                and goal.pred not in idb_preds
            ):
                # Only treat as a Skolemization candidate when the predicate has NO
                # existing facts.  If facts are present, normal resolution handles
                # the goal; Skolemizing the variable would replace it with a synthetic
                # entity name throughout the query and break fact lookups for all other
                # goals that share the same variable.
                if (goal.pred, len(goal.args)) not in fact_index:
                    if any(isinstance(a, _GroundTerm) for a in goal.args):
                        for a in goal.args:
                            if isinstance(a, _VarTerm):
                                vars_in_edb_assumptions.add(a.name)

        vars_in_idb_goals: Set[str] = set()
        for goal in compiled_goals:
            if isinstance(goal, _Atom) and goal.pred in idb_preds:
                for a in goal.args:
                    if isinstance(a, _VarTerm):
                        vars_in_idb_goals.add(a.name)

        skolem_map: Dict[str, str] = {
            v: f"_hyp_{v}" for v in vars_in_edb_assumptions & vars_in_idb_goals
        }

        if skolem_map:
            new_goals: List[_Goal] = []
            for goal in compiled_goals:
                if isinstance(goal, _Atom):
                    new_args = tuple(
                        _GroundTerm(skolem_map[a.name])
                        if isinstance(a, _VarTerm) and a.name in skolem_map
                        else a
                        for a in goal.args
                    )
                    new_goals.append(
                        _Atom(pred=goal.pred, negated=goal.negated, args=new_args)
                    )
                elif isinstance(goal, _BuiltinGoal):
                    new_args = tuple(
                        _GroundTerm(skolem_map[a.name])
                        if isinstance(a, _VarTerm) and a.name in skolem_map
                        else a
                        for a in goal.args
                    )
                    new_goals.append(_BuiltinGoal(op=goal.op, args=new_args))
                else:
                    new_goals.append(goal)
            compiled_goals = new_goals

        # ── Inline assumptions ────────────────────────────────────────────────
        # Fully-ground positive EDB atom goals become temporary facts with
        # b=1.0, d=0.0.  Only EDB predicates (no rules) are eligible.
        for goal in compiled_goals:
            if _should_inline_assume_goal(
                goal,
                compiled_goals=compiled_goals,
                fact_index=fact_index,
                idb_preds=idb_preds,
                query_vars=query_vars,
                    ):
                from doxa.core.base_kinds import BaseKind

                belief_args = []
                for arg in goal.args:
                    assert isinstance(arg, _GroundTerm)
                    val = arg.value
                    if isinstance(val, int):
                        belief_args.append(
                            BeliefLiteralArg(
                                kind=BaseKind.belief_arg,
                                term_kind=TermKind.lit,
                                lit_type=LiteralType.int,
                                value=val,
                            )
                        )
                    elif isinstance(val, float):
                        belief_args.append(
                            BeliefLiteralArg(
                                kind=BaseKind.belief_arg,
                                term_kind=TermKind.lit,
                                lit_type=LiteralType.float,
                                value=val,
                            )
                        )
                    else:
                        belief_args.append(
                            BeliefEntityArg(
                                kind=BaseKind.belief_arg,
                                term_kind="ent",
                                ent_name=str(val),
                            )
                        )

                rec = BeliefRecord(
                    kind=BaseKind.belief_record,
                    created_at=datetime.now(timezone.utc),
                    pred_name=goal.pred,
                    pred_arity=len(goal.args),
                    args=belief_args,
                    b=1.0,
                    d=0.0,
                )
                key = (rec.pred_name, rec.pred_arity)
                fact_index.setdefault(key, []).append(rec)

        # Seed substitution with Skolem bindings so they appear in results
        initial_subst: Subst = {var: skolem for var, skolem in skolem_map.items()}

        ctx = _Context(
            fact_index=fact_index,
            rules=tuple(branch.rules),
            constraints=tuple(branch.constraints),
            query=query,
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            max_depth=query.options.max_depth,
            explain_enabled=(query.options.explain != "false"),
        )

        collector = ExplainCollector(enabled=ctx.explain_enabled)

        answers: List[QueryAnswer]


        truth_rows = list(
            _solve_body_truth(
                compiled_goals,
                initial_subst,
                ctx,
                collector,
                depth=0,
                current_support=1.0,
                current_falsity=0.0,
                current_atoms=(),
                apply_constraints=True,
            )
        )
        answers = _aggregate_answers_from_truth(truth_rows, query, query_vars)

        # Closed query: return a single neither-answer if unsupported.
        if not query_vars and not answers:
            answers = [
                QueryAnswer(
                    bindings={},
                    b=0.0,
                    d=0.0,
                    belnap_status=BelnapStatus.neither,
                )
            ]

        # ── Post-processing ──────────────────────────────────────────────────
        # Note: distinct is not needed -- answer aggregation merges identical
        # projected bindings, which subsumes row-level deduplication.

        answers = _apply_focus(answers, query.options.focus)
        answers = _sort_answers(answers, query.options.order_by)

        if query.options.offset:
            answers = answers[query.options.offset :]

        if query.options.limit is not None:
            answers = answers[: query.options.limit]

        explain = tuple(collector.events) if ctx.explain_enabled else None

        return QueryResult(
            answers=tuple(answers),
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            epistemic_semantics=query.options.epistemic_semantics,
            explain=explain,
        )
