//! Join and substitution logic for rule body evaluation.
//!
//! A substitution maps variable names to ground symbol IDs. Rule body
//! goals are evaluated left-to-right, extending the substitution at each
//! step. When all goals succeed, the substitution is applied to the head
//! to produce a grounded derived atom.

use std::collections::HashMap;

use doxa_core::rule::{BuiltinOp, CompiledGoal};
use doxa_core::types::{PredId, SymId, Term};
use doxa_idb::{AtomKey, AtomState, DoxaStore};

/// A substitution: variable name → ground symbol ID.
pub type Subst = HashMap<String, SymId>;

/// One successful body match: the substitution, accumulated belief, and
/// accumulated doubt from the matched body atoms.
#[derive(Debug, Clone)]
pub struct BodyMatch {
    pub subst: Subst,
    /// Accumulated body truth (product of body-atom beliefs).
    pub body_b: f64,
    /// Accumulated body falsity (noisy-or of body-atom doubts).
    pub body_d: f64,
}

/// Resolve a term under a substitution. Returns None if a variable is
/// unbound (should not happen in well-formed rules after left-to-right
/// evaluation, but we handle it gracefully).
pub fn resolve_term(term: &Term, subst: &Subst) -> Option<SymId> {
    match term {
        Term::Var(name) => subst.get(name).copied(),
        Term::Entity(id) => Some(*id),
        Term::Str(id) => Some(*id),
        Term::Int(v) => Some(*v as SymId),
        Term::Float(bits) => Some(*bits),
    }
}

/// Evaluate a single compiled goal against the IDB, extending the
/// substitutions. Returns zero or more extended substitutions.
///
/// For positive atom goals, this scans the IDB for matching facts.
/// For negated atom goals, it succeeds only if no match exists.
/// For builtins, it filters the current substitution.
pub fn eval_goal(store: &DoxaStore, goal: &CompiledGoal, incoming: &[BodyMatch]) -> Vec<BodyMatch> {
    match goal {
        CompiledGoal::Atom {
            pred_id,
            arity,
            negated,
            args,
        } => eval_atom_goal(store, *pred_id, *arity, *negated, args, incoming),
        CompiledGoal::Builtin { op, args } => eval_builtin_goal(store, op, args, incoming),
    }
}

/// Evaluate a positive or negated atom goal.
fn eval_atom_goal(
    store: &DoxaStore,
    pred_id: PredId,
    _arity: usize,
    negated: bool,
    args: &[Term],
    incoming: &[BodyMatch],
) -> Vec<BodyMatch> {
    let mut result = Vec::new();

    for bm in incoming {
        // Try to resolve as many args as possible for a point lookup
        let resolved: Vec<Option<SymId>> =
            args.iter().map(|t| resolve_term(t, &bm.subst)).collect();

        let all_bound = resolved.iter().all(|o| o.is_some());

        if all_bound {
            // All arguments are bound → point lookup
            let bound_args: Vec<SymId> = resolved.into_iter().map(|o| o.unwrap()).collect();
            let key = AtomKey::new(pred_id, bound_args);
            let state = store.get_state(&key).unwrap_or(AtomState::empty());

            let has_support = state.b > 1e-12;

            if negated {
                if !has_support {
                    // Negation succeeds: atom has no support
                    result.push(bm.clone());
                }
            } else if has_support {
                // Positive match
                result.push(BodyMatch {
                    subst: bm.subst.clone(),
                    body_b: bm.body_b * state.b,
                    body_d: 1.0 - (1.0 - bm.body_d) * (1.0 - state.d),
                });
            }
        } else {
            // Some or all arguments are unbound → scan all atoms for this
            // predicate and unify each one against the current substitution.
            let atoms = store.scan_predicate(pred_id).unwrap_or_default();

            if negated {
                // NAF: succeed only if no atom with support unifies
                let any_match = atoms.iter().any(|(ak, st)| {
                    st.b > 1e-12 && unify_args(args, &ak.args, &bm.subst).is_some()
                });
                if !any_match {
                    result.push(bm.clone());
                }
            } else {
                for (atom_key, atom_state) in &atoms {
                    if atom_state.b <= 1e-12 {
                        continue;
                    }
                    if let Some(ext_subst) = unify_args(args, &atom_key.args, &bm.subst) {
                        result.push(BodyMatch {
                            subst: ext_subst,
                            body_b: bm.body_b * atom_state.b,
                            body_d: 1.0 - (1.0 - bm.body_d) * (1.0 - atom_state.d),
                        });
                    }
                }
            }
        }
    }

    result
}

