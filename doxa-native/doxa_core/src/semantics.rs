//! Epistemic semantics configuration — mirrors the Python
//! `EpistemicSemanticsConfig` and related enums.

use serde::{Deserialize, Serialize};

/// How body-atom truth values are combined within a single rule body.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum BodyTruthSemantics {
    /// `b = ∏ bᵢ` (product of body-atom beliefs).
    Product,
    /// `b = min(bᵢ)`.
    Minimum,
}

impl Default for BodyTruthSemantics {
    fn default() -> Self {
        Self::Product
    }
}

/// How body-atom falsity values are combined.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum BodyFalsitySemantics {
    /// Noisy-OR over body-atom doubt values.
    NoisyOr,
    /// Componentwise maximum.
    Maximum,
}

impl Default for BodyFalsitySemantics {
    fn default() -> Self {
        Self::NoisyOr
    }
}

/// How a rule's body truth/falsity is propagated to the head.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RulePropagationSemantics {
    /// `head.b = body_truth * rule.b`, `head.d = body_truth * rule.d`.
    BodyTimesRuleWeights,
}

impl Default for RulePropagationSemantics {
    fn default() -> Self {
        Self::BodyTimesRuleWeights
    }
}

/// How multiple rule derivations for the same head atom are aggregated.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum SupportAggregationSemantics {
    NoisyOr,
    Maximum,
    CappedSum,
}

impl Default for SupportAggregationSemantics {
    fn default() -> Self {
        Self::NoisyOr
    }
}

/// Whether a rule fires based on body truth alone, or discounted by falsity.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RuleApplicabilitySemantics {
    BodyTruthOnly,
    BodyTruthDiscountedByBodyFalsity,
}

impl Default for RuleApplicabilitySemantics {
    fn default() -> Self {
        Self::BodyTruthDiscountedByBodyFalsity
    }
}

/// Full epistemic semantics configuration for an evaluation session.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EpistemicSemantics {
    pub body_truth: BodyTruthSemantics,
    pub body_falsity: BodyFalsitySemantics,
    pub rule_propagation: RulePropagationSemantics,
    pub support_aggregation: SupportAggregationSemantics,
    pub rule_applicability: RuleApplicabilitySemantics,
}

impl Default for EpistemicSemantics {
    fn default() -> Self {
        Self {
            body_truth: BodyTruthSemantics::default(),
            body_falsity: BodyFalsitySemantics::default(),
            rule_propagation: RulePropagationSemantics::default(),
            support_aggregation: SupportAggregationSemantics::default(),
            rule_applicability: RuleApplicabilitySemantics::default(),
        }
    }
}
