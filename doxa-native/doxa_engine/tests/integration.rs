//! End-to-end integration tests for the Doxa-native engine.
//!
//! These tests exercise the full pipeline: EDB → compile → fixpoint → query.

use doxa_core::rule::{AtomGoal, Goal, Rule};
use doxa_core::types::{AggregationMode, EvidenceMode, Term};

use doxa_engine::EngineSession;

fn temp_dir() -> tempfile::TempDir {
    tempfile::TempDir::new().expect("create temp dir")
}

/// Helper: build a simple rule `head(X₀, …) :- body₀(…), body₁(…), …`
fn rule(id: u64, head: &str, head_arity: usize, head_args: Vec<Term>, body: Vec<Goal>) -> Rule {
    Rule {
        id,
        head_pred_name: head.to_string(),
        head_pred_arity: head_arity,
        head_args,
        body,
        b: 1.0,
        d: 0.0,
    }
}

fn atom_goal(name: &str, arity: usize, args: Vec<Term>) -> Goal {
    Goal::Atom(AtomGoal {
        pred_name: name.to_string(),
        pred_arity: arity,
        negated: false,
        args,
    })
}

// ── Test: simple transitive closure ──────────────────────────────────

/// edge(a,b). edge(b,c).
/// path(X,Y) :- edge(X,Y).
/// path(X,Z) :- path(X,Y), edge(Y,Z).
///
/// Expected: path(a,b)=1, path(b,c)=1, path(a,c)=1
#[test]
fn test_transitive_closure() {
    let tmp_edb = temp_dir();
    let tmp_idb = temp_dir();

    let mut session = EngineSession::open(tmp_edb.path(), tmp_idb.path()).unwrap();

    // Configure predicates
    session.configure_predicate("edge", AggregationMode::Maximum, EvidenceMode::PerSource);
    session.configure_predicate("path", AggregationMode::Maximum, EvidenceMode::PerSource);

    // Intern symbols
    let a = session.intern("a").unwrap();
    let b = session.intern("b").unwrap();
    let c = session.intern("c").unwrap();

    // Assert EDB facts
    session
        .edb
        .assert_fact("main", "edge", 2, vec![a, b], 1.0, 0.0, None)
        .unwrap();
    session
        .edb
        .assert_fact("main", "edge", 2, vec![b, c], 1.0, 0.0, None)
        .unwrap();

    // Add rules to EDB
    // path(X,Y) :- edge(X,Y).
    let r1 = rule(
        1,
        "path",
        2,
        vec![Term::Var("X".into()), Term::Var("Y".into())],
        vec![atom_goal(
            "edge",
            2,
            vec![Term::Var("X".into()), Term::Var("Y".into())],
        )],
    );
    // path(X,Z) :- path(X,Y), edge(Y,Z).
    let r2 = rule(
        2,
        "path",
        2,
        vec![Term::Var("X".into()), Term::Var("Z".into())],
        vec![
            atom_goal(
                "path",
                2,
                vec![Term::Var("X".into()), Term::Var("Y".into())],
            ),
            atom_goal(
                "edge",
                2,
                vec![Term::Var("Y".into()), Term::Var("Z".into())],
            ),
        ],
    );

    session.edb.add_rule("main", r1).unwrap();
    session.edb.add_rule("main", r2).unwrap();

    // Materialize
    let result = session.materialize("main").unwrap();
    assert!(result.atoms_changed > 0, "some atoms should have changed");

    // Check derived path atoms
    let state_ab = session.get_atom_state("path", &[a, b]).unwrap();
    assert!(
        state_ab.b > 0.5,
        "path(a,b) should have belief > 0.5, got {}",
        state_ab.b
    );

    let state_bc = session.get_atom_state("path", &[b, c]).unwrap();
    assert!(
        state_bc.b > 0.5,
        "path(b,c) should have belief > 0.5, got {}",
        state_bc.b
    );

    let state_ac = session.get_atom_state("path", &[a, c]).unwrap();
    assert!(
        state_ac.b > 0.5,
        "path(a,c) should have belief > 0.5, got {}",
        state_ac.b
    );

    // Negative check: path(c,a) should not exist
    let state_ca = session.get_atom_state("path", &[c, a]).unwrap();
    assert!(
        state_ca.b < 1e-9,
        "path(c,a) should have no belief, got {}",
        state_ca.b
    );
}

