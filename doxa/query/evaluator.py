from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

from doxa.core.belief_record import (
    BeliefRecord,
)
from doxa.core.branch import Branch
from doxa.core.builtins import Builtin
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
from doxa.core.query import Query
from doxa.core.rule import Rule
from doxa.query._answers import (
    _aggregate_answers_from_truth,
    _inject_assume_facts,
    _query_var_names,
)
from doxa.query._compilation import _compile_query_goals
from doxa.query._solving import _solve_body_truth
from doxa.query._types import (
    ExplainCollector,
    _Context,
)
from doxa.query.engine import (
    BelnapStatus,
    EngineInfo,
    QueryAnswer,
    QueryEngine,
    QueryResult,
)
from doxa.query.postprocess import finalize_answers

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


def resolve_effective_times(query: Query) -> Tuple[datetime, datetime, datetime]:
    """Public wrapper for effective query/valid/known times."""
    return _resolve_effective_times(query)


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


def evaluate_with_records(
    *,
    query: Query,
    records: Sequence[BeliefRecord],
    rules: Sequence[Rule],
    constraints: Sequence[Constraint],
    effective_query_time: datetime,
    effective_valid_at: datetime,
    effective_known_at: datetime,
    records_prefiltered: bool,
) -> Tuple[List[QueryAnswer], Optional[Tuple[Dict[str, Any], ...]]]:
    """Evaluate a query against provided records/rules/constraints.

    This is a public shared path used by non-memory engines that want to reuse
    evaluator semantics with prefiltered record streams.
    """
    known_at_for_index = (
        datetime(9999, 12, 31, tzinfo=timezone.utc)
        if records_prefiltered
        else effective_known_at
    )
    fact_index = _build_fact_index(
        records,
        valid_at=effective_valid_at,
        known_at=known_at_for_index,
    )

    compiled_goals = _compile_query_goals(query)
    query_vars = _query_var_names(query)

    _inject_assume_facts(compiled_goals, fact_index, {})

    ctx = _Context(
        fact_index=fact_index,
        rules=tuple(rules),
        constraints=tuple(constraints),
        query=query,
        effective_query_time=effective_query_time,
        effective_valid_at=effective_valid_at,
        effective_known_at=effective_known_at,
        max_depth=query.options.max_depth,
        explain_enabled=(query.options.explain != "false"),
    )

    collector = ExplainCollector(enabled=ctx.explain_enabled)
    truth_rows = list(
        _solve_body_truth(
            compiled_goals,
            {},
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
    answers = finalize_answers(
        answers,
        query,
        is_closed_query=(not query_vars),
        closed_query_fallback=QueryAnswer(
            bindings={},
            b=0.0,
            d=0.0,
            belnap_status=BelnapStatus.neither,
        ),
    )

    explain = tuple(collector.events) if ctx.explain_enabled else None
    return answers, explain


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
        answers, explain = evaluate_with_records(
            query=query,
            records=branch.belief_records,
            rules=branch.rules,
            constraints=branch.constraints,
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            records_prefiltered=False,
        )

        return QueryResult(
            answers=tuple(answers),
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            epistemic_semantics=query.options.epistemic_semantics,
            explain=explain,
        )
