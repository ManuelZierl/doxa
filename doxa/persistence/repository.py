"""Abstract persistence interface for AX branches."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from doxa.core.belief_record import BeliefRecord
from doxa.core.branch import Branch
from doxa.core.constraint import Constraint
from doxa.core.predicate import Predicate
from doxa.core.rule import Rule


class BranchRepository(ABC):
    """Abstract persistence interface for branches and their contents.

    Every backend must implement the four core methods:
      - get, save, delete, list_names

    Fine-grained accessors (add_belief_record, get_rules, …) have default
    implementations that load the full branch and filter in Python.
    Backends that can do better (e.g. SQL with indexed tables) may override
    them for performance.
    """

    # ------------------------------------------------------------------
    # Core CRUD – every backend MUST implement these
    # ------------------------------------------------------------------

    @abstractmethod
    def get(self, name: str) -> Optional[Branch]:
        """Return the branch with the given name, or None."""
        ...

    @abstractmethod
    def save(self, branch: Branch) -> None:
        """Create or replace a branch."""
        ...

    @abstractmethod
    def delete(self, name: str) -> None:
        """Delete a branch by name (no-op if it does not exist)."""
        ...

    @abstractmethod
    def list_names(self) -> List[str]:
        """Return the names of all stored branches."""
        ...

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Release backend resources (default: no-op)."""
        return None

    def __enter__(self) -> "BranchRepository":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Fine-grained accessors – default implementations
    # Backends MAY override for performance.
    # ------------------------------------------------------------------

    def _require(self, name: str) -> Branch:
        branch = self.get(name)
        if branch is None:
            raise KeyError(f"Branch not found: {name!r}")
        return branch

    def get_predicates(self, branch_name: str) -> List[Predicate]:
        return list(self._require(branch_name).predicates)

    def get_belief_records(
        self, branch_name: str, *, pred_name: Optional[str] = None
    ) -> List[BeliefRecord]:
        records = self._require(branch_name).belief_records
        if pred_name is not None:
            records = [r for r in records if r.pred_name == pred_name]
        return list(records)

    def get_rules(
        self, branch_name: str, *, head_pred_name: Optional[str] = None
    ) -> List[Rule]:
        rules = self._require(branch_name).rules
        if head_pred_name is not None:
            rules = [r for r in rules if r.head_pred_name == head_pred_name]
        return list(rules)

    def get_constraints(self, branch_name: str) -> List[Constraint]:
        return list(self._require(branch_name).constraints)

    def _append_belief_record_to_branch(
        self, branch: Branch, record: BeliefRecord
    ) -> Branch:
        return branch.model_copy(
            update={"belief_records": [*branch.belief_records, record]}
        )

    def _append_rule_to_branch(self, branch: Branch, rule: Rule) -> Branch:
        return branch.model_copy(update={"rules": [*branch.rules, rule]})

    def _append_constraint_to_branch(
        self, branch: Branch, constraint: Constraint
    ) -> Branch:
        return branch.model_copy(
            update={"constraints": [*branch.constraints, constraint]}
        )

    def add_belief_record(self, branch_name: str, record: BeliefRecord) -> None:
        branch = self._require(branch_name)
        updated = self._append_belief_record_to_branch(branch, record)
        self.save(updated)

    def add_rule(self, branch_name: str, rule: Rule) -> None:
        branch = self._require(branch_name)
        updated = self._append_rule_to_branch(branch, rule)
        self.save(updated)

    def add_constraint(self, branch_name: str, constraint: Constraint) -> None:
        branch = self._require(branch_name)
        updated = self._append_constraint_to_branch(branch, constraint)
        self.save(updated)
