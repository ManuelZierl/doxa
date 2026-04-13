//! Event log types for the EDB append-only store.

use serde::{Deserialize, Serialize};

use doxa_core::types::SymId;
use doxa_core::rule::Rule;

/// Monotonically increasing event identifier.
pub type EventId = u64;

/// A single event in the EDB log. Events are append-only and immutable
/// once written.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum EdbEvent {
    /// Assert a ground fact with epistemic weights.
    AssertFact {
        /// Event sequence number.
        event_id: EventId,
        /// Branch this fact belongs to.
        branch: String,
        /// Predicate name.
        pred_name: String,
        /// Predicate arity.
        pred_arity: usize,
        /// Ground argument values (interned as SymIds).
        args: Vec<SymId>,
        /// Belief weight.
        b: f64,
        /// Doubt weight.
        d: f64,
        /// Source identifier (who asserted this).
        source: Option<String>,
    },

    /// Register a predicate declaration.
    DeclarePredicate {
        event_id: EventId,
        branch: String,
        pred_name: String,
        pred_arity: usize,
    },

    /// Add a rule to the branch.
    AddRule {
        event_id: EventId,
        branch: String,
        rule: Rule,
    },

    /// Retract a previously asserted fact by its event ID.
    RetractFact {
        event_id: EventId,
        branch: String,
        /// The event_id of the original AssertFact event.
        target_event_id: EventId,
    },
}

impl EdbEvent {
    /// Get the event ID.
    pub fn event_id(&self) -> EventId {
        match self {
            EdbEvent::AssertFact { event_id, .. } => *event_id,
            EdbEvent::DeclarePredicate { event_id, .. } => *event_id,
            EdbEvent::AddRule { event_id, .. } => *event_id,
            EdbEvent::RetractFact { event_id, .. } => *event_id,
        }
    }

    /// Get the branch name.
    pub fn branch(&self) -> &str {
        match self {
            EdbEvent::AssertFact { branch, .. } => branch,
            EdbEvent::DeclarePredicate { branch, .. } => branch,
            EdbEvent::AddRule { branch, .. } => branch,
            EdbEvent::RetractFact { branch, .. } => branch,
        }
    }
}
