use doxa_idb::{
    AggregationMode, AtomKey, AtomState, Contribution, DoxaStore, EvidenceMode, IndexSpec,
    StoreError,
};

// Helper to create a temporary directory for tests
fn temp_dir() -> tempfile::TempDir {
    tempfile::TempDir::new().expect("create temp dir")
}

#[test]
fn test_predicate_registration_and_symbol_store() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    // register predicate
    let profile = store
        .predicate_registry
        .register_predicate(
            "parent",
            2,
            AggregationMode::Maximum,
            EvidenceMode::None,
            vec![
                IndexSpec::new("by_first", vec![0]),
                IndexSpec::new("by_second", vec![1]),
            ],
        )
        .unwrap();
    assert_eq!(profile.name, "parent");
    assert_eq!(profile.arity, 2);
    // register again returns same ID
    let profile2 = store
        .predicate_registry
        .register_predicate(
            "parent",
            2,
            AggregationMode::Maximum,
            EvidenceMode::None,
            vec![],
        )
        .unwrap();
    assert_eq!(profile.pred_id, profile2.pred_id);
    // symbol store mapping
    let sym_a = store.symbol_store.get_or_insert("alice").unwrap();
    let sym_b = store.symbol_store.get_or_insert("bob").unwrap();
    assert_eq!(
        store.symbol_store.get_text(sym_a).unwrap().unwrap(),
        "alice"
    );
    assert_eq!(store.symbol_store.get_text(sym_b).unwrap().unwrap(), "bob");
    // ensure retrieving again yields same ID
    assert_eq!(store.symbol_store.get("alice").unwrap().unwrap(), sym_a);
}

#[test]
fn test_insert_with_id() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    // Insert with explicit ID
    store.symbol_store.insert_with_id("x", 100).unwrap();
    assert_eq!(store.symbol_store.get("x").unwrap().unwrap(), 100);
    assert_eq!(store.symbol_store.get_text(100).unwrap().unwrap(), "x");
    // Subsequent get_or_insert should not reuse ID 100
    let next = store.symbol_store.get_or_insert("y").unwrap();
    assert!(next > 100, "next ID {} should be > 100", next);
}

#[test]
fn test_upsert_maximum() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    let profile = store
        .predicate_registry
        .register_predicate(
            "likes",
            2,
            AggregationMode::Maximum,
            EvidenceMode::None,
            vec![IndexSpec::new("by_first", vec![0])],
        )
        .unwrap();
    // create atom key
    let s1 = store.symbol_store.get_or_insert("alice").unwrap();
    let s2 = store.symbol_store.get_or_insert("chocolate").unwrap();
    let atom_key = AtomKey {
        pred_id: profile.pred_id,
        args: vec![s1, s2],
    };
    // insert first contribution (b=0.4, d=0.0)
    let state = store
        .upsert_atom(
            &atom_key,
            &Contribution {
                b: 0.4,
                d: 0.0,
                evidence_id: None,
            },
        )
        .unwrap();
    assert!((state.b - 0.4).abs() < 1e-6);
    // insert second contribution (b=0.6, d=0.1)
    let state = store
        .upsert_atom(
            &atom_key,
            &Contribution {
                b: 0.6,
                d: 0.1,
                evidence_id: None,
            },
        )
        .unwrap();
    // maximum aggregator should take componentwise max
    assert!((state.b - 0.6).abs() < 1e-6);
    assert!((state.d - 0.1).abs() < 1e-6);
    // check index scan
    let results = store
        .scan_by_index(profile.pred_id, "by_first", &[s1])
        .unwrap();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].0.args, atom_key.args);
}

#[test]
fn test_upsert_noisy_or_with_retract() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    let profile = store
        .predicate_registry
        .register_predicate(
            "evidence",
            1,
            AggregationMode::NoisyOr,
            EvidenceMode::PerSource,
            vec![IndexSpec::new("by_arg0", vec![0])],
        )
        .unwrap();
    let s1 = store.symbol_store.get_or_insert("fact1").unwrap();
    let atom_key = AtomKey {
        pred_id: profile.pred_id,
        args: vec![s1],
    };
    // insert two contributions from distinct sources
    let c1 = Contribution {
        b: 0.5,
        d: 0.0,
        evidence_id: Some(b"src1".to_vec()),
    };
    let c2 = Contribution {
        b: 0.3,
        d: 0.0,
        evidence_id: Some(b"src2".to_vec()),
    };
    let state1 = store.upsert_atom(&atom_key, &c1).unwrap();
    assert!((state1.b - 0.5).abs() < 1e-6);
    let state2 = store.upsert_atom(&atom_key, &c2).unwrap();
    // Noisy OR: 1 - (1-0.5)*(1-0.3) = 0.65
    assert!((state2.b - 0.65).abs() < 1e-6);
    // retract contribution src1
    let state3 = store.retract_contribution(&atom_key, b"src1").unwrap();
    // remaining contribution: 0.3
    assert!((state3.b - 0.3).abs() < 1e-6);
}

