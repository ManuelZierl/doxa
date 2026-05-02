//! Doxa-native core types — the semantic layer.
//!
//! This crate defines the fundamental types that every other crate in the
//! doxa-native workspace depends on:
//!
//! - **Epistemic state** (`b`, `d`) and Belnap status
//! - **Terms** (variables, entities, literals)
//! - **Atoms** (predicate + grounded args + epistemic state)
//! - **Rules** (head atom + body goals, with weights)
//! - **Constraints** (integrity constraints producing violations)
//! - **Predicates** (name, arity, profile)
//! - **Epistemic semantics configuration** (body truth, aggregation, etc.)
//! - **SCC** (strongly connected component metadata)
//!
//! No storage or evaluation logic lives here — only data definitions and
//! small helper methods.

pub mod rule;
pub mod scc;
pub mod semantics;
pub mod types;

pub use rule::*;
pub use scc::*;
pub use semantics::*;
pub use types::*;
