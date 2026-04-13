//! PyO3 bindings for the doxa-native engine.
//!
//! Exposes a `NativeStore` Python class that wraps the EDB, IDB, and
//! fixpoint engine, providing a flat API for the Python wrapper classes
//! (`NativeBranchRepository`, `NativeQueryEngine`).

use std::path::PathBuf;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use doxa_core::rule::{AtomGoal, BuiltinGoal, BuiltinOp, Goal, Rule as RustRule};
use doxa_core::types::{AggregationMode, EvidenceMode, Term};
use doxa_engine::EngineSession;

// ── Helpers ──────────────────────────────────────────────────────────

fn to_py_err(e: impl std::fmt::Debug) -> PyErr {
    PyRuntimeError::new_err(format!("{:?}", e))
}

fn parse_aggregation(s: &str) -> PyResult<AggregationMode> {
    match s {
        "maximum" | "Maximum" => Ok(AggregationMode::Maximum),
        "noisy_or" | "NoisyOr" => Ok(AggregationMode::NoisyOr),
        "capped_sum" | "CappedSum" => Ok(AggregationMode::CappedSum),
        _ => Err(PyValueError::new_err(format!(
            "Unknown aggregation mode: {s}"
        ))),
    }
}

fn parse_evidence_mode(s: &str) -> PyResult<EvidenceMode> {
    match s {
        "none" | "None" => Ok(EvidenceMode::None),
        "per_source" | "PerSource" => Ok(EvidenceMode::PerSource),
        "proof_tree" | "ProofTree" => Ok(EvidenceMode::ProofTree),
        _ => Err(PyValueError::new_err(format!(
            "Unknown evidence mode: {s}"
        ))),
    }
}

/// Convert a Python term representation to a Rust Term.
/// Python sends either {"Var": "X"} or {"Const": 42} or a plain string
/// (treated as Var) or a plain int (treated as Const/SymId).
fn py_to_term(obj: &Bound<'_, PyAny>) -> PyResult<Term> {
    if let Ok(s) = obj.extract::<String>() {
        // If it starts with uppercase or _, it's a variable
        if s.starts_with(|c: char| c.is_uppercase() || c == '_') {
            Ok(Term::Var(s))
        } else {
            // treat as entity name → caller should have interned it
            Err(PyValueError::new_err(format!(
                "Term string '{s}' looks like an entity — use intern() first and pass the SymId"
            )))
        }
    } else if let Ok(id) = obj.extract::<u64>() {
        Ok(Term::Entity(id))
    } else if let Ok(dict) = obj.downcast::<PyDict>() {
        if let Some(v) = dict.get_item("Var")? {
            Ok(Term::Var(v.extract::<String>()?))
        } else if let Some(v) = dict.get_item("Const")? {
            Ok(Term::Entity(v.extract::<u64>()?))
        } else {
            Err(PyValueError::new_err("Term dict must have 'Var' or 'Const' key"))
        }
    } else {
        Err(PyValueError::new_err("Term must be str, int, or dict"))
    }
}

fn parse_builtin_op(name: &str) -> PyResult<BuiltinOp> {
    match name {
        "eq" => Ok(BuiltinOp::Eq),
        "ne" => Ok(BuiltinOp::Ne),
        "lt" => Ok(BuiltinOp::Lt),
        "leq" => Ok(BuiltinOp::Leq),
        "gt" => Ok(BuiltinOp::Gt),
        "geq" => Ok(BuiltinOp::Geq),
        "add" => Ok(BuiltinOp::Add),
        "sub" => Ok(BuiltinOp::Sub),
        "mul" => Ok(BuiltinOp::Mul),
        "div" => Ok(BuiltinOp::Div),
        "between" => Ok(BuiltinOp::Between),
        _ => Err(PyValueError::new_err(format!("Unknown builtin: {name}"))),
    }
}

/// Convert a Python goal dict to a Rust Goal.
/// Atom shape: {"pred_name": str, "pred_arity": int, "negated": bool, "args": [...]}
/// Builtin shape: {"builtin_name": str, "args": [...]}
fn py_to_goal(obj: &Bound<'_, PyAny>) -> PyResult<Goal> {
    let dict = obj.downcast::<PyDict>().map_err(|_| {
        PyValueError::new_err("Goal must be a dict")
    })?;

    // Check if it's a builtin goal
    if let Some(builtin_name) = dict.get_item("builtin_name")? {
        let name: String = builtin_name.extract()?;
        let op = parse_builtin_op(&name)?;
        let args_obj = dict
            .get_item("args")?
            .ok_or_else(|| PyValueError::new_err("Builtin goal missing 'args'"))?;
        let args_list = args_obj.downcast::<PyList>().map_err(|_| {
            PyValueError::new_err("Builtin goal 'args' must be a list")
        })?;
        let mut args = Vec::new();
        for item in args_list.iter() {
            args.push(py_to_term(&item)?);
        }
        return Ok(Goal::Builtin(BuiltinGoal { op, args }));
    }

    let pred_name: String = dict
        .get_item("pred_name")?
        .ok_or_else(|| PyValueError::new_err("Goal missing 'pred_name'"))?
        .extract()?;
    let pred_arity: usize = dict
        .get_item("pred_arity")?
        .ok_or_else(|| PyValueError::new_err("Goal missing 'pred_arity'"))?
        .extract()?;
    let negated: bool = dict
        .get_item("negated")?
        .map(|v| v.extract::<bool>())
        .transpose()?
        .unwrap_or(false);
    let args_list = dict
        .get_item("args")?
        .ok_or_else(|| PyValueError::new_err("Goal missing 'args'"))?;
    let args_list = args_list.downcast::<PyList>().map_err(|_| {
        PyValueError::new_err("Goal 'args' must be a list")
    })?;

    let mut args = Vec::new();
    for item in args_list.iter() {
        args.push(py_to_term(&item)?);
    }

    Ok(Goal::Atom(AtomGoal {
        pred_name,
        pred_arity,
        negated,
        args,
    }))
}

