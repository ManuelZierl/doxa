import re
from typing import Literal

from pydantic import Field, field_validator

from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind


_UNQUOTED_RE = re.compile(r"^[A-Z_][A-Za-z0-9_]*$")


class Var(Base):
    kind: Literal[BaseKind.var] = Field(...)
    name: str = Field(
        ..., description="Variable identifier in rule/constraint patterns."
    )

    def to_ax(self) -> str:
        return self.name

    @classmethod
    def from_ax(cls, inp: str) -> "Var":
        return cls(kind=BaseKind.var, name=inp)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("Var.name must be a non-empty string")

        if _UNQUOTED_RE.fullmatch(v):
            return v

        raise ValueError(
            "Invalid Var.name: expected an unquoted variable identifier that starts "
            "with an uppercase letter or '_' and then uses only letters, digits, or '_'. "
            "Examples: X, _X, X1, _Tmp9."
        )
