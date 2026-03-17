"""In-memory persistence backend – useful for tests and ephemeral sessions."""

from __future__ import annotations

from typing import Dict, List, Optional

from doxa.core.branch import Branch
from doxa.persistence.repository import BranchRepository


class InMemoryBranchRepository(BranchRepository):
    """Stores branches in a plain Python dict (no durability)."""

    def __init__(self) -> None:
        self._branches: Dict[str, Branch] = {}

    def get(self, name: str) -> Optional[Branch]:
        return self._branches.get(name)

    def save(self, branch: Branch) -> None:
        self._branches[branch.name] = branch

    def delete(self, name: str) -> None:
        self._branches.pop(name, None)

    def list_names(self) -> List[str]:
        return list(self._branches.keys())
