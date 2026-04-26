"""Compatibility surface for the in-memory query engine.

Keep this module intentionally narrow so evaluator internals stay private.
"""

from doxa.query.evaluator import InMemoryQueryEngine

__all__ = ["InMemoryQueryEngine"]
