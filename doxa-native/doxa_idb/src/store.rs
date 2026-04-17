use std::collections::HashMap;
use std::convert::TryInto;
use std::fmt;
use std::path::Path;
use std::sync::RwLock;

use sled::{self, Db, Tree};

use crate::types::{
    AggregationMode, AtomKey, AtomState, Contribution, EvidenceMode, IndexSpec, PredId,
    PredicateProfile, SymId,
};

/// Custom error type for the Doxa store. Wraps errors from sled and bincode.
#[derive(Debug)]
pub enum StoreError {
    /// Error raised by the underlying sled database.
    Sled(sled::Error),
    /// Error during (de)serialization.
    Bincode(Box<bincode::ErrorKind>),
    /// Predicate not found.
    UnknownPredicate(PredId),
    /// Index not found for the given predicate.
    UnknownIndex { pred_id: PredId, index_name: String },
    /// Invalid argument length for atom key relative to predicate arity.
    InvalidArity { expected: usize, found: usize },
    /// Evidence identifier required but missing.
    MissingEvidence,
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StoreError::Sled(e) => write!(f, "sled error: {}", e),
            StoreError::Bincode(e) => write!(f, "bincode error: {}", e),
            StoreError::UnknownPredicate(id) => write!(f, "unknown predicate id {}", id),
            StoreError::UnknownIndex {
                pred_id,
                index_name,
            } => {
                write!(
                    f,
                    "unknown index '{}' for predicate id {}",
                    index_name, pred_id
                )
            }
            StoreError::InvalidArity { expected, found } => {
                write!(f, "arity mismatch: expected {}, found {}", expected, found)
            }
            StoreError::MissingEvidence => write!(f, "evidence identifier required but missing"),
        }
    }
}

impl std::error::Error for StoreError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            StoreError::Sled(e) => Some(e),
            StoreError::Bincode(e) => Some(e.as_ref()),
            _ => None,
        }
    }
}

impl From<sled::Error> for StoreError {
    fn from(err: sled::Error) -> Self {
        StoreError::Sled(err)
    }
}

impl From<Box<bincode::ErrorKind>> for StoreError {
    fn from(err: Box<bincode::ErrorKind>) -> Self {
        StoreError::Bincode(err)
    }
}

pub type Result<T> = std::result::Result<T, StoreError>;

/// A persistent store for mapping between symbol texts and numeric identifiers.
///
/// Symbols represent entities or string constants used as arguments in atoms.
/// The mapping is kept on disk and is safe to scale to large numbers of unique
/// symbols. Both forward (text → id) and reverse (id → text) lookups are
/// supported.
pub struct SymbolStore {
    symbols_by_text: Tree,
    symbols_by_id: Tree,
    meta: Tree,
}

impl SymbolStore {
    const NEXT_SYM_KEY: &'static [u8] = b"next_sym_id";

    /// Open or create a new symbol store within the given sled database.
    pub(crate) fn new(db: &Db) -> Result<Self> {
        let symbols_by_text = db.open_tree("sym_by_text")?;
        let symbols_by_id = db.open_tree("sym_by_id")?;
        let meta = db.open_tree("sym_meta")?;

        // Initialize next_sym_id if not present.
        if meta.get(Self::NEXT_SYM_KEY)?.is_none() {
            // Start IDs at 1 (reserve 0 for unknown).
            meta.insert(Self::NEXT_SYM_KEY, 1u64.to_be_bytes().as_slice())?;
        }

        Ok(Self {
            symbols_by_text,
            symbols_by_id,
            meta,
        })
    }

    /// Return the symbol ID for the given text, inserting a new one if absent.
    ///
    /// This method is safe to call from multiple threads: the ID counter is
    /// incremented atomically via [`sled::Tree::fetch_and_update`], and the
    /// bidirectional mapping uses compare-and-swap to avoid races.
    pub fn get_or_insert(&self, text: &str) -> Result<SymId> {
        // Try fast path: lookup existing ID.
        if let Some(id_bytes) = self.symbols_by_text.get(text)? {
            return Ok(u64::from_be_bytes(id_bytes.as_ref().try_into().unwrap()));
        }
        // Acquire new ID atomically.
        let id = self.next_sym_id()?;
        // CAS loop: only the first writer wins; losers read the existing ID.
        let id_be = id.to_be_bytes();
        match self.symbols_by_text.compare_and_swap(
            text.as_bytes(),
            None as Option<&[u8]>,
            Some(id_be.as_slice()),
        )? {
            Ok(()) => {
                // We won — insert reverse mapping.
                self.symbols_by_id
                    .insert(id_be.as_slice(), text.as_bytes())?;
                Ok(id)
            }
            Err(cas_err) => {
                // Another thread inserted first — use its ID. The ID we
                // allocated is "wasted" but harmless.
                let existing = cas_err.current.unwrap();
                Ok(u64::from_be_bytes(existing.as_ref().try_into().unwrap()))
            }
        }
    }

