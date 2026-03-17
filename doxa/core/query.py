from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator

from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.goal import (
    Goal,
    goal_from_doxa,
)
from doxa.core.schema_utils import compact_schema_for_llm
from doxa.core._parsing.annotation_parser import parse_ax_annotation
from doxa.core._parsing.parsing_utils import split_annotation_suffix, split_top_level


class QueryOptions(BaseModel):
    """Validated query execution options.

    policy : "report" (default) | "credulous" | "skeptical"
        report    → no belief-score filter (all facts pass)
        credulous → only facts where b > d
        skeptical → only facts where b > d  (same gate as credulous)

    asof : ISO-8601 string or datetime
        Restrict facts to those whose validity window [vf, vt] contains asof.
        A fact with vf=None is valid from the beginning of time.
        A fact with vt=None is valid until the end of time.

    limit : int >= 0
        Return at most this many result bindings (applied after ordering).

    offset : int >= 0
        Skip this many result bindings before applying limit.

    order_by : str or list[str]
        Variable name(s) to sort results by.  A single string may be
        comma-separated (e.g. ``"X, Y"``).

    distinct : bool
        When True, deduplicate identical binding rows.

    max_depth : int > 0
        Hard cap on recursive rule-application depth.  Default 24.
    """

    policy: Literal["report", "credulous", "skeptical"] = "report"
    asof: Optional[datetime] = None
    limit: Optional[int] = Field(default=None, ge=0)
    offset: int = Field(default=0, ge=0)
    order_by: List[str] = Field(default_factory=list)
    distinct: bool = False
    max_depth: int = Field(default=24, gt=0)
    explain: Literal["false", "true", "human"] = "false"

    model_config = {"extra": "forbid"}

    @field_validator("asof", mode="before")
    @classmethod
    def _coerce_asof(cls, v: Any) -> Any:
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    @field_validator("order_by", mode="before")
    @classmethod
    def _coerce_order_by(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @field_validator("limit", "offset", "max_depth", mode="before")
    @classmethod
    def _coerce_int(cls, v: Any) -> Any:
        if v is not None and not isinstance(v, bool):
            return int(v)
        return v

    @field_validator("explain", mode="before")
    @classmethod
    def _coerce_explain(cls, v: Any) -> Any:
        if v is None or v is False:
            return "false"
        if v is True:
            return "true"
        if isinstance(v, str):
            mode = v.lower().strip()
            if mode in {"false", "true", "human"}:
                return mode
            raise ValueError(
                f"Invalid explain mode: {v!r}. Must be 'false', 'true', or 'human'."
            )
        raise ValueError(f"Invalid explain value: {v!r}. Must be boolean or string.")

    def to_doxa_parts(self) -> List[str]:
        """Return a list of ``key:value`` strings for non-default options."""
        parts: List[str] = []
        dump = self.model_dump(exclude_defaults=True, exclude_none=True)
        for key, value in dump.items():
            if isinstance(value, datetime):
                iso = value.isoformat()
                if iso.endswith("+00:00"):
                    iso = iso[:-6] + "Z"
                parts.append(f'{key}:"{iso}"')
            elif isinstance(value, list):
                joined = ", ".join(value)
                parts.append(f'{key}:"{joined}"')
            elif isinstance(value, str):
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                parts.append(f'{key}:"{escaped}"')
            else:
                parts.append(f"{key}:{value}")
        return parts


class Query(Base):
    kind: Literal[BaseKind.query] = Field(...)
    goals: List[Goal] = Field(
        ...,
        description="Ordered query body goals evaluated left-to-right.",
    )
    anon_vars: Set[str] = Field(
        default_factory=set,
        description="Variable names generated from bare anonymous _ placeholders.",
    )
    options: QueryOptions = Field(
        default_factory=QueryOptions,
        description="Query execution options (policy, asof, limit, offset, order_by, distinct, max_depth).",
    )

    @model_validator(mode="after")
    def validate_goal_indices(self) -> "Query":
        indices = [g.idx for g in self.goals]
        if indices != list(range(len(self.goals))):
            raise ValueError(
                f"Query goal indices must be contiguous and ordered from 0; got {indices}."
            )
        return self

    def to_doxa(self) -> str:
        body = ", ".join(goal.to_doxa() for goal in self.goals)
        parts = self.options.to_doxa_parts()
        if not parts:
            return f"?- {body}"
        return f"?- {body} @{{{', '.join(parts)}}}"

    @classmethod
    def from_doxa(cls, inp: str) -> "Query":
        if not isinstance(inp, str):
            raise TypeError("Query input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Query input must not be empty.")

        if not s.startswith("?-"):
            raise ValueError("Query must start with '?-'.")

        rest = s[2:].strip()
        if not rest:
            raise ValueError("Query body must not be empty.")

        body_str, annotation_str = split_annotation_suffix(rest)
        goal_parts = split_top_level(body_str)
        if not goal_parts:
            raise ValueError("Query body must contain at least one goal.")

        goals: List[Goal] = []
        anon_counter = 0
        for i, part in enumerate(goal_parts):
            goal = goal_from_doxa(part)

            # Rename anonymous variables (_) to unique names (_0, _1, _2, …)
            if hasattr(goal, "goal_args"):
                updated_args = []
                for arg in goal.goal_args:
                    if hasattr(arg, "var") and arg.var.name == "_":
                        unique_name = f"_{anon_counter}"
                        anon_counter += 1
                        updated_arg = arg.model_copy(
                            update={
                                "var": arg.var.model_copy(update={"name": unique_name})
                            }
                        )
                        updated_args.append(updated_arg)
                    else:
                        updated_args.append(arg)
                goal = goal.model_copy(update={"goal_args": updated_args})

            goals.append(goal.model_copy(update={"idx": i}))

        options: Dict[str, Any] = {}
        if annotation_str:
            options = parse_ax_annotation(annotation_str)

        anon_vars = {f"_{i}" for i in range(anon_counter)}

        return cls(
            kind=BaseKind.query,
            goals=goals,
            anon_vars=anon_vars,
            options=options,  # pydantic coerces dict → QueryOptions
        )

    @classmethod
    def llm_schema(cls) -> Dict[str, Any]:
        return compact_schema_for_llm(
            cls.model_json_schema(),
            purpose=(
                "Compact schema for AX queries. "
                "Internal parser-managed fields such as kind, idx, and pos are omitted."
            ),
        )
