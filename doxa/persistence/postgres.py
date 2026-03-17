"""PostgreSQL persistence backend (placeholder).

TODO: Implement using SQLAlchemy / psycopg.  Suggested approach:
  - Single ``branches`` table with ``name TEXT PRIMARY KEY`` and ``data JSONB``.
  - Optional secondary index tables for hot-path lookups
    (e.g. ``belief_records(branch_name, pred_name, data)``).
  - Override fine-grained accessors from BranchRepository when needed.
"""

from __future__ import annotations

from typing import List, Optional

from doxa.core.branch import Branch
from doxa.persistence.repository import BranchRepository


class PostgresBranchRepository(BranchRepository):
    """PostgreSQL-backed branch storage."""

    def __init__(self, db_url: str) -> None:
        self._db_url = db_url
        raise NotImplementedError(
            "PostgresBranchRepository is a placeholder. "
            "Implement using SQLAlchemy + psycopg."
        )

    def get(self, name: str) -> Optional[Branch]:
        raise NotImplementedError

    def save(self, branch: Branch) -> None:
        raise NotImplementedError

    def delete(self, name: str) -> None:
        raise NotImplementedError

    def list_names(self) -> List[str]:
        raise NotImplementedError