    /// Get the symbol ID for the given text if it exists. Returns None when
    /// the symbol has not been assigned an ID yet.
    pub fn get(&self, text: &str) -> Result<Option<SymId>> {
        Ok(self
            .symbols_by_text
            .get(text.as_bytes())?
            .map(|id_bytes| u64::from_be_bytes(id_bytes.as_ref().try_into().unwrap())))
    }

    /// Get the text for a given symbol ID. Returns None when the ID is
    /// unknown.
    pub fn get_text(&self, id: SymId) -> Result<Option<String>> {
        Ok(self
            .symbols_by_id
            .get(id.to_be_bytes().as_slice())?
            .map(|bytes| String::from_utf8(bytes.to_vec()).unwrap()))
    }

    /// Reserve a specific symbol ID for a given text. If the ID is already in
    /// use, this will overwrite the existing mapping. Use with caution.
    pub fn insert_with_id(&self, text: &str, id: SymId) -> Result<()> {
        self.symbols_by_text
            .insert(text.as_bytes(), id.to_be_bytes().as_slice())?;
        self.symbols_by_id
            .insert(id.to_be_bytes().as_slice(), text.as_bytes())?;
        // Ensure next_sym_id is beyond this ID (read-only check, then CAS).
        self.ensure_next_sym_id_above(id + 1)?;
        Ok(())
    }

    /// Atomically allocate the next symbol ID using fetch_and_update.
    fn next_sym_id(&self) -> Result<u64> {
        let old = self.meta.fetch_and_update(Self::NEXT_SYM_KEY, |old| {
            let current = u64::from_be_bytes(old.unwrap().try_into().unwrap());
            Some(Vec::from((current + 1).to_be_bytes()))
        })?;
        let id = u64::from_be_bytes(old.unwrap().as_ref().try_into().unwrap());
        Ok(id)
    }

    /// Ensure that next_sym_id is at least `min_next`. Uses CAS to avoid
    /// lowering the counter if another thread already bumped it higher.
    fn ensure_next_sym_id_above(&self, min_next: u64) -> Result<()> {
        self.meta.fetch_and_update(Self::NEXT_SYM_KEY, |old| {
            let current = u64::from_be_bytes(old.unwrap().try_into().unwrap());
            if min_next > current {
                Some(Vec::from(min_next.to_be_bytes()))
            } else {
                Some(Vec::from(current.to_be_bytes()))
            }
        })?;
        Ok(())
    }
}

/// Registry for predicates. Assigns numeric IDs to predicate names and arities
/// and stores their associated profiles. All registered predicates are
/// persisted on disk.
pub struct PredicateRegistry {
    pred_by_name: Tree,
    pred_profiles: Tree,
    meta: Tree,
}

impl PredicateRegistry {
    const NEXT_PRED_KEY: &'static [u8] = b"next_pred_id";

    pub(crate) fn new(db: &Db) -> Result<Self> {
        let pred_by_name = db.open_tree("pred_by_name")?;
        let pred_profiles = db.open_tree("pred_profiles")?;
        let meta = db.open_tree("pred_meta")?;
        if meta.get(Self::NEXT_PRED_KEY)?.is_none() {
            meta.insert(Self::NEXT_PRED_KEY, 1u64.to_be_bytes().as_slice())?;
        }
        Ok(Self {
            pred_by_name,
            pred_profiles,
            meta,
        })
    }

