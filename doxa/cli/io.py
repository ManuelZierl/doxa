"""File loading helpers shared by CLI commands."""

from __future__ import annotations

import json as json_module
from pathlib import Path

from pydantic import ValidationError

from doxa.cli.json_repair import repair_branch_json
from doxa.core.branch import Branch


class BranchLoadError(ValueError):
    """Raised when loading a branch file fails."""


def load_branch_file(path: Path, fix_missing_kinds: bool = False) -> Branch:
    suffix = path.suffix.lower()

    text = None
    for encoding in [
        "utf-8",
        "utf-8-sig",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "latin-1",
        "cp1252",
    ]:
        try:
            text = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if text is None:
        raise BranchLoadError("Could not decode file with any supported encoding")

    if suffix == ".json":
        if fix_missing_kinds:
            try:
                return Branch.model_validate_json(text)
            except ValidationError:
                data = json_module.loads(text)
                data = repair_branch_json(data)
                return Branch.model_validate(data)
        try:
            return Branch.model_validate_json(text)
        except ValidationError as exc:
            raise BranchLoadError(f"Invalid branch JSON in {path}: {exc}") from exc

    try:
        return Branch.from_doxa(text)
    except Exception as exc:
        raise BranchLoadError(f"Invalid .doxa content in {path}: {exc}") from exc
