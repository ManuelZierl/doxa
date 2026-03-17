from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field

from doxa.core._parsing.annotation_parser import parse_ax_annotation


class DescriptionMixin(BaseModel):
    description: Optional[str] = Field(
        default=None,
        description="Optional human-readable description.",
    )


class AnnotateMixin(DescriptionMixin):
    b: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Belief component in Belnap evidence range [0, 1].",
    )
    d: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Disbelief component in Belnap evidence range [0, 1].",
    )

    src: Optional[str] = Field(
        None,
        description="Optional source entity id for provenance.",
    )

    et: Optional[datetime] = Field(
        None,
        description="Epistemic time in UTC (when AX learned this record).",
    )
    vf: Optional[datetime] = Field(
        None,
        description="Valid-from time in UTC (world validity interval start).",
    )
    vt: Optional[datetime] = Field(
        None,
        description="Valid-to time in UTC (world validity interval end).",
    )
    name: Optional[str] = Field(
        None,
        description="Optional human readable name",
    )

    def to_ax_annotation(self) -> str:
        parts: List[str] = []

        for key, value in self.model_dump().items():
            if value is None:
                continue

            if isinstance(value, datetime):
                iso = value.isoformat()
                if iso.endswith("+00:00"):
                    iso = iso[:-6] + "Z"
                parts.append(f'{key}:"{iso}"')
            elif isinstance(value, str):
                if key in {"name", "description"}:
                    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                    parts.append(f'{key}:"{escaped}"')
                else:
                    parts.append(f"{key}:{value}")
            else:
                parts.append(f"{key}:{value}")

        return "@{" + ", ".join(parts) + "}"

    @classmethod
    def from_ax_annotation(cls, inp: str) -> "AnnotateMixin":
        raw = parse_ax_annotation(inp)
        allowed = {"b", "d", "src", "et", "vf", "vt", "name", "description"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(
                f"{cls.__name__} annotations do not allow keys: {sorted(unknown)}"
            )
        return cls(**raw)
