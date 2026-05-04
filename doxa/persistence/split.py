"""Python-facing split of the native store into explicit EDB and IDB views.

The Rust workspace already separates ``doxa_edb``, ``doxa_idb``, and
``doxa_engine`` into independent crates.  On the Python side, however, the
``NativeStore`` class exposes EDB-, IDB-, and engine-level methods through
a single flat API.  That is convenient but hides the architectural split.

This module provides two thin **view objects** on top of a shared
``NativeStore`` handle:

* :class:`NativeEdb` — durable event-log source of truth.
  Only operations that write to or read from the append-only EDB
  (``assert_fact``, ``add_rule``, ``add_constraint``, ``get_facts``,
  ``get_rules``, ``get_constraints``, ``current_watermark``,
  ``list_branches``, symbol interning for encoding purposes).

* :class:`NativeIdb` — derived/materialized reasoning state.
  Only operations that touch the IDB or engine:
  ``materialize``, ``query_predicate``, ``query_predicate_bulk``,
  ``get_atom_state``, ``idb_watermark``, ``configure_predicate``,
  ``set_semantics``.

Both views share the *same* underlying ``NativeStore`` — this is the
v0.1 stable composition described in ``doxa/persistence/native.py``.
The goal of this split is not to enable cross-backend composition today;
it is to make the EDB/IDB contract visible in Python code so that future
backends (Postgres EDB, memory IDB, …) slot in without redesigning the
public surface.

This composition keeps the native Rust coupling intact while making the
following v0.1 contract explicit:

* The EDB is the durable source of truth.
* The IDB is disposable and rebuildable from the EDB.
* Deleting the IDB must not lose knowledge; deleting the EDB does.

See ``tests/persistence/test_native_edb_source_of_truth.py`` for the
regression tests that pin down this invariant.
"""

from __future__ import annotations

import importlib
from typing import Any, List, Optional

try:
    doxa_native: Any = importlib.import_module("doxa._native")
except ImportError:
    doxa_native = None


def _require_native() -> None:
    if doxa_native is None:
        raise ImportError(
            "doxa._native is not available. "
            "Install a wheel with `pip install doxa-lang`, or build from source "
            "with `maturin develop --release` (requires Rust toolchain)."
        )


class NativeEdb:
    """Durable event-log view over a shared ``NativeStore``.

    All writes the EDB accepts (``assert_fact``, ``add_rule``,
    ``add_constraint``) are append-only.  Reads (``get_facts``,
    ``get_rules``, ``get_constraints``, ``list_branches``,
    ``current_watermark``) see an immutable log ordered by event id.

    This is the component that must survive everything else. If the IDB
    directory is wiped, the EDB must be enough to rebuild the system's
    knowledge.
    """

    def __init__(self, store: Any) -> None:
        _require_native()
        self._store = store

    # ── Interning (boundary encoding helper, not state) ──────────────

    def intern(self, text: str) -> int:
        return self._store.intern(text)

    def intern_batch(self, texts: List[str]) -> List[int]:
        return self._store.intern_batch(texts)

    def resolve(self, sym_id: int) -> Optional[str]:
        return self._store.resolve(sym_id)

    def resolve_batch(self, sym_ids: List[int]) -> List[Optional[str]]:
        return self._store.resolve_batch(sym_ids)

    # ── Writes (append-only) ─────────────────────────────────────────

    def assert_fact(
        self,
        branch: str,
        pred_name: str,
        pred_arity: int,
        args: List[int],
        b: float,
        d: float,
        source: Optional[str] = None,
    ) -> int:
        return self._store.assert_fact(
            branch, pred_name, pred_arity, args, b, d, source
        )

    def assert_facts_bulk(self, branch: str, facts: list) -> int:
        return self._store.assert_facts_bulk(branch, facts)

    def add_rule(
        self,
        branch: str,
        rule_id: int,
        head_pred_name: str,
        head_pred_arity: int,
        head_args: list,
        body: list,
        b: float,
        d: float,
    ) -> int:
        return self._store.add_rule(
            branch, rule_id, head_pred_name, head_pred_arity, head_args, body, b, d
        )

    def add_constraint(
        self,
        branch: str,
        constraint_id: int,
        body: list,
        b: float,
        d: float,
    ) -> int:
        return self._store.add_constraint(branch, constraint_id, body, b, d)

    def retract_fact(self, branch: str, target_event_id: int) -> int:
        return self._store.retract_fact(branch, target_event_id)

    # ── Reads ────────────────────────────────────────────────────────

    def get_facts(self, branch: str, watermark: Optional[int] = None) -> list:
        return self._store.get_facts(branch, watermark)

    def get_rules(self, branch: str, watermark: Optional[int] = None) -> list:
        return self._store.get_rules(branch, watermark)

    def get_constraints(self, branch: str, watermark: Optional[int] = None) -> list:
        return self._store.get_constraints(branch, watermark)

    def list_branches(self) -> List[str]:
        return self._store.list_branches()

    def current_watermark(self) -> int:
        """Highest event id written to the EDB (synonym: ``watermark``)."""
        return self._store.edb_watermark()

    watermark = current_watermark

    # ── Lifecycle ────────────────────────────────────────────────────

    def flush(self) -> None:
        self._store.flush()


