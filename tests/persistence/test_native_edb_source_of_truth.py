"""EDB source-of-truth invariants for ``NativeBranchRepository``.

These tests pin down the rule that **the native EDB is the durable source of
truth** for a branch.  JSON snapshot files may exist as a cache/optimization,
but removing them must not lose belief records, rules, or constraints — those
are explicit EDB events and must be reconstructible from the native event log
alone.

The tests require the real ``doxa._native`` module because the whole point
is to exercise the round-trip through Rust-side event storage.  They are
skipped when the native module is unavailable (e.g. source checkout without
``maturin develop``).
"""

from __future__ import annotations

import gc
import shutil
from pathlib import Path

import pytest

from doxa.core.branch import Branch


def _has_native() -> bool:
    try:
        from doxa import _native  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _has_native(), reason="doxa._native not installed")


def _fresh_repo(tmp_path: Path):
    from doxa.persistence.native import NativeBranchRepository

    edb = tmp_path / "edb"
    idb = tmp_path / "idb"
    edb.mkdir(exist_ok=True)
    idb.mkdir(exist_ok=True)
    return NativeBranchRepository(str(edb), str(idb))


def _reopen_repo(tmp_path: Path, previous=None):
    """Open a *new* NativeBranchRepository over the same on-disk EDB/IDB.

    If ``previous`` is given its native handle is closed first, which
    releases the sled file lock so the new handle can attach.
    """
    from doxa.persistence.native import NativeBranchRepository

    if previous is not None:
        previous.close()
    gc.collect()
    return NativeBranchRepository(str(tmp_path / "edb"), str(tmp_path / "idb"))


def _drop_snapshots(tmp_path: Path) -> None:
    """Simulate "snapshot is lost / corrupted" — EDB is still on disk."""
    meta_dir = tmp_path / "edb" / ".doxa_native_repo"
    if meta_dir.exists():
        shutil.rmtree(meta_dir)


# ── Test 1 (primary): rules and constraints survive snapshot loss ────────


def test_edb_reconstructs_rules_and_constraints_without_snapshot(
    tmp_path: Path,
) -> None:
    """The snapshot is a cache, not the source of truth.

    After deleting ``.doxa_native_repo`` (the snapshot/index directory), a
    fresh repository opened over the same EDB must still be able to list the
    branch and reconstruct its belief records, rules, and constraints.
    """
    repo = _fresh_repo(tmp_path)
    branch = Branch.from_doxa(
        """
        pred p/1.
        p(a).
        p(b).
        q(X) :- p(X).
        !:- p(a).
        """
    )
    repo.save(branch)

    # Lose the snapshot; the EDB event log must still be intact.
    _drop_snapshots(tmp_path)

    reopened = _reopen_repo(tmp_path, previous=repo)

    assert reopened.list_names() == ["main"], (
        "Branch must be discoverable from EDB events alone"
    )

    loaded = reopened.get("main")
    assert loaded is not None, "Branch must be reconstructible from EDB"

    assert len(loaded.belief_records) == len(branch.belief_records), (
        "All asserted facts must survive snapshot loss"
    )
    assert len(loaded.rules) == len(branch.rules), (
        "Rules must survive snapshot loss — EDB AddRule events are the source "
        "of truth, not the JSON snapshot"
    )
    assert len(loaded.constraints) == len(branch.constraints), (
        "Constraints must survive snapshot loss — EDB AddConstraint events "
        "are the source of truth, not the JSON snapshot"
    )


def test_edb_reconstruction_preserves_rule_structure(tmp_path: Path) -> None:
    """Reconstructed rules retain head/body predicate names and arities."""
    repo = _fresh_repo(tmp_path)
    branch = Branch.from_doxa(
        """
        pred p/1.
        pred q/1.
        p(a).
        q(X) :- p(X).
        """
    )
    repo.save(branch)
    _drop_snapshots(tmp_path)

    reopened = _reopen_repo(tmp_path, previous=repo)
    loaded = reopened.get("main")
    assert loaded is not None
    assert len(loaded.rules) == 1

    rule = loaded.rules[0]
    assert rule.head_pred_name == "q"
    assert rule.head_pred_arity == 1
    assert len(rule.goals) == 1
    assert rule.goals[0].pred_name == "p"
    assert rule.goals[0].pred_arity == 1


def test_edb_reconstruction_preserves_constraint_structure(
    tmp_path: Path,
) -> None:
    """Reconstructed constraints retain body-goal predicate references."""
    repo = _fresh_repo(tmp_path)
    branch = Branch.from_doxa(
        """
        pred p/1.
        p(a).
        !:- p(a).
        """
    )
    repo.save(branch)
    _drop_snapshots(tmp_path)

    reopened = _reopen_repo(tmp_path, previous=repo)
    loaded = reopened.get("main")
    assert loaded is not None
    assert len(loaded.constraints) == 1

    constraint = loaded.constraints[0]
    assert len(constraint.goals) == 1
    assert constraint.goals[0].pred_name == "p"
    assert constraint.goals[0].pred_arity == 1


