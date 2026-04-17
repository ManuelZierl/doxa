"""Core Pydantic schema models for the Doxa language."""

from doxa.core.annotate_mixin import AnnotateMixin, DescriptionMixin
from doxa.core.audit_mixin import AuditMixin
from doxa.core.base import Base
from doxa.core.base_kinds import BaseKind
from doxa.core.belief_record import (
    BeliefArg,
    BeliefEntityArg,
    BeliefLiteralArg,
    BeliefPredRefArg,
    BeliefRecord,
)
from doxa.core.branch import Branch
from doxa.core.builtins import Builtin
from doxa.core.constraint import Constraint
from doxa.core.entity import Entity
from doxa.core.goal import (
    AssumeGoal,
    AtomGoal,
    BuiltinGoal,
    EntityArg,
    Goal,
    GoalArg,
    GoalBase,
    LiteralArg,
    PredRefArg,
    VarArg,
)
from doxa.core.goal_kinds import GoalKind
from doxa.core.literal import Literal
from doxa.core.literal_type import LiteralType
from doxa.core.predicate import Predicate
from doxa.core.query import Query
from doxa.core.rule import (
    Rule,
    RuleAtomGoal,
    RuleBuiltinGoal,
    RuleGoal,
    RuleGoalArg,
    RuleGoalEntityArg,
    RuleGoalLiteralArg,
    RuleGoalPredRefArg,
    RuleGoalVarArg,
    RuleHeadArg,
    RuleHeadEntityArg,
    RuleHeadLiteralArg,
    RuleHeadPredRefArg,
    RuleHeadVarArg,
)
from doxa.core.template import (
    DoxaStatement,
    DoxaTemplate,
    EntityTemplateArg,
    FloatTemplateArg,
    IntTemplateArg,
    PredRefTemplateArg,
    StringTemplateArg,
    TemplateArg,
    TemplateCall,
    TemplateContext,
    TemplateImport,
    TypeListTemplateArg,
    VarTemplateArg,
    parse_template_call,
    parse_use_templates,
)
from doxa.core.template_registry import TemplateRegistry
from doxa.core.term_kinds import TermKind
from doxa.core.var import Var

__all__ = [
    "Base",
    "BaseKind",
    "Entity",
    "Var",
    "Literal",
    "LiteralType",
    "Predicate",
    "BeliefRecord",
    "BeliefArg",
    "BeliefEntityArg",
    "BeliefLiteralArg",
    "BeliefPredRefArg",
    "Rule",
    "RuleHeadArg",
    "RuleHeadVarArg",
    "RuleHeadEntityArg",
    "RuleHeadLiteralArg",
    "RuleGoal",
    "RuleAtomGoal",
    "RuleBuiltinGoal",
    "RuleGoalArg",
    "RuleGoalVarArg",
    "RuleGoalEntityArg",
    "RuleGoalLiteralArg",
    "RuleGoalPredRefArg",
    "RuleHeadPredRefArg",
    "Goal",
    "GoalBase",
    "AssumeGoal",
    "AtomGoal",
    "BuiltinGoal",
    "GoalArg",
    "VarArg",
    "EntityArg",
    "LiteralArg",
    "PredRefArg",
    "GoalKind",
    "TermKind",
    "Constraint",
    "Branch",
    "Query",
    "Builtin",
    "AnnotateMixin",
    "DescriptionMixin",
    "AuditMixin",
    "DoxaStatement",
    "DoxaTemplate",
    "TemplateArg",
    "TemplateCall",
    "TemplateContext",
    "TemplateImport",
    "TemplateRegistry",
    "PredRefTemplateArg",
    "TypeListTemplateArg",
    "VarTemplateArg",
    "EntityTemplateArg",
    "StringTemplateArg",
    "IntTemplateArg",
    "FloatTemplateArg",
    "parse_template_call",
    "parse_use_templates",
]
