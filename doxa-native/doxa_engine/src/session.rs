//! Engine session: the top-level API for loading an EDB branch,
//! evaluating rules to fixpoint, and querying derived atom states.

use std::collections::HashMap;
use std::path::Path;

use doxa_core::semantics::EpistemicSemantics;
use doxa_core::types::{
    AggregationMode, BelnapStatus, EpistemicState, EvidenceMode, PredId, SymId,
};

use doxa_edb::{EdbStore, GroundFact};
use doxa_idb::{AtomKey, Contribution, DoxaStore};

use crate::compiler::{self, CompileError, PredConfig};
use crate::eval::{self, EvalError, EvalResult};

/// Top-level engine errors.
#[derive(Debug)]
pub enum EngineError {
    Idb(doxa_idb::StoreError),
    Edb(doxa_edb::EdbError),
    Compile(CompileError),
    Eval(EvalError),
}

impl From<doxa_idb::StoreError> for EngineError {
    fn from(e: doxa_idb::StoreError) -> Self {
        EngineError::Idb(e)
    }
}

impl From<doxa_edb::EdbError> for EngineError {
    fn from(e: doxa_edb::EdbError) -> Self {
        EngineError::Edb(e)
    }
}

impl From<CompileError> for EngineError {
    fn from(e: CompileError) -> Self {
        EngineError::Compile(e)
    }
}

impl From<EvalError> for EngineError {
    fn from(e: EvalError) -> Self {
        EngineError::Eval(e)
    }
}

impl std::fmt::Display for EngineError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EngineError::Idb(e) => write!(f, "IDB error: {}", e),
            EngineError::Edb(e) => write!(f, "EDB error: {}", e),
            EngineError::Compile(e) => write!(f, "compile error: {}", e),
            EngineError::Eval(e) => write!(f, "eval error: {}", e),
        }
    }
}

impl std::error::Error for EngineError {}

pub type Result<T> = std::result::Result<T, EngineError>;

/// One answer row from a query.
#[derive(Debug, Clone)]
pub struct QueryAnswer {
    /// Variable bindings for projected variables.
    pub bindings: HashMap<String, SymId>,
    /// Belief value of the grounded answer.
    pub b: f64,
    /// Doubt value of the grounded answer.
    pub d: f64,
    /// Belnap four-valued status.
    pub belnap_status: BelnapStatus,
}

/// A flat answer row from `query_all` — returns all atoms of a predicate.
#[derive(Debug, Clone)]
pub struct PredicateAnswer {
    pub args: Vec<SymId>,
    pub b: f64,
    pub d: f64,
    pub status: BelnapStatus,
}

/// Result of evaluating a query.
#[derive(Debug)]
pub struct QueryResult {
    pub answers: Vec<QueryAnswer>,
    pub eval_stats: Option<EvalResult>,
}

/// An engine session operates on a specific EDB branch, evaluates rules
/// into the IDB, and answers queries against the derived state.
pub struct EngineSession {
    pub idb: DoxaStore,
    pub edb: EdbStore,
    pub semantics: EpistemicSemantics,
    pred_configs: HashMap<String, PredConfig>,
    pred_map: HashMap<String, PredId>,
}

impl EngineSession {
    /// Create a new engine session with separate EDB and IDB paths.
    pub fn open(edb_path: impl AsRef<Path>, idb_path: impl AsRef<Path>) -> Result<Self> {
        let edb = EdbStore::open(edb_path)?;
        let idb = DoxaStore::open(idb_path)?;
        Ok(Self {
            idb,
            edb,
            semantics: EpistemicSemantics::default(),
            pred_configs: HashMap::new(),
            pred_map: HashMap::new(),
        })
    }

