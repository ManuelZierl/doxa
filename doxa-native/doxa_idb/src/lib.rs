//! Doxa-native intensional database (IDB) store.
//!
//! This crate provides a storage layer tailored for the needs of a Doxa reasoning
//! engine. It focuses on managing extensional and intensional facts, tracking
//! contributions from multiple evidence sources, and exposing multiple index
//! projections on the same logical atom. The goal of this layer is to
//! efficiently support point lookups by atom key, lookups by predicate and
//! argument position, and incremental updates for non‑idempotent aggregations.
//!
//! The API is intentionally minimal: users can register predicates with
//! associated profiles, upsert contributions to atoms, retract individual
//! contributions, and scan for derived states via secondary indices.
//!
//! Under the hood this implementation leverages the `sled` embedded
//! key‑value store. Keys are constructed in a lexicographically sortable
//! binary form to enable efficient prefix scans. Values are encoded using
//! `bincode` for compact serialization.
//!
//! Note that this crate is experimental and does not provide a complete
//! Doxa evaluation engine—rule evaluation, fixpoint iteration, and Magic
//! Sets rewriting live above this layer. However, the storage API is
//! designed to serve those higher layers.

mod types;
mod store;

pub use crate::types::{
    AggregationMode, AtomKey, AtomState, Contribution, EvidenceMode, IndexSpec,
    PredicateProfile, PredId, SymId,
};
pub use crate::store::{DoxaStore, SymbolStore, PredicateRegistry, StoreError};