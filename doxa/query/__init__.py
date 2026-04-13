"""Query evaluation layer – swappable engines for evaluating AX queries."""

from doxa.query.engine import QueryEngine, QueryResult

__all__ = ["QueryEngine", "QueryResult"]


def __getattr__(name: str):
    if name == "PostgresQueryEngine":
        from doxa.query.postgres import PostgresQueryEngine

        return PostgresQueryEngine
    if name == "NativeQueryEngine":
        from doxa.query.native import NativeQueryEngine

        return NativeQueryEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
