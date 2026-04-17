"""Native Rust-backed persistence backend using doxa-native (sled + EDB)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

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
    from doxa import _native as doxa_native
except ImportError:
    doxa_native = None  # type: ignore[assignment]


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
        self._store = doxa_native.NativeStore(edb_path, idb_path)
        # Track which branches exist (branch names are not enumerable from EDB
        # events alone without a full scan, so we keep a lightweight set).
        self._known_branches: set[str] = set()

    # ------------------------------------------------------------------
    # Argument ↔ SymId conversion
    # ------------------------------------------------------------------

    def _intern_belief_arg(self, arg: BeliefArg) -> int:
        """Intern a BeliefArg and return its SymId."""
        if isinstance(arg, BeliefEntityArg):
            return self._store.intern(arg.ent_name)
        elif isinstance(arg, BeliefLiteralArg):
            return self._store.intern(arg.to_doxa())
        elif isinstance(arg, BeliefPredRefArg):
            return self._store.intern(f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        else:
            raise TypeError(f"Unknown belief arg type: {type(arg)}")

    def _resolve_belief_arg(self, sym_id: int, pred_name: str, pos: int) -> BeliefArg:
        """Resolve a SymId back to a BeliefArg (best-effort)."""
        text = self._store.resolve(sym_id)
        if text is None:
            text = str(sym_id)
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
            # Builtins are not yet supported in the Rust engine;
            # skip them for now and let the Python evaluator handle them.
            raise NotImplementedError(
                f"Builtin goals ({goal.builtin_name}) are not yet supported "
                "by the native engine."
            )
        else:
            raise TypeError(f"Unknown goal type: {type(goal)}")

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[Branch]:
        if name not in self._known_branches:
            return None

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
                pred_name=fact["pred_name"],
                pred_arity=fact["pred_arity"],
                args=args,
                b=fact["b"],
                d=fact["d"],
                src=fact.get("source"),
            )
            belief_records.append(record)

        # Rules are stored in the EDB but we can't easily reconstruct
        # the full Python Rule from the Rust representation yet.
        # For now, return an empty rules list — the native engine handles
        # rule evaluation internally.
        # TODO: round-trip rules through EDB once type fidelity is complete.

        return Branch(
            kind=BaseKind.branch,
            created_at=datetime.now(timezone.utc),
            name=name,
            belief_records=belief_records,
            rules=[],
            constraints=[],
        )

    def save(self, branch: Branch) -> None:
        name = branch.name

        # If branch already exists, we need to retract all existing facts
        # and re-assert. For now, we always assert (append-only semantics).
        # TODO: implement diff-based save for efficiency.

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
        self._store.flush()

    def delete(self, name: str) -> None:
        # EDB is append-only, so we just remove from known set.
        # Existing events are ignored when branch is not in known set.
        self._known_branches.discard(name)

    def list_names(self) -> List[str]:
        return list(self._known_branches)

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

    def add_rule(self, branch_name: str, rule: Rule) -> None:
        if branch_name not in self._known_branches:
            raise KeyError(f"Branch not found: {branch_name!r}")

        head_args = [self._head_arg_to_term(a) for a in rule.head_args]
        body = [self._goal_to_dict(g) for g in rule.goals]
        self._store.add_rule(
            branch_name,
            0,  # rule_id (auto-assigned)
            rule.head_pred_name,
            rule.head_pred_arity,
            head_args,
            body,
            rule.b,
            rule.d,
        )
