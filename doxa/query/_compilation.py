"""Query compilation: translate core models into internal compiled representation."""

from __future__ import annotations

from typing import Any, List, Tuple

from doxa.core.constraint import Constraint
from doxa.core.goal import AssumeGoal, AtomGoal, BuiltinGoal
from doxa.core.query import Query
from doxa.core.rule import Rule, RuleAtomGoal, RuleBuiltinGoal
from doxa.query._types import (
    _AssumeGoal,
    _Atom,
    _BuiltinGoal,
    _CompiledRule,
    _Context,
    _Goal,
    _GroundTerm,
    _Term,
    _VarTerm,
)


def _strip_prefix(name: str, prefix: str) -> str:
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


def _term(arg: Any) -> _Term:
    if hasattr(arg, "var"):
        return _VarTerm(arg.var.name)
    if hasattr(arg, "ent_name"):
        return _GroundTerm(arg.ent_name)
    if hasattr(arg, "pred_ref_name"):
        return _GroundTerm(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
    if hasattr(arg, "value"):
        return _GroundTerm(arg.value)
    raise TypeError(f"Unsupported arg type for compilation: {type(arg)!r}")


def _prefixed_term(arg: Any, prefix: str) -> _Term:
    if hasattr(arg, "var"):
        return _VarTerm(prefix + arg.var.name)
    if hasattr(arg, "ent_name"):
        return _GroundTerm(arg.ent_name)
    if hasattr(arg, "pred_ref_name"):
        return _GroundTerm(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
    if hasattr(arg, "value"):
        return _GroundTerm(arg.value)
    raise TypeError(f"Unsupported arg type for compilation: {type(arg)!r}")


def _compile_query_goals(query: Query) -> List[_Goal]:
    out: List[_Goal] = []
    for g in query.goals:
        if isinstance(g, AssumeGoal):
            compiled_atoms: List[_Atom] = []
            for assumption in g.assumptions:
                compiled_atoms.append(
                    _Atom(
                        pred=assumption.pred_name,
                        negated=assumption.negated,
                        args=tuple(_term(a) for a in assumption.goal_args),
                    )
                )
            out.append(_AssumeGoal(atoms=tuple(compiled_atoms)))
        elif isinstance(g, AtomGoal):
            out.append(
                _Atom(
                    pred=g.pred_name,
                    negated=g.negated,
                    args=tuple(_term(a) for a in g.goal_args),
                )
            )
        elif isinstance(g, BuiltinGoal):
            out.append(
                _BuiltinGoal(
                    op=g.builtin_name,
                    args=tuple(_term(a) for a in g.goal_args),
                )
            )
        else:
            raise TypeError(f"Unsupported query goal type: {type(g)!r}")
    return out


def _compile_rule_head(rule: Rule, prefix: str) -> Tuple[_Term, ...]:
    return tuple(_prefixed_term(a, prefix) for a in rule.head_args)


def _compile_rule_body(rule: Rule, prefix: str) -> List[_Goal]:
    out: List[_Goal] = []
    for g in rule.goals:
        if isinstance(g, RuleAtomGoal):
            out.append(
                _Atom(
                    pred=g.pred_name,
                    negated=g.negated,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        elif isinstance(g, RuleBuiltinGoal):
            out.append(
                _BuiltinGoal(
                    op=g.builtin_name,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        else:
            raise TypeError(f"Unsupported rule goal type: {type(g)!r}")
    return out


def _get_compiled_rule(
    ctx: _Context, rule_idx: int, rule: Rule, depth: int
) -> _CompiledRule:
    key = (rule_idx, depth)
    compiled = ctx.compiled_rule_cache.get(key)
    if compiled is None:
        prefix = f"_r{depth}_"
        compiled = _CompiledRule(
            head_terms=_compile_rule_head(rule, prefix),
            body_goals=tuple(_compile_rule_body(rule, prefix)),
        )
        ctx.compiled_rule_cache[key] = compiled
    return compiled


def _compile_constraint_body(constraint: Constraint, prefix: str) -> List[_Goal]:
    out: List[_Goal] = []
    for g in constraint.goals:
        if isinstance(g, AtomGoal):
            out.append(
                _Atom(
                    pred=g.pred_name,
                    negated=g.negated,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        elif isinstance(g, BuiltinGoal):
            out.append(
                _BuiltinGoal(
                    op=g.builtin_name,
                    args=tuple(_prefixed_term(a, prefix) for a in g.goal_args),
                )
            )
        else:
            raise TypeError(f"Unsupported constraint goal type: {type(g)!r}")
    return out
