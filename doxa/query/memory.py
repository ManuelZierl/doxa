"""In-memory Datalog-style query engine for AX.

Evaluation strategy
-------------------
Top-down SLD resolution (Prolog-style), extended with:
  - Negation as Failure (NAF) for negated atom goals
  - Builtin goal evaluation:
      2-arg filters : ne / lt / leq / gt / geq
      2-arg binder  : eq  (binds an unbound variable to the other side's value)
      3-arg arith   : add / sub / mul / div  (A op B = C, solves for any one unknown)
      3-arg range   : between(X, Lo, Hi)
  - Belief-score filtering (report / credulous / skeptical policy)
  - Temporal filtering via ``asof`` query option (validity window [vf, vt])
  - Result post-processing: distinct, order_by, offset, limit
  - Configurable recursion depth via ``max_depth`` query option

Variable namespacing
--------------------
When applying a rule at depth *d*, every rule variable ``X`` is renamed to
``_r<d>_X`` internally.  This prevents clashes between query variables and rule
variables across recursive calls.  The solver maintains two substitution
dictionaries in parallel:

  query_subst   – maps original query-level variable names → ground values
  rule_subst    – maps prefixed rule variable names → ground values

After solving a rule body the link table propagates rule-variable bindings
back to the query substitution.

Internal goal representation
------------------------------
All pydantic goal/arg objects are converted to two lightweight frozen
dataclasses (_Atom / _Builtin) and a _Term union (_VarTerm / _GroundTerm)
before the solver runs.  This keeps the core solver free of pydantic
import noise and makes unit-testing the solver trivial.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

from doxa.core.branch import Branch
from doxa.core.builtins import Builtin
from doxa.core.belief_record import BeliefEntityArg, BeliefLiteralArg, BeliefRecord
from doxa.core.goal import AtomGoal, BuiltinGoal, VarArg
from doxa.core.query import Query
from doxa.core.rule import (
    Rule,
    RuleAtomGoal,
    RuleBuiltinGoal,
)
from doxa.query.engine import Binding, QueryEngine, QueryResult

# ── comparison-only builtin operators (ne / lt / leq / gt / geq) ─────────────

_CMP_OPS: Dict[Builtin, Any] = {
    Builtin.ne: operator.ne,
    Builtin.lt: operator.lt,
    Builtin.leq: operator.le,
    Builtin.gt: operator.gt,
    Builtin.geq: operator.ge,
}

# ── internal term / goal types ────────────────────────────────────────────────

Subst = Dict[str, Any]  # var_name → ground value


@dataclass(frozen=True)
class _VarTerm:
    """A variable – may be unbound in the current substitution."""

    name: str  # already prefixed when derived from a rule


@dataclass(frozen=True)
class _GroundTerm:
    """A ground value (entity name or literal)."""

    value: Any


_Term = Union[_VarTerm, _GroundTerm]


@dataclass(frozen=True)
class _Atom:
    pred: str
    negated: bool
    args: Tuple[_Term, ...]


@dataclass(frozen=True)
class _Builtin:
    op: Builtin
    args: Tuple[_Term, ...]  # length 2 for comparisons/eq, 3 for arith/between


_Goal = Union[_Atom, _Builtin]


# ── explain collector ────────────────────────────────────────────────────────


class ExplainCollector:
    """Collects explain trace events during query evaluation."""

    __slots__ = ("enabled", "events")

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.events: List[Dict[str, Any]] = []

    def record(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.events.append({"type": event_type, **payload})


def _term_repr(t: _Term) -> Any:
    """Return a JSON-friendly representation of an internal term."""
    if isinstance(t, _GroundTerm):
        return t.value
    return f"?{t.name}"


def _belief_arg_repr(arg: Any) -> Any:
    """Return a JSON-friendly representation of a BeliefRecord arg."""
    if isinstance(arg, BeliefEntityArg):
        return arg.ent_name
    if hasattr(arg, "value"):
        return arg.value
    return str(arg)


# ── pydantic → internal conversion ───────────────────────────────────────────


def _term(arg: Any) -> _Term:
    if hasattr(arg, "var"):
        return _VarTerm(arg.var.name)
    if hasattr(arg, "ent_name"):
        return _GroundTerm(arg.ent_name)
    if hasattr(arg, "value"):
        return _GroundTerm(arg.value)
    raise TypeError(f"_term(): unrecognised arg type {type(arg)!r}")


def _prefixed_term(arg: Any, prefix: str) -> _Term:
    if hasattr(arg, "var"):
        return _VarTerm(prefix + arg.var.name)
    if hasattr(arg, "ent_name"):
        return _GroundTerm(arg.ent_name)
    if hasattr(arg, "value"):
        return _GroundTerm(arg.value)
    raise TypeError(f"_prefixed_term(): unrecognised arg type {type(arg)!r}")


def _query_goals(query: Query) -> List[_Goal]:
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
                _Builtin(
                    op=g.builtin_name,
                    args=tuple(_term(a) for a in g.goal_args),
                )
            )
    return out


def _rule_head_terms(rule: Rule, prefix: str) -> Tuple[_Term, ...]:
    return tuple(_prefixed_term(a, prefix) for a in rule.head_args)


def _rule_body_goals(rule: Rule, prefix: str) -> List[_Goal]:
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
                _Builtin(
                    op=g.builtin_name,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
    return out


# ── fact-index helper ─────────────────────────────────────────────────────────


def _build_fact_index(
    belief_records: List[BeliefRecord],
) -> Dict[Tuple[str, int], List[BeliefRecord]]:
    """Group belief records by (pred_name, arity) for O(1) lookup."""
    idx: Dict[Tuple[str, int], List[BeliefRecord]] = {}
    for rec in belief_records:
        key = (rec.pred_name, rec.pred_arity)
        idx.setdefault(key, []).append(rec)
    return idx


# ── belief / temporal filtering ───────────────────────────────────────────────


def _is_active(
    record: BeliefRecord,
    asof: Optional[datetime],
    policy: str,
) -> bool:
    """Return True when *record* passes policy and temporal filters.

    Policy gate (aligned with legacy):
      report    → no filter
      credulous → b > d
      skeptical → b > d

    Temporal gate:
      Uses the validity window [vf, vt].  A record is active at *asof* if:
        (vf is None OR vf <= asof) AND (vt is None OR vt >= asof)
    """
    # Belief-score gate
    if policy in ("credulous", "skeptical"):
        if record.b <= record.d:
            return False
    # report: no filter

    # Validity-time gate
    if asof is not None:
        cmp_asof = (
            asof if asof.tzinfo is not None else asof.replace(tzinfo=timezone.utc)
        )

        if record.vf is not None:
            vf = (
                record.vf
                if record.vf.tzinfo is not None
                else record.vf.replace(tzinfo=timezone.utc)
            )
            if vf > cmp_asof:
                return False

        if record.vt is not None:
            vt = (
                record.vt
                if record.vt.tzinfo is not None
                else record.vt.replace(tzinfo=timezone.utc)
            )
            if vt < cmp_asof:
                return False

    return True


# ── substitution helpers ──────────────────────────────────────────────────────


def _resolve(term: _Term, subst: Subst) -> Optional[Any]:
    if isinstance(term, _GroundTerm):
        return term.value
    return subst.get(term.name)


def _unify(term: _Term, value: Any, subst: Subst) -> Optional[Subst]:
    if isinstance(term, _GroundTerm):
        return subst if term.value == value else None
    name = term.name
    if name in subst:
        return subst if subst[name] == value else None
    return {**subst, name: value}


# ── rule-head matching ────────────────────────────────────────────────────────


def _match_head(
    head_terms: Tuple[_Term, ...],
    goal_args: Tuple[_Term, ...],
    query_subst: Subst,
) -> Optional[Tuple[Subst, Subst, List[Tuple[str, str]]]]:
    new_q: Subst = dict(query_subst)
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

        else:  # h_term is _VarTerm (prefixed rule var)
            if g_val is not None:
                if h_term.name in r_subst and r_subst[h_term.name] != g_val:
                    return None
                r_subst[h_term.name] = g_val
            else:
                if isinstance(g_term, _VarTerm):
                    links.append((g_term.name, h_term.name))

    return new_q, r_subst, links


# ── arithmetic helpers ────────────────────────────────────────────────────────


def _numeric(val: Any) -> Optional[float]:
    """Extract a float from a Python value; returns None for non-numeric types."""
    if isinstance(val, bool):
        return None  # bool subclasses int but is not numeric here
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _to_number(v: float) -> Union[int, float]:
    """Return int when the float value is whole, otherwise float."""
    if abs(v - round(v)) <= 1e-9:
        return int(round(v))
    return v


def _arith_forward(op: Builtin, a: float, b: float) -> Optional[float]:
    """Compute a op b = c."""
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
    """Solve a op b = c for a."""
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
    """Solve a op b = c for b."""
    if op == Builtin.add:
        return c - a
    if op == Builtin.sub:
        return a - c
    if op == Builtin.mul:
        return None if abs(a) <= 1e-12 else c / a
    if op == Builtin.div:
        return None if abs(c) <= 1e-12 else a / c
    return None


# ── core solver ───────────────────────────────────────────────────────────────


def _solve(
    goals: List[_Goal],
    subst: Subst,
    fact_index: Dict[Tuple[str, int], List[BeliefRecord]],
    rules: List[Rule],
    asof: Optional[datetime],
    policy: str,
    depth: int,
    max_depth: int,
    collector: Optional[ExplainCollector] = None,
    for_negation_probe: bool = False,
) -> Iterator[Subst]:
    """Recursively solve *goals* under *subst*.

    Yields every substitution that satisfies the goal list.
    """
    if not goals:
        yield subst
        return

    if depth > max_depth:
        if collector and not for_negation_probe and goals:
            goal = goals[0]
            if isinstance(goal, _Atom):
                collector.record(
                    "rule_depth_limit",
                    {
                        "goal": {"pred": goal.pred, "args": [_term_repr(a) for a in goal.args]},
                        "depth": depth,
                        "max_depth": max_depth,
                    },
                )
        return

    goal, *rest = goals
    rest_goals: List[_Goal] = rest  # type: ignore[assignment]

    # ── builtin goal ──────────────────────────────────────────────────────────
    if isinstance(goal, _Builtin):
        # eq: can bind an unbound variable to the other side's value
        if goal.op == Builtin.eq:
            a_term, b_term = goal.args[0], goal.args[1]
            a_val = _resolve(a_term, subst)
            b_val = _resolve(b_term, subst)

            if a_val is not None and b_val is not None:
                # Both ground – filter
                if a_val == b_val:
                    yield from _solve(
                        rest_goals,
                        subst,
                        fact_index,
                        rules,
                        asof,
                        policy,
                        depth,
                        max_depth,
                        collector,
                        for_negation_probe,
                    )
            elif a_val is None and isinstance(a_term, _VarTerm) and b_val is not None:
                # Bind left variable
                new_subst = _unify(a_term, b_val, subst)
                if new_subst is not None:
                    yield from _solve(
                        rest_goals,
                        new_subst,
                        fact_index,
                        rules,
                        asof,
                        policy,
                        depth,
                        max_depth,
                        collector,
                        for_negation_probe,
                    )
            elif b_val is None and isinstance(b_term, _VarTerm) and a_val is not None:
                # Bind right variable
                new_subst = _unify(b_term, a_val, subst)
                if new_subst is not None:
                    yield from _solve(
                        rest_goals,
                        new_subst,
                        fact_index,
                        rules,
                        asof,
                        policy,
                        depth,
                        max_depth,
                        collector,
                        for_negation_probe,
                    )
            elif (
                isinstance(a_term, _VarTerm)
                and isinstance(b_term, _VarTerm)
                and a_term.name == b_term.name
            ):
                # Same variable – trivially equal
                yield from _solve(
                    rest_goals, subst, fact_index, rules, asof, policy, depth, max_depth,
                    collector, for_negation_probe,
                )
            # else: two distinct unbound variables – no solution
            return

        # add / sub / mul / div: 3-arg arithmetic, solves for one unknown
        if goal.op in (Builtin.add, Builtin.sub, Builtin.mul, Builtin.div):
            a_term, b_term, c_term = goal.args[0], goal.args[1], goal.args[2]
            a_val = _resolve(a_term, subst)
            b_val = _resolve(b_term, subst)
            c_val = _resolve(c_term, subst)
            na = _numeric(a_val)
            nb = _numeric(b_val)
            nc = _numeric(c_val)

            unbound = sum(1 for n in (na, nb, nc) if n is None)
            if unbound == 0:
                # All ground – check
                result = _arith_forward(goal.op, na, nb)  # type: ignore[arg-type]
                if result is not None and abs(result - nc) <= 1e-9:  # type: ignore[operator]
                    yield from _solve(
                        rest_goals,
                        subst,
                        fact_index,
                        rules,
                        asof,
                        policy,
                        depth,
                        max_depth,
                        collector,
                        for_negation_probe,
                    )
            elif unbound == 1:
                if nc is None and isinstance(c_term, _VarTerm):
                    r = _arith_forward(goal.op, na, nb)  # type: ignore[arg-type]
                    if r is not None:
                        new_s = _unify(c_term, _to_number(r), subst)
                        if new_s is not None:
                            yield from _solve(
                                rest_goals,
                                new_s,
                                fact_index,
                                rules,
                                asof,
                                policy,
                                depth,
                                max_depth,
                                collector,
                                for_negation_probe,
                            )
                elif na is None and isinstance(a_term, _VarTerm):
                    r = _arith_solve_a(goal.op, nb, nc)  # type: ignore[arg-type]
                    if r is not None:
                        new_s = _unify(a_term, _to_number(r), subst)
                        if new_s is not None:
                            yield from _solve(
                                rest_goals,
                                new_s,
                                fact_index,
                                rules,
                                asof,
                                policy,
                                depth,
                                max_depth,
                                collector,
                                for_negation_probe,
                            )
                elif nb is None and isinstance(b_term, _VarTerm):
                    r = _arith_solve_b(goal.op, na, nc)  # type: ignore[arg-type]
                    if r is not None:
                        new_s = _unify(b_term, _to_number(r), subst)
                        if new_s is not None:
                            yield from _solve(
                                rest_goals,
                                new_s,
                                fact_index,
                                rules,
                                asof,
                                policy,
                                depth,
                                max_depth,
                                collector,
                                for_negation_probe,
                            )
            # else: 2+ unknowns – no solution
            return

        # between(X, Lo, Hi): Lo <= X <= Hi, all three must be numeric
        if goal.op == Builtin.between:
            x_val = _resolve(goal.args[0], subst)
            lo_val = _resolve(goal.args[1], subst)
            hi_val = _resolve(goal.args[2], subst)
            nx = _numeric(x_val)
            nlo = _numeric(lo_val)
            nhi = _numeric(hi_val)
            if (
                nx is not None
                and nlo is not None
                and nhi is not None
                and nlo <= nx <= nhi
            ):
                yield from _solve(
                    rest_goals, subst, fact_index, rules, asof, policy, depth, max_depth,
                    collector, for_negation_probe,
                )
            return

        # ne / lt / leq / gt / geq: filter only (both args must be ground)
        a_val = _resolve(goal.args[0], subst)
        b_val = _resolve(goal.args[1], subst)
        if a_val is None or b_val is None:
            return
        op_fn = _CMP_OPS[goal.op]
        try:
            if op_fn(a_val, b_val):
                yield from _solve(
                    rest_goals, subst, fact_index, rules, asof, policy, depth, max_depth,
                    collector, for_negation_probe,
                )
        except TypeError:
            pass
        return

    # ── negation as failure ───────────────────────────────────────────────────
    assert isinstance(goal, _Atom)

    if goal.negated:
        positive = _Atom(pred=goal.pred, negated=False, args=goal.args)
        has_any = any(
            True
            for _ in _solve(
                [positive], subst, fact_index, rules, asof, policy, depth + 1, max_depth,
                collector, for_negation_probe=True,
            )
        )
        if not has_any:
            if collector and not for_negation_probe:
                collector.record(
                    "negation_success",
                    {
                        "goal": {
                            "pred": goal.pred,
                            "args": [_term_repr(a) for a in goal.args],
                            "negated": True,
                        },
                        "binding": {k: v for k, v in subst.items()},
                    },
                )
            yield from _solve(
                rest_goals, subst, fact_index, rules, asof, policy, depth, max_depth,
                collector, for_negation_probe,
            )
        return

    # ── positive atom – try facts ─────────────────────────────────────────────
    for record in fact_index.get((goal.pred, len(goal.args)), ()):
        if not _is_active(record, asof, policy):
            continue

        new_subst: Optional[Subst] = subst
        for g_term, f_arg in zip(goal.args, record.args):
            f_val: Any
            if isinstance(f_arg, BeliefEntityArg):
                f_val = f_arg.ent_name
            else:  # BeliefLiteralArg
                f_val = f_arg.value  # type: ignore[union-attr]

            new_subst = _unify(g_term, f_val, new_subst)  # type: ignore[arg-type]
            if new_subst is None:
                break

        if new_subst is not None:
            if collector and not for_negation_probe:
                collector.record(
                    "atom_match",
                    {
                        "goal": {
                            "pred": goal.pred,
                            "args": [_term_repr(a) for a in goal.args],
                            "negated": False,
                        },
                        "fact": [_belief_arg_repr(a) for a in record.args],
                    },
                )
            yield from _solve(
                rest_goals, new_subst, fact_index, rules, asof, policy, depth, max_depth,
                collector, for_negation_probe,
            )

    # ── positive atom – try rules ─────────────────────────────────────────────
    prefix = f"_r{depth}_"
    for rule in rules:
        if rule.head_pred_name != goal.pred or rule.head_pred_arity != len(goal.args):
            continue

        head_terms = _rule_head_terms(rule, prefix)
        match = _match_head(head_terms, goal.args, subst)
        if match is None:
            continue

        new_q_subst, initial_r_subst, links = match
        body_goals = _rule_body_goals(rule, prefix)

        for body_subst in _solve(
            body_goals,
            initial_r_subst,
            fact_index,
            rules,
            asof,
            policy,
            depth + 1,
            max_depth,
            collector,
            for_negation_probe,
        ):
            result_subst: Subst = dict(new_q_subst)
            conflict = False
            for q_var, r_var in links:
                if r_var in body_subst:
                    val = body_subst[r_var]
                    if q_var in result_subst and result_subst[q_var] != val:
                        conflict = True
                        break
                    result_subst[q_var] = val
            if conflict:
                continue

            if collector and not for_negation_probe:
                collector.record(
                    "rule_match",
                    {
                        "goal": {
                            "pred": goal.pred,
                            "args": [_term_repr(a) for a in goal.args],
                            "negated": False,
                        },
                        "rule": rule.head_pred_name,
                    },
                )
            yield from _solve(
                rest_goals,
                result_subst,
                fact_index,
                rules,
                asof,
                policy,
                depth,
                max_depth,
                collector,
                for_negation_probe,
            )


# ── post-processing helpers ───────────────────────────────────────────────────


def _apply_distinct(bindings: List[Binding]) -> List[Binding]:
    seen: Set[Tuple[Tuple[str, Any], ...]] = set()
    out: List[Binding] = []
    for b in bindings:
        key = tuple(sorted(b.values.items(), key=lambda kv: kv[0]))
        if key not in seen:
            seen.add(key)
            out.append(b)
    return out


def _apply_order_by(bindings: List[Binding], order_by: List[str]) -> List[Binding]:
    if not order_by:
        return bindings

    def _sort_key(b: Binding) -> Tuple[Any, ...]:
        parts = []
        for k in order_by:
            v = b.values.get(k)
            if v is None:
                parts.append((1, "", ""))
            else:
                parts.append((0, type(v).__name__, v))
        return tuple(parts)

    return sorted(bindings, key=_sort_key)


# ── public engine ─────────────────────────────────────────────────────────────


def _query_var_names(query: Query) -> Set[str]:
    names: Set[str] = set()
    for goal in query.goals:
        args = getattr(goal, "goal_args", [])
        for arg in args:
            if isinstance(arg, VarArg):
                names.add(arg.var.name)
    return names - query.anon_vars


class InMemoryQueryEngine(QueryEngine):
    """Pure-Python top-down Datalog evaluation over an in-memory Branch.

    Query options (set via ``QueryOptions`` on the Query object):

    policy : "report" (default) | "credulous" | "skeptical"
        report    → no belief-score filter
        credulous → b > d
        skeptical → b > d
    asof : ISO-8601 string or datetime
        Restrict to facts whose validity window [vf, vt] contains asof.
    limit : int
        Return at most this many bindings (after ordering).
    offset : int
        Skip this many bindings before applying limit.
    order_by : str or list[str]
        Sort results by these variable names.
    distinct : bool
        Deduplicate identical binding rows.
    max_depth : int
        Hard cap on recursive rule-application depth (default 24).
    """

    def evaluate(self, branch: Branch, query: Query) -> QueryResult:
        opts = query.options
        policy: str = opts.policy
        asof: Optional[datetime] = opts.asof

        # Build index and internal goals once per query
        fact_index = _build_fact_index(branch.belief_records)
        internal_goals = _query_goals(query)
        query_vars = _query_var_names(query)

        # ── Skolemize bridging variables ──────────────────────────────────────
        # A variable is skolemized when it appears in:
        #   1. A non-negated EDB assumption-candidate goal (EDB pred, ≥1 ground arg)
        #   2. At least one IDB goal (predicate has rules)
        # This allows hypothetical facts to be connected through rule derivations.
        idb_preds: Set[str] = {r.head_pred_name for r in branch.rules}

        vars_in_edb_assumptions: Set[str] = set()
        for goal in internal_goals:
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
        for goal in internal_goals:
            if isinstance(goal, _Atom) and goal.pred in idb_preds:
                for a in goal.args:
                    if isinstance(a, _VarTerm):
                        vars_in_idb_goals.add(a.name)

        skolem_map: Dict[str, str] = {
            v: f"_hyp_{v}" for v in vars_in_edb_assumptions & vars_in_idb_goals
        }

        if skolem_map:
            new_goals: List[_Goal] = []
            for goal in internal_goals:
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
                elif isinstance(goal, _Builtin):
                    new_args = tuple(
                        _GroundTerm(skolem_map[a.name])
                        if isinstance(a, _VarTerm) and a.name in skolem_map
                        else a
                        for a in goal.args
                    )
                    new_goals.append(_Builtin(op=goal.op, args=new_args))
                else:
                    new_goals.append(goal)
            internal_goals = new_goals

        # ── Inline assumptions: fully-ground positive EDB atom goals become temp facts ─
        # Only EDB predicates (no rules) are eligible.  IDB predicates must be
        # proved through rule evaluation, not injected as self-fulfilling facts.
        inline_assumptions: List[BeliefRecord] = []
        for goal in internal_goals:
            if (
                isinstance(goal, _Atom)
                and not goal.negated
                and goal.pred not in idb_preds
            ):
                if all(isinstance(arg, _GroundTerm) for arg in goal.args):
                    from doxa.core.base_kinds import BaseKind

                    belief_args = []
                    for arg in goal.args:
                        assert isinstance(arg, _GroundTerm)
                        val = arg.value
                        if isinstance(val, bool):
                            belief_args.append(
                                BeliefLiteralArg(
                                    kind=BaseKind.belief_arg,
                                    term_kind="lit",
                                    lit_type="bool",
                                    value=val,
                                )
                            )
                        elif isinstance(val, int):
                            belief_args.append(
                                BeliefLiteralArg(
                                    kind=BaseKind.belief_arg,
                                    term_kind="lit",
                                    lit_type="int",
                                    value=val,
                                )
                            )
                        elif isinstance(val, float):
                            belief_args.append(
                                BeliefLiteralArg(
                                    kind=BaseKind.belief_arg,
                                    term_kind="lit",
                                    lit_type="float",
                                    value=val,
                                )
                            )
                        else:
                            # str values: treat as entity references
                            belief_args.append(
                                BeliefEntityArg(
                                    kind=BaseKind.belief_arg,
                                    term_kind="ent",
                                    ent_name=str(val),
                                )
                            )

                    inline_assumptions.append(
                        BeliefRecord(
                            kind=BaseKind.belief_record,
                            created_at=datetime.now(timezone.utc),
                            pred_name=goal.pred,
                            pred_arity=len(goal.args),
                            args=belief_args,
                            b=1.0,
                            d=0.0,
                        )
                    )

        if inline_assumptions:
            fact_index = _build_fact_index(branch.belief_records + inline_assumptions)

        # Seed substitution with Skolem bindings so they appear in results
        initial_subst: Subst = {var: skolem for var, skolem in skolem_map.items()}

        # ── Solve ─────────────────────────────────────────────────────────────
        collector = ExplainCollector(enabled=(opts.explain != "false"))
        all_bindings: List[Binding] = []
        for subst in _solve(
            internal_goals,
            initial_subst,
            fact_index,
            branch.rules,
            asof,
            policy,
            depth=0,
            max_depth=opts.max_depth,
            collector=collector,
        ):
            binding = Binding(
                values={k: v for k, v in subst.items() if k in query_vars}
            )
            all_bindings.append(binding)

        # ── Post-processing ────────────────────────────────────────────────────
        bindings = all_bindings

        if opts.distinct:
            bindings = _apply_distinct(bindings)

        if opts.order_by:
            bindings = _apply_order_by(bindings, opts.order_by)

        if opts.offset:
            bindings = bindings[opts.offset :]

        if opts.limit is not None:
            bindings = bindings[: opts.limit]

        explain = collector.events if opts.explain != "false" else None
        return QueryResult(bindings=bindings, explain=explain)
