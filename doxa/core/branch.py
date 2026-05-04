import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field

from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import BeliefEntityArg, BeliefRecord
from doxa.core.constraint import Constraint
from doxa.core.entity import Entity
from doxa.core.goal import AtomGoal, EntityArg
from doxa.core.predicate import Predicate
from doxa.core.rule import Rule, RuleAtomGoal, RuleGoalEntityArg, RuleHeadEntityArg
from doxa.core.schema_utils import compact_schema_for_llm
from doxa.core.template import (
    DoxaStatement,
    TemplateContext,
    parse_template_call,
    parse_use_templates,
)
from doxa.core.template_registry import TemplateRegistry, resolve_template_import


def _split_ax_statements(inp: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []

    depth_paren = 0
    depth_brace = 0
    in_single = False
    in_double = False
    escape = False

    for ch in inp:
        if escape:
            buf.append(ch)
            escape = False
            continue

        if ch == "\\" and in_double:
            buf.append(ch)
            escape = True
            continue

        if ch == "'" and not in_double:
            buf.append(ch)
            in_single = not in_single
            continue

        if ch == '"' and not in_single:
            buf.append(ch)
            in_double = not in_double
            continue

        if in_single or in_double:
            buf.append(ch)
            continue

        if ch == "(":
            depth_paren += 1
            buf.append(ch)
            continue

        if ch == ")":
            depth_paren -= 1
            if depth_paren < 0:
                raise ValueError("Unbalanced parentheses in AX program.")
            buf.append(ch)
            continue

        if ch == "{":
            depth_brace += 1
            buf.append(ch)
            continue

        if ch == "}":
            depth_brace -= 1
            if depth_brace < 0:
                raise ValueError("Unbalanced braces in AX program.")
            buf.append(ch)
            continue

        if ch == "." and depth_paren == 0 and depth_brace == 0:
            part = "".join(buf).strip()
            if not part:
                raise ValueError("Empty AX statement between '.' delimiters.")
            parts.append(part)
            buf = []
            continue

        buf.append(ch)

    if in_single or in_double:
        raise ValueError("Unterminated quoted string in AX program.")
    if depth_paren != 0:
        raise ValueError("Unbalanced parentheses in AX program.")
    if depth_brace != 0:
        raise ValueError("Unbalanced braces in AX program.")

    tail = "".join(buf).strip()
    if tail:
        raise ValueError("AX program must terminate each statement with '.'")

    return parts


def _contains_top_level_rule_operator(inp: str) -> bool:
    s = inp.strip()
    in_single = False
    in_double = False
    escape = False
    depth_paren = 0
    depth_brace = 0

    i = 0
    while i < len(s) - 1:
        ch = s[i]

        if escape:
            escape = False
            i += 1
            continue

        if ch == "\\" and in_double:
            escape = True
            i += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if in_single or in_double:
            i += 1
            continue

        if ch == "(":
            depth_paren += 1
            i += 1
            continue

        if ch == ")":
            depth_paren -= 1
            i += 1
            continue

        if ch == "{":
            depth_brace += 1
            i += 1
            continue

        if ch == "}":
            depth_brace -= 1
            i += 1
            continue

        if depth_paren == 0 and depth_brace == 0 and s[i : i + 2] == ":-":
            return True

        i += 1

    return False


def _strip_comment_lines(inp: str) -> str:
    lines = inp.split("\n")
    filtered_lines = [line for line in lines if not line.strip().startswith("%")]
    return "\n".join(filtered_lines).strip()


class _BranchBuilder:
    """Collector/builder for `Branch.from_doxa` parsing flow."""

    def __init__(self, branch_cls: type["Branch"], registry: TemplateRegistry) -> None:
        self._branch_cls = branch_cls
        self._registry = registry
        self._ctx = TemplateContext()

        self.predicates: list[Predicate] = []
        self.entities: list[Entity] = []
        self.belief_records: list[BeliefRecord] = []
        self.rules: list[Rule] = []
        self.constraints: list[Constraint] = []

        self.pred_map: Dict[tuple[str, int], Predicate] = {}
        self.explicit_pred_decls: set[tuple[str, int]] = set()
        self.ent_map: Dict[str, Entity] = {}

    def process_statement(self, stmt: str) -> None:
        stripped = stmt.strip()

        if stripped.startswith("use templates "):
            self._import_templates(stripped)
            return

        first_token = stripped.split()[0] if stripped else ""
        if self._registry.has(first_token) and not stripped.startswith("!:-"):
            self._expand_template(stripped)
            return

        if stripped.startswith("!:-"):
            self._add_constraint(Constraint.from_doxa(stripped))
        elif _contains_top_level_rule_operator(stripped):
            self._add_rule(Rule.from_doxa(stripped))
        else:
            self._add_belief_record(BeliefRecord.from_doxa(stripped))

    def build(self) -> "Branch":
        self.predicates.extend(
            p for p in self.pred_map.values() if p not in self.predicates
        )
        self.entities = list(self.ent_map.values())
        return self._branch_cls(
            kind=BaseKind.branch,
            created_at=datetime.now(timezone.utc),
            name="main",
            ephemeral=False,
            predicates=self.predicates,
            entities=self.entities,
            belief_records=self.belief_records,
            rules=self.rules,
            constraints=self.constraints,
        )

    def _import_templates(self, stmt: str) -> None:
        imp = parse_use_templates(stmt)
        loaded = resolve_template_import(imp)
        for name, tmpl in loaded.items():
            self._registry.register(name, tmpl)

    def _expand_template(self, stmt: str) -> None:
        call = parse_template_call(stmt)
        expanded = self._registry.expand(call, self._ctx)
        self._branch_cls._integrate_statements(
            expanded,
            self.predicates,
            self.entities,
            self.belief_records,
            self.rules,
            self.constraints,
            self.pred_map,
            self.explicit_pred_decls,
            self.ent_map,
        )

    def _add_constraint(self, constraint: Constraint) -> None:
        self.constraints.append(constraint)
        self._branch_cls._collect_entities_from_constraint(constraint, self.ent_map)
        self._branch_cls._collect_predicates_from_constraint(constraint, self.pred_map)

    def _add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)
        self._branch_cls._collect_entities_from_rule(rule, self.ent_map)
        self._branch_cls._collect_predicates_from_rule(rule, self.pred_map)

    def _add_belief_record(self, record: BeliefRecord) -> None:
        self.belief_records.append(record)
        self._branch_cls._collect_entities_from_belief_record(record, self.ent_map)
        key = (record.pred_name, record.pred_arity)
        if key not in self.pred_map:
            self.pred_map[key] = Predicate(
                kind=BaseKind.predicate,
                name=record.pred_name,
                arity=record.pred_arity,
                type_list=["entity"] * record.pred_arity,
            )


