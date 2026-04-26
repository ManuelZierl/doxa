from __future__ import annotations

from pathlib import Path

import doxa.persistence.native as native_mod
from doxa.core.branch import Branch


class _FakeNativeStore:
    def __init__(self, edb_path: str, idb_path: str) -> None:
        self.edb_path = edb_path
        self.idb_path = idb_path
        self._sym_to_id: dict[str, int] = {}

    def intern(self, text: str) -> int:
        if text not in self._sym_to_id:
            self._sym_to_id[text] = len(self._sym_to_id) + 1
        return self._sym_to_id[text]

    def resolve(self, sym_id: int) -> str | None:
        for text, known_id in self._sym_to_id.items():
            if known_id == sym_id:
                return text
        return None

    def assert_fact(self, *args, **kwargs):
        return 0

    def add_rule(self, *args, **kwargs):
        return 0

    def add_constraint(self, *args, **kwargs):
        return 0

    def get_facts(self, branch_name: str):
        return []

    def flush(self) -> None:
        return None


class _FakeNativeModule:
    NativeStore = _FakeNativeStore


def _make_repo(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(native_mod, "doxa_native", _FakeNativeModule())
    edb = tmp_path / "edb"
    idb = tmp_path / "idb"
    edb.mkdir()
    idb.mkdir()
    return native_mod.NativeBranchRepository(str(edb), str(idb))


def test_native_repo_roundtrips_full_branch_via_snapshot(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path, monkeypatch)
    branch = Branch.from_doxa(
        """
        pred p/1.
        p(a).
        q(X) :- p(X).
        !:- p(a).
        """
    )

    repo.save(branch)
    loaded = repo.get("main")

    assert loaded is not None
    assert len(loaded.belief_records) == 1
    assert len(loaded.rules) == 1
    assert len(loaded.constraints) == 1
    assert loaded.to_doxa() == branch.to_doxa()


def test_native_repo_save_replaces_previous_branch_state(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path, monkeypatch)
    first = Branch.from_doxa(
        """
        pred p/1.
        p(a).
        q(X) :- p(X).
        !:- p(a).
        """
    )
    second = Branch.from_doxa(
        """
        pred p/1.
        p(b).
        """
    )

    repo.save(first)
    repo.save(second)
    loaded = repo.get("main")

    assert loaded is not None
    assert loaded.to_doxa() == second.to_doxa()
    assert len(loaded.rules) == 0
    assert len(loaded.constraints) == 0


def test_native_repo_persists_branch_index_across_restarts(tmp_path: Path, monkeypatch):
    repo1 = _make_repo(tmp_path, monkeypatch)
    branch = Branch.from_doxa(
        """
        pred p/1.
        p(a).
        """
    )
    repo1.save(branch)

    monkeypatch.setattr(native_mod, "doxa_native", _FakeNativeModule())
    repo2 = native_mod.NativeBranchRepository(
        str(tmp_path / "edb"),
        str(tmp_path / "idb"),
    )

    assert repo2.list_names() == ["main"]
    loaded = repo2.get("main")
    assert loaded is not None
    assert loaded.to_doxa() == branch.to_doxa()
