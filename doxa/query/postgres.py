"""PostgreSQL-native query engine (placeholder).

TODO: Implement query evaluation that translates AX goals into SQL.
  - AtomGoal  →  SELECT … JOIN on belief_records / rule tables
  - BuiltinGoal (eq/lt/gt/…)  →  WHERE clauses
  - negated goals  →  NOT EXISTS subqueries
  - Rule chaining  →  recursive CTEs or iterative fixpoint
"""

from __future__ import annotations

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.engine import QueryEngine, QueryResult


class PostgresQueryEngine(QueryEngine):
    """Pushes query evaluation into PostgreSQL."""

    def __init__(self, db_url: str) -> None:
        self._db_url = db_url
        raise NotImplementedError(
            "PostgresQueryEngine is a placeholder. Implement SQL-based evaluation here."
        )

    def evaluate(self, branch: Branch, query: Query) -> QueryResult:
        raise NotImplementedError