class NativeIdb:
    """Derived/materialized-state view over a shared ``NativeStore``.

    Everything this view exposes is, by contract, **rebuildable from the
    EDB**.  Wiping the IDB and calling ``materialize`` again on the same
    branch must yield identical query answers.  The IDB watermark records
    the EDB event id up to which derived state is current.
    """

    def __init__(self, store: Any) -> None:
        _require_native()
        self._store = store

    # ── Session configuration ────────────────────────────────────────

    def configure_predicate(
        self, name: str, aggregation: str, evidence_mode: str
    ) -> None:
        self._store.configure_predicate(name, aggregation, evidence_mode)

    def set_semantics(
        self,
        rule_applicability: str,
        constraint_applicability: str,
    ) -> None:
        self._store.set_semantics(rule_applicability, constraint_applicability)

    # ── Materialization / queries ────────────────────────────────────

    def materialize(self, branch: str, max_depth: Optional[int] = None) -> dict:
        """Run the fixpoint evaluator and bring the IDB in sync with the
        current EDB head.  Returns evaluation stats."""
        return self._store.materialize(branch, max_depth)

    def query_predicate(self, pred_name: str) -> list:
        return self._store.query_predicate(pred_name)

    def query_predicate_bulk(self, pred_name: str) -> list:
        return self._store.query_predicate_bulk(pred_name)

    def get_atom_state(self, pred_name: str, args: List[int]) -> dict:
        return self._store.get_atom_state(pred_name, args)

    # ── Watermark (sync contract with the EDB) ───────────────────────

    def watermark(self, branch: str) -> Optional[int]:
        """EDB event id up to which this IDB is materialized for *branch*.

        Returns ``None`` if the branch has never been materialized.
        Compare with ``NativeEdb.current_watermark()`` to detect staleness.
        """
        return self._store.idb_watermark(branch)


class NativeRuntime:
    """Default composition of ``NativeEdb + NativeIdb`` over one shared
    ``NativeStore``.

    This is the v0.1 stable default.  Future work may compose different
    EDB/IDB backends; users of the runtime should not depend on the two
    views being backed by the same native store.

    Example
    -------

    >>> from doxa.persistence.split import NativeRuntime
    >>> rt = NativeRuntime.new_temporary()
    >>> rt.edb.assert_fact("main", "p", 1, [rt.edb.intern("alice")], 1.0, 0.0, None)
    >>> rt.idb.configure_predicate("p", "maximum", "proof_tree")
    >>> rt.idb.materialize("main")  # doctest: +ELLIPSIS
    {...}
    >>> rt.idb.watermark("main") == rt.edb.current_watermark()
    True
    """

    def __init__(self, store: Any) -> None:
        _require_native()
        self._store = store
        self.edb = NativeEdb(store)
        self.idb = NativeIdb(store)

    @classmethod
    def open(cls, edb_path: str, idb_path: str) -> "NativeRuntime":
        _require_native()
        assert doxa_native is not None  # for type checkers
        return cls(doxa_native.NativeStore(edb_path, idb_path))

    @classmethod
    def new_temporary(cls) -> "NativeRuntime":
        _require_native()
        assert doxa_native is not None
        return cls(doxa_native.NativeStore.new_temporary())

    def flush(self) -> None:
        self._store.flush()

    def close(self) -> None:
        """Release the shared native handle (best-effort flush first).

        Sled holds an OS file lock on the EDB directory; this method
        makes it explicit that after ``close()`` no further EDB/IDB
        operations will be issued against this runtime.
        """
        try:
            self._store.flush()
        except Exception:
            pass
        # Break the reference chain so GC can drop the Rust handle.
        self._store = None
        self.edb = None  # type: ignore[assignment]
        self.idb = None  # type: ignore[assignment]
