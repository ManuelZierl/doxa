"""Shared branch serialization helpers for CLI commands."""

from __future__ import annotations

from doxa.core.branch import Branch


def branch_to_doxa(
    branch: Branch,
    *,
    predicates: bool = True,
    belief_records: bool = True,
    rules: bool = True,
    constraints: bool = True,
) -> str:
    lines: list[str] = []
    if predicates:
        for pred in branch.predicates:
            lines.append(f"{pred.to_doxa()}.")
    if belief_records:
        for record in branch.belief_records:
            lines.append(f"{record.to_doxa()}.")
    if rules:
        for rule in branch.rules:
            lines.append(f"{rule.to_doxa()}.")
    if constraints:
        for constraint in branch.constraints:
            lines.append(f"{constraint.to_doxa()}.")
    return "\n".join(lines)
