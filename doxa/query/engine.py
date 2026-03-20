from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Tuple

from doxa.core.branch import Branch
from doxa.core.epistemic_semantics import (
    DEFAULT_EPISTEMIC_SEMANTICS,
    BelnapStatus,
    BelnapStatusSemantics,
    BodyFalsitySemantics,
    BodyTruthSemantics,
    ConstraintApplicabilitySemantics,
    ConstraintPropagationSemantics,
    EpistemicSemanticsCapabilities,
    EpistemicSemanticsConfig,
    NonAtomSemantics,
    RuleApplicabilitySemantics,
    RulePropagationSemantics,
    SupportAggregationSemantics,
)
from doxa.core.query import Query


class QueryError(Exception):
    """Base class for query-engine errors."""


class UnsupportedEpistemicSemanticsError(QueryError):
    """Raised when a query requests an epistemic semantics unsupported by the engine."""


@dataclass(frozen=True)
class EngineInfo:
    """
    Metadata about a query engine.

    A conforming Doxa engine should support the full core Query language and
    the canonical Doxa epistemic semantics config. Experimental engines may
    support additional semantics variants, but should be explicit about that.
    """

    name: str
    version: str
    supported_epistemic_semantics: EpistemicSemanticsCapabilities = field(
        default_factory=lambda: EpistemicSemanticsCapabilities(
            body_truth=(BodyTruthSemantics.product,),
            body_falsity=(BodyFalsitySemantics.noisy_or,),
            rule_propagation=(RulePropagationSemantics.body_times_rule_weights,),
            constraint_propagation=(
                ConstraintPropagationSemantics.body_times_constraint_weights_to_violation,
            ),
            support_aggregation=(SupportAggregationSemantics.noisy_or,),
            belnap_status=(BelnapStatusSemantics.nonzero,),
            non_atom=(NonAtomSemantics.crisp_filters,),
            rule_applicability=(
                RuleApplicabilitySemantics.body_truth_discounted_by_body_falsity,
            ),
            constraint_applicability=(
                ConstraintApplicabilitySemantics.body_truth_discounted_by_body_falsity,
            ),
        )
    )
    default_epistemic_semantics: EpistemicSemanticsConfig = field(
        default_factory=lambda: DEFAULT_EPISTEMIC_SEMANTICS
    )
    experimental: bool = False


@dataclass(frozen=True)
class QueryAnswer:
    """
    One epistemic answer row.

    bindings:
        Query-variable bindings for projected variables. For closed queries this
        will usually be empty.

    b / d:
        Answer-level epistemic belief / disbelief values for the grounded answer.

    belnap_status:
        Derived category from (b, d). The exact derivation rule belongs to the
        selected epistemic semantics.
    """

    bindings: Mapping[str, Any]
    b: float
    d: float
    belnap_status: BelnapStatus


@dataclass(frozen=True)
class QueryResult:
    """
    Result of evaluating a Doxa query.

    answers:
        For open queries, zero or more epistemic answer rows.
        For closed queries, typically exactly one epistemic answer row.

    effective_query_time:
        The resolved query-time default used by the engine when specific time
        fields were omitted.

    effective_valid_at:
        The resolved validity-time cutoff applied to [vf, vt].

    effective_known_at:
        The resolved knowledge-time cutoff applied to et.

    epistemic_semantics:
        The epistemic semantics identifier actually used for evaluation.

    explain:
        Optional structured explanation payload.
    """

    answers: Tuple[QueryAnswer, ...] = ()
    effective_query_time: Optional[datetime] = None
    effective_valid_at: Optional[datetime] = None
    effective_known_at: Optional[datetime] = None
    epistemic_semantics: EpistemicSemanticsConfig = field(
        default_factory=lambda: DEFAULT_EPISTEMIC_SEMANTICS
    )
    explain: Optional[Tuple[Dict[str, Any], ...]] = None


class QueryEngine(ABC):
    """
    Abstract Doxa query engine.

    Contract:
    - Must evaluate core Query objects against core Branch objects.
    - Must implement the full Doxa query semantics for conforming operation.
    - Must treat answer rows as epistemic answers, not just logical substitutions.
    - Must resolve time semantics from Query.options, not from extra evaluate()
      parameters.
    """

    @property
    @abstractmethod
    def info(self) -> EngineInfo: ...

    def evaluate(self, branch: Branch, query: Query) -> QueryResult:
        self.validate_epistemic_semantics(query)
        return self._evaluate(branch, query)

    @abstractmethod
    def _evaluate(self, branch: Branch, query: Query) -> QueryResult:
        """
        Evaluate query against branch and return epistemic answer rows.

        Time resolution is driven by Query.options:
        - effective_query_time = query.options.query_time or current UTC time
        - effective_valid_at = query.options.valid_at or effective_query_time
        - effective_known_at = query.options.known_at or effective_query_time

        A visible belief record must satisfy:
        - record.et <= effective_known_at
        - record validity window [vf, vt] contains effective_valid_at
        """
        ...

    def validate_epistemic_semantics(self, query: Query) -> None:
        config = query.options.epistemic_semantics
        caps = self.info.supported_epistemic_semantics

        unsupported: Dict[str, str] = {}

        if config.body_truth not in caps.body_truth:
            unsupported["body_truth"] = config.body_truth.value

        if config.body_falsity not in caps.body_falsity:
            unsupported["body_falsity"] = config.body_falsity.value

        if config.rule_propagation not in caps.rule_propagation:
            unsupported["rule_propagation"] = config.rule_propagation.value

        if config.constraint_propagation not in caps.constraint_propagation:
            unsupported["constraint_propagation"] = config.constraint_propagation.value

        if config.support_aggregation not in caps.support_aggregation:
            unsupported["support_aggregation"] = config.support_aggregation.value

        if config.belnap_status not in caps.belnap_status:
            unsupported["belnap_status"] = config.belnap_status.value

        if config.non_atom not in caps.non_atom:
            unsupported["non_atom"] = config.non_atom.value

        if config.rule_applicability not in caps.rule_applicability:
            unsupported["rule_applicability"] = config.rule_applicability.value

        if config.constraint_applicability not in caps.constraint_applicability:
            unsupported["constraint_applicability"] = (
                config.constraint_applicability.value
            )

        if unsupported:
            details = ", ".join(f"{k}={v!r}" for k, v in unsupported.items())
            raise UnsupportedEpistemicSemanticsError(
                f"Engine {self.info.name!r} does not support requested epistemic semantics parts: {details}."
            )
