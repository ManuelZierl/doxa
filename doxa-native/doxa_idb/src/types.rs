//! Re-exports core Doxa types from [`doxa_core`] and defines
//! IDB-specific types (AtomState, Contribution).

use serde::{Deserialize, Serialize};

// Re-export shared types from doxa_core so the rest of doxa_idb (and
// downstream crates) can use a single canonical definition.
pub use doxa_core::types::{
    AggregationMode, AtomKey, EvidenceMode, IndexSpec, PredId, PredicateProfile,
    SymId,
};

/// The epistemic state of a derived atom as stored in the IDB. Fields
/// represent the belief and doubt channels described by Belnap
/// four‑valued semantics.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AtomState {
    pub b: f64,
    pub d: f64,
}

impl AtomState {
    /// Small epsilon for floating-point comparisons.
    const EPS: f64 = 1e-12;

    /// Create an empty state with both channels set to zero.
    pub fn empty() -> Self {
        AtomState { b: 0.0, d: 0.0 }
    }

    /// Returns true if `self` and `other` are approximately equal within
    /// [`Self::EPS`] tolerance.
    pub fn approx_eq(&self, other: &Self) -> bool {
        (self.b - other.b).abs() < Self::EPS && (self.d - other.d).abs() < Self::EPS
    }
}

impl PartialEq for AtomState {
    fn eq(&self, other: &Self) -> bool {
        self.approx_eq(other)
    }
}

/// A contribution to an atom's state produced by a single rule application.
/// In non‑idempotent aggregation modes, multiple contributions may be
/// accumulated for the same atom. The evidence ID identifies which
/// contributions are distinct when computing noisy OR or capped sum.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Contribution {
    pub b: f64,
    pub d: f64,
    /// Optional evidence identifier. When evidence mode is
    /// [`EvidenceMode::PerSource`] or [`EvidenceMode::ProofTree`], this
    /// distinguishes independent contributions. When omitted and the
    /// evidence mode requires distinct identities, the atom key is used as
    /// fallback identifier.
    pub evidence_id: Option<Vec<u8>>,
}