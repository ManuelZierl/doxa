"""Built-in ``pred`` template.

Expands a ``pred name/arity [type_list] @{description:"..."}`` invocation
into a :class:`Predicate` declaration and any associated type-checking
constraints.
"""

from __future__ import annotations

from typing import List

from doxa.core.base_kinds import BaseKind
from doxa.core.builtins import Builtin
from doxa.core.predicate import Predicate
from doxa.core.template import (
    DoxaStatement,
    PredRefTemplateArg,
    TemplateCall,
    TemplateContext,
    TypeListTemplateArg,
    VarTemplateArg,
)

ALLOWED_ANNOTATIONS = {"description"}


class PredTemplate:
    """The built-in ``pred`` template.

    Usage::

        pred foo/2.
        pred foo/2 [int, entity].
        pred foo/2 [int, entity] @{description: "..."}.
    """

    @staticmethod
    def _parse_pred_signature(call: TemplateCall) -> tuple[str, int]:
        if len(call.args) == 0:
            raise ValueError(
                "Template 'pred' requires at least one argument: a predicate reference (name/arity)."
            )
        if len(call.args) > 2:
            raise ValueError(
                f"Template 'pred' accepts 1 or 2 positional arguments, got {len(call.args)}."
            )

        pred_ref_arg = call.args[0]
        if isinstance(pred_ref_arg, VarTemplateArg):
            raise ValueError(
                "Template 'pred' requires a predicate reference (name/arity) as its "
                f"first argument, but got variable '{pred_ref_arg.name}'."
            )
        if not isinstance(pred_ref_arg, PredRefTemplateArg):
            raise ValueError(
                "Template 'pred' requires a predicate reference (name/arity) as its "
                f"first argument, but got {type(pred_ref_arg).__name__}."
            )

        return pred_ref_arg.name, pred_ref_arg.arity

    @staticmethod
    def _parse_type_list(
        call: TemplateCall, pred_name: str, pred_arity: int
    ) -> List[str]:
        if len(call.args) != 2:
            return [Builtin.entity.value] * pred_arity

        type_list_arg = call.args[1]
        if not isinstance(type_list_arg, TypeListTemplateArg):
            raise ValueError(
                "Template 'pred' expects an optional type list [t1, t2, ...] as its "
                f"second argument, but got {type(type_list_arg).__name__}."
            )

        type_list = type_list_arg.types
        if len(type_list) != pred_arity:
            raise ValueError(
                f"Template 'pred': type list length ({len(type_list)}) "
                f"does not match arity ({pred_arity}) for '{pred_name}/{pred_arity}'."
            )

        return type_list

    @staticmethod
    def _parse_description(call: TemplateCall) -> str | None:
        unknown = set(call.annotations) - ALLOWED_ANNOTATIONS
        if unknown:
            raise ValueError(
                "Template 'pred' annotations only allow ['description']; "
                f"got unsupported keys: {sorted(unknown)}"
            )
        return call.annotations.get("description", None)

    def expand(self, call: TemplateCall, ctx: TemplateContext) -> List[DoxaStatement]:
        _ = ctx
        pred_name, pred_arity = self._parse_pred_signature(call)
        type_list = self._parse_type_list(call, pred_name, pred_arity)
        description = self._parse_description(call)

        # ── build Predicate ──────────────────────────────────────────
        pred = Predicate(
            kind=BaseKind.predicate,
            name=pred_name,
            arity=pred_arity,
            type_list=type_list,
            description=description,
        )
        # Mark as explicitly declared
        pred.mark_explicitly_declared()

        # ── build type constraints ───────────────────────────────────
        statements: List[DoxaStatement] = [pred]
        constraints = pred.generate_type_constraints()
        statements.extend(constraints)

        return statements
