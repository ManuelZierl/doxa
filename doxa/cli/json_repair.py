"""JSON repair helpers for importing Branch payloads."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from doxa.core.base_kinds import BaseKind


def repair_branch_json(data: dict[str, Any]) -> dict[str, Any]:
    """Auto-fix missing ``kind`` fields and required Branch defaults."""
    repaired = copy.deepcopy(data)

    kind_map = {
        "predicates": BaseKind.predicate,
        "belief_records": BaseKind.belief_record,
        "rules": BaseKind.rule,
        "constraints": BaseKind.constraint,
        "entities": BaseKind.entity,
    }

    if "name" not in repaired:
        repaired["name"] = "imported"
    if "ephemeral" not in repaired:
        repaired["ephemeral"] = False
    if "created_at" not in repaired:
        repaired["created_at"] = datetime.now(timezone.utc).isoformat()

    for field_name in kind_map:
        if field_name not in repaired:
            repaired[field_name] = []

    for field_name, kind in kind_map.items():
        if field_name in repaired and isinstance(repaired[field_name], list):
            for item in repaired[field_name]:
                if isinstance(item, dict) and "kind" not in item:
                    item["kind"] = kind

    if "kind" not in repaired:
        repaired["kind"] = BaseKind.branch

    _fix_nested_kinds(repaired)
    return repaired


def _fix_nested_kinds(obj: Any, parent_context: str | None = None) -> None:
    if isinstance(obj, dict):
        current_context = parent_context
        if "head_pred_name" in obj:
            current_context = "rule"
        elif "kind" in obj and obj["kind"] == BaseKind.constraint:
            current_context = "constraint"

        if "args" in obj and isinstance(obj["args"], list) and "pred_name" in obj:
            for arg in obj["args"]:
                if isinstance(arg, dict) and "kind" not in arg:
                    arg["kind"] = BaseKind.belief_arg

        if "head_args" in obj and isinstance(obj["head_args"], list):
            for i, arg in enumerate(obj["head_args"]):
                if isinstance(arg, dict):
                    if "kind" not in arg:
                        arg["kind"] = BaseKind.rule_head_arg
                    if "pos" not in arg:
                        arg["pos"] = i
                    _fix_nested_kinds(arg, current_context)

        if "goals" in obj and isinstance(obj["goals"], list):
            for i, goal in enumerate(obj["goals"]):
                if isinstance(goal, dict):
                    if "kind" not in goal:
                        goal["kind"] = (
                            BaseKind.rule_goal
                            if current_context == "rule"
                            else BaseKind.goal
                        )
                    if "idx" not in goal:
                        goal["idx"] = i

                    if "goal_args" in goal and isinstance(goal["goal_args"], list):
                        for j, arg in enumerate(goal["goal_args"]):
                            if isinstance(arg, dict):
                                if "kind" not in arg:
                                    arg["kind"] = (
                                        BaseKind.rule_goal_arg
                                        if current_context == "rule"
                                        else BaseKind.goal_arg
                                    )
                                if "pos" not in arg:
                                    arg["pos"] = j
                                _fix_nested_kinds(arg, current_context)
                    _fix_nested_kinds(goal, current_context)

        if "var" in obj and isinstance(obj["var"], dict) and "kind" not in obj["var"]:
            obj["var"]["kind"] = BaseKind.var

        for value in obj.values():
            if isinstance(value, (dict, list)):
                _fix_nested_kinds(value, current_context)

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _fix_nested_kinds(item, parent_context)