    /// Register a predicate with the given name, arity and profile. If a
    /// predicate with the same name and arity already exists, its ID and
    /// profile are returned unchanged. Otherwise a new ID is assigned and
    /// persisted. The returned profile always reflects the stored profile.
    pub fn register_predicate(
        &self,
        name: &str,
        arity: usize,
        aggregation: AggregationMode,
        evidence_mode: EvidenceMode,
        indexes: Vec<IndexSpec>,
    ) -> Result<PredicateProfile> {
        let key = format!("{}#{}", name, arity);
        if let Some(id_bytes) = self.pred_by_name.get(key.as_bytes())? {
            let pred_id = u64::from_be_bytes(id_bytes.as_ref().try_into().unwrap());
            let profile = self.get_profile(pred_id)?.unwrap();
            return Ok(profile);
        }
        let id = self.next_pred_id()?;
        let profile = PredicateProfile {
            pred_id: id,
            name: name.to_string(),
            arity,
            aggregation,
            evidence_mode,
            indexes,
        };
        // persist mapping and profile
        self.pred_by_name
            .insert(key.as_bytes(), id.to_be_bytes().as_slice())?;
        let profile_bytes = bincode::serialize(&profile)?;
        self.pred_profiles
            .insert(id.to_be_bytes().as_slice(), profile_bytes)?;
        Ok(profile)
    }

    /// Retrieve a predicate profile by ID.
    pub fn get_profile(&self, pred_id: PredId) -> Result<Option<PredicateProfile>> {
        if let Some(bytes) = self.pred_profiles.get(pred_id.to_be_bytes().as_slice())? {
            let profile: PredicateProfile = bincode::deserialize(bytes.as_ref())?;
            Ok(Some(profile))
        } else {
            Ok(None)
        }
    }

    /// Atomically allocate a new predicate ID using fetch_and_update.
    fn next_pred_id(&self) -> Result<u64> {
        let old = self.meta.fetch_and_update(Self::NEXT_PRED_KEY, |old| {
            let current = u64::from_be_bytes(old.unwrap().try_into().unwrap());
            Some(Vec::from((current + 1).to_be_bytes()))
        })?;
        let id = u64::from_be_bytes(old.unwrap().as_ref().try_into().unwrap());
        Ok(id)
    }
}

/// The main structure representing an intensional database storage layer.
/// It owns a sled database and manages state, contributions, symbols and
/// predicate registry. It exposes high‑level operations for inserting and
/// retracting contributions and scanning by secondary indices.
pub struct DoxaStore {
    db: Db,
    pub symbol_store: SymbolStore,
    pub predicate_registry: PredicateRegistry,
    /// Tree storing the current state of each atom. Keys are encoded using
    /// [`encode_state_key`]. Values are bincode‑encoded [`AtomState`].
    state_tree: Tree,
    /// Tree storing contributions for non‑idempotent aggregation. Keys are
    /// length-prefixed: `state_key || len(evidence_id) as u32be || evidence_id`.
    /// Values are serialized [`Contribution`].
    contrib_tree: Tree,
    /// Cached handles for secondary index trees, keyed by tree name.
    index_trees: RwLock<HashMap<String, Tree>>,
}

