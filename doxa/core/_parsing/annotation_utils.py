"""Shared utilities for annotation handling."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doxa.core.annotate_mixin import AnnotateMixin


def is_default_annotation(obj: "AnnotateMixin") -> bool:
    """Check if an AnnotateMixin object has all default values.

    Args:
        obj: AnnotateMixin instance to check

    Returns:
        True if all annotation fields are at their default values
    """
    return (
        obj.b == 1.0
        and obj.d == 0.0
        and obj.src is None
        and obj.et is None
        and obj.vf is None
        and obj.vt is None
        and obj.name is None
        and obj.description is None
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

    from doxa.core.annotate_mixin import AnnotateMixin

    ann = AnnotateMixin.from_ax_annotation(annotation_str)
    return {
        "b": ann.b,
        "d": ann.d,
        "src": ann.src,
        "et": ann.et,
        "vf": ann.vf,
        "vt": ann.vt,
        "name": ann.name,
        "description": ann.description,
    }
