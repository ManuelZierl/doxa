# doxa-native

A native Rust query and persistence engine for the Doxa epistemic reasoning system.

## Architecture

doxa-native is a Cargo workspace consisting of four crates, each responsible for one layer of the reasoning stack:

```
┌──────────────────────────────────────────────┐
│              doxa_engine                      │  Fixpoint evaluation, joins,
│  semi-naive iteration, SCC scheduling,       │  query answering
│  contribution propagation                    │
├──────────────────────────────────────────────┤
│     doxa_edb          │     doxa_idb         │  Persistence layer
│  append-only event    │  intensional DB:     │
│  log, branch-aware    │  atom states,        │
│  fact/rule storage    │  contributions,      │
│                       │  secondary indexes   │
├───────────────────────┴──────────────────────┤
│              doxa_core                        │  Shared types & semantics
│  Term, Atom, Rule, EpistemicState,           │
│  SCC analysis, semantics config              │
└──────────────────────────────────────────────┘
```

### Crate summary

| Crate | Purpose |
|-------|---------|
| **doxa_core** | Shared types (Term, AtomKey, EpistemicState, Rule, Goal, Constraint), epistemic semantics config, Tarjan SCC analysis |
| **doxa_edb** | Append-only event log for ground facts and rules, watermark-based visibility, retraction, branch isolation |
| **doxa_idb** | Sled-backed intensional DB: atom state storage, contribution tracking, aggregation (Maximum/NoisyOr/CappedSum), secondary indexes |
| **doxa_engine** | Rule compiler, semi-naive fixpoint evaluator, join/unification, `EngineSession` top-level API |

## Core Principles

1. **Epistemic atoms are first-class.** Every atom carries an independent belief (`b`) and doubt (`d`) channel — not a boolean, not a probability. Belnap four-valued status (True/False/Both/Neither) is derived from these channels.

2. **Predicate-native storage.** The IDB is organized by predicate, with per-predicate aggregation mode and evidence tracking. Secondary indexes are declared per-predicate.

3. **Contribution-aware merges.** Non-idempotent aggregation modes (NoisyOr, CappedSum) track individual contributions by evidence ID. Updating or retracting a contribution triggers a full re-aggregation.

4. **Incremental fixpoint.** Rules are evaluated SCC-by-SCC in topological order. Recursive SCCs use semi-naive delta iteration until convergence.

5. **Append-only EDB.** All mutations are recorded as immutable events. Retraction is modeled as a new event that marks a previous event as retracted, enabling time-travel queries via watermarks.

## Quick Start

```rust
use doxa_core::rule::{AtomGoal, Goal, Rule};
use doxa_core::types::{AggregationMode, EvidenceMode, Term};
use doxa_engine::EngineSession;

// Open EDB and IDB stores
let mut session = EngineSession::open("./edb", "./idb").unwrap();

// Configure predicates
session.configure_predicate("edge", AggregationMode::Maximum, EvidenceMode::PerSource);
session.configure_predicate("path", AggregationMode::NoisyOr, EvidenceMode::PerSource);

// Intern symbols
let a = session.intern("a").unwrap();
let b = session.intern("b").unwrap();

// Assert EDB facts
session.edb.assert_fact("main", "edge", 2, vec![a, b], 1.0, 0.0, None).unwrap();

// Add rules
let rule = Rule {
    id: 1,
    head_pred_name: "path".into(),
    head_pred_arity: 2,
    head_args: vec![Term::Var("X".into()), Term::Var("Y".into())],
    body: vec![Goal::Atom(AtomGoal {
        pred_name: "edge".into(),
        pred_arity: 2,
        negated: false,
        args: vec![Term::Var("X".into()), Term::Var("Y".into())],
    })],
    b: 1.0,
    d: 0.0,
};
session.edb.add_rule("main", rule).unwrap();

// Evaluate to fixpoint
let result = session.materialize("main").unwrap();
println!("atoms changed: {}", result.atoms_changed);

// Query derived state
let state = session.get_atom_state("path", &[a, b]).unwrap();
println!("path(a,b): b={}, d={}", state.b, state.d);
```

## Building & Testing

```bash
cd doxa-native
cargo build
cargo test --workspace
```

## Status

This is a foundational implementation. Current capabilities:

- [x] Epistemic atom state with (b, d) channels
- [x] Three aggregation modes: Maximum, NoisyOr, CappedSum
- [x] Evidence-tracked contributions with upsert and retraction
- [x] Append-only EDB with watermark visibility and branch isolation
- [x] Rule compilation with predicate name resolution
- [x] Semi-naive fixpoint evaluation with SCC ordering
- [x] Join/unification for rule body evaluation
- [x] 20 passing tests (3 SCC unit + 11 IDB + 6 integration)

Future work:

- [ ] Magic Sets / demand-driven evaluation
- [ ] Constraint evaluation and violation propagation
- [ ] Index-accelerated joins (currently uses full predicate scan for unbound goals)
- [ ] Negation-as-failure with well-founded semantics
- [ ] Python bindings (PyO3) for integration with the existing Doxa Python layer
- [ ] Incremental re-evaluation (delta EDB events → targeted re-derivation)
- [ ] Explain/provenance tracking
