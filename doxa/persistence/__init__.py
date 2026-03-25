"""Persistence layer – swappable backends for storing AX branches."""

from doxa.persistence.repository import BranchRepository

__all__ = ["BranchRepository"]


def __getattr__(name: str):
    if name in ("PostgresBranchRepository", "connect_postgres"):
        from doxa.persistence import postgres

        return getattr(postgres, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
