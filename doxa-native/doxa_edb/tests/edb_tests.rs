//! Unit tests for the doxa_edb crate.

use doxa_core::rule::{AtomGoal, Goal, Rule};
use doxa_core::types::Term;
use doxa_edb::EdbStore;

fn temp_dir() -> tempfile::TempDir {
    tempfile::TempDir::new().expect("create temp dir")
}

// ── Basic fact assertion and retrieval ───────────────────────────────

#[test]
fn test_assert_and_get_facts() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    let eid1 = store
        .assert_fact("main", "person", 1, vec![10], 1.0, 0.0, None)
        .unwrap();
    let eid2 = store
        .assert_fact(
            "main",
            "person",
            1,
            vec![20],
            0.8,
            0.1,
            Some("source_a".into()),
        )
        .unwrap();

    assert!(eid1 < eid2, "event IDs should be monotonically increasing");

    let facts = store.get_facts("main", None).unwrap();
    assert_eq!(facts.len(), 2);

    let f1 = facts.iter().find(|f| f.event_id == eid1).unwrap();
    assert_eq!(f1.pred_name, "person");
    assert_eq!(f1.pred_arity, 1);
    assert_eq!(f1.args, vec![10]);
    assert!((f1.b - 1.0).abs() < 1e-9);
    assert!(f1.source.is_none());

    let f2 = facts.iter().find(|f| f.event_id == eid2).unwrap();
    assert!((f2.b - 0.8).abs() < 1e-9);
    assert!((f2.d - 0.1).abs() < 1e-9);
    assert_eq!(f2.source.as_deref(), Some("source_a"));
}

// ── Retraction ──────────────────────────────────────────────────────

#[test]
fn test_retract_fact() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    let eid1 = store
        .assert_fact("main", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    let eid2 = store
        .assert_fact("main", "p", 1, vec![2], 1.0, 0.0, None)
        .unwrap();

    // Retract the first fact
    let retract_eid = store.retract_fact("main", eid1).unwrap();
    assert!(
        retract_eid > eid2,
        "retraction event should have a higher ID"
    );

    let facts = store.get_facts("main", None).unwrap();
    assert_eq!(facts.len(), 1);
    assert_eq!(facts[0].event_id, eid2);
}

#[test]
fn test_retract_nonexistent_is_harmless() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    store
        .assert_fact("main", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();

    // Retract an event ID that doesn't exist — should not panic,
    // just creates a retraction event that has no effect.
    let _ = store.retract_fact("main", 9999).unwrap();

    let facts = store.get_facts("main", None).unwrap();
    assert_eq!(facts.len(), 1, "original fact should remain");
}

// ── Branch isolation ────────────────────────────────────────────────

#[test]
fn test_branch_isolation() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    store
        .assert_fact("branch_a", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    store
        .assert_fact("branch_b", "p", 1, vec![2], 1.0, 0.0, None)
        .unwrap();
    store
        .assert_fact("branch_a", "q", 1, vec![3], 1.0, 0.0, None)
        .unwrap();

    let facts_a = store.get_facts("branch_a", None).unwrap();
    assert_eq!(facts_a.len(), 2);

    let facts_b = store.get_facts("branch_b", None).unwrap();
    assert_eq!(facts_b.len(), 1);
    assert_eq!(facts_b[0].args, vec![2]);

    // Empty branch returns no facts
    let facts_empty = store.get_facts("nonexistent", None).unwrap();
    assert_eq!(facts_empty.len(), 0);
}

// ── Watermark-based visibility ──────────────────────────────────────

#[test]
fn test_watermark_visibility() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    let eid1 = store
        .assert_fact("main", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    let eid2 = store
        .assert_fact("main", "p", 1, vec![2], 1.0, 0.0, None)
        .unwrap();
    let _eid3 = store
        .assert_fact("main", "p", 1, vec![3], 1.0, 0.0, None)
        .unwrap();

    // Only see facts up to eid2
    let facts = store.get_facts("main", Some(eid2)).unwrap();
    assert_eq!(facts.len(), 2);
    let ids: Vec<u64> = facts.iter().map(|f| f.event_id).collect();
    assert!(ids.contains(&eid1));
    assert!(ids.contains(&eid2));
}

#[test]
fn test_watermark_hides_retraction() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    let eid1 = store
        .assert_fact("main", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    let eid2 = store
        .assert_fact("main", "p", 1, vec![2], 1.0, 0.0, None)
        .unwrap();

    // Retract eid1 (creates eid3)
    let eid3 = store.retract_fact("main", eid1).unwrap();

    // At watermark eid2: retraction hasn't happened yet
    let facts_before = store.get_facts("main", Some(eid2)).unwrap();
    assert_eq!(
        facts_before.len(),
        2,
        "both facts visible before retraction"
    );

    // At watermark eid3: retraction is visible
    let facts_after = store.get_facts("main", Some(eid3)).unwrap();
    assert_eq!(facts_after.len(), 1, "only one fact after retraction");
    assert_eq!(facts_after[0].event_id, eid2);
}

// ── Rule storage ────────────────────────────────────────────────────