// ── NativeStore ──────────────────────────────────────────────────────

/// The main Python-facing handle for the doxa-native engine.
///
/// Wraps EDB + IDB + fixpoint engine in a single object.
#[pyclass]
struct NativeStore {
    session: EngineSession,
}

#[pymethods]
impl NativeStore {
    /// Open or create a native store backed by the given paths.
    #[new]
    fn new(edb_path: &str, idb_path: &str) -> PyResult<Self> {
        let session = EngineSession::open(
            &PathBuf::from(edb_path),
            &PathBuf::from(idb_path),
        )
        .map_err(to_py_err)?;
        Ok(Self { session })
    }

    /// Create a fully in-memory store (no filesystem I/O).
    #[staticmethod]
    fn new_temporary() -> PyResult<Self> {
        let session = EngineSession::open_temporary().map_err(to_py_err)?;
        Ok(Self { session })
    }

    /// Intern a symbol string, returning its numeric ID.
    fn intern(&mut self, text: &str) -> PyResult<u64> {
        self.session.intern(text).map_err(to_py_err)
    }

    /// Intern a batch of symbol strings at once. Returns list of SymIds.
    fn intern_batch(&mut self, texts: Vec<String>) -> PyResult<Vec<u64>> {
        let mut ids = Vec::with_capacity(texts.len());
        for text in &texts {
            ids.push(self.session.intern(text).map_err(to_py_err)?);
        }
        Ok(ids)
    }

    /// Resolve a batch of symbol IDs back to strings.
    fn resolve_batch(&self, sym_ids: Vec<u64>) -> PyResult<Vec<Option<String>>> {
        let mut results = Vec::with_capacity(sym_ids.len());
        for id in sym_ids {
            results.push(
                self.session.idb.symbol_store.get_text(id).map_err(to_py_err)?
            );
        }
        Ok(results)
    }

    /// Resolve a symbol ID back to its string.
    fn resolve(&self, sym_id: u64) -> PyResult<Option<String>> {
        self.session
            .idb
            .symbol_store
            .get_text(sym_id)
            .map_err(to_py_err)
    }

    /// Configure a predicate's aggregation and evidence mode.
    fn configure_predicate(
        &mut self,
        name: &str,
        aggregation: &str,
        evidence_mode: &str,
    ) -> PyResult<()> {
        let agg = parse_aggregation(aggregation)?;
        let ev = parse_evidence_mode(evidence_mode)?;
        self.session.configure_predicate(name, agg, ev);
        Ok(())
    }

    /// Assert a ground fact in the EDB. Returns the event ID.
    #[pyo3(signature = (branch, pred_name, pred_arity, args, b, d, source=None))]
    fn assert_fact(
        &self,
        branch: &str,
        pred_name: &str,
        pred_arity: usize,
        args: Vec<u64>,
        b: f64,
        d: f64,
        source: Option<String>,
    ) -> PyResult<u64> {
        self.session
            .edb
            .assert_fact(branch, pred_name, pred_arity, args, b, d, source)
            .map_err(to_py_err)
    }

    /// Assert multiple facts at once. Each fact is a tuple:
    /// (pred_name, pred_arity, args, b, d, source_or_none)
    /// Returns the number of facts asserted.
    fn assert_facts_bulk(
        &self,
        branch: &str,
        facts: Vec<(String, usize, Vec<u64>, f64, f64, Option<String>)>,
    ) -> PyResult<usize> {
        let count = facts.len();
        for (pred_name, pred_arity, args, b, d, source) in facts {
            self.session
                .edb
                .assert_fact(branch, &pred_name, pred_arity, args, b, d, source)
                .map_err(to_py_err)?;
        }
        Ok(count)
    }

    /// Retract a fact by its original event ID. Returns the retraction event ID.
    fn retract_fact(&self, branch: &str, target_event_id: u64) -> PyResult<u64> {
        self.session
            .edb
            .retract_fact(branch, target_event_id)
            .map_err(to_py_err)
    }

