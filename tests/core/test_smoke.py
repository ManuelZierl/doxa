"""Smoke tests to verify the new package structure imports correctly."""

from doxa.core import (
    BaseKind,
    Branch,
    Entity,
    Predicate,
)
from doxa.persistence import BranchRepository
from doxa.persistence.memory import InMemoryBranchRepository
from doxa.query import QueryEngine


def test_entity_roundtrip():
    e = Entity(kind=BaseKind.entity, name="alice")
    assert e.to_ax() == "alice"
    assert Entity.from_ax("alice").name == "alice"


def test_predicate_roundtrip():
    p = Predicate(kind=BaseKind.predicate, name="parent", arity=2)
    assert p.to_ax() == "pred parent/2"


def test_branch_from_ax():
    ax_src = "parent(alice, bob)."
    branch = Branch.from_ax(ax_src)
    assert len(branch.belief_records) == 1
    assert branch.belief_records[0].pred_name == "parent"


def test_in_memory_repository():
    repo = InMemoryBranchRepository()
    assert repo.list_names() == []

    branch = Branch.from_ax("person(alice).")
    repo.save(branch)
    assert repo.list_names() == ["main"]

    loaded = repo.get("main")
    assert loaded is not None
    assert len(loaded.belief_records) == 1

    repo.delete("main")
    assert repo.list_names() == []


def test_repository_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        BranchRepository()  # type: ignore[abstract]


def test_query_engine_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        QueryEngine()  # type: ignore[abstract]
