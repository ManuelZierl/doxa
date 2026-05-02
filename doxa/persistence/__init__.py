"""Persistence layer - swappable backends for storing Doxa branches.

Structure
---------

* :class:`~doxa.persistence.repository.BranchRepository` — abstract base
  shared by every backend.
* :class:`~doxa.persistence.memory.InMemoryBranchRepository` — RAM only,
  test/ephemeral default.
* :class:`~doxa.persistence.native.NativeBranchRepository` — sled-backed
  native Rust engine with append-only EDB and materialised IDB.
* :class:`~doxa.persistence.postgres.PostgresBranchRepository` — PostgreSQL
  (optional).

For code that wants to see the EDB/IDB split explicitly (e.g. tests that
assert source-of-truth invariants), use
:mod:`doxa.persistence.split` which exposes
``NativeEdb`` / ``NativeIdb`` / ``NativeRuntime`` views over a shared
native store.
"""

from doxa.persistence.repository import BranchRepository

__all__ = ["BranchRepository"]


def __getattr__(name: str):
    if name in ("PostgresBranchRepository", "connect_postgres"):
        from doxa.persistence import postgres

        return getattr(postgres, name)
    if name == "NativeBranchRepository":
        from doxa.persistence.native import NativeBranchRepository

        return NativeBranchRepository
    if name in ("NativeEdb", "NativeIdb", "NativeRuntime"):
        from doxa.persistence import split

        return getattr(split, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
