//! Doxa-native Extensional Database (EDB).
//!
//! The EDB is the persistent source of truth for asserted facts and rules.
//! It is modeled as an append-only event log with visibility filtering
//! and branch isolation.
//!
//! Responsibilities:
//! - Append-only storage of belief records (facts with epistemic weights)
//! - Durable rule and predicate declaration storage
//! - Visibility filtering by knowledge-time and validity-time
//! - Branch isolation (each branch is an independent namespace)

mod event_log;
mod store;

pub use event_log::{EdbEvent, EventId};
pub use store::{EdbError, EdbStore, GroundFact};
