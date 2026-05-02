//! Rule and goal definitions for the Doxa logical engine layer.

use serde::{Deserialize, Serialize};

use crate::types::{PredId, Term};

// ── Goals (rule body elements) ───────────────────────────────────────

/// A single goal in a rule body.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum Goal {
    /// Positive or negated atom lookup.
    Atom(AtomGoal),
    /// Built-in comparison or filter.
    Builtin(BuiltinGoal),
}

/// An atom goal: `pred(t₁, t₂, …)` or `not pred(t₁, t₂, …)`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AtomGoal {
    pub pred_name: String,
    pub pred_arity: usize,
    pub negated: bool,
    pub args: Vec<Term>,
}

/// Built-in operations (comparisons, arithmetic filters).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum BuiltinOp {
    Eq,
    Ne,
    Lt,
    Leq,
    Gt,
    Geq,
    Add,
    Sub,
    Mul,
    Div,
    Between,
    Int,
    String,
    Float,
    Entity,
    PredicateRef,
    Date,
    DateTime,
    Duration,
}

/// A built-in goal: `op(t₁, t₂)`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BuiltinGoal {
    pub op: BuiltinOp,
    pub args: Vec<Term>,
}

// ── Rules ────────────────────────────────────────────────────────────

/// A Doxa rule: `head(t₁, …) :- g₁, g₂, …`
///
/// Rules carry epistemic weights (`b`, `d`) that modulate the
/// contribution propagated from body truth to head atom state.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Rule {
    /// Unique identifier for this rule (assigned at load time).
    pub id: u64,
    /// Head predicate name.
    pub head_pred_name: String,
    /// Head predicate arity.
    pub head_pred_arity: usize,
    /// Head argument terms (may contain variables).
    pub head_args: Vec<Term>,
    /// Body goals, evaluated left-to-right.
    pub body: Vec<Goal>,
    /// Rule belief weight (default 1.0 = full pass-through).
    pub b: f64,
    /// Rule doubt weight (default 0.0 = no doubt injection).
    pub d: f64,
}

/// A compiled, ID-resolved version of a rule where predicate names have
/// been resolved to [`PredId`]s and entity/string terms to [`SymId`]s.
/// This is the form used during actual evaluation.
#[derive(Debug, Clone)]
pub struct CompiledRule {
    pub id: u64,
    pub head_pred_id: PredId,
    pub head_arity: usize,
    pub head_args: Vec<Term>,
    pub body: Vec<CompiledGoal>,
    pub b: f64,
    pub d: f64,
}

/// A goal in a compiled rule body.
#[derive(Debug, Clone)]
pub enum CompiledGoal {
    Atom {
        pred_id: PredId,
        arity: usize,
        negated: bool,
        args: Vec<Term>,
    },
    Builtin {
        op: BuiltinOp,
        args: Vec<Term>,
    },
}

// ── Constraints ──────────────────────────────────────────────────────

/// An integrity constraint: `!:- g₁, g₂, …`
///
/// When all goals succeed, the constraint fires and produces a
/// violation contribution to the head atoms involved.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Constraint {
    pub id: u64,
    pub goals: Vec<Goal>,
    /// Violation belief weight.
    pub b: f64,
    /// Violation doubt weight.
    pub d: f64,
}

/// A compiled, ID-resolved version of a constraint.
#[derive(Debug, Clone)]
pub struct CompiledConstraint {
    pub id: u64,
    pub goals: Vec<CompiledGoal>,
    pub b: f64,
    pub d: f64,
}
