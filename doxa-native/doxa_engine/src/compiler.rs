//! Rule compiler: resolves predicate names and entity symbols to numeric
//! IDs via the IDB's symbol store and predicate registry.

use std::collections::HashMap;

use doxa_core::rule::{CompiledGoal, CompiledRule, Goal, Rule};
use doxa_core::types::{AggregationMode, EvidenceMode, IndexSpec, PredId};
use doxa_idb::{DoxaStore, StoreError};

/// Errors that can occur during compilation.
#[derive(Debug)]
pub enum CompileError {
    Store(StoreError),
    UnknownPredicate(String),
}

impl From<StoreError> for CompileError {
    fn from(e: StoreError) -> Self {
        CompileError::Store(e)
    }
}

impl std::fmt::Display for CompileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CompileError::Store(e) => write!(f, "store error: {}", e),
            CompileError::UnknownPredicate(name) => {
                write!(f, "unknown predicate: {}", name)
            }
        }
    }
}

impl std::error::Error for CompileError {}

pub type Result<T> = std::result::Result<T, CompileError>;

/// Compile a set of rules against the IDB store, resolving all predicate
/// names to IDs and registering predicates that don't yet exist.
///
/// Returns compiled rules and a mapping from predicate name to PredId.
pub fn compile_rules(
    store: &DoxaStore,
    rules: &[Rule],
    pred_configs: &HashMap<String, PredConfig>,
) -> Result<(Vec<CompiledRule>, HashMap<String, PredId>)> {
    let mut pred_map: HashMap<String, PredId> = HashMap::new();
    let mut compiled = Vec::with_capacity(rules.len());

    // First pass: ensure all predicates are registered
    for rule in rules {
        ensure_predicate(
            store,
            &rule.head_pred_name,
            rule.head_pred_arity,
            pred_configs,
            &mut pred_map,
        )?;
        for goal in &rule.body {
            if let Goal::Atom(ag) = goal {
                ensure_predicate(
                    store,
                    &ag.pred_name,
                    ag.pred_arity,
                    pred_configs,
                    &mut pred_map,
                )?;
            }
        }
    }

    // Second pass: compile rules
    for rule in rules {
        let head_pred_id = pred_map[&rule.head_pred_name];
        let body = rule
            .body
            .iter()
            .map(|g| compile_goal(g, &pred_map))
            .collect::<Result<Vec<_>>>()?;

        compiled.push(CompiledRule {
            id: rule.id,
            head_pred_id,
            head_arity: rule.head_pred_arity,
            head_args: rule.head_args.clone(),
            body,
            b: rule.b,
            d: rule.d,
        });
    }

    Ok((compiled, pred_map))
}

/// Per-predicate configuration hints for the compiler.
#[derive(Debug, Clone)]
pub struct PredConfig {
    pub aggregation: AggregationMode,
    pub evidence_mode: EvidenceMode,
    pub indexes: Vec<IndexSpec>,
}

impl Default for PredConfig {
    fn default() -> Self {
        Self {
            aggregation: AggregationMode::default(),
            evidence_mode: EvidenceMode::default(),
            indexes: Vec::new(),
        }
    }
}

fn ensure_predicate(
    store: &DoxaStore,
    name: &str,
    arity: usize,
    configs: &HashMap<String, PredConfig>,
    pred_map: &mut HashMap<String, PredId>,
) -> Result<()> {
    if pred_map.contains_key(name) {
        return Ok(());
    }
    let config = configs.get(name).cloned().unwrap_or_default();
    let profile = store.predicate_registry.register_predicate(
        name,
        arity,
        config.aggregation,
        config.evidence_mode,
        config.indexes,
    )?;
    pred_map.insert(name.to_string(), profile.pred_id);
    Ok(())
}

fn compile_goal(goal: &Goal, pred_map: &HashMap<String, PredId>) -> Result<CompiledGoal> {
    match goal {
        Goal::Atom(ag) => {
            let pred_id = *pred_map
                .get(&ag.pred_name)
                .ok_or_else(|| CompileError::UnknownPredicate(ag.pred_name.clone()))?;
            Ok(CompiledGoal::Atom {
                pred_id,
                arity: ag.pred_arity,
                negated: ag.negated,
                args: ag.args.clone(),
            })
        }
        Goal::Builtin(bg) => Ok(CompiledGoal::Builtin {
            op: bg.op.clone(),
            args: bg.args.clone(),
        }),
    }
}