// ── Test: weighted rules with NoisyOr aggregation ────────────────────

/// source1(X). source2(X).
/// derived(X) :- source1(X).   [b=0.6]
/// derived(X) :- source2(X).   [b=0.4]
///
/// NoisyOr: 1 - (1-0.6)*(1-0.4) = 0.76
#[test]
fn test_noisy_or_aggregation() {
    let tmp_edb = temp_dir();
    let tmp_idb = temp_dir();

    let mut session = EngineSession::open(tmp_edb.path(), tmp_idb.path()).unwrap();

    session.configure_predicate("source1", AggregationMode::Maximum, EvidenceMode::PerSource);
    session.configure_predicate("source2", AggregationMode::Maximum, EvidenceMode::PerSource);
    session.configure_predicate("derived", AggregationMode::NoisyOr, EvidenceMode::PerSource);

    let x = session.intern("x_entity").unwrap();

    session
        .edb
        .assert_fact("main", "source1", 1, vec![x], 1.0, 0.0, None)
        .unwrap();
    session
        .edb
        .assert_fact("main", "source2", 1, vec![x], 1.0, 0.0, None)
        .unwrap();

    // derived(X) :- source1(X).  with b=0.6
    let r1 = Rule {
        id: 1,
        head_pred_name: "derived".to_string(),
        head_pred_arity: 1,
        head_args: vec![Term::Var("X".into())],
        body: vec![atom_goal("source1", 1, vec![Term::Var("X".into())])],
        b: 0.6,
        d: 0.0,
    };

    // derived(X) :- source2(X).  with b=0.4
    let r2 = Rule {
        id: 2,
        head_pred_name: "derived".to_string(),
        head_pred_arity: 1,
        head_args: vec![Term::Var("X".into())],
        body: vec![atom_goal("source2", 1, vec![Term::Var("X".into())])],
        b: 0.4,
        d: 0.0,
    };

    session.edb.add_rule("main", r1).unwrap();
    session.edb.add_rule("main", r2).unwrap();

    session.materialize("main").unwrap();

    let state = session.get_atom_state("derived", &[x]).unwrap();
    // NoisyOr of 0.6 and 0.4: 1 - (1-0.6)*(1-0.4) = 1 - 0.4*0.6 = 0.76
    assert!(
        (state.b - 0.76).abs() < 0.05,
        "derived(x) belief should be ~0.76, got {}",
        state.b
    );
}

// ── Test: EDB retraction and re-evaluation ───────────────────────────

/// Assert a fact, materialize, retract, re-materialize.
#[test]
fn test_edb_fact_lifecycle() {
    let tmp_edb = temp_dir();
    let edb_path = tmp_edb.path().to_path_buf();

    // Phase 1: assert fact, materialize, verify
    let a;
    let eid;
    {
        let tmp_idb = temp_dir();
        let mut session = EngineSession::open(&edb_path, tmp_idb.path()).unwrap();
        session.configure_predicate("data", AggregationMode::Maximum, EvidenceMode::PerSource);

        a = session.intern("a").unwrap();
        eid = session
            .edb
            .assert_fact("main", "data", 1, vec![a], 0.9, 0.0, None)
            .unwrap();

        session.materialize("main").unwrap();
        let state = session.get_atom_state("data", &[a]).unwrap();
        assert!(state.b > 0.5, "data(a) should exist after assert");

        // Retract the fact
        session.edb.retract_fact("main", eid).unwrap();
        session.flush_all().unwrap();
    } // session dropped → sled lock released

    // Phase 2: re-open with fresh IDB, verify retraction
    {
        let tmp_idb2 = temp_dir();
        let mut session2 = EngineSession::open(&edb_path, tmp_idb2.path()).unwrap();
        session2.configure_predicate("data", AggregationMode::Maximum, EvidenceMode::PerSource);

        session2.materialize("main").unwrap();

        let state2 = session2.get_atom_state("data", &[a]).unwrap();
        assert!(
            state2.b < 1e-9,
            "data(a) should be gone after retract, got b={}",
            state2.b
        );
    }
}

// ── Test: simple non-recursive derivation ────────────────────────────

