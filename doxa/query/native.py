"""Native Rust-backed query engine using doxa-native (fixpoint evaluator)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from doxa.core._parsing.parsing_utils import (
    parse_date_literal,
    parse_datetime_literal,
    parse_duration_literal,
)
from doxa.core.belief_record import (
    BeliefEntityArg,
    BeliefLiteralArg,
    BeliefPredRefArg,
)
from doxa.core.branch import Branch
from doxa.core.builtins import Builtin
from doxa.core.epistemic_semantics import (
    BelnapStatus,
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
from doxa.core.goal import (
    AssumeGoal,
    AtomGoal,
    BuiltinGoal,
    EntityArg,
    LiteralArg,
    PredRefArg,
    VarArg,
)
from doxa.core.query import Query
from doxa.core.rule import (
    RuleAtomGoal,
    RuleBuiltinGoal,
    RuleGoalEntityArg,
    RuleGoalLiteralArg,
    RuleGoalPredRefArg,
    RuleGoalVarArg,
    RuleHeadEntityArg,
    RuleHeadLiteralArg,
    RuleHeadPredRefArg,
    RuleHeadVarArg,
)
from doxa.query.engine import (
    EngineInfo,
    QueryAnswer,
    QueryEngine,
    QueryResult,
)

try:
    from doxa import _native as doxa_native
except ImportError:
    doxa_native = None  # type: ignore[assignment]


def _require_native() -> None:
    if doxa_native is None:
        raise ImportError(
            "doxa._native is not available. "
            "Install a wheel with `pip install doxa`, or build from source with "
            "`maturin develop --release` (requires Rust toolchain)."
        )


# ── Belnap status mapping ────────────────────────────────────────────

_BELNAP_MAP: Dict[str, BelnapStatus] = {
    "True": BelnapStatus.true,
    "False": BelnapStatus.false,
    "Both": BelnapStatus.both,
    "Neither": BelnapStatus.neither,
    "Unknown": BelnapStatus.neither,
}


def _parse_belnap(s: str) -> BelnapStatus:
    return _BELNAP_MAP.get(s, BelnapStatus.neither)


_DATE_LIT_RE = re.compile(r'^d"(.+)"$')
_DATETIME_LIT_RE = re.compile(r'^dt"(.+)"$')
_DURATION_LIT_RE = re.compile(r'^dur"(.+)"$')


def _clean_resolved(text: str) -> Any:
    """Convert a resolved symbol text back to its natural Python type.

    String literals are stored with surrounding double-quotes;
    integer and float literals are stored as their text representation.
    Temporal literals (d"...", dt"...", dur"...") are parsed to Python types.
    Entity names are returned as-is (str).
    """
    # String literal: "hello world" → hello world
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    # Date literal: d"2024-06-15"
    if (
        text.startswith('d"')
        and not text.startswith('dt"')
        and not text.startswith('dur"')
    ):
        try:
            return parse_date_literal(text)
        except (ValueError, TypeError):
            pass
    # Datetime literal: dt"2024-06-15T10:30:00Z"
    if text.startswith('dt"'):
        try:
            return parse_datetime_literal(text)
        except (ValueError, TypeError):
            pass
    # Duration literal: dur"P30D"
    if text.startswith('dur"'):
        try:
            return parse_duration_literal(text)
        except (ValueError, TypeError):
            pass
    # Integer literal
    try:
        return int(text)
    except ValueError:
        pass
    # Float literal
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _belnap_from_bd(b: float, d: float) -> BelnapStatus:
    """Derive BelnapStatus from (b, d) using nonzero semantics."""
    has_b = b > 1e-12
    has_d = d > 1e-12
    if has_b and has_d:
        return BelnapStatus.both
    if has_b:
        return BelnapStatus.true
    if has_d:
        return BelnapStatus.false
    return BelnapStatus.neither


# ── NativeQueryEngine ─────────────────────────────────────────────────


class NativeQueryEngine(QueryEngine):
    """Query engine backed by the doxa-native Rust fixpoint evaluator.

    Each ``_evaluate`` call creates a fresh temporary store, loads the
    branch data, materializes derived facts, and answers the query goals.
    This is the simplest correct approach; caching / incremental
    materialization can be added later.

    Usage::

        engine = NativeQueryEngine()
        result = engine.evaluate(branch, query)
    """

    def __init__(self) -> None:
        _require_native()

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name="native",
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

    # ------------------------------------------------------------------
    # Term / goal conversion helpers
    # ------------------------------------------------------------------

    def _intern_goal_arg(self, store, arg) -> object:
        """Convert a query GoalArg to a Rust term (str for Var, int for ground)."""
        if isinstance(arg, VarArg):
            return arg.var.name  # str starting with uppercase → Var
        elif isinstance(arg, EntityArg):
            return store.intern(arg.ent_name)
        elif isinstance(arg, LiteralArg):
            return store.intern(arg.to_doxa())
        elif isinstance(arg, PredRefArg):
            return store.intern(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        else:
            raise TypeError(f"Unknown goal arg type: {type(arg)}")

    def _intern_belief_arg(self, store, arg) -> int:
        """Intern a BeliefArg and return its SymId."""
        if isinstance(arg, BeliefEntityArg):
            return store.intern(arg.ent_name)
        elif isinstance(arg, BeliefLiteralArg):
            return store.intern(arg.to_doxa())
        elif isinstance(arg, BeliefPredRefArg):
            return store.intern(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        else:
            raise TypeError(f"Unknown belief arg type: {type(arg)}")

    def _head_arg_to_term(self, store, arg) -> object:
        """Convert a RuleHeadArg to a term for the Rust side."""
        if isinstance(arg, RuleHeadVarArg):
            return arg.var.name
        elif isinstance(arg, RuleHeadEntityArg):
            return store.intern(arg.ent_name)
        elif isinstance(arg, RuleHeadLiteralArg):
            return store.intern(arg.to_doxa())
        elif isinstance(arg, RuleHeadPredRefArg):
            return store.intern(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        else:
            raise TypeError(f"Unknown head arg type: {type(arg)}")

    def _rule_goal_arg_to_term(self, store, arg) -> object:
        """Convert a RuleGoalArg to a term for the Rust side."""
        if isinstance(arg, RuleGoalVarArg):
            return arg.var.name
        elif isinstance(arg, RuleGoalEntityArg):
            return store.intern(arg.ent_name)
        elif isinstance(arg, RuleGoalLiteralArg):
            return store.intern(arg.to_doxa())
        elif isinstance(arg, RuleGoalPredRefArg):
            return store.intern(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        else:
            raise TypeError(f"Unknown rule goal arg type: {type(arg)}")

    def _rule_goal_to_dict(self, store, goal) -> dict:
        """Convert a Python RuleGoal to a dict for the Rust side."""
        if isinstance(goal, RuleAtomGoal):
            return {
                "pred_name": goal.pred_name,
                "pred_arity": goal.pred_arity,
                "negated": goal.negated,
                "args": [self._rule_goal_arg_to_term(store, a) for a in goal.goal_args],
            }
        elif isinstance(goal, RuleBuiltinGoal):
            return {
                "builtin_name": goal.builtin_name.value,
                "args": [self._rule_goal_arg_to_term(store, a) for a in goal.goal_args],
            }
        else:
            raise TypeError(f"Unknown goal type: {type(goal)}")

    # ------------------------------------------------------------------
    # Branch loading
    # ------------------------------------------------------------------

    def _load_branch(self, store, branch: Branch) -> None:
        """Load all branch data into a native store."""
        branch_name = branch.name

        # ── Bulk-intern all symbol texts first ────────────────────────
        texts_to_intern: list[str] = []
        text_index: dict[str, int] = {}  # text → position in texts_to_intern

        def _collect_text(text: str) -> int:
            """Register a text for bulk interning, return its index."""
            if text in text_index:
                return text_index[text]
            idx = len(texts_to_intern)
            text_index[text] = idx
            texts_to_intern.append(text)
            return idx

        def _collect_belief_arg(arg) -> int:
            if isinstance(arg, BeliefEntityArg):
                return _collect_text(arg.ent_name)
            elif isinstance(arg, BeliefLiteralArg):
                return _collect_text(arg.to_doxa())
            elif isinstance(arg, BeliefPredRefArg):
                return _collect_text(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
            else:
                raise TypeError(f"Unknown belief arg type: {type(arg)}")

        def _collect_goal_arg(arg) -> object:
            if isinstance(arg, VarArg):
                return arg.var.name  # variable, not interned
            elif isinstance(arg, EntityArg):
                return ("sym", _collect_text(arg.ent_name))
            elif isinstance(arg, LiteralArg):
                return ("sym", _collect_text(arg.to_doxa()))
            elif isinstance(arg, PredRefArg):
                return (
                    "sym",
                    _collect_text(f"{arg.pred_ref_name}/{arg.pred_ref_arity}"),
                )
            else:
                raise TypeError(f"Unknown goal arg type: {type(arg)}")

        def _collect_head_arg(arg) -> object:
            if isinstance(arg, RuleHeadVarArg):
                return arg.var.name
            elif isinstance(arg, RuleHeadEntityArg):
                return ("sym", _collect_text(arg.ent_name))
            elif isinstance(arg, RuleHeadLiteralArg):
                return ("sym", _collect_text(arg.to_doxa()))
            elif isinstance(arg, RuleHeadPredRefArg):
                return (
                    "sym",
                    _collect_text(f"{arg.pred_ref_name}/{arg.pred_ref_arity}"),
                )
            else:
                raise TypeError(f"Unknown head arg type: {type(arg)}")

        def _collect_rule_goal_arg(arg) -> object:
            if isinstance(arg, RuleGoalVarArg):
                return arg.var.name
            elif isinstance(arg, RuleGoalEntityArg):
                return ("sym", _collect_text(arg.ent_name))
            elif isinstance(arg, RuleGoalLiteralArg):
                return ("sym", _collect_text(arg.to_doxa()))
            elif isinstance(arg, RuleGoalPredRefArg):
                return (
                    "sym",
                    _collect_text(f"{arg.pred_ref_name}/{arg.pred_ref_arity}"),
                )
            else:
                raise TypeError(f"Unknown rule goal arg type: {type(arg)}")

        # Pre-collect all texts from belief records
        fact_specs = []
        for record in branch.belief_records:
            arg_indices = [_collect_belief_arg(a) for a in record.args]
            fact_specs.append(
                (
                    record.pred_name,
                    record.pred_arity,
                    arg_indices,
                    record.b,
                    record.d,
                    record.src,
                )
            )

        # Pre-collect texts from rules
        rule_specs = []
        for i, rule in enumerate(branch.rules):
            head_args_raw = [_collect_head_arg(a) for a in rule.head_args]
            body_raw = []
            for goal in rule.goals:
                if isinstance(goal, RuleBuiltinGoal):
                    body_raw.append(
                        {
                            "builtin_name": goal.builtin_name.value,
                            "args_raw": [
                                _collect_rule_goal_arg(a) for a in goal.goal_args
                            ],
                        }
                    )
                elif isinstance(goal, RuleAtomGoal):
                    body_raw.append(
                        {
                            "pred_name": goal.pred_name,
                            "pred_arity": goal.pred_arity,
                            "negated": goal.negated,
                            "args_raw": [
                                _collect_rule_goal_arg(a) for a in goal.goal_args
                            ],
                        }
                    )
            rule_specs.append((i, rule, head_args_raw, body_raw))

        # Pre-collect texts from ground constraints
        constraint_facts = []
        for constraint in branch.constraints:
            all_ground = True
            for goal in constraint.goals:
                if not isinstance(goal, AtomGoal):
                    all_ground = False
                    break
                if any(isinstance(a, VarArg) for a in goal.goal_args):
                    all_ground = False
                    break
            if not all_ground:
                continue
            for goal in constraint.goals:
                if not goal.negated:
                    arg_indices = [_collect_goal_arg(a) for a in goal.goal_args]
                    constraint_facts.append(
                        (
                            goal.pred_name,
                            goal.pred_arity,
                            arg_indices,
                            0.0,
                            constraint.b,
                            constraint.src,
                        )
                    )

        # ── Single bulk intern call ───────────────────────────────────
        sym_ids = store.intern_batch(texts_to_intern) if texts_to_intern else []

        def _resolve_arg(raw):
            """Convert a pre-collected arg to its final form (SymId or str)."""
            if isinstance(raw, str):
                return raw  # variable name
            # ("sym", idx)
            return sym_ids[raw[1]]

        # ── Bulk assert facts ─────────────────────────────────────────
        bulk_facts = []
        for pred_name, pred_arity, arg_indices, b, d, src in fact_specs:
            args = [sym_ids[idx] for idx in arg_indices]
            bulk_facts.append((pred_name, pred_arity, args, b, d, src))
        # Also add constraint disbelief facts
        for pred_name, pred_arity, arg_raws, b, d, src in constraint_facts:
            args = [_resolve_arg(r) for r in arg_raws]
            bulk_facts.append((pred_name, pred_arity, args, b, d, src))

        if bulk_facts:
            store.assert_facts_bulk(branch_name, bulk_facts)

        # ── Add rules (still one-by-one due to complex structure) ─────
        for i, rule, head_args_raw, body_raw in rule_specs:
            head_args = [_resolve_arg(a) for a in head_args_raw]
            body = []
            for g in body_raw:
                if "builtin_name" in g:
                    body.append(
                        {
                            "builtin_name": g["builtin_name"],
                            "args": [_resolve_arg(a) for a in g["args_raw"]],
                        }
                    )
                else:
                    body.append(
                        {
                            "pred_name": g["pred_name"],
                            "pred_arity": g["pred_arity"],
                            "negated": g["negated"],
                            "args": [_resolve_arg(a) for a in g["args_raw"]],
                        }
                    )
            store.add_rule(
                branch_name,
                i,
                rule.head_pred_name,
                rule.head_pred_arity,
                head_args,
                body,
                rule.b,
                rule.d,
            )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _scan_goal(
        self,
        store,
        goal: AtomGoal,
        env: Dict[str, str],
    ) -> List[Tuple[Dict[str, str], float, float]]:
        """Scan a single atom goal against the store, extending *env*.

        Returns a list of ``(new_env, b, d)`` tuples for every matching
        atom.  Variables already bound in *env* are treated as ground
        constraints; free variables are bound to the resolved symbol text.
        Negated goals invert the match: if any atom matches, the goal
        fails; if none match, the goal succeeds with b=1, d=0.
        """
        # Use bulk API: returns list of (args, b, d) tuples
        raw_answers = store.query_predicate_bulk(goal.pred_name)

        # Build per-position constraint: either a bound value (str) from
        # env / ground arg, or None (free variable to bind).
        constraints: List[Tuple[Optional[str], Optional[str]]] = []
        #   (expected_value_or_None, var_name_or_None)
        for arg in goal.goal_args:
            if isinstance(arg, VarArg):
                var_name = arg.var.name
                if var_name in env:
                    # already bound → ground constraint
                    constraints.append((env[var_name], None))
                else:
                    constraints.append((None, var_name))
            else:
                # Ground arg — intern, resolve, compare as text
                gid = self._intern_goal_arg(store, arg)
                gtxt = _clean_resolved(store.resolve(gid) or str(gid))
                constraints.append((gtxt, None))

        # Collect all sym_ids that need resolving across all rows
        all_sym_ids: list[int] = []
        row_ranges: list[tuple[int, int]] = []  # (start, end) into all_sym_ids
        for raw_args, _b, _d in raw_answers:
            start = len(all_sym_ids)
            all_sym_ids.extend(raw_args)
            row_ranges.append((start, len(all_sym_ids)))

        # Single bulk resolve call
        all_resolved: list[str] = []
        if all_sym_ids:
            raw_texts = store.resolve_batch(all_sym_ids)
            all_resolved = [
                _clean_resolved(t if t is not None else str(sid))
                for t, sid in zip(raw_texts, all_sym_ids)
            ]

        if goal.negated:
            # NAF: succeed with (env, 1, 0) iff no atom matches
            for (raw_args, _b, _d), (rs, re) in zip(raw_answers, row_ranges):
                if self._row_matches_resolved(all_resolved[rs:re], constraints):
                    return []  # at least one match → negation fails
            return [(dict(env), 1.0, 0.0)]

        results: List[Tuple[Dict[str, str], float, float]] = []
        for (raw_args, b, d), (rs, re) in zip(raw_answers, row_ranges):
            resolved_row = all_resolved[rs:re]
            if len(resolved_row) != len(constraints):
                continue
            new_env = dict(env)
            match = True
            for (expected, var_name), resolved in zip(constraints, resolved_row):
                if expected is not None:
                    if resolved != expected:
                        match = False
                        break
                elif var_name is not None:
                    new_env[var_name] = resolved
            if match:
                results.append((new_env, b, d))
        return results

    def _eval_builtin_goal(
        self,
        goal: BuiltinGoal,
        env: Dict[str, Any],
    ) -> List[Tuple[Dict[str, Any], float, float]]:
        """Evaluate a builtin goal against the current environment."""
        args = goal.goal_args
        name = goal.builtin_name

        def _resolve(arg):
            if isinstance(arg, VarArg):
                return env.get(arg.var.name)
            elif isinstance(arg, LiteralArg):
                return arg.value
            elif isinstance(arg, EntityArg):
                return arg.ent_name
            return None

        def _var_name(arg):
            return arg.var.name if isinstance(arg, VarArg) else None

        # ── eq: equality check or variable binding ────────────────────
        if name == Builtin.eq:
            a, b = _resolve(args[0]), _resolve(args[1])
            av, bv = _var_name(args[0]), _var_name(args[1])
            if a is not None and b is not None:
                return [(dict(env), 1.0, 0.0)] if a == b else []
            if a is not None and bv and bv not in env:
                new = dict(env)
                new[bv] = a
                return [(new, 1.0, 0.0)]
            if b is not None and av and av not in env:
                new = dict(env)
                new[av] = b
                return [(new, 1.0, 0.0)]
            return []

        # ── ne: inequality ────────────────────────────────────────────
        if name == Builtin.ne:
            a, b = _resolve(args[0]), _resolve(args[1])
            if a is not None and b is not None:
                return [(dict(env), 1.0, 0.0)] if a != b else []
            return []

        # ── comparisons: lt, leq, gt, geq ────────────────────────────
        if name in (Builtin.lt, Builtin.leq, Builtin.gt, Builtin.geq):
            a, b = _resolve(args[0]), _resolve(args[1])
            if a is None or b is None:
                return []
            try:
                if name == Builtin.lt:
                    ok = a < b
                elif name == Builtin.leq:
                    ok = a <= b
                elif name == Builtin.gt:
                    ok = a > b
                else:
                    ok = a >= b
                return [(dict(env), 1.0, 0.0)] if ok else []
            except TypeError:
                return []

        # ── arithmetic: add, sub, mul, div ────────────────────────────
        if name in (Builtin.add, Builtin.sub, Builtin.mul, Builtin.div):
            vals = [_resolve(a) for a in args]
            var_names = [_var_name(a) for a in args]
            bound = [(i, v) for i, v in enumerate(vals) if v is not None]
            unbound = [
                (i, vn)
                for i, (v, vn) in enumerate(zip(vals, var_names))
                if v is None and vn and vn not in env
            ]

            if len(bound) == 3:
                a, b, c = vals
                try:
                    if name == Builtin.add:
                        ok = a + b == c
                    elif name == Builtin.sub:
                        ok = a - b == c
                    elif name == Builtin.mul:
                        ok = a * b == c
                    else:
                        ok = b != 0 and a / b == c
                    return [(dict(env), 1.0, 0.0)] if ok else []
                except TypeError:
                    return []

            if len(bound) == 2 and len(unbound) == 1:
                ui, uv = unbound[0]
                try:
                    if name == Builtin.add:
                        result = (
                            vals[0] + vals[1]
                            if ui == 2
                            else vals[2] - vals[1]
                            if ui == 0
                            else vals[2] - vals[0]
                        )
                    elif name == Builtin.sub:
                        result = (
                            vals[0] - vals[1]
                            if ui == 2
                            else vals[2] + vals[1]
                            if ui == 0
                            else vals[0] - vals[2]
                        )
                    elif name == Builtin.mul:
                        if ui == 2:
                            result = vals[0] * vals[1]
                        elif ui == 0:
                            result = vals[2] / vals[1] if vals[1] else None
                        else:
                            result = vals[2] / vals[0] if vals[0] else None
                    else:  # div
                        if ui == 2:
                            result = vals[0] / vals[1] if vals[1] else None
                        elif ui == 0:
                            result = vals[2] * vals[1]
                        else:
                            result = vals[0] / vals[2] if vals[2] else None

                    if result is None:
                        return []
                    # Coerce float results to int when exact
                    if isinstance(result, float) and result == int(result):
                        result = int(result)
                    new = dict(env)
                    new[uv] = result
                    return [(new, 1.0, 0.0)]
                except (TypeError, ZeroDivisionError):
                    return []
            return []

        # ── between ──────────────────────────────────────────────────
        if name == Builtin.between:
            x, lo, hi = _resolve(args[0]), _resolve(args[1]), _resolve(args[2])
            if x is None or lo is None or hi is None:
                return []
            try:
                return [(dict(env), 1.0, 0.0)] if lo <= x <= hi else []
            except TypeError:
                return []

        # ── type checks ──────────────────────────────────────────────
        if name == Builtin.int:
            v = _resolve(args[0])
            return (
                [(dict(env), 1.0, 0.0)]
                if isinstance(v, int) and not isinstance(v, bool)
                else []
            )
        if name == Builtin.float:
            v = _resolve(args[0])
            return (
                [(dict(env), 1.0, 0.0)]
                if isinstance(v, (int, float)) and not isinstance(v, bool)
                else []
            )
        if name == Builtin.string:
            v = _resolve(args[0])
            return [(dict(env), 1.0, 0.0)] if isinstance(v, str) else []
        if name == Builtin.date:
            v = _resolve(args[0])
            return (
                [(dict(env), 1.0, 0.0)]
                if isinstance(v, date) and not isinstance(v, datetime)
                else []
            )
        if name == Builtin.datetime:
            v = _resolve(args[0])
            return [(dict(env), 1.0, 0.0)] if isinstance(v, datetime) else []
        if name == Builtin.duration:
            v = _resolve(args[0])
            return [(dict(env), 1.0, 0.0)] if isinstance(v, timedelta) else []
        if name == Builtin.entity:
            v = _resolve(args[0])
            return [(dict(env), 1.0, 0.0)] if isinstance(v, str) else []
        if name == Builtin.predicate_ref:
            # predicate_ref args look like "name/arity"
            v = _resolve(args[0])
            return [(dict(env), 1.0, 0.0)] if isinstance(v, str) and "/" in v else []

        return []

    @staticmethod
    def _row_matches_resolved(resolved_row: list, constraints) -> bool:
        if len(resolved_row) != len(constraints):
            return False
        for (expected, _), resolved in zip(constraints, resolved_row):
            if expected is not None:
                if resolved != expected:
                    return False
        return True

    def _is_ground_single_goal(self, query: Query) -> bool:
        """Check if query is a single fully-ground goal (point lookup / filter)."""
        non_assume = [g for g in query.goals if not isinstance(g, AssumeGoal)]
        if len(non_assume) != 1:
            return False
        goal = non_assume[0]
        if isinstance(goal, AtomGoal):
            return all(not isinstance(a, VarArg) for a in goal.goal_args)
        if isinstance(goal, BuiltinGoal):
            return all(not isinstance(a, VarArg) for a in goal.goal_args)
        return False

    def _evaluate(self, branch: Branch, query: Query) -> QueryResult:
        effective_query_time = query.options.query_time or datetime.now(timezone.utc)
        effective_valid_at = query.options.valid_at or effective_query_time
        effective_known_at = query.options.known_at or effective_query_time

        # Create an in-memory store for this evaluation (no filesystem I/O)
        store = doxa_native.NativeStore.new_temporary()

        # Load branch data
        self._load_branch(store, branch)

        # ── Hypotheticals: process AssumeGoals before materialization ─
        remaining_goals = []
        for goal in query.goals:
            if isinstance(goal, AssumeGoal):
                for assumption in goal.assumptions:
                    args = [
                        self._intern_goal_arg(store, a) for a in assumption.goal_args
                    ]
                    store.assert_fact(
                        branch.name,
                        assumption.pred_name,
                        assumption.pred_arity,
                        args,
                        1.0,
                        0.0,
                        None,
                    )
            else:
                remaining_goals.append(goal)

        # ── Materialize (run fixpoint) with optional max_depth ────────
        max_depth = getattr(query.options, "max_depth", None)
        store.materialize(branch.name, max_depth)

        # ── Point-lookup for fully-ground single-goal queries ─────────
        is_ground = self._is_ground_single_goal(query)

        # ── Multi-goal join ───────────────────────────────────────────
        envs: List[Tuple[Dict[str, Any], float, float]] = [({}, 1.0, 0.0)]

        for goal in remaining_goals:
            if isinstance(goal, AtomGoal):
                next_envs: List[Tuple[Dict[str, Any], float, float]] = []
                for env, acc_b, acc_d in envs:
                    matches = self._scan_goal(store, goal, env)
                    for new_env, gb, gd in matches:
                        combined_b = acc_b * gb
                        combined_d = 1.0 - (1.0 - acc_d) * (1.0 - gd)
                        next_envs.append((new_env, combined_b, combined_d))
                envs = next_envs
            elif isinstance(goal, BuiltinGoal):
                next_envs = []
                for env, acc_b, acc_d in envs:
                    matches = self._eval_builtin_goal(goal, env)
                    for new_env, gb, gd in matches:
                        combined_b = acc_b * gb
                        combined_d = 1.0 - (1.0 - acc_d) * (1.0 - gd)
                        next_envs.append((new_env, combined_b, combined_d))
                envs = next_envs

        # ── Ground single-goal fallback: return b=0,d=0 when no match ──
        if is_ground and not envs:
            goal = remaining_goals[0]
            if isinstance(goal, AtomGoal):
                args = [self._intern_goal_arg(store, a) for a in goal.goal_args]
                state = store.get_atom_state(goal.pred_name, args)
                envs = [({}, state["b"], state["d"])]
            else:
                # Builtin goal failed — return neither
                envs = [({}, 0.0, 0.0)]

        # ── Build answer rows ─────────────────────────────────────────
        answers: List[QueryAnswer] = []
        seen: set[tuple] = set()

        for env, b, d in envs:
            status = _belnap_from_bd(b, d)

            if not _focus_matches(query.options.focus.value, b, d, status):
                continue

            # Filter anonymous vars from bindings, sort alphabetically
            filtered = dict(
                sorted((k, v) for k, v in env.items() if k not in query.anon_vars)
            )

            # Distinct: deduplicate by (bindings_tuple)
            key = tuple(sorted(filtered.items()))
            if key in seen:
                continue
            seen.add(key)

            answers.append(
                QueryAnswer(
                    bindings=filtered,
                    b=b,
                    d=d,
                    belnap_status=status,
                )
            )

        # ── Ordering ──────────────────────────────────────────────────
        if query.options.order_by:
            sort_keys = query.options.order_by
            answers.sort(key=lambda a: tuple(a.bindings.get(k, "") for k in sort_keys))

        # ── Limit / offset ───────────────────────────────────────────
        if query.options.offset:
            answers = answers[query.options.offset :]
        if query.options.limit is not None:
            answers = answers[: query.options.limit]

        return QueryResult(
            answers=tuple(answers),
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            epistemic_semantics=query.options.epistemic_semantics,
        )


# ── Focus filter ──────────────────────────────────────────────────────


def _focus_matches(focus: str, b: float, d: float, status: BelnapStatus) -> bool:
    """Return True if the answer matches the query focus filter."""
    if focus == "all":
        return True
    if focus == "support":
        return b > 1e-12
    if focus == "disbelief":
        return d > 1e-12
    if focus == "contradiction":
        return status == BelnapStatus.both
    if focus == "ignorance":
        return status == BelnapStatus.neither
    return True
