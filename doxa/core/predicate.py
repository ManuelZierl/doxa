import re
from typing import Optional, Literal, Dict

from pydantic import Field, field_validator

from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core._parsing.annotation_parser import parse_ax_annotation

_PRED_RE = re.compile(
    r"""
    ^\s*
    pred
    \s+
    (?P<name>[a-z][A-Za-z0-9_]*)
    \s*/\s*
    (?P<arity>\d+)
    (?:\s+(?P<annotation>@\{.*\}))?
    \s*$
    """,
    re.VERBOSE | re.DOTALL,
)

_PRED_NAME_RE = re.compile(r"^[a-z][A-Za-z0-9_]*$")


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

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("Predicate.name must be a non-empty string")

        if _PRED_NAME_RE.fullmatch(v):
            return v

        raise ValueError(
            "Invalid Predicate.name: expected an unquoted identifier starting "
            "with a lowercase letter and then using only letters, digits, or '_'. "
            "Examples: parent, source_document, riskScore2."
        )

    @field_validator("arity")
    @classmethod
    def validate_arity(cls, v: int) -> int:
        if not isinstance(v, int):
            raise ValueError("Predicate.arity must be an integer")

        if v < 0:
            raise ValueError("Predicate.arity must be >= 0")

        return v

    def to_ax(self) -> str:
        head = f"pred {self.name}/{self.arity}"

        if self.description is None:
            return head

        escaped = self.description.replace("\\", "\\\\").replace('"', '\\"')
        return f'{head} @{{description:"{escaped}"}}'

    @classmethod
    def from_ax(cls, inp: str) -> "Predicate":
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

        kwargs: Dict[str, object] = {
            "kind": BaseKind.predicate,
            "name": m.group("name"),
            "arity": int(m.group("arity")),
        }

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

        return cls(**kwargs)