#[test]
fn test_capped_sum() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    let profile = store
        .predicate_registry
        .register_predicate(
            "score",
            1,
            AggregationMode::CappedSum,
            EvidenceMode::PerSource,
            vec![],
        )
        .unwrap();
    let s1 = store.symbol_store.get_or_insert("item1").unwrap();
    let atom_key = AtomKey::new(profile.pred_id, vec![s1]);
    let c1 = Contribution {
        b: 0.4,
        d: 0.0,
        evidence_id: Some(b"e1".to_vec()),
    };
    let c2 = Contribution {
        b: 0.5,
        d: 0.0,
        evidence_id: Some(b"e2".to_vec()),
    };
    let c3 = Contribution {
        b: 0.3,
        d: 0.0,
        evidence_id: Some(b"e3".to_vec()),
    };
    store.upsert_atom(&atom_key, &c1).unwrap();
    store.upsert_atom(&atom_key, &c2).unwrap();
    let state = store.upsert_atom(&atom_key, &c3).unwrap();
    // 0.4 + 0.5 + 0.3 = 1.2 → capped at 1.0
    assert!((state.b - 1.0).abs() < 1e-6);
    // retract one and check
    let state2 = store.retract_contribution(&atom_key, b"e2").unwrap();
    // 0.4 + 0.3 = 0.7
    assert!((state2.b - 0.7).abs() < 1e-6);
}

#[test]
fn test_upsert_existing_evidence_updates() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    let profile = store
        .predicate_registry
        .register_predicate(
            "upd",
            1,
            AggregationMode::NoisyOr,
            EvidenceMode::PerSource,
            vec![],
        )
        .unwrap();
    let s1 = store.symbol_store.get_or_insert("a").unwrap();
    let ak = AtomKey::new(profile.pred_id, vec![s1]);
    // Insert contribution
    let c1 = Contribution {
        b: 0.3,
        d: 0.0,
        evidence_id: Some(b"ev1".to_vec()),
    };
    store.upsert_atom(&ak, &c1).unwrap();
    // Update same evidence ID with different value
    let c1_updated = Contribution {
        b: 0.8,
        d: 0.0,
        evidence_id: Some(b"ev1".to_vec()),
    };
    let state = store.upsert_atom(&ak, &c1_updated).unwrap();
    // Should reflect the updated value (0.8), not the old one (0.3)
    assert!((state.b - 0.8).abs() < 1e-6);
}

#[test]
fn test_invalid_arity_error() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    let profile = store
        .predicate_registry
        .register_predicate("p", 2, AggregationMode::Maximum, EvidenceMode::None, vec![])
        .unwrap();
    // Wrong number of args
    let ak = AtomKey::new(profile.pred_id, vec![1]);
    let result = store.upsert_atom(
        &ak,
        &Contribution {
            b: 0.5,
            d: 0.0,
            evidence_id: None,
        },
    );
    match result {
        Err(StoreError::InvalidArity {
            expected: 2,
            found: 1,
        }) => {}
        other => panic!("expected InvalidArity, got {:?}", other),
    }
}

#[test]
fn test_missing_evidence_error() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    let profile = store
        .predicate_registry
        .register_predicate(
            "ev_pred",
            1,
            AggregationMode::NoisyOr,
            EvidenceMode::PerSource,
            vec![],
        )
        .unwrap();
    let s1 = store.symbol_store.get_or_insert("x").unwrap();
    let ak = AtomKey::new(profile.pred_id, vec![s1]);
    // Missing evidence_id when PerSource requires it
    let result = store.upsert_atom(
        &ak,
        &Contribution {
            b: 0.5,
            d: 0.0,
            evidence_id: None,
        },
    );
    match result {
        Err(StoreError::MissingEvidence) => {}
        other => panic!("expected MissingEvidence, got {:?}", other),
    }
}

#[test]
fn test_unknown_index_error() {
    let tmp = temp_dir();
    let store = DoxaStore::open(tmp.path()).unwrap();
    let profile = store
        .predicate_registry
        .register_predicate("q", 1, AggregationMode::Maximum, EvidenceMode::None, vec![])
        .unwrap();
    let result = store.scan_by_index(profile.pred_id, "nonexistent", &[1]);
    match result {
        Err(StoreError::UnknownIndex { .. }) => {}
        other => panic!("expected UnknownIndex, got {:?}", other),
    }
}

#[test]
fn test_persistence_roundtrip() {
    let tmp = temp_dir();
    let path = tmp.path().to_path_buf();
    // Open, insert data, flush, and drop
    {
        let store = DoxaStore::open(&path).unwrap();
        let profile = store
            .predicate_registry
            .register_predicate(
                "fact",
                1,
                AggregationMode::Maximum,
                EvidenceMode::None,
                vec![],
            )
            .unwrap();
        let s1 = store.symbol_store.get_or_insert("hello").unwrap();
        let ak = AtomKey::new(profile.pred_id, vec![s1]);
        store
            .upsert_atom(
                &ak,
                &Contribution {
                    b: 0.9,
                    d: 0.1,
                    evidence_id: None,
                },
            )
            .unwrap();
        store.flush_all().unwrap();
    }
    // Reopen and verify
    {
        let store = DoxaStore::open(&path).unwrap();
        let sym = store.symbol_store.get("hello").unwrap().unwrap();
        let profile = store.predicate_registry.get_profile(1).unwrap().unwrap();
        let ak = AtomKey::new(profile.pred_id, vec![sym]);
        let state = store.get_state(&ak).unwrap();
        assert!((state.b - 0.9).abs() < 1e-6);
        assert!((state.d - 0.1).abs() < 1e-6);
    }
}

#[test]
fn test_atom_state_approx_eq() {
    let a = AtomState {
        b: 0.1 + 0.2,
        d: 0.0,
    };
    let b = AtomState { b: 0.3, d: 0.0 };
    assert_eq!(a, b, "epsilon-based PartialEq should handle float rounding");
}