/// Attempt to unify rule args (which may contain variables) with a
/// ground atom's args, extending the given substitution. Returns None
/// if unification fails (a variable is already bound to a different value).
fn unify_args(rule_args: &[Term], ground_args: &[SymId], base_subst: &Subst) -> Option<Subst> {
    if rule_args.len() != ground_args.len() {
        return None;
    }
    let mut subst = base_subst.clone();
    for (term, &ground_val) in rule_args.iter().zip(ground_args.iter()) {
        match term {
            Term::Var(name) => {
                if let Some(&existing) = subst.get(name) {
                    if existing != ground_val {
                        return None; // Conflict
                    }
                } else {
                    subst.insert(name.clone(), ground_val);
                }
            }
            Term::Entity(id) | Term::Str(id) => {
                if *id != ground_val {
                    return None;
                }
            }
            Term::Int(v) => {
                if (*v as SymId) != ground_val {
                    return None;
                }
            }
            Term::Float(bits) => {
                if *bits != ground_val {
                    return None;
                }
            }
        }
    }
    Some(subst)
}

/// Resolve a term to an f64 value, looking up SymIds in the symbol store.
fn resolve_to_f64(store: &DoxaStore, term: &Term, subst: &Subst) -> Option<f64> {
    match term {
        Term::Int(v) => Some(*v as f64),
        Term::Float(bits) => Some(f64::from_bits(*bits)),
        _ => {
            let sym_id = resolve_term(term, subst)?;
            let text = store.symbol_store.get_text(sym_id).ok()??;
            text.parse::<f64>().ok()
        }
    }
}

/// Evaluate a builtin goal (comparison, arithmetic, equality).
fn eval_builtin_goal(
    store: &DoxaStore,
    op: &BuiltinOp,
    args: &[Term],
    incoming: &[BodyMatch],
) -> Vec<BodyMatch> {
    match op {
        BuiltinOp::Eq => eval_eq(args, incoming),
        BuiltinOp::Ne => eval_ne(args, incoming),
        BuiltinOp::Lt | BuiltinOp::Leq | BuiltinOp::Gt | BuiltinOp::Geq => {
            eval_comparison(store, op, args, incoming)
        }
        BuiltinOp::Add | BuiltinOp::Sub | BuiltinOp::Mul | BuiltinOp::Div => {
            eval_arithmetic(store, op, args, incoming)
        }
        BuiltinOp::Between => eval_between(store, args, incoming),
        BuiltinOp::Int
        | BuiltinOp::String
        | BuiltinOp::Float
        | BuiltinOp::Entity
        | BuiltinOp::PredicateRef
        | BuiltinOp::Date
        | BuiltinOp::DateTime
        | BuiltinOp::Duration => eval_type_builtin(store, op, args, incoming),
    }
}

/// eq(A, B): equality check or variable binding.
fn eval_eq(args: &[Term], incoming: &[BodyMatch]) -> Vec<BodyMatch> {
    if args.len() != 2 {
        return Vec::new();
    }
    let mut result = Vec::new();
    for bm in incoming {
        let a = resolve_term(&args[0], &bm.subst);
        let b = resolve_term(&args[1], &bm.subst);
        let a_var = match &args[0] {
            Term::Var(name) if !bm.subst.contains_key(name) => Some(name.as_str()),
            _ => None,
        };
        let b_var = match &args[1] {
            Term::Var(name) if !bm.subst.contains_key(name) => Some(name.as_str()),
            _ => None,
        };
        match (a, b) {
            (Some(av), Some(bv)) => {
                if av == bv {
                    result.push(bm.clone());
                }
            }
            (Some(av), None) if b_var.is_some() => {
                let mut s = bm.subst.clone();
                s.insert(b_var.unwrap().to_string(), av);
                result.push(BodyMatch {
                    subst: s,
                    body_b: bm.body_b,
                    body_d: bm.body_d,
                });
            }
            (None, Some(bv)) if a_var.is_some() => {
                let mut s = bm.subst.clone();
                s.insert(a_var.unwrap().to_string(), bv);
                result.push(BodyMatch {
                    subst: s,
                    body_b: bm.body_b,
                    body_d: bm.body_d,
                });
            }
            _ => {} // both unbound
        }
    }
    result
}

/// ne(A, B): inequality check on SymIds.
fn eval_ne(args: &[Term], incoming: &[BodyMatch]) -> Vec<BodyMatch> {
    if args.len() != 2 {
        return Vec::new();
    }
    incoming
        .iter()
        .filter(|bm| {
            match (
                resolve_term(&args[0], &bm.subst),
                resolve_term(&args[1], &bm.subst),
            ) {
                (Some(a), Some(b)) => a != b,
                _ => false,
            }
        })
        .cloned()
        .collect()
}

