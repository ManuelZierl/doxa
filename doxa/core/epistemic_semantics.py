from __future__ import annotations

from enum import Enum
from typing import Tuple

from pydantic import BaseModel, ConfigDict, Field


class BodyTruthSemantics(str, Enum):
    product = "product"
    minimum = "minimum"


class BodyFalsitySemantics(str, Enum):
    noisy_or = "noisy_or"
    maximum = "maximum"


class RulePropagationSemantics(str, Enum):
    body_times_rule_weights = "body_times_rule_weights"


class ConstraintPropagationSemantics(str, Enum):
    body_times_constraint_weights_to_violation = (
        "body_times_constraint_weights_to_violation"
    )


class SupportAggregationSemantics(str, Enum):
    noisy_or = "noisy_or"
    maximum = "maximum"
    capped_sum = "capped_sum"


class BelnapStatusSemantics(str, Enum):
    nonzero = "nonzero"


class NonAtomSemantics(str, Enum):
    crisp_filters = "crisp_filters"


class RuleApplicabilitySemantics(str, Enum):
    body_truth_only = "body_truth_only"
    body_truth_discounted_by_body_falsity = "body_truth_discounted_by_body_falsity"


class ConstraintApplicabilitySemantics(str, Enum):
    body_truth_only = "body_truth_only"
    body_truth_discounted_by_body_falsity = "body_truth_discounted_by_body_falsity"


class EpistemicSemanticsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    body_truth: BodyTruthSemantics = Field(default=BodyTruthSemantics.product)
    body_falsity: BodyFalsitySemantics = Field(default=BodyFalsitySemantics.noisy_or)
    rule_propagation: RulePropagationSemantics = Field(
        default=RulePropagationSemantics.body_times_rule_weights
    )
    constraint_propagation: ConstraintPropagationSemantics = Field(
        default=ConstraintPropagationSemantics.body_times_constraint_weights_to_violation
    )
    support_aggregation: SupportAggregationSemantics = Field(
        default=SupportAggregationSemantics.noisy_or
    )
    belnap_status: BelnapStatusSemantics = Field(default=BelnapStatusSemantics.nonzero)
    non_atom: NonAtomSemantics = Field(default=NonAtomSemantics.crisp_filters)
    rule_applicability: RuleApplicabilitySemantics = Field(
        default=RuleApplicabilitySemantics.body_truth_discounted_by_body_falsity
    )
    constraint_applicability: ConstraintApplicabilitySemantics = Field(
        default=ConstraintApplicabilitySemantics.body_truth_discounted_by_body_falsity
    )


class EpistemicSemanticsCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    body_truth: Tuple[BodyTruthSemantics, ...] = Field(...)
    body_falsity: Tuple[BodyFalsitySemantics, ...] = Field(...)
    rule_propagation: Tuple[RulePropagationSemantics, ...] = Field(
        ...,
    )
    constraint_propagation: Tuple[ConstraintPropagationSemantics, ...] = Field(
        ...,
    )
    support_aggregation: Tuple[SupportAggregationSemantics, ...] = Field(
        ...,
    )
    belnap_status: Tuple[BelnapStatusSemantics, ...] = Field(
        ...,
    )
    non_atom: Tuple[NonAtomSemantics, ...] = Field(
        ...,
    )
    rule_applicability: Tuple[RuleApplicabilitySemantics, ...] = Field(
        ...,
    )
    constraint_applicability: Tuple[ConstraintApplicabilitySemantics, ...] = Field(
        ...,
    )


DEFAULT_EPISTEMIC_SEMANTICS = EpistemicSemanticsConfig()


class BelnapStatus(str, Enum):
    true = "true"
    false = "false"
    both = "both"
    neither = "neither"