# ── Test 2: IDB can be wiped without losing EDB knowledge ────────────────


def test_idb_rebuild_does_not_affect_reconstruction(tmp_path: Path) -> None:
    """Deleting the IDB directory must not lose durable knowledge.

    The IDB is derived/materialized state.  Removing it and reopening must
    not lose any belief records, rules, or constraints — those live in the
    EDB and must be fully reconstructible.
    """
    repo = _fresh_repo(tmp_path)
    branch = Branch.from_doxa(
        """
        pred p/1.
        p(a).
        q(X) :- p(X).
        !:- p(a).
        """
    )
    repo.save(branch)

    # Wipe the IDB; the EDB is the source of truth so knowledge must survive.
    idb = tmp_path / "idb"
    shutil.rmtree(idb)
    idb.mkdir()

    reopened = _reopen_repo(tmp_path, previous=repo)
    loaded = reopened.get("main")
    assert loaded is not None
    assert len(loaded.belief_records) == 1
    assert len(loaded.rules) == 1
    assert len(loaded.constraints) == 1


# ── Test 3: rules & constraints are explicit EDB events ───────────────────


def test_rules_and_constraints_roundtrip_without_any_snapshots_ever(
    tmp_path: Path,
) -> None:
    """Even if a snapshot was *never written*, rules and constraints must be
    visible via the EDB.

    We save via the repository (which does write a snapshot), then drop the
    snapshot immediately and force reconstruction through the EDB path.
    The reconstructed branch must contain all three explicit events types.
    """
    repo = _fresh_repo(tmp_path)
    branch = Branch.from_doxa(
        """
        pred p/2.
        p(a, 1).
        r(X, Y) :- p(X, Y).
        !:- p(a, 1).
        """
    )
    repo.save(branch)
    _drop_snapshots(tmp_path)

    reopened = _reopen_repo(tmp_path, previous=repo)
    loaded = reopened.get("main")
    assert loaded is not None
    assert len(loaded.belief_records) >= 1
    assert len(loaded.rules) >= 1
    assert len(loaded.constraints) >= 1


# ── Test 4: IDB watermark advances with materialization ──────────────────


def test_idb_watermark_tracks_edb_after_materialize() -> None:
    """After materialization the IDB must record the EDB event-id up to
    which it is synced.  Subsequent EDB writes must leave the IDB
    watermark *behind* the EDB watermark until the next materialize.
    """
    from doxa import _native

    store = _native.NativeStore.new_temporary()
    store.configure_predicate("p", "maximum", "proof_tree")

    # IDB has never been materialized -> no watermark.
    assert store.idb_watermark("main") is None

    alice = store.intern("ent:alice")
    store.assert_fact("main", "p", 1, [alice], 1.0, 0.0, None)
    edb_before = store.edb_watermark()
    assert edb_before >= 1

    store.materialize("main", None)

    idb_wm = store.idb_watermark("main")
    assert idb_wm is not None, "IDB watermark must be set after materialize"
    assert idb_wm >= edb_before, (
        "IDB watermark must cover all EDB events present at materialize time"
    )

    # Append a new event — EDB advances, IDB does not.
    bob = store.intern("ent:bob")
    store.assert_fact("main", "p", 1, [bob], 1.0, 0.0, None)
    edb_after = store.edb_watermark()
    assert edb_after > edb_before

    stale_wm = store.idb_watermark("main")
    assert stale_wm == idb_wm, (
        "IDB watermark must not silently advance when only the EDB grows"
    )
    assert stale_wm < edb_after, (
        "IDB is stale relative to EDB — queries must either sync or report it"
    )


def test_idb_watermark_survives_reopen(tmp_path: Path) -> None:
    """The IDB watermark is durable: reopening the store must see the
    same watermark that was recorded before close."""
    from doxa import _native

    edb = tmp_path / "edb"
    idb = tmp_path / "idb"
    edb.mkdir()
    idb.mkdir()

    store = _native.NativeStore(str(edb), str(idb))
    store.configure_predicate("p", "maximum", "proof_tree")
    alice = store.intern("ent:alice")
    store.assert_fact("main", "p", 1, [alice], 1.0, 0.0, None)
    store.materialize("main", None)
    recorded = store.idb_watermark("main")
    store.flush()
    assert recorded is not None

    # Drop the handle so sled releases its file lock.
    del store
    gc.collect()

    store2 = _native.NativeStore(str(edb), str(idb))
    assert store2.idb_watermark("main") == recorded