/// Numeric comparison: lt, leq, gt, geq.
fn eval_comparison(
    store: &DoxaStore,
    op: &BuiltinOp,
    args: &[Term],
    incoming: &[BodyMatch],
) -> Vec<BodyMatch> {
    if args.len() != 2 {
        return Vec::new();
    }
    incoming
        .iter()
        .filter(|bm| {
            let a = resolve_to_f64(store, &args[0], &bm.subst);
            let b = resolve_to_f64(store, &args[1], &bm.subst);
            match (a, b) {
                (Some(av), Some(bv)) => match op {
                    BuiltinOp::Lt => av < bv,
                    BuiltinOp::Leq => av <= bv,
                    BuiltinOp::Gt => av > bv,
                    BuiltinOp::Geq => av >= bv,
                    _ => false,
                },
                _ => false,
            }
        })
        .cloned()
        .collect()
}

/// Arithmetic: add, sub, mul, div — 3 args, compute the unbound one.
fn eval_arithmetic(
    store: &DoxaStore,
    op: &BuiltinOp,
    args: &[Term],
    incoming: &[BodyMatch],
) -> Vec<BodyMatch> {
    if args.len() != 3 {
        return Vec::new();
    }
    let mut result = Vec::new();
    for bm in incoming {
        let vals: Vec<Option<f64>> = args
            .iter()
            .map(|t| resolve_to_f64(store, t, &bm.subst))
            .collect();
        // Find the single unbound variable (if any)
        let unbound: Vec<(usize, &str)> = args
            .iter()
            .enumerate()
            .filter_map(|(i, t)| match t {
                Term::Var(name) if !bm.subst.contains_key(name) => Some((i, name.as_str())),
                _ => None,
            })
            .collect();

        let bound_count = vals.iter().filter(|v| v.is_some()).count();

        if bound_count == 3 {
            // All bound — verify the relation
            let (a, b, c) = (vals[0].unwrap(), vals[1].unwrap(), vals[2].unwrap());
            let ok = match op {
                BuiltinOp::Add => (a + b - c).abs() < 1e-9,
                BuiltinOp::Sub => (a - b - c).abs() < 1e-9,
                BuiltinOp::Mul => (a * b - c).abs() < 1e-9,
                BuiltinOp::Div => b.abs() > 1e-12 && (a / b - c).abs() < 1e-9,
                _ => false,
            };
            if ok {
                result.push(bm.clone());
            }
        } else if bound_count == 2 && unbound.len() == 1 {
            let (ui, uname) = unbound[0];
            let computed = match (op, ui) {
                (BuiltinOp::Add, 2) => Some(vals[0].unwrap() + vals[1].unwrap()),
                (BuiltinOp::Add, 0) => Some(vals[2].unwrap() - vals[1].unwrap()),
                (BuiltinOp::Add, 1) => Some(vals[2].unwrap() - vals[0].unwrap()),
                (BuiltinOp::Sub, 2) => Some(vals[0].unwrap() - vals[1].unwrap()),
                (BuiltinOp::Sub, 0) => Some(vals[2].unwrap() + vals[1].unwrap()),
                (BuiltinOp::Sub, 1) => Some(vals[0].unwrap() - vals[2].unwrap()),
                (BuiltinOp::Mul, 2) => Some(vals[0].unwrap() * vals[1].unwrap()),
                (BuiltinOp::Mul, 0) => {
                    let d = vals[1].unwrap();
                    if d.abs() > 1e-12 {
                        Some(vals[2].unwrap() / d)
                    } else {
                        None
                    }
                }
                (BuiltinOp::Mul, 1) => {
                    let d = vals[0].unwrap();
                    if d.abs() > 1e-12 {
                        Some(vals[2].unwrap() / d)
                    } else {
                        None
                    }
                }
                (BuiltinOp::Div, 2) => {
                    let d = vals[1].unwrap();
                    if d.abs() > 1e-12 {
                        Some(vals[0].unwrap() / d)
                    } else {
                        None
                    }
                }
                (BuiltinOp::Div, 0) => Some(vals[2].unwrap() * vals[1].unwrap()),
                (BuiltinOp::Div, 1) => {
                    let d = vals[2].unwrap();
                    if d.abs() > 1e-12 {
                        Some(vals[0].unwrap() / d)
                    } else {
                        None
                    }
                }
                _ => None,
            };
            if let Some(val) = computed {
                // Format result: integer if exact, else float
                let text = if val == val.floor() && val.abs() < i64::MAX as f64 {
                    format!("{}", val as i64)
                } else {
                    format!("{}", val)
                };
                if let Ok(sym_id) = store.symbol_store.get_or_insert(&text) {
                    let mut s = bm.subst.clone();
                    s.insert(uname.to_string(), sym_id);
                    result.push(BodyMatch {
                        subst: s,
                        body_b: bm.body_b,
                        body_d: bm.body_d,
                    });
                }
            }
        }
    }
    result
}

