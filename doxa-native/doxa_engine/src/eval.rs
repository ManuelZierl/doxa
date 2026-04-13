//! Semi-naive fixpoint evaluation engine.
//!
//! The evaluator processes rules SCC-by-SCC in topological order.
//! Non-recursive SCCs are evaluated in a single pass. Recursive SCCs
//! use delta iteration: each round only considers atoms that changed in
//! the previous round, stopping when no more changes occur.

use std::collections::{HashMap, HashSet};

use doxa_core::rule::CompiledRule;
use doxa_core::scc::compute_sccs;
use doxa_core::semantics::EpistemicSemantics;
use doxa_core::types::PredId;

use doxa_idb::{
    AtomKey, Contribution, DoxaStore, StoreError,
};

use crate::join::{self, BodyMatch, Subst};

/// Maximum number of fixpoint iterations before we bail out.
const MAX_ITERATIONS: usize = 1000;

/// Result of evaluating a set of rules to fixpoint.
#[derive(Debug)]
pub struct EvalResult {
    /// Number of fixpoint iterations performed (across all SCCs).
    pub total_iterations: usize,
    /// Number of atoms whose state changed.
    pub atoms_changed: usize,
}

/// Errors during evaluation.
#[derive(Debug)]
pub enum EvalError {
    Store(StoreError),
    MaxIterationsExceeded,
}

impl From<StoreError> for EvalError {
    fn from(e: StoreError) -> Self {
        EvalError::Store(e)
    }
}

impl std::fmt::Display for EvalError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EvalError::Store(e) => write!(f, "store error: {}", e),
            EvalError::MaxIterationsExceeded => {
                write!(f, "fixpoint did not converge within {} iterations", MAX_ITERATIONS)
            }
        }
    }
}

impl std::error::Error for EvalError {}

pub type Result<T> = std::result::Result<T, EvalError>;

/// Evaluate all compiled rules to fixpoint using semi-naive iteration.
///
/// Rules are grouped into SCCs and evaluated in topological order.
/// The IDB store is updated in place.
pub fn evaluate_to_fixpoint(
    store: &DoxaStore,
    rules: &[CompiledRule],
    semantics: &EpistemicSemantics,
    pred_map: &HashMap<String, PredId>,
    max_depth: Option<usize>,
) -> Result<EvalResult> {
    // Build the uncompiled rule representation for SCC analysis
    let core_rules: Vec<doxa_core::rule::Rule> = rules
        .iter()
        .map(|cr| compiled_to_core_rule(cr, pred_map))
        .collect();

    let sccs = compute_sccs(&core_rules);
    let mut total_iterations = 0;
    let mut atoms_changed = 0;

    for scc in &sccs {
        // Collect rules whose head predicate is in this SCC
        let scc_preds: HashSet<&str> = scc.predicates.iter().map(|s| s.as_str()).collect();
        let scc_rules: Vec<&CompiledRule> = rules
            .iter()
            .filter(|r| {
                // Find head pred name from pred_map (reverse lookup)
                pred_map
                    .iter()
                    .any(|(name, &id)| id == r.head_pred_id && scc_preds.contains(name.as_str()))
            })
            .collect();

        if scc_rules.is_empty() {
            continue;
        }

        if scc.recursive {
            let (iters, changed) =
                evaluate_recursive_scc(store, &scc_rules, semantics, max_depth)?;
            total_iterations += iters;
            atoms_changed += changed;
        } else {
            let changed = evaluate_stratum(store, &scc_rules, semantics)?;
            total_iterations += 1;
            atoms_changed += changed;
        }
    }

    Ok(EvalResult {
        total_iterations,
        atoms_changed,
    })
}

/// Evaluate a non-recursive SCC (single pass).
fn evaluate_stratum(
    store: &DoxaStore,
    rules: &[&CompiledRule],
    semantics: &EpistemicSemantics,
) -> Result<usize> {
    let mut changed = 0;

    for rule in rules {
        changed += fire_rule(store, rule, semantics)?;
    }

    Ok(changed)
}

/// Evaluate a recursive SCC using semi-naive delta iteration.
fn evaluate_recursive_scc(
    store: &DoxaStore,
    rules: &[&CompiledRule],
    semantics: &EpistemicSemantics,
    max_depth: Option<usize>,
) -> Result<(usize, usize)> {
    let limit = max_depth.unwrap_or(MAX_ITERATIONS);
    let mut iterations = 0;
    let mut total_changed = 0;

    // Initial pass: fire all rules once
    let mut changed_this_round = 0;
    for rule in rules {
        changed_this_round += fire_rule(store, rule, semantics)?;
    }
    total_changed += changed_this_round;
    iterations += 1;

    // Delta iterations: keep going while something changes
    while changed_this_round > 0 {
        if iterations >= limit {
            if max_depth.is_some() {
                break; // Soft limit: just stop
            }
            return Err(EvalError::MaxIterationsExceeded);
        }

        changed_this_round = 0;
        for rule in rules {
            changed_this_round += fire_rule(store, rule, semantics)?;
        }
        total_changed += changed_this_round;
        iterations += 1;
    }

    Ok((iterations, total_changed))
}

