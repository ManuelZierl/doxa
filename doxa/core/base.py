from pydantic import BaseModel, ConfigDict, Field

from doxa.core.base_kinds import BaseKind


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: BaseKind = Field(..., description="the kind of this Ax Element")

    def to_doxa(self) -> str:
        raise NotImplementedError()

    @classmethod
    def from_doxa(cls, inp: str) -> "Base":
        raise NotImplementedError()