impl DoxaStore {
    /// Create or open a Doxa store at the given path. The database will
    /// persist on disk. All subtrees are created if they do not yet exist.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let db = sled::open(path.as_ref())?;
        Self::from_db(db)
    }

    /// Create a temporary in-memory store (no filesystem I/O).
    pub fn open_temporary() -> Result<Self> {
        let db = sled::Config::new().temporary(true).open()?;
        Self::from_db(db)
    }

    fn from_db(db: sled::Db) -> Result<Self> {
        let symbol_store = SymbolStore::new(&db)?;
        let predicate_registry = PredicateRegistry::new(&db)?;
        let state_tree = db.open_tree("state")?;
        let contrib_tree = db.open_tree("contrib")?;
        Ok(DoxaStore {
            db,
            symbol_store,
            predicate_registry,
            state_tree,
            contrib_tree,
            index_trees: RwLock::new(HashMap::new()),
        })
    }

    /// Flush all trees to disk. Call this at appropriate checkpoints (e.g.
    /// after a fixpoint iteration) rather than on every write.
    pub fn flush_all(&self) -> Result<()> {
        self.state_tree.flush()?;
        self.contrib_tree.flush()?;
        self.db.flush()?;
        Ok(())
    }

    /// Insert or update a contribution for the given atom key. Returns the
    /// updated epistemic state of the atom after aggregation. If the
    /// predicate is unknown or the arity does not match, an error is
    /// returned.
    ///
    /// When a contribution with the same evidence ID already exists, the
    /// stored contribution is **replaced** and the aggregate is recomputed
    /// from all contributions.
    pub fn upsert_atom(
        &self,
        atom_key: &AtomKey,
        contribution: &Contribution,
    ) -> Result<AtomState> {
        // Fetch predicate profile
        let profile = self
            .predicate_registry
            .get_profile(atom_key.pred_id)?
            .ok_or(StoreError::UnknownPredicate(atom_key.pred_id))?;
        // Arity check
        if atom_key.args.len() != profile.arity {
            return Err(StoreError::InvalidArity {
                expected: profile.arity,
                found: atom_key.args.len(),
            });
        }
        let state_key = encode_state_key(atom_key);
        // Load current state
        let old_state: AtomState = self.load_state(&state_key)?;
        // Determine new state and update contributions if needed
        let new_state = match profile.aggregation {
            AggregationMode::Maximum => {
                // idempotent: take componentwise maximum — no contrib store
                let mut s = old_state.clone();
                if contribution.b > old_state.b {
                    s.b = contribution.b;
                }
                if contribution.d > old_state.d {
                    s.d = contribution.d;
                }
                s
            }
            AggregationMode::NoisyOr | AggregationMode::CappedSum => {
                self.upsert_non_idempotent(&profile, &state_key, &old_state, contribution)?
            }
        };
        // Persist new state if changed
        if new_state != old_state {
            self.state_tree
                .insert(&state_key, bincode::serialize(&new_state)?.as_slice())?;
            self.update_indices(&profile, atom_key, &state_key)?;
        }
        Ok(new_state)
    }

    /// Handles upsert for NoisyOr and CappedSum modes. When evidence mode is
    /// `None`, the formula is applied directly without tracking contributions
    /// (note: this is **not** idempotent — repeated calls accumulate).
    /// Otherwise the contribution is stored (or replaced) and the aggregate
    /// recomputed when the evidence ID already existed.
    fn upsert_non_idempotent(
        &self,
        profile: &PredicateProfile,
        state_key: &[u8],
        old_state: &AtomState,
        contribution: &Contribution,
    ) -> Result<AtomState> {
        let evid = match (&profile.evidence_mode, &contribution.evidence_id) {
            (EvidenceMode::PerSource, Some(id)) => id.clone(),
            (EvidenceMode::ProofTree, Some(id)) => id.clone(),
            (EvidenceMode::None, _) => {
                // No evidence tracking: apply formula directly.
                // NOTE: this is not idempotent — repeated upserts accumulate.
                return Ok(aggregate_pair(
                    &profile.aggregation,
                    old_state,
                    contribution,
                ));
            }
            (_, None) => {
                return Err(StoreError::MissingEvidence);
            }
        };
        // Build contribution key with length-prefixed evidence ID to avoid
        // ambiguity between atoms of different arity.
        let ckey = encode_contrib_key(state_key, &evid);
        let existed = self.contrib_tree.get(&ckey)?.is_some();
        // Always (re)write the contribution so that updated values take effect.
        self.contrib_tree
            .insert(&ckey, bincode::serialize(contribution)?.as_slice())?;
        if existed {
            // Evidence ID was already present — recompute aggregate from scratch.
            self.recompute_aggregate(profile, state_key)
        } else {
            // New contribution — incremental aggregation is safe.
            Ok(aggregate_pair(
                &profile.aggregation,
                old_state,
                contribution,
            ))
        }
    }

    /// Retract a contribution for a given atom and evidence ID. Only has
    /// effect for non‑idempotent aggregation modes; idempotent modes do
    /// nothing. Returns the updated state if retraction occurred. If the
    /// contribution is not found or idempotent mode, returns the current
    /// state.
    pub fn retract_contribution(
        &self,
        atom_key: &AtomKey,
        evidence_id: &[u8],
    ) -> Result<AtomState> {
        let profile = self
            .predicate_registry
            .get_profile(atom_key.pred_id)?
            .ok_or(StoreError::UnknownPredicate(atom_key.pred_id))?;
        if profile.aggregation == AggregationMode::Maximum {
            // idempotent: nothing to retract
            return self.get_state(atom_key);
        }
        let state_key = encode_state_key(atom_key);
        let ckey = encode_contrib_key(&state_key, evidence_id);
        if self.contrib_tree.remove(&ckey)?.is_some() {
            // Recompute state from remaining contributions
            let new_state = self.recompute_aggregate(&profile, &state_key)?;
            self.state_tree
                .insert(&state_key, bincode::serialize(&new_state)?.as_slice())?;
            self.update_indices(&profile, atom_key, &state_key)?;
            Ok(new_state)
        } else {
            // nothing removed; return current state
            self.get_state(atom_key)
        }
    }

    /// Retrieve the current state of an atom by key.
    pub fn get_state(&self, atom_key: &AtomKey) -> Result<AtomState> {
        let state_key = encode_state_key(atom_key);
        self.load_state(&state_key)
    }

    /// Scan all atoms belonging to a predicate. Returns every `(AtomKey, AtomState)`
    /// pair whose state key starts with the given predicate ID.
    pub fn scan_predicate(&self, pred_id: PredId) -> Result<Vec<(AtomKey, AtomState)>> {
        let prefix = pred_id.to_be_bytes();
        let mut results = Vec::new();
        for item in self.state_tree.scan_prefix(prefix) {
            let (key_bytes, val_bytes) = item?;
            let atom_key = decode_state_key(&key_bytes);
            let state: AtomState = bincode::deserialize(val_bytes.as_ref())?;
            results.push((atom_key, state));
        }
        Ok(results)
    }

    /// Load an [`AtomState`] from the state tree by raw key.
    fn load_state(&self, state_key: &[u8]) -> Result<AtomState> {
        Ok(if let Some(bytes) = self.state_tree.get(state_key)? {
            bincode::deserialize(bytes.as_ref())?
        } else {
            AtomState::empty()
        })
    }

    /// Recompute the aggregate state for an atom from all stored
    /// contributions. Used after retraction or evidence-ID update.
    fn recompute_aggregate(
        &self,
        profile: &PredicateProfile,
        state_key: &[u8],
    ) -> Result<AtomState> {
        let mut new_state = AtomState::empty();
        // The contribution key prefix is `state_key || len` but we only
        // know the state_key portion. We use a prefix that covers exactly
        // the state_key bytes — this is unambiguous because the next 4
        // bytes are the evidence-length field which distinguishes atoms
        // of different arity.
        let prefix = encode_contrib_prefix(state_key);
        for item in self.contrib_tree.scan_prefix(&prefix) {
            let (_, val) = item?;
            let c: Contribution = bincode::deserialize(val.as_ref())?;
            new_state = aggregate_pair(&profile.aggregation, &new_state, &c);
        }
        Ok(new_state)
    }

    /// Update secondary indices for a given atom. This inserts index entries
    /// mapping the selected argument positions to the full state key. The
    /// underlying index trees are cached after first access.
    fn update_indices(
        &self,
        profile: &PredicateProfile,
        atom_key: &AtomKey,
        state_key: &[u8],
    ) -> Result<()> {
        for index in &profile.indexes {
            let tree = self.get_index_tree(profile.pred_id, &index.name)?;
            // Build index key: concatenated argument IDs for the selected positions,
            // followed by the full state key as tiebreaker.
            let mut key = Vec::with_capacity(index.positions.len() * 8 + state_key.len());
            for &pos in &index.positions {
                let sym_id = atom_key.args[pos];
                key.extend_from_slice(&sym_id.to_be_bytes());
            }
            key.extend_from_slice(state_key);
            tree.insert(key, &[])?;
        }
        Ok(())
    }

    /// Get or create a cached handle for an index tree.
    fn get_index_tree(&self, pred_id: PredId, index_name: &str) -> Result<Tree> {
        let tree_name = format!("idx_{}_{}", pred_id, index_name);
        // Fast path: read lock
        {
            let cache = self.index_trees.read().unwrap();
            if let Some(tree) = cache.get(&tree_name) {
                return Ok(tree.clone());
            }
        }
        // Slow path: write lock
        let mut cache = self.index_trees.write().unwrap();
        // Double-check after acquiring write lock
        if let Some(tree) = cache.get(&tree_name) {
            return Ok(tree.clone());
        }
        let tree = self.db.open_tree(&tree_name)?;
        cache.insert(tree_name, tree.clone());
        Ok(tree)
    }

    /// Scan by a secondary index, returning all atom keys and states matching
    /// the given bound argument values. The `values` slice should match the
    /// positions defined by the index specification. Prefix matching is used,
    /// so shorter `values` will return all atoms whose indexed prefix
    /// matches the provided arguments.
    pub fn scan_by_index(
        &self,
        pred_id: PredId,
        index_name: &str,
        values: &[SymId],
    ) -> Result<Vec<(AtomKey, AtomState)>> {
        // load predicate profile
        let profile = self
            .predicate_registry
            .get_profile(pred_id)?
            .ok_or(StoreError::UnknownPredicate(pred_id))?;
        // find index spec
        let spec = profile
            .indexes
            .iter()
            .find(|idx| idx.name == index_name)
            .ok_or(StoreError::UnknownIndex {
                pred_id,
                index_name: index_name.to_string(),
            })?;
        // ensure provided values length <= positions length
        if values.len() > spec.positions.len() {
            return Err(StoreError::InvalidArity {
                expected: spec.positions.len(),
                found: values.len(),
            });
        }
        // Build prefix
        let mut prefix = Vec::with_capacity(values.len() * 8);
        for &val in values {
            prefix.extend_from_slice(&val.to_be_bytes());
        }
        // Acquire tree (cached)
        let tree = self.get_index_tree(pred_id, &spec.name)?;
        let mut results = Vec::new();
        for item in tree.scan_prefix(prefix) {
            let (key_bytes, _) = item?;
            // Extract state_key by slicing off the prefix used by this index.
            let state_key_len = 8 /*pred_id*/ + profile.arity * 8;
            let key_slice = &key_bytes[key_bytes.len() - state_key_len..];
            let state_key = key_slice.to_vec();
            // decode state key into AtomKey
            let atom_key = decode_state_key(&state_key);
            let state = self.load_state(&state_key)?;
            results.push((atom_key, state));
        }
        Ok(results)
    }
}

