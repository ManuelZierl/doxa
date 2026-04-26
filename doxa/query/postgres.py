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
from typing import TYPE_CHECKING

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.engine import EngineInfo, QueryEngine, QueryResult
from doxa.query.postgres_native import probe_native_support, try_evaluate_native

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
from doxa.query.evaluator import (
    evaluate_with_records,
    resolve_effective_times,
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

    def __init__(
        self,
        repo: "PostgresBranchRepository",
        *,
        native_sql_enabled: bool | None = None,
        auto_sync_on_evaluate: bool = True,
    ) -> None:
        self._repo = repo
        self._synced_branch_signatures: dict[str, str] = {}
        self._native_sql_enabled = native_sql_enabled
        self._auto_sync_on_evaluate = auto_sync_on_evaluate
        self.last_native_fallback_reason: str | None = None

    def _use_native_sql(self) -> bool:
        if self._native_sql_enabled is not None:
            return self._native_sql_enabled
        import os

        return os.environ.get("DOXA_POSTGRES_NATIVE_SQL") == "1"

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

    def sync_branch(self, branch: Branch) -> None:
        """Explicitly persist a branch snapshot for subsequent evaluations."""
        self._ensure_branch_saved(branch)

    def _evaluate(self, branch: Branch, query: Query) -> QueryResult:
        effective_query_time, effective_valid_at, effective_known_at = (
            resolve_effective_times(query)
        )

        # ── Optional auto-sync: ensure branch is in the database ─────
        if self._auto_sync_on_evaluate:
            self._ensure_branch_saved(branch)
        if self._use_native_sql():
            supported, reason = probe_native_support(branch, query)
            if not supported:
                self.last_native_fallback_reason = reason
            else:
                self.last_native_fallback_reason = None
            native_result = try_evaluate_native(
                self._repo.get_connection(), branch, query
            )
            if native_result is not None:
                return native_result

        # ── Fast path: load only visible records from PostgreSQL ──────
        records = self._repo.get_visible_belief_records(
            branch.name,
            valid_at=effective_valid_at,
            known_at=effective_known_at,
        )

        answers, explain = evaluate_with_records(
            query=query,
            records=records,
            rules=branch.rules,
            constraints=branch.constraints,
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            records_prefiltered=True,
        )

        return QueryResult(
            answers=tuple(answers),
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            epistemic_semantics=query.options.epistemic_semantics,
            explain=explain,
        )