    /// Add a rule to the EDB. Takes a dict with the rule structure.
    /// Returns the event ID.
    fn add_rule(
        &self,
        branch: &str,
        rule_id: u64,
        head_pred_name: &str,
        head_pred_arity: usize,
        head_args: &Bound<'_, PyList>,
        body: &Bound<'_, PyList>,
        b: f64,
        d: f64,
    ) -> PyResult<u64> {
        let mut rust_head_args = Vec::new();
        for item in head_args.iter() {
            rust_head_args.push(py_to_term(&item)?);
        }

        let mut rust_body = Vec::new();
        for item in body.iter() {
            rust_body.push(py_to_goal(&item)?);
        }

        let rule = RustRule {
            id: rule_id,
            head_pred_name: head_pred_name.to_string(),
            head_pred_arity,
            head_args: rust_head_args,
            body: rust_body,
            b,
            d,
        };

        self.session
            .edb
            .add_rule(branch, rule)
            .map_err(to_py_err)
    }

    /// Get all visible facts for a branch. Returns a list of dicts.
    #[pyo3(signature = (branch, watermark=None))]
    fn get_facts<'py>(
        &self,
        py: Python<'py>,
        branch: &str,
        watermark: Option<u64>,
    ) -> PyResult<Bound<'py, PyList>> {
        let facts = self
            .session
            .edb
            .get_facts(branch, watermark)
            .map_err(to_py_err)?;

        let result = PyList::empty_bound(py);
        for fact in &facts {
            let dict = PyDict::new_bound(py);
            dict.set_item("event_id", fact.event_id)?;
            dict.set_item("pred_name", &fact.pred_name)?;
            dict.set_item("pred_arity", fact.pred_arity)?;
            dict.set_item("args", &fact.args)?;
            dict.set_item("b", fact.b)?;
            dict.set_item("d", fact.d)?;
            dict.set_item("source", &fact.source)?;
            result.append(dict)?;
        }
        Ok(result)
    }

    /// Materialize: load EDB facts + rules, evaluate to fixpoint.
    /// Returns a dict with evaluation stats.
    #[pyo3(signature = (branch, max_depth=None))]
    fn materialize<'py>(
        &mut self,
        py: Python<'py>,
        branch: &str,
        max_depth: Option<usize>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let result = self.session.materialize_with_options(branch, max_depth).map_err(to_py_err)?;
        let dict = PyDict::new_bound(py);
        dict.set_item("atoms_changed", result.atoms_changed)?;
        dict.set_item("iterations", result.total_iterations)?;
        Ok(dict)
    }

    /// Get the epistemic state of a specific grounded atom.
    /// Returns a dict with 'b', 'd', 'status'.
    fn get_atom_state<'py>(
        &self,
        py: Python<'py>,
        pred_name: &str,
        args: Vec<u64>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let state = self
            .session
            .get_atom_state(pred_name, &args)
            .map_err(to_py_err)?;
        let dict = PyDict::new_bound(py);
        dict.set_item("b", state.b)?;
        dict.set_item("d", state.d)?;
        dict.set_item("status", format!("{:?}", state.belnap_status()))?;
        Ok(dict)
    }

    /// Query all atoms of a predicate. Returns list of answer dicts.
    fn query_predicate<'py>(
        &self,
        py: Python<'py>,
        pred_name: &str,
    ) -> PyResult<Bound<'py, PyList>> {
        let answers = self.session.query_all(pred_name).map_err(to_py_err)?;
        let result = PyList::empty_bound(py);
        for answer in &answers {
            let dict = PyDict::new_bound(py);
            dict.set_item("args", &answer.args)?;
            dict.set_item("b", answer.b)?;
            dict.set_item("d", answer.d)?;
            dict.set_item("status", format!("{:?}", answer.status))?;
            result.append(dict)?;
        }
        Ok(result)
    }

    /// Query all atoms of a predicate, returning a flat list of tuples:
    /// [(args_list, b, d), ...]
    /// This avoids per-row dict construction overhead.
    fn query_predicate_bulk(
        &self,
        pred_name: &str,
    ) -> PyResult<Vec<(Vec<u64>, f64, f64)>> {
        let answers = self.session.query_all(pred_name).map_err(to_py_err)?;
        Ok(answers
            .into_iter()
            .map(|a| (a.args, a.b, a.d))
            .collect())
    }

    /// Return the current EDB watermark.
    fn current_watermark(&self) -> PyResult<u64> {
        self.session.edb.current_watermark().map_err(to_py_err)
    }

    /// Flush all stores to disk.
    fn flush(&self) -> PyResult<()> {
        self.session.flush_all().map_err(to_py_err)
    }
}

// ── Module ───────────────────────────────────────────────────────────

/// doxa._native Python module.
#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NativeStore>()?;
    Ok(())
}
