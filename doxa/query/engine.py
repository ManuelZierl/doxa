"""Abstract query evaluation interface for AX."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from doxa.core.branch import Branch
from doxa.core.query import Query


@dataclass(frozen=True)
class Binding:
    """A single variable-binding row returned by query evaluation."""

    values: Dict[str, Any]


@dataclass(frozen=True)
class QueryResult:
    """Result of evaluating a query against a branch.

    Attributes:
        bindings: List of variable-binding rows satisfying the query.
        success: True if at least one binding was found.
    """

    bindings: List[Binding] = field(default_factory=list)
    explain: Optional[List[Dict[str, Any]]] = None

    @property
    def success(self) -> bool:
        return len(self.bindings) > 0


class QueryEngine(ABC):
    """Abstract interface for evaluating AX queries against a branch.

    Different implementations may evaluate queries in Python (Datalog-style),
    push evaluation into a SQL database, or use other strategies.
    """

    @abstractmethod
    def evaluate(self, branch: Branch, query: Query) -> QueryResult:
        """Evaluate *query* against the data in *branch* and return results."""
        ...
