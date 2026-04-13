"""PostgreSQL-accelerated query engine.

This engine produces *exactly* the same epistemic answers as the shared
evaluator. The speed-up comes from pushing temporal visibility filtering
(``et``, ``vf``, ``vt``) into SQL ``WHERE`` clauses so that only the
relevant belief records are transferred from PostgreSQL to the evaluator.

The epistemic reasoning itself (rule chaining, constraint checking,
Belnap status derivation, builtins, …) reuses the battle-tested functions
from :mod:`doxa.query.evaluator`.

Usage::

    from doxa.persistence.postgres import connect_postgres
    from doxa.query.postgres import PostgresQueryEngine

    repo = connect_postgres("postgresql://user:pass@localhost/doxa")
    engine = PostgresQueryEngine(repo)

    repo.save(branch)
    result = engine.evaluate(branch, query)
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.engine import EngineInfo, QueryEngine, QueryResult
from doxa.query.postgres_native import try_evaluate_native

if TYPE_CHECKING:
    from doxa.persistence.postgres import PostgresBranchRepository


# ---------------------------------------------------------------------------
# Import the full epistemic evaluation machinery from the shared evaluator.
# This keeps Postgres independent from the in-memory engine module while
# preserving bit-identical semantics.
# ---------------------------------------------------------------------------

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
from doxa.query.engine import BelnapStatus, QueryAnswer
from doxa.query.evaluator import (
    ExplainCollector,
    _aggregate_answers_from_truth,
    _apply_focus,
    _build_fact_index,
    _compile_query_goals,
    _Context,
    _inject_assume_facts,
    _query_var_names,
    _resolve_effective_times,
    _solve_body_truth,
    _sort_answers,
)


class PostgresQueryEngine(QueryEngine):
    """Epistemic query engine backed by a PostgreSQL repository.

    Semantically equivalent to
    :class:`~doxa.query.memory.InMemoryQueryEngine` but loads only
    time-visible belief records from the database, leveraging SQL indexes
    for the temporal filtering that the in-memory engine must do in Python.

    Parameters
    ----------
    repo:
        A :class:`~doxa.persistence.postgres.PostgresBranchRepository`
        used to fetch belief records with server-side filtering.
    """

    def __init__(self, repo: "PostgresBranchRepository") -> None:
        self._repo = repo
        self._synced_branch_signatures: dict[str, str] = {}

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name="postgres",
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
    # Core evaluation
    # ------------------------------------------------------------------

    def _branch_signature(self, branch: Branch) -> str:
        return hashlib.sha256(branch.model_dump_json().encode("utf-8")).hexdigest()

    def _ensure_branch_saved(self, branch: Branch) -> None:
        signature = self._branch_signature(branch)
        if self._synced_branch_signatures.get(branch.name) == signature:
            return
        self._repo.save(branch)
        self._synced_branch_signatures[branch.name] = signature

    def _evaluate(self, branch: Branch, query: Query) -> QueryResult:
        effective_query_time, effective_valid_at, effective_known_at = (
            _resolve_effective_times(query)
        )

        # ── Auto-sync: ensure the branch is in the database ──────────
        self._ensure_branch_saved(branch)
        if os.environ.get("DOXA_POSTGRES_NATIVE_SQL") == "1":
            native_result = try_evaluate_native(self._repo._conn, branch, query)
            if native_result is not None:
                return native_result

        # ── Fast path: load only visible records from PostgreSQL ──────
        records = self._repo.get_visible_belief_records(
            branch.name,
            valid_at=effective_valid_at,
            known_at=effective_known_at,
        )

        # Build the in-memory fact index from the pre-filtered records.
        # Since the SQL already enforced temporal visibility we pass
        # permissive time bounds so _build_fact_index keeps everything.
        _FAR_FUTURE = datetime(9999, 12, 31, tzinfo=timezone.utc)
        fact_index = _build_fact_index(
            records,
            valid_at=effective_valid_at,
            known_at=_FAR_FUTURE,
        )

        compiled_goals = _compile_query_goals(query)
        query_vars = _query_var_names(query)

        # ── Inject explicit assume(...) facts ────────────────────────────────
        _inject_assume_facts(compiled_goals, fact_index, {})

        initial_subst = {}

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

        # ── Post-processing ──────────────────────────────────────────
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
