from __future__ import annotations

from copy import deepcopy
from typing import Any


def compact_schema_for_llm(
    schema: dict[str, Any],
    *,
    drop_keys: set[str] | None = None,
    drop_fields: set[str] | None = None,
    surface_syntax_notes: dict[str, Any] | None = None,
    purpose: str | None = None,
) -> dict[str, Any]:
    """Compact a Pydantic JSON schema for LLM consumption.

    Removes noisy metadata keys and internal parser-managed fields,
    then wraps the result with an optional purpose string and
    surface-syntax notes.

    Args:
        schema: Raw ``model_json_schema()`` output.
        drop_keys: Top-level dict keys to strip everywhere
            (defaults to title, default, additionalProperties, examples).
        drop_fields: Property names to remove from every ``properties``
            block (defaults to created_at, updated_at, kind, idx, pos).
        surface_syntax_notes: Optional dict of syntax hints for the LLM.
        purpose: Optional purpose string for the wrapper.
    """
    schema = deepcopy(schema)

    if drop_keys is None:
        drop_keys = {
            "title",
            "default",
            "additionalProperties",
            "examples",
        }

    if drop_fields is None:
        drop_fields = {
            "created_at",
            "updated_at",
            "kind",
            "idx",
            "pos",
        }

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            # drop noisy keys
            for key in list(node.keys()):
                if key in drop_keys:
                    del node[key]

            # prune object properties
            props = node.get("properties")
            if isinstance(props, dict):
                for field in list(props.keys()):
                    if field in drop_fields:
                        del props[field]

                required = node.get("required")
                if isinstance(required, list):
                    node["required"] = [x for x in required if x not in drop_fields]
                    if not node["required"]:
                        node.pop("required", None)

            # recurse
            for value in list(node.values()):
                walk(value)

        elif isinstance(node, list):
            for item in node:
                walk(item)

        return node

    walk(schema)

    result: dict[str, Any] = {}
    if purpose is not None:
        result["purpose"] = purpose
    if surface_syntax_notes is not None:
        result["surface_syntax_notes"] = surface_syntax_notes
    result["schema"] = schema
    return result
