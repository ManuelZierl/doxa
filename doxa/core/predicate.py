import re
from typing import TYPE_CHECKING, Dict, List, Literal, Optional

from pydantic import Field, PrivateAttr, field_validator, model_validator

from doxa.core._parsing.annotation_parser import parse_ax_annotation
from doxa.core._parsing.parsing_utils import split_top_level
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import Builtin

if TYPE_CHECKING:
    from doxa.core.constraint import Constraint

_PRED_RE = re.compile(
    r"""
    ^\s*
    pred
    \s+
    (?P<name>[a-z][A-Za-z0-9_]*)
    \s*/\s*
    (?P<arity>\d+)
    (?:\s+\[(?P<types>[^\]]+)\])?
    (?:\s+(?P<annotation>@\{.*\}))?
    \s*$
    """,
    re.VERBOSE | re.DOTALL,
)

_PRED_NAME_RE = re.compile(r"^[a-z][A-Za-z0-9_]*$")

# Reserved keywords that cannot be used as predicate names
_RESERVED_KEYWORDS = {"not", "pred"}


class Predicate(Base):
    kind: Literal[BaseKind.predicate] = Field(...)

    name: str = Field(
        ...,
        description="Predicate name (symbol).",
    )
    arity: int = Field(
        ...,
        gt=0,
        description="Predicate arity (number of arguments).",
    )
    description: Optional[str] = Field(
        default=None,
        description="Optional human-readable predicate documentation.",
    )
    type_list: Optional[List[str]] = Field(
        default=None,
        description="Optional list of type names for each argument position.",
    )

    _explicitly_declared: bool = PrivateAttr(default=False)

    def mark_explicitly_declared(self) -> None:
        object.__setattr__(self, "_explicitly_declared", True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("Predicate.name must be a non-empty string")

        if not _PRED_NAME_RE.fullmatch(v):
            raise ValueError(
                "Invalid Predicate.name: expected an unquoted identifier starting "
                "with a lowercase letter and then using only letters, digits, or '_'. "
                "Examples: parent, source_document, riskScore2."
            )

        if v in _RESERVED_KEYWORDS:
            raise ValueError(
                f"Predicate name '{v}' is a reserved keyword and cannot be used. "
                f"Reserved keywords: {sorted(_RESERVED_KEYWORDS)}"
            )

        if v in [b.value for b in Builtin]:
            raise ValueError(
                f"Predicate name '{v}' is a builtin predicate and cannot be redeclared. "
                f"Builtin predicates: {sorted([b.value for b in Builtin])}"
            )

        return v

    @field_validator("arity")
    @classmethod
    def validate_arity(cls, v: int) -> int:
        if not isinstance(v, int):
            raise ValueError("Predicate.arity must be an integer")

        if v <= 0:
            raise ValueError("Predicate.arity must be > 0")

        return v

    @model_validator(mode="after")
    def validate_type_list_matches_arity(self) -> "Predicate":
        if self.type_list is not None:
            if len(self.type_list) != self.arity:
                raise ValueError(
                    f"Predicate type_list length ({len(self.type_list)}) "
                    f"must match arity ({self.arity})"
                )
        return self

    def to_doxa(self) -> str:
        head = f"pred {self.name}/{self.arity}"

        # Only output type_list if it's not the default [entity, entity, ...]
        if (
            self.type_list is not None
            and self.type_list != [Builtin.entity.value] * self.arity
        ):
            types_str = ", ".join(self.type_list)
            head = f"{head} [{types_str}]"

        if self.description is None:
            return head

        escaped = self.description.replace("\\", "\\\\").replace('"', '\\"')
        return f'{head} @{{description:"{escaped}"}}'

    @classmethod
    def from_doxa(cls, inp: str) -> "Predicate":
        if not isinstance(inp, str):
            raise TypeError("Predicate input must be a string.")

        s = inp.strip()
        if not s:
            raise ValueError("Predicate input must not be empty.")

        m = _PRED_RE.fullmatch(s)
        if not m:
            raise ValueError(
                "Invalid predicate declaration. Expected "
                "'pred <name>/<arity>' or "
                "'pred <name>/<arity> @{description:\"...\"}'."
            )

        arity = int(m.group("arity"))
        kwargs: Dict[str, object] = {
            "kind": BaseKind.predicate,
            "name": m.group("name"),
            "arity": arity,
        }

        types_str = m.group("types")
        if types_str:
            type_parts = split_top_level(types_str.strip())
            kwargs["type_list"] = [t.strip() for t in type_parts]
        else:
            # Auto-generate type_list with 'entity' for all positions
            kwargs["type_list"] = [Builtin.entity.value] * arity

        annotation = m.group("annotation")
        if annotation:
            raw = parse_ax_annotation(annotation)
            unknown = set(raw) - {"description"}
            if unknown:
                raise ValueError(
                    "Predicate annotations only allow ['description']; "
                    f"got unsupported keys: {sorted(unknown)}"
                )
            kwargs.update(raw)

        instance = cls(**kwargs)
        instance.mark_explicitly_declared()
        return instance

    def generate_type_constraints(self) -> List["Constraint"]:
        """Generate type-checking constraints from the type_list.

        Returns an empty list if type_list is None.
        For each argument position i with type T, generates:
            !:- pred_name(X0, ..., Xi, ..., Xn), not T(Xi).
        """
        from doxa.core.type_constraints import generate_predicate_type_constraints

        return generate_predicate_type_constraints(
            self.name, self.arity, self.type_list
        )