    /// Create a fully in-memory session (no filesystem I/O).
    /// Uses sled's temporary mode for both EDB and IDB.
    pub fn open_temporary() -> Result<Self> {
        let edb = EdbStore::open_temporary()?;
        let idb = DoxaStore::open_temporary()?;
        Ok(Self {
            idb,
            edb,
            semantics: EpistemicSemantics::default(),
            pred_configs: HashMap::new(),
            pred_map: HashMap::new(),
        })
    }

    /// Set the epistemic semantics configuration.
    pub fn with_semantics(mut self, semantics: EpistemicSemantics) -> Self {
        self.semantics = semantics;
        self
    }

    /// Set a per-predicate configuration hint.
    pub fn configure_predicate(
        &mut self,
        name: &str,
        aggregation: AggregationMode,
        evidence_mode: EvidenceMode,
    ) {
        self.pred_configs.insert(
            name.to_string(),
            PredConfig {
                aggregation,
                evidence_mode,
                indexes: Vec::new(),
            },
        );
    }

    /// Load EDB facts for a branch into the IDB, then evaluate all rules
    /// to fixpoint.
    pub fn materialize(&mut self, branch: &str) -> Result<EvalResult> {
        self.materialize_with_options(branch, None)
    }

    /// Like `materialize`, but with an optional max_depth to limit
    /// fixpoint iterations for recursive SCCs.
    pub fn materialize_with_options(
        &mut self,
        branch: &str,
        max_depth: Option<usize>,
    ) -> Result<EvalResult> {
        // 1. Load EDB facts
        let facts = self.edb.get_facts(branch, None)?;
        let rules = self.edb.get_rules(branch, None)?;

        // 2. Register predicates and load facts into IDB
        self.load_facts_into_idb(&facts)?;

        // 3. Compile rules (merge pred_map so fact-only predicates survive)
        let (compiled_rules, rule_pred_map) =
            compiler::compile_rules(&self.idb, &rules, &self.pred_configs)?;
        self.pred_map.extend(rule_pred_map);

        // 4. Evaluate to fixpoint
        let result = eval::evaluate_to_fixpoint(
            &self.idb,
            &compiled_rules,
            &self.semantics,
            &self.pred_map,
            max_depth,
        )?;

        Ok(result)
    }

    /// Load ground facts from the EDB into the IDB as base contributions.
    fn load_facts_into_idb(&mut self, facts: &[GroundFact]) -> Result<()> {
        for fact in facts {
            // Ensure predicate is registered
            let config = self
                .pred_configs
                .get(&fact.pred_name)
                .cloned()
                .unwrap_or_default();

            let profile = self.idb.predicate_registry.register_predicate(
                &fact.pred_name,
                fact.pred_arity,
                config.aggregation,
                config.evidence_mode,
                config.indexes.clone(),
            )?;

            self.pred_map
                .insert(fact.pred_name.clone(), profile.pred_id);

            let atom_key = AtomKey::new(profile.pred_id, fact.args.clone());
            let evidence_id = format!("edb_{}", fact.event_id).into_bytes();

            let contribution = Contribution {
                b: fact.b,
                d: fact.d,
                evidence_id: Some(evidence_id),
            };

            self.idb.upsert_atom(&atom_key, &contribution)?;
        }

        Ok(())
    }

    /// Query the IDB for the current state of a specific grounded atom.
    /// Returns an empty epistemic state if the predicate or atom is unknown.
    pub fn get_atom_state(&self, pred_name: &str, args: &[SymId]) -> Result<EpistemicState> {
        let pred_id = match self.pred_map.get(pred_name).copied() {
            Some(id) => id,
            None => return Ok(EpistemicState::empty()),
        };

        let key = AtomKey::new(pred_id, args.to_vec());
        let state = self.idb.get_state(&key)?;
        Ok(EpistemicState::new(state.b, state.d))
    }

