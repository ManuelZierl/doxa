import pytest

from doxa.cli.compat import ENGINE_KINDS, MEMORY_KINDS, check_compat, default_engine_for


def test_memory_kinds_defined() -> None:
    assert "memory" in MEMORY_KINDS
    assert "postgres" in MEMORY_KINDS
    assert "native" in MEMORY_KINDS
    assert len(MEMORY_KINDS) == 3


def test_engine_kinds_defined() -> None:
    assert "memory" in ENGINE_KINDS
    assert "postgres" in ENGINE_KINDS
    assert "native" in ENGINE_KINDS
    assert len(ENGINE_KINDS) == 3


def test_check_compat_memory_memory_succeeds() -> None:
    check_compat("memory", "memory")


def test_check_compat_postgres_postgres_succeeds() -> None:
    check_compat("postgres", "postgres")


def test_check_compat_memory_postgres_raises() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        check_compat("memory", "postgres")


def test_check_compat_postgres_memory_raises() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        check_compat("postgres", "memory")


def test_check_compat_unknown_memory_raises() -> None:
    with pytest.raises(ValueError, match="Unknown memory/engine combination"):
        check_compat("unknown", "memory")


def test_check_compat_unknown_engine_raises() -> None:
    with pytest.raises(ValueError, match="Unknown memory/engine combination"):
        check_compat("memory", "unknown")


def test_check_compat_both_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown memory/engine combination"):
        check_compat("unknown", "unknown")


def test_default_engine_for_memory() -> None:
    assert default_engine_for("memory") == "memory"


def test_default_engine_for_postgres() -> None:
    assert default_engine_for("postgres") == "postgres"


def test_default_engine_for_unknown_returns_same() -> None:
    assert default_engine_for("custom") == "custom"