#[test]
fn test_add_and_get_rules() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    let r1 = Rule {
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

    let r2 = Rule {
        id: 2,
        head_pred_name: "path".into(),
        head_pred_arity: 2,
        head_args: vec![Term::Var("X".into()), Term::Var("Z".into())],
        body: vec![
            Goal::Atom(AtomGoal {
                pred_name: "path".into(),
                pred_arity: 2,
                negated: false,
                args: vec![Term::Var("X".into()), Term::Var("Y".into())],
            }),
            Goal::Atom(AtomGoal {
                pred_name: "edge".into(),
                pred_arity: 2,
                negated: false,
                args: vec![Term::Var("Y".into()), Term::Var("Z".into())],
            }),
        ],
        b: 0.9,
        d: 0.0,
    };

    store.add_rule("main", r1).unwrap();
    store.add_rule("main", r2).unwrap();

    let rules = store.get_rules("main", None).unwrap();
    assert_eq!(rules.len(), 2);
    assert_eq!(rules[0].id, 1);
    assert_eq!(rules[1].id, 2);
    assert!((rules[1].b - 0.9).abs() < 1e-9);

    // Different branch sees no rules
    let rules_other = store.get_rules("other", None).unwrap();
    assert_eq!(rules_other.len(), 0);
}

// ── Predicate declarations ──────────────────────────────────────────

#[test]
fn test_declare_and_get_predicates() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    store.declare_predicate("main", "person", 1).unwrap();
    store.declare_predicate("main", "likes", 2).unwrap();
    store.declare_predicate("other", "item", 3).unwrap();

    let preds = store.get_predicates("main", None).unwrap();
    assert_eq!(preds.len(), 2);
    assert!(preds.contains(&("person".into(), 1)));
    assert!(preds.contains(&("likes".into(), 2)));

    let preds_other = store.get_predicates("other", None).unwrap();
    assert_eq!(preds_other.len(), 1);
}

// ── Delta events (get_events_since) ─────────────────────────────────

#[test]
fn test_get_events_since() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    let eid1 = store
        .assert_fact("main", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    let eid2 = store
        .assert_fact("main", "p", 1, vec![2], 1.0, 0.0, None)
        .unwrap();
    let eid3 = store
        .assert_fact("main", "p", 1, vec![3], 1.0, 0.0, None)
        .unwrap();

    // Events since eid1 (exclusive) → should get eid2 and eid3
    let delta = store.get_events_since(eid1, None).unwrap();
    assert_eq!(delta.len(), 2);
    assert_eq!(delta[0].event_id(), eid2);
    assert_eq!(delta[1].event_id(), eid3);

    // Events since eid2, capped at eid3
    let delta2 = store.get_events_since(eid2, Some(eid3)).unwrap();
    assert_eq!(delta2.len(), 1);
    assert_eq!(delta2[0].event_id(), eid3);

    // Events since eid3 → nothing
    let delta3 = store.get_events_since(eid3, None).unwrap();
    assert_eq!(delta3.len(), 0);
}

// ── Watermark tracking ──────────────────────────────────────────────

#[test]
fn test_current_watermark() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    // No events yet
    let wm0 = store.current_watermark().unwrap();
    assert_eq!(wm0, 0);

    let eid1 = store
        .assert_fact("main", "p", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    assert_eq!(store.current_watermark().unwrap(), eid1);

    let eid2 = store
        .assert_fact("main", "p", 1, vec![2], 1.0, 0.0, None)
        .unwrap();
    assert_eq!(store.current_watermark().unwrap(), eid2);
}

// ── Persistence round-trip ──────────────────────────────────────────

#[test]
fn test_edb_persistence_roundtrip() {
    let tmp = temp_dir();
    let path = tmp.path().to_path_buf();

    let eid;
    {
        let store = EdbStore::open(&path).unwrap();
        eid = store
            .assert_fact("main", "data", 1, vec![42], 0.75, 0.05, None)
            .unwrap();
        store.flush_all().unwrap();
    }

    // Reopen
    {
        let store = EdbStore::open(&path).unwrap();
        let facts = store.get_facts("main", None).unwrap();
        assert_eq!(facts.len(), 1);
        assert_eq!(facts[0].event_id, eid);
        assert_eq!(facts[0].args, vec![42]);
        assert!((facts[0].b - 0.75).abs() < 1e-9);
        assert!((facts[0].d - 0.05).abs() < 1e-9);

        // Watermark should also persist
        assert_eq!(store.current_watermark().unwrap(), eid);
    }
}

// ── Mixed event types ───────────────────────────────────────────────

#[test]
fn test_mixed_events_ordering() {
    let tmp = temp_dir();
    let store = EdbStore::open(tmp.path()).unwrap();

    let e1 = store.declare_predicate("main", "person", 1).unwrap();
    let e2 = store
        .assert_fact("main", "person", 1, vec![1], 1.0, 0.0, None)
        .unwrap();
    let e3 = store
        .add_rule(
            "main",
            Rule {
                id: 1,
                head_pred_name: "knows".into(),
                head_pred_arity: 2,
                head_args: vec![Term::Var("X".into()), Term::Var("Y".into())],
                body: vec![],
                b: 1.0,
                d: 0.0,
            },
        )
        .unwrap();
    let e4 = store
        .assert_fact("main", "person", 1, vec![2], 1.0, 0.0, None)
        .unwrap();
    let e5 = store.retract_fact("main", e2).unwrap();

    // All event IDs should be strictly increasing
    assert!(e1 < e2);
    assert!(e2 < e3);
    assert!(e3 < e4);
    assert!(e4 < e5);

    // Facts: only e4 remains (e2 was retracted)
    let facts = store.get_facts("main", None).unwrap();
    assert_eq!(facts.len(), 1);
    assert_eq!(facts[0].event_id, e4);

    // Rules: one rule
    let rules = store.get_rules("main", None).unwrap();
    assert_eq!(rules.len(), 1);

    // Predicates: one declaration
    let preds = store.get_predicates("main", None).unwrap();
    assert_eq!(preds.len(), 1);

    // Watermark
    assert_eq!(store.current_watermark().unwrap(), e5);
}