/// Fire a single rule: evaluate its body, ground the head for each
/// successful substitution, and upsert the contribution. Returns the
/// number of atoms whose state actually changed.
fn fire_rule(
    store: &DoxaStore,
    rule: &CompiledRule,
    semantics: &EpistemicSemantics,
) -> Result<usize> {
    let mut changed = 0;

    // Start with a single empty substitution
    let initial = vec![BodyMatch {
        subst: Subst::new(),
        body_b: 1.0,
        body_d: 0.0,
    }];

    // Evaluate body goals left-to-right
    let mut current = initial;
    for goal in &rule.body {
        current = join::eval_goal(store, goal, &current);
        if current.is_empty() {
            return Ok(0);
        }
    }

    // For each successful body match, derive the head atom
    for bm in &current {
        let head_args = match join::ground_head(&rule.head_args, &bm.subst) {
            Some(args) => args,
            None => continue, // Ungrounded head — skip
        };

        let atom_key = AtomKey::new(rule.head_pred_id, head_args);

        // Compute applicability based on semantics
        let applicability = compute_applicability(bm, semantics);
        if applicability <= 0.0 {
            continue;
        }

        let contrib_b = applicability * rule.b;
        let contrib_d = applicability * rule.d;

        // Build evidence ID from rule ID + substitution for uniqueness
        let evidence_id = make_evidence_id(rule.id, &bm.subst);

        let old_state = store.get_state(&atom_key)?;
        let contribution = Contribution {
            b: contrib_b,
            d: contrib_d,
            evidence_id: Some(evidence_id),
        };

        let new_state = store.upsert_atom(&atom_key, &contribution)?;

        if !old_state.approx_eq(&new_state) {
            changed += 1;
        }
    }

    Ok(changed)
}

/// Compute rule applicability based on body truth and semantics.
fn compute_applicability(
    bm: &BodyMatch,
    semantics: &EpistemicSemantics,
) -> f64 {
    use doxa_core::semantics::RuleApplicabilitySemantics;

    let a = match semantics.rule_applicability {
        RuleApplicabilitySemantics::BodyTruthOnly => bm.body_b,
        RuleApplicabilitySemantics::BodyTruthDiscountedByBodyFalsity => {
            bm.body_b * (1.0 - bm.body_d)
        }
    };

    a.min(1.0).max(0.0)
}

/// Create a deterministic evidence ID from a rule ID and substitution.
fn make_evidence_id(rule_id: u64, subst: &Subst) -> Vec<u8> {
    let mut buf = Vec::new();
    buf.extend_from_slice(&rule_id.to_be_bytes());

    // Sort by variable name for determinism
    let mut pairs: Vec<_> = subst.iter().collect();
    pairs.sort_by_key(|(k, _)| *k);

    for (name, &val) in pairs {
        buf.extend_from_slice(name.as_bytes());
        buf.push(0); // separator
        buf.extend_from_slice(&val.to_be_bytes());
    }

    buf
}

/// Helper: reverse-map a CompiledRule back to a core::Rule for SCC analysis.
/// Only the head/body predicate names matter here.
fn compiled_to_core_rule(
    cr: &CompiledRule,
    pred_map: &HashMap<String, PredId>,
) -> doxa_core::rule::Rule {
    // Reverse-lookup: PredId → name
    let rev_map: HashMap<PredId, &str> = pred_map
        .iter()
        .map(|(name, &id)| (id, name.as_str()))
        .collect();

    let head_name = rev_map
        .get(&cr.head_pred_id)
        .map(|s| s.to_string())
        .unwrap_or_else(|| format!("__pred_{}", cr.head_pred_id));

    let body = cr
        .body
        .iter()
        .map(|g| match g {
            doxa_core::rule::CompiledGoal::Atom {
                pred_id,
                arity,
                negated,
                args,
            } => {
                let name = rev_map
                    .get(pred_id)
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| format!("__pred_{}", pred_id));
                doxa_core::rule::Goal::Atom(doxa_core::rule::AtomGoal {
                    pred_name: name,
                    pred_arity: *arity,
                    negated: *negated,
                    args: args.clone(),
                })
            }
            doxa_core::rule::CompiledGoal::Builtin { op, args } => {
                doxa_core::rule::Goal::Builtin(doxa_core::rule::BuiltinGoal {
                    op: op.clone(),
                    args: args.clone(),
                })
            }
        })
        .collect();

    doxa_core::rule::Rule {
        id: cr.id,
        head_pred_name: head_name,
        head_pred_arity: cr.head_arity,
        head_args: cr.head_args.clone(),
        body,
        b: cr.b,
        d: cr.d,
    }
}