/// between(X, Low, High): check Low <= X <= High.
fn eval_between(store: &DoxaStore, args: &[Term], incoming: &[BodyMatch]) -> Vec<BodyMatch> {
    if args.len() != 3 {
        return Vec::new();
    }
    incoming
        .iter()
        .filter(|bm| {
            let x = resolve_to_f64(store, &args[0], &bm.subst);
            let lo = resolve_to_f64(store, &args[1], &bm.subst);
            let hi = resolve_to_f64(store, &args[2], &bm.subst);
            match (x, lo, hi) {
                (Some(xv), Some(lov), Some(hiv)) => lov <= xv && xv <= hiv,
                _ => false,
            }
        })
        .cloned()
        .collect()
}

fn resolve_to_text(store: &DoxaStore, term: &Term, subst: &Subst) -> Option<String> {
    match term {
        Term::Var(_) => {
            let sym_id = resolve_term(term, subst)?;
            store.symbol_store.get_text(sym_id).ok()?
        }
        Term::Entity(sym_id) | Term::Str(sym_id) => store.symbol_store.get_text(*sym_id).ok()?,
        Term::Int(v) => Some(v.to_string()),
        Term::Float(bits) => Some(f64::from_bits(*bits).to_string()),
    }
}

fn is_int_text(text: &str) -> bool {
    let s = text.trim();
    if s.is_empty() {
        return false;
    }
    let body = if let Some(rest) = s.strip_prefix('-') {
        rest
    } else {
        s
    };
    !body.is_empty() && body.chars().all(|c| c.is_ascii_digit())
}

fn is_float_text(text: &str) -> bool {
    let s = text.trim();
    s.parse::<f64>().is_ok() && !is_int_text(s)
}

fn is_string_literal_text(text: &str) -> bool {
    text.len() >= 2 && text.starts_with('"') && text.ends_with('"')
}

fn is_predicate_ref_text(text: &str) -> bool {
    let mut parts = text.split('/');
    let Some(name) = parts.next() else {
        return false;
    };
    let Some(arity) = parts.next() else {
        return false;
    };
    if parts.next().is_some() {
        return false;
    }
    let mut name_chars = name.chars();
    let Some(first) = name_chars.next() else {
        return false;
    };
    if !first.is_ascii_lowercase() {
        return false;
    }
    if !name_chars.all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return false;
    }
    !arity.is_empty() && arity.chars().all(|c| c.is_ascii_digit())
}

fn eval_type_builtin(
    store: &DoxaStore,
    op: &BuiltinOp,
    args: &[Term],
    incoming: &[BodyMatch],
) -> Vec<BodyMatch> {
    if args.len() != 1 {
        return Vec::new();
    }

    incoming
        .iter()
        .filter(|bm| {
            let Some(text) = resolve_to_text(store, &args[0], &bm.subst) else {
                return false;
            };

            match op {
                BuiltinOp::Int => is_int_text(&text),
                BuiltinOp::Float => is_float_text(&text),
                BuiltinOp::String => is_string_literal_text(&text),
                BuiltinOp::Date => text.starts_with("d\"") && text.ends_with('"'),
                BuiltinOp::DateTime => text.starts_with("dt\"") && text.ends_with('"'),
                BuiltinOp::Duration => text.starts_with("dur\"") && text.ends_with('"'),
                BuiltinOp::PredicateRef => is_predicate_ref_text(&text),
                BuiltinOp::Entity => {
                    let is_temporal = (text.starts_with("d\"")
                        || text.starts_with("dt\"")
                        || text.starts_with("dur\""))
                        && text.ends_with('"');
                    !(is_int_text(&text)
                        || is_float_text(&text)
                        || is_string_literal_text(&text)
                        || is_temporal)
                }
                _ => false,
            }
        })
        .cloned()
        .collect()
}

/// Ground the head arguments of a compiled rule using a substitution.
/// Returns None if any variable is unbound.
pub fn ground_head(head_args: &[Term], subst: &Subst) -> Option<Vec<SymId>> {
    head_args.iter().map(|t| resolve_term(t, subst)).collect()
}