/// Apply one aggregation step combining the current state with a single
/// contribution.
fn aggregate_pair(mode: &AggregationMode, state: &AtomState, contrib: &Contribution) -> AtomState {
    match mode {
        AggregationMode::Maximum => AtomState {
            b: state.b.max(contrib.b),
            d: state.d.max(contrib.d),
        },
        AggregationMode::NoisyOr => AtomState {
            b: 1.0 - (1.0 - state.b) * (1.0 - contrib.b),
            d: 1.0 - (1.0 - state.d) * (1.0 - contrib.d),
        },
        AggregationMode::CappedSum => AtomState {
            b: (state.b + contrib.b).min(1.0),
            d: (state.d + contrib.d).min(1.0),
        },
    }
}

/// Encode an [`AtomKey`] into a fixed‑length byte vector suitable for use as a
/// key in sled. Uses big‑endian encoding for numeric fields so that
/// lexicographical order reflects numeric order.
fn encode_state_key(atom_key: &AtomKey) -> Vec<u8> {
    let mut buf = Vec::with_capacity(8 + atom_key.args.len() * 8);
    buf.extend_from_slice(&atom_key.pred_id.to_be_bytes());
    for &arg in &atom_key.args {
        buf.extend_from_slice(&arg.to_be_bytes());
    }
    buf
}

