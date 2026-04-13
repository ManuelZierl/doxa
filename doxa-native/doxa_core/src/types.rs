//! Fundamental Doxa types: terms, atoms, epistemic state, predicates.

use serde::{Deserialize, Serialize};

// ── Identifiers ──────────────────────────────────────────────────────

/// Numeric predicate identifier.
pub type PredId = u64;

/// Numeric symbol identifier (interned entity / constant).
pub type SymId = u64;

/// Argument position within a predicate (0-based).
pub type ArgPosition = usize;

// ── Epistemic state ──────────────────────────────────────────────────

/// Epistemic state of a derived atom: belief (`b`) and doubt (`d`).
///
/// This is the fundamental unit of state in Doxa — not a boolean, not a
/// probability, but a pair of independent channels following Belnap
/// four-valued semantics.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EpistemicState {
    pub b: f64,
    pub d: f64,
}

impl EpistemicState {
    /// Small epsilon for floating-point comparisons.
    const EPS: f64 = 1e-12;

    pub fn empty() -> Self {
        Self { b: 0.0, d: 0.0 }
    }

    pub fn new(b: f64, d: f64) -> Self {
        Self { b, d }
    }

    pub fn approx_eq(&self, other: &Self) -> bool {
        (self.b - other.b).abs() < Self::EPS && (self.d - other.d).abs() < Self::EPS
    }

    /// Belnap four-valued status derived from (b, d).
    pub fn belnap_status(&self) -> BelnapStatus {
        let has_b = self.b > Self::EPS;
        let has_d = self.d > Self::EPS;
        match (has_b, has_d) {
            (true, true) => BelnapStatus::Both,
            (true, false) => BelnapStatus::True,
            (false, true) => BelnapStatus::False,
            (false, false) => BelnapStatus::Neither,
        }
    }
}

impl PartialEq for EpistemicState {
    fn eq(&self, other: &Self) -> bool {
        self.approx_eq(other)
    }
}

/// Belnap four-valued status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum BelnapStatus {
    True,
    False,
    Both,
    Neither,
}

// ── Terms ────────────────────────────────────────────────────────────

/// A term in a rule body or head. Variables are represented by name,
/// ground values by their interned symbol ID or typed literal.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum Term {
    /// A logic variable, identified by name.
    Var(String),
    /// An interned entity reference.
    Entity(SymId),
    /// An integer literal.
    Int(i64),
    /// A float literal (stored as bits for Eq/Hash).
    Float(u64),
    /// A string literal (interned as symbol).
    Str(SymId),
}

impl Term {
    /// Create a float term from an f64 value.
    pub fn float(v: f64) -> Self {
        Term::Float(v.to_bits())
    }

    /// Retrieve the f64 value from a Float term.
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Term::Float(bits) => Some(f64::from_bits(*bits)),
            _ => None,
        }
    }

    /// Returns true if this term is a variable.
    pub fn is_var(&self) -> bool {
        matches!(self, Term::Var(_))
    }

    /// Returns true if this term is ground (not a variable).
    pub fn is_ground(&self) -> bool {
        !self.is_var()
    }
}

// ── Ground values ────────────────────────────────────────────────────

/// A ground value that can appear as an argument in a grounded atom.
/// This is the runtime representation after variable substitution.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum GroundValue {
    Entity(SymId),
    Int(i64),
    Float(u64),
    Str(SymId),
}

impl GroundValue {
    pub fn float(v: f64) -> Self {
        GroundValue::Float(v.to_bits())
    }

    pub fn as_sym_id(&self) -> Option<SymId> {
        match self {
            GroundValue::Entity(id) | GroundValue::Str(id) => Some(*id),
            _ => None,
        }
    }
}

// ── Atoms ────────────────────────────────────────────────────────────

/// Key identifying a grounded atom: predicate + argument values.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct AtomKey {
    pub pred_id: PredId,
    pub args: Vec<SymId>,
}

impl AtomKey {
    pub fn new(pred_id: PredId, args: Vec<SymId>) -> Self {
        Self { pred_id, args }
    }
}

/// A grounded atom with its current epistemic state.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Atom {
    pub key: AtomKey,
    pub state: EpistemicState,
}

// ── Contributions ────────────────────────────────────────────────────

/// A single contribution to an atom's epistemic state, produced by one
/// rule application or one EDB fact.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Contribution {
    pub b: f64,
    pub d: f64,
    /// Optional evidence identifier for non-idempotent aggregation.
    pub evidence_id: Option<Vec<u8>>,
}

// ── Predicate metadata ───────────────────────────────────────────────

/// Aggregation mode for combining contributions.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum AggregationMode {
    /// Componentwise maximum (idempotent).
    Maximum,
    /// Noisy-OR: `1 - ∏(1 - cᵢ)`.
    NoisyOr,
    /// Capped sum: `min(1, Σcᵢ)`.
    CappedSum,
}

impl Default for AggregationMode {
    fn default() -> Self {
        AggregationMode::Maximum
    }
}

/// Evidence tracking mode.
#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum EvidenceMode {
    /// No evidence tracking.
    None,
    /// Track by source identifier.
    PerSource,
    /// Track by full proof-tree signature.
    ProofTree,
}

impl Default for EvidenceMode {
    fn default() -> Self {
        EvidenceMode::None
    }
}

/// A secondary index specification for a predicate.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexSpec {
    pub name: String,
    pub positions: Vec<ArgPosition>,
}

impl IndexSpec {
    pub fn new(name: impl Into<String>, positions: Vec<ArgPosition>) -> Self {
        Self {
            name: name.into(),
            positions,
        }
    }
}

/// Full profile for a registered predicate.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PredicateProfile {
    pub pred_id: PredId,
    pub name: String,
    pub arity: usize,
    pub aggregation: AggregationMode,
    pub evidence_mode: EvidenceMode,
    pub indexes: Vec<IndexSpec>,
}
