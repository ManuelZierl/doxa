//! Doxa-native query and evaluation engine.
//!
//! This crate implements the logical engine layer of the Doxa-native
//! architecture. It is responsible for:
//!
//! - **Joins**: matching rule body goals against IDB/EDB facts
//! - **Semi-naive fixpoint**: iterating until no atom state changes
//! - **Delta propagation**: tracking which atoms changed per iteration
//! - **SCC-ordered evaluation**: evaluating predicates bottom-up
//! - **Query planning**: deciding which EDB slice to load and which
//!   bindings to push down
//!
//! The engine operates over epistemic atom states directly, using the
//! IDB (`doxa_idb`) for derived state storage and the EDB (`doxa_edb`)
//! for source facts and rules.
//!
//! # The engine in one loop
//!
//! 1. Load the relevant EDB slice
//! 2. Evaluate rules SCC by SCC
//! 3. In recursive SCCs, use semi-naive delta iteration
//! 4. For each candidate derived atom:
//!    - compute its contribution
//!    - merge it into current (b, d)
//!    - if state changed, emit it into next delta
//! 5. Stop when no atom changes anymore

mod compiler;
mod eval;
mod join;
mod session;

pub use session::{EngineSession, QueryResult, QueryAnswer, PredicateAnswer};
