import re
from typing import Literal as TypingLiteral
from typing import Union

from pydantic import Field

from doxa.core.literal_type import LiteralType
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")
_DQ_STR_RE = re.compile(r'^"(?:\\.|[^\\\"\n\r])*"$')


class Literal(Base):
    kind: TypingLiteral[BaseKind.literal] = Field(...)

    value: Union[str, int, float, bool] = Field(
        ..., description="Literal value in AX source form."
    )
    datatype: LiteralType = Field(..., description="Literal type tag used by AX.")

    def to_ax(self) -> str:
        if self.datatype == LiteralType.str:
            if "\n" in self.value or "\r" in self.value:
                raise ValueError("Multiline string literals are not allowed")
            s = self.value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{s}"'
        if self.datatype == LiteralType.bool:
            return "true" if bool(self.value) else "false"
        return str(self.value)

    @classmethod
    def from_ax(cls, inp: str) -> "Literal":
        if not inp:
            raise ValueError("Literal.from_ax: empty input")

        # string literal
        if _DQ_STR_RE.fullmatch(inp):
            return cls(kind=BaseKind.literal, datatype=LiteralType.str, value=inp[1:-1])

        # bool
        if inp == "true":
            return cls(kind=BaseKind.literal, datatype=LiteralType.bool, value=True)
        if inp == "false":
            return cls(kind=BaseKind.literal, datatype=LiteralType.bool, value=False)

        # int
        if _INT_RE.fullmatch(inp):
            return cls(kind=BaseKind.literal, datatype=LiteralType.int, value=int(inp))

        # float (after int)
        if _FLOAT_RE.fullmatch(inp):
            return cls(
                kind=BaseKind.literal, datatype=LiteralType.float, value=float(inp)
            )

        raise ValueError(
            "Literal.from_ax: unsupported literal syntax. Expected a double-quoted string, "
            "true/false, int, or float."
        )
