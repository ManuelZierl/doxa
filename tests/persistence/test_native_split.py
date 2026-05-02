"""Tests for the Python-facing EDB/IDB split in ``doxa.persistence.split``.

These tests pin down the contract of the ``NativeEdb`` / ``NativeIdb`` /
``NativeRuntime`` view objects: the EDB side is the durable source of
truth, the IDB side is rebuildable derived state, and both expose only
their own slice of the underlying native store.
"""

from __future__ import annotations

import gc
import shutil
from pathlib import Path

import pytest


def _has_native() -> bool:
    try:
        from doxa import _native  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _has_native(), reason="doxa._native not installed")


def test_runtime_exposes_edb_and_idb_views() -> None:
    from doxa.persistence.split import NativeEdb, NativeIdb, NativeRuntime

    rt = NativeRuntime.new_temporary()
    assert isinstance(rt.edb, NativeEdb)
    assert isinstance(rt.idb, NativeIdb)


def test_edb_is_the_write_side() -> None:
    """EDB view carries ``assert_fact`` / ``add_rule`` / ``add_constraint``
    and the IDB view does not."""
    from doxa.persistence.split import NativeIdb, NativeRuntime

    rt = NativeRuntime.new_temporary()
    assert hasattr(rt.edb, "assert_fact")
    assert hasattr(rt.edb, "add_rule")
    assert hasattr(rt.edb, "add_constraint")

    # Reading is an EDB operation too; deriving facts is not.
    assert hasattr(rt.edb, "get_facts")
    assert hasattr(rt.edb, "get_rules")
    assert hasattr(rt.edb, "get_constraints")

    # IDB view should not offer durable writes.
    assert not hasattr(NativeIdb, "assert_fact")
    assert not hasattr(NativeIdb, "add_rule")
    assert not hasattr(NativeIdb, "add_constraint")


def test_idb_is_the_materialization_side() -> None:
    """IDB view carries ``materialize`` / ``query_predicate`` /
    ``configure_predicate`` and the EDB view does not."""
    from doxa.persistence.split import NativeEdb, NativeRuntime

    rt = NativeRuntime.new_temporary()
    assert hasattr(rt.idb, "materialize")
    assert hasattr(rt.idb, "query_predicate")
    assert hasattr(rt.idb, "query_predicate_bulk")
    assert hasattr(rt.idb, "configure_predicate")
    assert hasattr(rt.idb, "set_semantics")
    assert hasattr(rt.idb, "watermark")

    # Pure derived/query operations must not live on the EDB view.
    assert not hasattr(NativeEdb, "materialize")
    assert not hasattr(NativeEdb, "query_predicate")


def test_watermark_contract_across_views() -> None:
    """EDB head advances on write. IDB watermark advances only on
    materialize. This is the minimum sync contract between the two
    views."""
    from doxa.persistence.split import NativeRuntime

    rt = NativeRuntime.new_temporary()
    rt.idb.configure_predicate("p", "maximum", "proof_tree")

    alice = rt.edb.intern("ent:alice")
    rt.edb.assert_fact("main", "p", 1, [alice], 1.0, 0.0, None)

    assert rt.idb.watermark("main") is None
    assert rt.edb.current_watermark() >= 1

    rt.idb.materialize("main")
    idb_wm = rt.idb.watermark("main")
    assert idb_wm == rt.edb.current_watermark()

    # Append one more event — EDB advances, IDB watermark stays put.
    bob = rt.edb.intern("ent:bob")
    rt.edb.assert_fact("main", "p", 1, [bob], 1.0, 0.0, None)
    assert rt.idb.watermark("main") == idb_wm
    assert rt.edb.current_watermark() > idb_wm


def test_idb_is_rebuildable_from_edb(tmp_path: Path) -> None:
    """The IDB can be wiped and rebuilt from the EDB with identical
    query answers. This is the v0.1 acceptance test for
    "IDB is disposable; EDB is the source of truth"."""
    from doxa.persistence.split import NativeRuntime

    edb = tmp_path / "edb"
    idb = tmp_path / "idb"
    edb.mkdir()
    idb.mkdir()

    rt = NativeRuntime.open(str(edb), str(idb))
    rt.idb.configure_predicate("p", "maximum", "proof_tree")

    alice = rt.edb.intern("ent:alice")
    bob = rt.edb.intern("ent:bob")
    rt.edb.assert_fact("main", "p", 1, [alice], 1.0, 0.0, None)
    rt.edb.assert_fact("main", "p", 1, [bob], 1.0, 0.0, None)
    rt.idb.materialize("main")
    before = sorted((tuple(a), b, d) for (a, b, d) in rt.idb.query_predicate_bulk("p"))
    assert len(before) == 2

    # Close the runtime so sled releases the IDB lock, then wipe the IDB.
    rt.close()
    gc.collect()
    shutil.rmtree(idb)
    idb.mkdir()

    rt2 = NativeRuntime.open(str(edb), str(idb))
    rt2.idb.configure_predicate("p", "maximum", "proof_tree")
    # No watermark yet — IDB was wiped.
    assert rt2.idb.watermark("main") is None

    rt2.idb.materialize("main")
    after = sorted((tuple(a), b, d) for (a, b, d) in rt2.idb.query_predicate_bulk("p"))
    assert after == before, "Rebuilt IDB must answer identically"
    assert rt2.idb.watermark("main") == rt2.edb.current_watermark()
    rt2.close()
    gc.collect()