/// Build a contribution key: `state_key || evidence_len (u32 BE) || evidence_id`.
///
/// The 4-byte length field makes the key unambiguous even when the state key
/// is variable-length (depends on arity). Without it, an atom with fewer
/// args could share a prefix with a longer atom's state key, causing
/// `scan_prefix` to return spurious results.
fn encode_contrib_key(state_key: &[u8], evidence_id: &[u8]) -> Vec<u8> {
    let mut buf = Vec::with_capacity(state_key.len() + 4 + evidence_id.len());
    buf.extend_from_slice(state_key);
    buf.extend_from_slice(&(evidence_id.len() as u32).to_be_bytes());
    buf.extend_from_slice(evidence_id);
    buf
}

/// Build the prefix used to scan all contributions for a given atom.
/// This is `state_key` alone — contributions for this atom always start
/// with these bytes followed by the length-prefixed evidence ID.
fn encode_contrib_prefix(state_key: &[u8]) -> Vec<u8> {
    state_key.to_vec()
}

/// Decode a state key back into an [`AtomKey`]. Assumes the key was encoded
/// using [`encode_state_key`].
fn decode_state_key(bytes: &[u8]) -> AtomKey {
    let pred_id = u64::from_be_bytes(bytes[0..8].try_into().unwrap());
    let mut args = Vec::new();
    let mut idx = 8;
    while idx < bytes.len() {
        let sym = u64::from_be_bytes(bytes[idx..idx + 8].try_into().unwrap());
        args.push(sym);
        idx += 8;
    }
    AtomKey { pred_id, args }
}
