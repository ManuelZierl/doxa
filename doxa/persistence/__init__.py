"""Persistence layer - swappable backends for storing Doxa branches."""

from doxa.persistence.repository import BranchRepository

__all__ = ["BranchRepository"]


def __getattr__(name: str):
    if name in ("PostgresBranchRepository", "connect_postgres"):
        from doxa.persistence import postgres

        return getattr(postgres, name)
    if name == "NativeBranchRepository":
        from doxa.persistence.native import NativeBranchRepository

        return NativeBranchRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