class Branch(Base, AuditMixin):
    kind: Literal[BaseKind.branch] = Field(...)
    name: str = Field(
        ...,
        description="Unique branch name.",
    )
    # todo: not necessary but maybe nice
    # parent: Optional['Branch'] = Field(
    #     ...,
    #     description="Optional parent branch id for overlay lineage.",
    # )
    ephemeral: bool = Field(
        False,
        description="Marks temporary/ephemeral workspace branches.",
    )

    belief_records: List[BeliefRecord] = Field(
        ...,
        description="Belief records stored in this branch.",
    )
    rules: List[Rule] = Field(
        ...,
        description="Derivation rules stored in this branch.",
    )
    constraints: List[Constraint] = Field(
        ...,
        description="Integrity constraints stored in this branch.",
    )
    # todo: ?
    predicates: List[Predicate] = Field(
        default_factory=list,
        description="Canonical predicates stored in this branch.",
    )
    entities: List[Entity] = Field(
        default_factory=list,
        description="Canonical entities stored in this branch.",
    )

    def to_doxa(self) -> str:
        statements: list[str] = []

        for pred in self.predicates:
            statements.append(f"{pred.to_doxa()}.")
        for rec in self.belief_records:
            statements.append(f"{rec.to_doxa()}.")
        for rule in self.rules:
            statements.append(f"{rule.to_doxa()}.")
        for constraint in self.constraints:
            statements.append(f"{constraint.to_doxa()}.")

        return "\n".join(statements)

    @classmethod
    def from_doxa(
        cls,
        inp: str,
        registry: Optional[TemplateRegistry] = None,
    ) -> "Branch":
        if not isinstance(inp, str):
            raise TypeError("Branch input must be a string.")

        s = _strip_comment_lines(inp)

        if not s:
            raise ValueError("Branch input must not be empty.")

        statements = _split_ax_statements(s)

        # Set up template registry (always includes builtins like 'pred')
        if registry is None:
            registry = TemplateRegistry()

        builder = _BranchBuilder(cls, registry)
        for stmt in statements:
            builder.process_statement(stmt)
        return builder.build()

    @classmethod
    def _integrate_statements(
        cls,
        statements: List["DoxaStatement"],
        predicates: list,
        entities: list,
        belief_records: list,
        rules: list,
        constraints: list,
        pred_map: Dict,
        explicit_pred_decls: set,
        ent_map: Dict,
    ) -> None:
        """Merge expanded template statements into the branch accumulators."""
        for item in statements:
            if isinstance(item, Predicate):
                key = (item.name, item.arity)
                if item._explicitly_declared:
                    if key in explicit_pred_decls:
                        raise ValueError(
                            f"Duplicate predicate declaration: pred {item.name}/{item.arity}. "
                            f"Each predicate may only be declared once with 'pred'."
                        )
                    was_auto_created = key in pred_map
                    explicit_pred_decls.add(key)
                    if was_auto_created:
                        old = pred_map[key]
                        if old in predicates:
                            predicates[predicates.index(old)] = item
                        else:
                            predicates.append(item)
                    else:
                        predicates.append(item)
                    pred_map[key] = item
                else:
                    if key not in pred_map:
                        pred_map[key] = item
                        predicates.append(item)
            elif isinstance(item, Constraint):
                constraints.append(item)
                cls._collect_entities_from_constraint(item, ent_map)
                cls._collect_predicates_from_constraint(item, pred_map)
            elif isinstance(item, Rule):
                rules.append(item)
                cls._collect_entities_from_rule(item, ent_map)
                cls._collect_predicates_from_rule(item, pred_map)
            elif isinstance(item, BeliefRecord):
                belief_records.append(item)
                cls._collect_entities_from_belief_record(item, ent_map)
                key = (item.pred_name, item.pred_arity)
                if key not in pred_map:
                    pred_map[key] = Predicate(
                        kind=BaseKind.predicate,
                        name=item.pred_name,
                        arity=item.pred_arity,
                        type_list=["entity"] * item.pred_arity,
                    )
            else:
                raise TypeError(
                    f"Template emitted unsupported statement type: {type(item).__name__}"
                )

    @classmethod
    def _collect_entities_from_belief_record(
        cls, record: BeliefRecord, ent_map: Dict[str, Entity]
    ) -> None:
        for arg in record.args:
            if isinstance(arg, cls._entity_arg_types()):
                name = arg.ent_name
                if name not in ent_map:
                    ent_map[name] = Entity(kind=BaseKind.entity, name=name)

    @staticmethod
    def _entity_arg_types() -> tuple[type, ...]:
        return (BeliefEntityArg, RuleHeadEntityArg, RuleGoalEntityArg, EntityArg)

    @classmethod
    def _collect_entities_from_rule(
        cls, rule: Rule, ent_map: Dict[str, Entity]
    ) -> None:
        for arg in rule.head_args:
            if isinstance(arg, RuleHeadEntityArg):
                name = arg.ent_name
                if name not in ent_map:
                    ent_map[name] = Entity(kind=BaseKind.entity, name=name)
        for goal in rule.goals:
            if isinstance(goal, RuleAtomGoal):
                for arg in goal.goal_args:
                    if isinstance(arg, RuleGoalEntityArg):
                        name = arg.ent_name
                        if name not in ent_map:
                            ent_map[name] = Entity(kind=BaseKind.entity, name=name)

    @classmethod
    def _collect_entities_from_constraint(
        cls, constraint: Constraint, ent_map: Dict[str, Entity]
    ) -> None:
        for goal in constraint.goals:
            if isinstance(goal, AtomGoal):
                for arg in goal.goal_args:
                    if isinstance(arg, EntityArg):
                        name = arg.ent_name
                        if name not in ent_map:
                            ent_map[name] = Entity(kind=BaseKind.entity, name=name)

    @classmethod
    def _collect_predicates_from_rule(
        cls, rule: Rule, pred_map: Dict[tuple[str, int], Predicate]
    ) -> None:
        key = (rule.head_pred_name, rule.head_pred_arity)
        if key not in pred_map:
            pred_map[key] = Predicate(
                kind=BaseKind.predicate,
                name=rule.head_pred_name,
                arity=rule.head_pred_arity,
                type_list=["entity"] * rule.head_pred_arity,
            )
        for goal in rule.goals:
            if isinstance(goal, RuleAtomGoal):
                key = (goal.pred_name, goal.pred_arity)
                if key not in pred_map:
                    pred_map[key] = Predicate(
                        kind=BaseKind.predicate,
                        name=goal.pred_name,
                        arity=goal.pred_arity,
                        type_list=["entity"] * goal.pred_arity,
                    )

    @classmethod
    def _collect_predicates_from_constraint(
        cls, constraint: Constraint, pred_map: Dict[tuple[str, int], Predicate]
    ) -> None:
        for goal in constraint.goals:
            if isinstance(goal, AtomGoal):
                key = (goal.pred_name, goal.pred_arity)
                if key not in pred_map:
                    pred_map[key] = Predicate(
                        kind=BaseKind.predicate,
                        name=goal.pred_name,
                        arity=goal.pred_arity,
                        type_list=["entity"] * goal.pred_arity,
                    )

    @classmethod
    def llm_schema(cls) -> Dict[str, Any]:
        return compact_schema_for_llm(
            cls.model_json_schema(),
            purpose=(
                "Compact schema for generating AX code. "
                "Internal parser-managed fields such as kind, created_at, updated_at, "
                "idx, and pos are omitted."
            ),
        )

    def merge(self, other: "Branch") -> "Branch":
        """Merge *other* into this branch and return a new combined Branch.

        Deduplication strategy:
          - Predicates: keyed by (name, arity)
          - Entities:   keyed by name
          - BeliefRecords, Rules, Constraints: keyed by their to_doxa() text
        """
        pred_map: Dict[tuple[str, int], "Predicate"] = {
            (p.name, p.arity): p for p in self.predicates
        }
        for p in other.predicates:
            key = (p.name, p.arity)
            if key in pred_map:
                existing = pred_map[key]
                if existing._explicitly_declared and p._explicitly_declared:
                    raise ValueError(
                        f"Duplicate predicate declaration: pred {p.name}/{p.arity}. "
                        f"Each predicate may only be declared once with 'pred'."
                    )
                # Upgrade auto-created predicate with explicit declaration
                if p._explicitly_declared:
                    pred_map[key] = p
            else:
                pred_map[key] = p

        ent_map: Dict[str, "Entity"] = {e.name: e for e in self.entities}
        for e in other.entities:
            if e.name not in ent_map:
                ent_map[e.name] = e

        def _stable_key(obj: Any) -> str:
            payload = obj.model_dump(mode="json", exclude={"created_at", "updated_at"})
            return json.dumps(payload, sort_keys=True, separators=(",", ":"))

        existing_br = {_stable_key(r) for r in self.belief_records}
        merged_brs = list(self.belief_records) + [
            r for r in other.belief_records if _stable_key(r) not in existing_br
        ]

        existing_rules = {_stable_key(r) for r in self.rules}
        merged_rules = list(self.rules) + [
            r for r in other.rules if _stable_key(r) not in existing_rules
        ]

        existing_constraints = {_stable_key(c) for c in self.constraints}
        merged_constraints = list(self.constraints) + [
            c for c in other.constraints if _stable_key(c) not in existing_constraints
        ]

        return self.model_copy(
            update={
                "predicates": list(pred_map.values()),
                "entities": list(ent_map.values()),
                "belief_records": merged_brs,
                "rules": merged_rules,
                "constraints": merged_constraints,
            }
        )
