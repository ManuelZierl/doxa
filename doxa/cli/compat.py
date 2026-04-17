"""Memory / engine compatibility registry for the Doxa CLI."""

from __future__ import annotations

# Map of (memory_kind, engine_kind) -> compatible
_COMPAT: dict[tuple[str, str], bool] = {
    ("memory", "memory"): True,
    ("memory", "native"): True,
    ("native", "native"): True,
    ("postgres", "postgres"): True,
    ("memory", "postgres"): False,
    ("postgres", "memory"): False,
    ("postgres", "native"): False,
    ("native", "memory"): True,
    ("native", "postgres"): False,
}


def check_compat(memory: str, engine: str) -> None:
    """Raise ValueError when *memory* and *engine* are incompatible."""
    key = (memory, engine)
    if key not in _COMPAT:
        raise ValueError(
            f"Unknown memory/engine combination: --memory {memory!r} --engine {engine!r}."
        )
    if not _COMPAT[key]:
        raise ValueError(
            f"--memory {memory!r} and --engine {engine!r} are incompatible. "
            "Use a supported pair: ('memory', 'memory'), ('memory', 'native'), "
            "('native', 'memory'), ('native', 'native'), or ('postgres', 'postgres')."
        )


def default_engine_for(memory: str) -> str:
    """Return the natural engine for a given memory backend."""
    return memory  # convention: engine name mirrors memory name


MEMORY_KINDS = ("memory", "native", "postgres")
ENGINE_KINDS = ("memory", "native", "postgres")
