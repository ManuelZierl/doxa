"""Shared utilities for annotation handling."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from doxa.core._parsing.annotation_parser import parse_ax_annotation

if TYPE_CHECKING:
    from doxa.core.annotate_mixin import AnnotateMixin


DEFAULT_ANNOTATION_VALUES: dict[str, object] = {
    "b": 1.0,
    "d": 0.0,
    "src": None,
    "et": None,
    "vf": None,
    "vt": None,
    "name": None,
    "description": None,
}


def is_default_annotation(obj: "AnnotateMixin") -> bool:
    """Check if an AnnotateMixin object has all default values.

    Args:
        obj: AnnotateMixin instance to check

    Returns:
        True if all annotation fields are at their default values
    """
    return all(
        getattr(obj, key) == value for key, value in DEFAULT_ANNOTATION_VALUES.items()
    )


def extract_annotation_kwargs(annotation_str: str | None) -> dict[str, object]:
    """Extract annotation fields from an annotation string.

    Args:
        annotation_str: Optional annotation string to parse

    Returns:
        Dictionary of annotation field names to values
    """
    if not annotation_str:
        return {}

    ann = parse_ax_annotation(annotation_str)
    out: dict[str, object] = {
        "b": ann.get("b", DEFAULT_ANNOTATION_VALUES["b"]),
        "d": ann.get("d", DEFAULT_ANNOTATION_VALUES["d"]),
        "et": ann.get("et", datetime.now(timezone.utc)),
    }
    for key in ("src", "vf", "vt", "name", "description"):
        if key in ann:
            out[key] = ann[key]
    return out
