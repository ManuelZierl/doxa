"""Compatibility wrapper for the in-memory query engine.

Shared evaluator internals live in :mod:`doxa.query.evaluator` so other
engines, including PostgreSQL, do not depend on this module.
"""

from doxa.query import evaluator as _evaluator


for _name in dir(_evaluator):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_evaluator, _name)


del _evaluator
del _name
