"""Native Rust-backed persistence backend using doxa-native (sled + EDB)."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import quote

from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import (
    BeliefArg,
    BeliefEntityArg,
    BeliefLiteralArg,
    BeliefPredRefArg,
    BeliefRecord,
)
from doxa.core.branch import Branch
from doxa.core.rule import (
    Rule,
    RuleAtomGoal,
    RuleBuiltinGoal,
    RuleGoalEntityArg,
    RuleGoalLiteralArg,
    RuleGoalPredRefArg,
    RuleGoalVarArg,
    RuleHeadEntityArg,
    RuleHeadLiteralArg,
    RuleHeadPredRefArg,
    RuleHeadVarArg,
)
from doxa.core.term_kinds import TermKind
from doxa.persistence.repository import BranchRepository

try:
    doxa_native: Any = importlib.import_module("doxa._native")
except ImportError:
    doxa_native = None


_ENC_ENT = "ent:"
_ENC_LIT = "lit:"
_ENC_PRED_REF = "predref:"


def _require_native() -> None:
    if doxa_native is None:
        raise ImportError(
            "doxa._native is not available. "
            "Install a wheel with `pip install doxa`, or build from source with "
            "`maturin develop --release` (requires Rust toolchain)."
        )


class NativeBranchRepository(BranchRepository):
    """Sled-backed branch storage using the doxa-native Rust engine.

    Usage::

        repo = NativeBranchRepository("./data/edb", "./data/idb")
        repo.save(branch)
        loaded = repo.get("main")
    """

    def __init__(self, edb_path: str, idb_path: str) -> None:
        _require_native()
        if doxa_native is None:
            raise ImportError("doxa._native is not available")
        self._store = doxa_native.NativeStore(edb_path, idb_path)
        # Persistent metadata/snapshots so branch names and full branch content
        # survive process restarts and `save` can obey replace semantics.
        self._repo_meta_dir = Path(edb_path) / ".doxa_native_repo"
        self._branches_dir = self._repo_meta_dir / "branches"
        self._index_file = self._repo_meta_dir / "index.json"
        self._repo_meta_dir.mkdir(parents=True, exist_ok=True)
        self._branches_dir.mkdir(parents=True, exist_ok=True)
        self._known_branches: set[str] = set()
        self._load_index()

    def _snapshot_path(self, branch_name: str) -> Path:
        # Keep filenames portable across filesystems.
        return self._branches_dir / f"{quote(branch_name, safe='')}.json"

    def _load_index(self) -> None:
        if not self._index_file.exists():
            self._known_branches = set()
            return
        try:
            raw = json.loads(self._index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._known_branches = set()
            return

        names = raw.get("branches", []) if isinstance(raw, dict) else []
        if isinstance(names, list):
            self._known_branches = {n for n in names if isinstance(n, str)}
        else:
            self._known_branches = set()

    def _persist_index(self) -> None:
        payload = {"branches": sorted(self._known_branches)}
        tmp = self._index_file.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        tmp.replace(self._index_file)

    def _persist_snapshot(self, branch: Branch) -> None:
        path = self._snapshot_path(branch.name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(branch.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def _load_snapshot(self, branch_name: str) -> Optional[Branch]:
        path = self._snapshot_path(branch_name)
        if not path.exists():
            return None
        try:
            return Branch.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive corruption path
            raise ValueError(
                f"Corrupt native branch snapshot for {branch_name!r} at {path}"
            ) from exc

    # ------------------------------------------------------------------
    # Argument ↔ SymId conversion
    # ------------------------------------------------------------------

    def _intern_belief_arg(self, arg: BeliefArg) -> int:
        """Intern a BeliefArg and return its SymId."""
        if isinstance(arg, BeliefEntityArg):
            return self._store.intern(f"{_ENC_ENT}{arg.ent_name}")
        elif isinstance(arg, BeliefLiteralArg):
            return self._store.intern(f"{_ENC_LIT}{arg.to_doxa()}")
        elif isinstance(arg, BeliefPredRefArg):
            return self._store.intern(
                f"{_ENC_PRED_REF}{arg.pred_ref_name}/{arg.pred_ref_arity}"
            )
        else:
            raise TypeError(f"Unknown belief arg type: {type(arg)}")

    def _resolve_belief_arg(self, sym_id: int, pred_name: str, pos: int) -> BeliefArg:
        """Resolve a SymId back to a BeliefArg (best-effort)."""
        text = self._store.resolve(sym_id)
        if text is None:
            text = str(sym_id)

        if text.startswith(_ENC_ENT):
            return BeliefEntityArg(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.ent,
                ent_name=text[len(_ENC_ENT) :],
            )

        if text.startswith(_ENC_LIT):
            from doxa.core.belief_record import BeliefLiteralArg

            return BeliefLiteralArg.from_doxa(text[len(_ENC_LIT) :])

        if text.startswith(_ENC_PRED_REF):
            from doxa.core.belief_record import BeliefPredRefArg

            return BeliefPredRefArg.from_doxa(text[len(_ENC_PRED_REF) :])

        # Try to reconstruct the original arg type.
        # Since we lose type info during interning, we default to entity.
        from doxa.core.belief_record import belief_arg_from_doxa

        try:
            return belief_arg_from_doxa(text)
        except ValueError:
            return BeliefEntityArg(
                kind=BaseKind.belief_arg,
                term_kind=TermKind.ent,
                ent_name=text,
            )

    # ------------------------------------------------------------------
    # Rule conversion helpers
    # ------------------------------------------------------------------

    def _head_arg_to_term(self, arg) -> object:
        """Convert a Python RuleHeadArg to a term for the Rust side.

        Variables → str (uppercase), ground values → SymId (int).
        """
        if isinstance(arg, RuleHeadVarArg):
            return arg.var.name  # str starting with uppercase
        elif isinstance(arg, RuleHeadEntityArg):
            return self._store.intern(arg.ent_name)
        elif isinstance(arg, RuleHeadLiteralArg):
            return self._store.intern(arg.to_doxa())
        elif isinstance(arg, RuleHeadPredRefArg):
            return self._store.intern(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        else:
            raise TypeError(f"Unknown head arg type: {type(arg)}")

    def _goal_arg_to_term(self, arg) -> object:
        """Convert a Python RuleGoalArg to a term for the Rust side."""
        if isinstance(arg, RuleGoalVarArg):
            return arg.var.name
        elif isinstance(arg, RuleGoalEntityArg):
            return self._store.intern(arg.ent_name)
        elif isinstance(arg, RuleGoalLiteralArg):
            return self._store.intern(arg.to_doxa())
        elif isinstance(arg, RuleGoalPredRefArg):
            return self._store.intern(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        else:
            raise TypeError(f"Unknown goal arg type: {type(arg)}")

    def _goal_to_dict(self, goal) -> dict:
        """Convert a Python RuleGoal to a dict for the Rust side."""
        if isinstance(goal, RuleAtomGoal):
            return {
                "pred_name": goal.pred_name,
                "pred_arity": goal.pred_arity,
                "negated": goal.negated,
                "args": [self._goal_arg_to_term(a) for a in goal.goal_args],
            }
        elif isinstance(goal, RuleBuiltinGoal):
            return {
                "builtin_name": goal.builtin_name.value,
                "args": [self._goal_arg_to_term(a) for a in goal.goal_args],
            }
        else:
            raise TypeError(f"Unknown goal type: {type(goal)}")

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[Branch]:
        if name not in self._known_branches:
            return None

        # Fast path: exact branch round-trip from persisted snapshot.
        snapshot = self._load_snapshot(name)
        if snapshot is not None:
            return snapshot

        # Reconstruct Branch from EDB events
        facts_raw = self._store.get_facts(name)
        belief_records: List[BeliefRecord] = []

        for fact in facts_raw:
            args = [
                self._resolve_belief_arg(sym_id, fact["pred_name"], i)
                for i, sym_id in enumerate(fact["args"])
            ]
            record = BeliefRecord(
                kind=BaseKind.belief_record,
                created_at=datetime.now(timezone.utc),
                updated_at=None,
                pred_name=fact["pred_name"],
                pred_arity=fact["pred_arity"],
                args=args,
                b=fact["b"],
                d=fact["d"],
                src=fact.get("source"),
                vf=None,
                vt=None,
                name=None,
                description=None,
            )
            belief_records.append(record)

        # Fallback mode for legacy stores without snapshots.
        # New saves always persist full branch snapshots.

        return Branch(
            kind=BaseKind.branch,
            created_at=datetime.now(timezone.utc),
            updated_at=None,
            name=name,
            ephemeral=False,
            belief_records=belief_records,
            rules=[],
            constraints=[],
            predicates=[],
            entities=[],
        )

    def save(self, branch: Branch) -> None:
        name = branch.name

        # Assert belief records as EDB facts
        for record in branch.belief_records:
            args = [self._intern_belief_arg(a) for a in record.args]
            self._store.assert_fact(
                name,
                record.pred_name,
                record.pred_arity,
                args,
                record.b,
                record.d,
                record.src,
            )

        # Add rules
        for i, rule in enumerate(branch.rules):
            head_args = [self._head_arg_to_term(a) for a in rule.head_args]
            body = [self._goal_to_dict(g) for g in rule.goals]
            self._store.add_rule(
                name,
                i,  # rule_id
                rule.head_pred_name,
                rule.head_pred_arity,
                head_args,
                body,
                rule.b,
                rule.d,
            )

        # Declare predicates
        for pred in branch.predicates:
            # The native store auto-registers predicates from facts/rules,
            # but explicit declarations are preserved for metadata.
            pass

        self._known_branches.add(name)
        self._persist_snapshot(branch)
        self._persist_index()
        self._store.flush()

    def delete(self, name: str) -> None:
        # EDB is append-only, so we just remove from known set.
        # Existing events are ignored when branch is not in known set.
        self._known_branches.discard(name)
        snapshot = self._snapshot_path(name)
        if snapshot.exists():
            snapshot.unlink()
        self._persist_index()

    def list_names(self) -> List[str]:
        return sorted(self._known_branches)

    # ------------------------------------------------------------------
    # Fine-grained overrides for performance
    # ------------------------------------------------------------------

    def add_belief_record(self, branch_name: str, record: BeliefRecord) -> None:
        if branch_name not in self._known_branches:
            raise KeyError(f"Branch not found: {branch_name!r}")

        args = [self._intern_belief_arg(a) for a in record.args]
        self._store.assert_fact(
            branch_name,
            record.pred_name,
            record.pred_arity,
            args,
            record.b,
            record.d,
            record.src,
        )
        branch = self.get(branch_name)
        if branch is not None:
            updated = self._append_belief_record_to_branch(branch, record)
            self._persist_snapshot(updated)

    def add_rule(self, branch_name: str, rule: Rule) -> None:
        if branch_name not in self._known_branches:
            raise KeyError(f"Branch not found: {branch_name!r}")

        head_args = [self._head_arg_to_term(a) for a in rule.head_args]
        body = [self._goal_to_dict(g) for g in rule.goals]
        branch = self.get(branch_name)
        rule_id = len(branch.rules) if branch is not None else 0
        self._store.add_rule(
            branch_name,
            rule_id,
            rule.head_pred_name,
            rule.head_pred_arity,
            head_args,
            body,
            rule.b,
            rule.d,
        )
        if branch is not None:
            updated = self._append_rule_to_branch(branch, rule)
            self._persist_snapshot(updated)