/// parent(alice, bob). parent(bob, charlie).
/// grandparent(X, Z) :- parent(X, Y), parent(Y, Z).
#[test]
fn test_grandparent() {
    let tmp_edb = temp_dir();
    let tmp_idb = temp_dir();

    let mut session = EngineSession::open(tmp_edb.path(), tmp_idb.path()).unwrap();
    session.configure_predicate("parent", AggregationMode::Maximum, EvidenceMode::PerSource);
    session.configure_predicate(
        "grandparent",
        AggregationMode::Maximum,
        EvidenceMode::PerSource,
    );

    let alice = session.intern("alice").unwrap();
    let bob = session.intern("bob").unwrap();
    let charlie = session.intern("charlie").unwrap();

    session
        .edb
        .assert_fact("main", "parent", 2, vec![alice, bob], 1.0, 0.0, None)
        .unwrap();
    session
        .edb
        .assert_fact("main", "parent", 2, vec![bob, charlie], 1.0, 0.0, None)
        .unwrap();

    let r = rule(
        1,
        "grandparent",
        2,
        vec![Term::Var("X".into()), Term::Var("Z".into())],
        vec![
            atom_goal(
                "parent",
                2,
                vec![Term::Var("X".into()), Term::Var("Y".into())],
            ),
            atom_goal(
                "parent",
                2,
                vec![Term::Var("Y".into()), Term::Var("Z".into())],
            ),
        ],
    );
    session.edb.add_rule("main", r).unwrap();

    let result = session.materialize("main").unwrap();
    assert!(result.atoms_changed > 0);

    let gp = session
        .get_atom_state("grandparent", &[alice, charlie])
        .unwrap();
    assert!(
        gp.b > 0.5,
        "grandparent(alice, charlie) should be derived, got b={}",
        gp.b
    );

    // Negative: grandparent(bob, alice) should not exist
    let neg = session
        .get_atom_state("grandparent", &[bob, alice])
        .unwrap();
    assert!(neg.b < 1e-9, "grandparent(bob, alice) should not exist");
}

// ── Test: EDB watermark-based delta ──────────────────────────────────

#[test]
fn test_edb_watermark_and_delta() {
    let tmp_edb = temp_dir();
    let edb = doxa_edb::EdbStore::open(tmp_edb.path()).unwrap();

    let eid1 = edb
        .assert_fact("main", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    let eid2 = edb
        .assert_fact("main", "p", 1, vec![2], 1.0, 0.0, None)
        .unwrap();
    let eid3 = edb
        .assert_fact("main", "p", 1, vec![3], 1.0, 0.0, None)
        .unwrap();

    // Watermark at eid2 should only see events 1 and 2
    let facts = edb.get_facts("main", Some(eid2)).unwrap();
    assert_eq!(facts.len(), 2);

    // Delta: events since eid1
    let delta = edb.get_events_since(eid1, None).unwrap();
    assert_eq!(delta.len(), 2); // eid2 and eid3

    // Current watermark
    let wm = edb.current_watermark().unwrap();
    assert_eq!(wm, eid3);
}

// ── Test: persistence round-trip of EDB + IDB ───────────────────────

#[test]
fn test_session_flush_and_reopen() {
    let tmp_edb = temp_dir();
    let tmp_idb = temp_dir();

    let edb_path = tmp_edb.path().to_path_buf();
    let idb_path = tmp_idb.path().to_path_buf();

    // Session 1: write data
    {
        let mut session = EngineSession::open(&edb_path, &idb_path).unwrap();
        session.configure_predicate("fact", AggregationMode::Maximum, EvidenceMode::PerSource);

        let a = session.intern("alpha").unwrap();
        session
            .edb
            .assert_fact("main", "fact", 1, vec![a], 0.8, 0.1, None)
            .unwrap();
        session.materialize("main").unwrap();
        session.flush_all().unwrap();
    }

    // Session 2: reopen and verify
    {
        let mut session = EngineSession::open(&edb_path, &idb_path).unwrap();
        session.configure_predicate("fact", AggregationMode::Maximum, EvidenceMode::PerSource);

        let a = session.intern("alpha").unwrap();
        // Re-materialize to populate pred_map
        session.materialize("main").unwrap();

        let state = session.get_atom_state("fact", &[a]).unwrap();
        assert!(
            (state.b - 0.8).abs() < 0.01,
            "fact(alpha) b should persist, got {}",
            state.b
        );
    }
}