    /// Query the IDB using a goal pattern. Returns answer rows with
    /// variable bindings and epistemic state.
    pub fn query(
        &self,
        pred_name: &str,
        args: &[doxa_core::types::Term],
    ) -> Result<Vec<QueryAnswer>> {
        let pred_id = self.pred_map.get(pred_name).copied().ok_or_else(|| {
            EngineError::Compile(CompileError::UnknownPredicate(pred_name.to_string()))
        })?;

        // If all args are ground, do a point lookup
        let all_ground = args.iter().all(|t| t.is_ground());
        if all_ground {
            let sym_ids: Vec<SymId> = args
                .iter()
                .map(|t| crate::join::resolve_term(t, &HashMap::new()).unwrap())
                .collect();
            let key = AtomKey::new(pred_id, sym_ids);
            let state = self.idb.get_state(&key)?;
            let es = EpistemicState::new(state.b, state.d);
            return Ok(vec![QueryAnswer {
                bindings: HashMap::new(),
                b: state.b,
                d: state.d,
                belnap_status: es.belnap_status(),
            }]);
        }

        // Otherwise, use index scan
        let bound_positions: Vec<usize> = args
            .iter()
            .enumerate()
            .filter_map(|(i, t)| if t.is_ground() { Some(i) } else { None })
            .collect();

        let bound_values: Vec<SymId> = bound_positions
            .iter()
            .map(|&i| crate::join::resolve_term(&args[i], &HashMap::new()).unwrap())
            .collect();

        // Find matching index
        let profile = self
            .idb
            .predicate_registry
            .get_profile(pred_id)?
            .ok_or_else(|| EngineError::Idb(doxa_idb::StoreError::UnknownPredicate(pred_id)))?;

        for idx in &profile.indexes {
            if idx.positions == bound_positions {
                let results = self.idb.scan_by_index(pred_id, &idx.name, &bound_values)?;
                let answers: Vec<QueryAnswer> = results
                    .into_iter()
                    .filter(|(_, state)| state.b > 1e-12 || state.d > 1e-12)
                    .map(|(atom_key, state)| {
                        let mut bindings = HashMap::new();
                        for (i, term) in args.iter().enumerate() {
                            if let doxa_core::types::Term::Var(name) = term {
                                bindings.insert(name.clone(), atom_key.args[i]);
                            }
                        }
                        let es = EpistemicState::new(state.b, state.d);
                        QueryAnswer {
                            bindings,
                            b: state.b,
                            d: state.d,
                            belnap_status: es.belnap_status(),
                        }
                    })
                    .collect();
                return Ok(answers);
            }
        }

        // No suitable index found — return empty (conservative)
        Ok(Vec::new())
    }

    /// Return all atoms stored for a predicate. Useful for enumerating
    /// all derived facts.
    pub fn query_all(&self, pred_name: &str) -> Result<Vec<PredicateAnswer>> {
        let pred_id = match self.pred_map.get(pred_name).copied() {
            Some(id) => id,
            None => return Ok(Vec::new()),
        };

        let atoms = self.idb.scan_predicate(pred_id)?;
        let mut answers = Vec::new();
        for (atom_key, atom_state) in atoms {
            if atom_state.b <= 1e-12 && atom_state.d <= 1e-12 {
                continue;
            }
            let es = EpistemicState::new(atom_state.b, atom_state.d);
            answers.push(PredicateAnswer {
                args: atom_key.args,
                b: atom_state.b,
                d: atom_state.d,
                status: es.belnap_status(),
            });
        }
        Ok(answers)
    }

    /// Intern a symbol text into the IDB's symbol store.
    pub fn intern(&self, text: &str) -> Result<SymId> {
        Ok(self.idb.symbol_store.get_or_insert(text)?)
    }

    /// Look up the text for a symbol ID.
    pub fn symbol_text(&self, id: SymId) -> Result<Option<String>> {
        Ok(self.idb.symbol_store.get_text(id)?)
    }

    /// Flush both EDB and IDB to disk.
    pub fn flush_all(&self) -> Result<()> {
        self.edb.flush_all()?;
        self.idb.flush_all()?;
        Ok(())
    }
}
