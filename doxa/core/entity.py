import re
from typing import Literal

from pydantic import Field, field_validator

from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind


_UNQUOTED_RE = re.compile(r"^[a-z][A-Za-z0-9_]*$")
_QUOTED_RE = re.compile(r"^'([A-Za-z0-9_ ]*)'$")


class Entity(Base):
    kind: Literal[BaseKind.entity] = Field(...)

    name: str = Field(..., description="Entity identifier/symbol in the AX language.")

    def to_ax(self) -> str:
        return self.name

    @classmethod
    def from_ax(cls, inp: str) -> "Entity":
        return cls(kind=BaseKind.entity, name=inp)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("Entity.name must be a non-empty string")

        if _UNQUOTED_RE.fullmatch(v):
            return v

        if _QUOTED_RE.fullmatch(v):
            return v

        raise ValueError(
            "Invalid Entity.name: expected either "
            "(1) an unquoted entity identifier starting with a lowercase letter and then "
            "containing only letters, digits, or '_', "
            "or (2) a single-quoted identifier containing only letters, digits, '_', or spaces. "
            "Examples: x, foo1, 'foo', 'foo bar', '_Bar 9'."
        )
