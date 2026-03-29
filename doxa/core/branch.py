from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

from pydantic import Field

from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import BeliefRecord
from doxa.core.constraint import Constraint
from doxa.core.entity import Entity
from doxa.core.predicate import Predicate
from doxa.core.rule import Rule
from doxa.core.schema_utils import compact_schema_for_llm


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
    def from_doxa(cls, inp: str) -> "Branch":
        if not isinstance(inp, str):
            raise TypeError("Branch input must be a string.")

        # Filter out comment lines starting with %
        lines = inp.split("\n")
        filtered_lines = [line for line in lines if not line.strip().startswith("%")]
        s = "\n".join(filtered_lines).strip()

        if not s:
            raise ValueError("Branch input must not be empty.")

        statements = _split_ax_statements(s)

        predicates: list[Predicate] = []
        entities: list[Entity] = []
        belief_records: list[BeliefRecord] = []
        rules: list[Rule] = []
        constraints: list[Constraint] = []

        pred_map: Dict[tuple[str, int], Predicate] = {}
        explicit_pred_decls: set[tuple[str, int]] = set()
        ent_map: Dict[str, Entity] = {}

        for stmt in statements:
            stripped = stmt.strip()

            if stripped.startswith("pred "):
                pred = Predicate.from_doxa(stripped)
                key = (pred.name, pred.arity)
                if key in explicit_pred_decls:
                    raise ValueError(
                        f"Duplicate predicate declaration: pred {pred.name}/{pred.arity}. "
                        f"Each predicate may only be declared once with 'pred'."
                    )
                was_auto_created = key in pred_map
                explicit_pred_decls.add(key)
                if was_auto_created:
                    # Upgrade auto-created predicate with explicit declaration
                    old = pred_map[key]
                    if old in predicates:
                        predicates[predicates.index(old)] = pred
                    else:
                        predicates.append(pred)
                else:
                    predicates.append(pred)
                pred_map[key] = pred
                # Generate type-checking constraints if type_list is present
                type_constraints = pred.generate_type_constraints()
                for constraint in type_constraints:
                    constraints.append(constraint)
                    cls._collect_entities_from_constraint(constraint, ent_map)
                    cls._collect_predicates_from_constraint(constraint, pred_map)
            elif stripped.startswith("!:-"):
                constraint = Constraint.from_doxa(stripped)
                constraints.append(constraint)
                cls._collect_entities_from_constraint(constraint, ent_map)
                cls._collect_predicates_from_constraint(constraint, pred_map)
            elif _contains_top_level_rule_operator(stripped):
                rule = Rule.from_doxa(stripped)
                rules.append(rule)
                cls._collect_entities_from_rule(rule, ent_map)
                cls._collect_predicates_from_rule(rule, pred_map)
            else:
                record = BeliefRecord.from_doxa(stripped)
                belief_records.append(record)
                cls._collect_entities_from_belief_record(record, ent_map)
                key = (record.pred_name, record.pred_arity)
                if key not in pred_map:
                    pred_map[key] = Predicate(
                        kind=BaseKind.predicate,
                        name=record.pred_name,
                        arity=record.pred_arity,
                        type_list=["entity"] * record.pred_arity,
                    )

        predicates.extend(p for p in pred_map.values() if p not in predicates)
        entities = list(ent_map.values())

        return cls(
            kind=BaseKind.branch,
            created_at=datetime.now(timezone.utc),
            name="main",
            ephemeral=False,
            predicates=predicates,
            entities=entities,
            belief_records=belief_records,
            rules=rules,
            constraints=constraints,
        )

    @classmethod
    def _collect_entities_from_belief_record(
        cls, record: BeliefRecord, ent_map: Dict[str, Entity]
    ) -> None:
        for arg in record.args:
            if hasattr(arg, "ent_name"):
                name = arg.ent_name
                if name not in ent_map:
                    ent_map[name] = Entity(kind=BaseKind.entity, name=name)

    @classmethod
    def _collect_entities_from_rule(
        cls, rule: Rule, ent_map: Dict[str, Entity]
    ) -> None:
        for arg in rule.head_args:
            if hasattr(arg, "ent_name"):
                name = arg.ent_name
                if name not in ent_map:
                    ent_map[name] = Entity(kind=BaseKind.entity, name=name)
        for goal in rule.goals:
            if hasattr(goal, "goal_args"):
                for arg in goal.goal_args:
                    if hasattr(arg, "ent_name"):
                        name = arg.ent_name
                        if name not in ent_map:
                            ent_map[name] = Entity(kind=BaseKind.entity, name=name)

    @classmethod
    def _collect_entities_from_constraint(
        cls, constraint: Constraint, ent_map: Dict[str, Entity]
    ) -> None:
        for goal in constraint.goals:
            if hasattr(goal, "goal_args"):
                for arg in goal.goal_args:
                    if hasattr(arg, "ent_name"):
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
            if hasattr(goal, "pred_name") and hasattr(goal, "pred_arity"):
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
            if hasattr(goal, "pred_name") and hasattr(goal, "pred_arity"):
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

        existing_br = {r.to_doxa() for r in self.belief_records}
        merged_brs = list(self.belief_records) + [
            r for r in other.belief_records if r.to_doxa() not in existing_br
        ]

        existing_rules = {r.to_doxa() for r in self.rules}
        merged_rules = list(self.rules) + [
            r for r in other.rules if r.to_doxa() not in existing_rules
        ]

        existing_constraints = {c.to_doxa() for c in self.constraints}
        merged_constraints = list(self.constraints) + [
            c for c in other.constraints if c.to_doxa() not in existing_constraints
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


# print(Branch.from_doxa(
#     """
#
# pred name/2 @{description:"name(E, NameStr): human-readable label for entity E"}.
# pred alias/2 @{description:"alias(E, AliasStr): alternative label/abbreviation for entity E"}.
#
#
# pred source_document/1 @{description:"source_document(S): provenance source entity for extracted facts"}.
#
# pred concept/1 @{description:"concept(E): abstract concept or analytical construct"}.
# pred procedure/1 @{description:"procedure(E): process / method / analysis / step"}.
# pred organization/1 @{description:"organization(E): organization, institution, initiative, or body"}.
# pred regulation/1 @{description:"regulation(E): law, directive, regulation, guideline or legally-relevant policy text"}.
# pred standard/1 @{description:"standard(E): standard, framework, or set of standards"}.
# pred committee/1 @{description:"committee(E): committee body"}.
# pred country/1 @{description:"country(E): country"}.
# pred government_ministry/1 @{description:"government_ministry(E): government ministry"}.
# pred decision_process/1 @{description:"decision_process(E): formal decision/endorsement process"}.
# pred sustainability_report/1 @{description:"sustainability_report(E): sustainability report document type or instance"}.
#
# pred related_to/2 @{description:"related_to(A,B): generic conceptual relation when no specific predicate fits"}.
# pred part_of/2 @{description:"part_of(Part,Whole): part-whole relation"}.
#
# pred requires/2 @{description:"requires(A,B): A requires B (generic requirement relation)"}.
# pred applies_to/2 @{description:"applies_to(ReqOrStd, TargetClass): requirement/standard applies to a target class"}.
# pred recommends/2 @{description:"recommends(Agent, ProcessOrPractice): Agent recommends a process/practice"}.
# pred considers/2 @{description:"considers(ProcOrConcept, Topic): explicitly considers Topic as part of Proc/Concept"}.
# pred has_step/2 @{description:"has_step(Process, Step): Step is a step of Process"}.
# pred meets/2 @{description:"meets(S,Req): subject S meets requirement/concept Req"}.
#
#
# pred published_by/2 @{description:"published_by(Report, Publisher): publisher of a sustainability report"}.
# pred reports_on/2 @{description:"reports_on(Report, Topic): report covers a topic"}.
#
#
# pred implemented_by/2 @{description:"implemented_by(RequirementOrRegulation, Process): implementation process"}.
# pred consults/2 @{description:"consults(Process, Entity): process consults an entity"}.
#
# organization(european_union) @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
# name(european_union, "Europäische Union") @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
# alias(european_union, "EU") @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
#
# organization(european_commission) @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
# name(european_commission, "Europäische Kommission") @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
# alias(european_commission, "EC") @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:0.8, d:0.0}.
#
# organization(european_financial_reporting_advisory_group) @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
# name(european_financial_reporting_advisory_group, "European Financial Reporting Advisory Group") @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
# alias(european_financial_reporting_advisory_group, "EFRAG") @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
#
# source_document(kb_seed) @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
# name(kb_seed, "KB seed") @{src:kb_seed, et:"2026-03-05T00:00:00Z", b:1.0, d:0.0}.
#     """
# ).model_dump_json())
#
# print(Branch.llm_schema())
