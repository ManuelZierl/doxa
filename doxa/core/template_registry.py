"""Template registry for managing built-in and user-defined templates."""

from __future__ import annotations

import importlib
from typing import Dict, List, Optional

from doxa.core.template import (
    DoxaStatement,
    DoxaTemplate,
    TemplateCall,
    TemplateContext,
    TemplateImport,
)


class TemplateRegistry:
    """Registry holding named templates available for expansion.

    The registry is pre-populated with built-in templates (e.g. ``pred``).
    User templates are registered via :meth:`register`.
    """

    def __init__(self) -> None:
        self._templates: Dict[str, DoxaTemplate] = {}
        from doxa.core.templates import register_builtin_templates

        register_builtin_templates(self)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has(self, name: str) -> bool:
        return name in self._templates

    def get(self, name: str) -> DoxaTemplate:
        if name not in self._templates:
            raise ValueError(f"Unknown template: {name!r}")
        return self._templates[name]

    def register(self, name: str, template: DoxaTemplate) -> None:
        if not isinstance(template, DoxaTemplate):
            raise TypeError(
                f"Template {name!r} must satisfy the DoxaTemplate protocol "
                f"(got {type(template).__name__})."
            )
        self._templates[name] = template

    def expand(
        self,
        call: TemplateCall,
        ctx: Optional[TemplateContext] = None,
    ) -> List[DoxaStatement]:
        if ctx is None:
            ctx = TemplateContext()
        template = self.get(call.name)
        return template.expand(call, ctx)

    def names(self) -> list[str]:
        return list(self._templates.keys())


# ---------------------------------------------------------------------------
# Free-standing template import resolution
# ---------------------------------------------------------------------------


def resolve_template_import(imp: TemplateImport) -> Dict[str, DoxaTemplate]:
    """Resolve a ``use templates`` import by loading the target Python module.

    The module must expose a ``DOXA_TEMPLATES`` dict mapping template names
    to :class:`DoxaTemplate` instances.  Returns a dict of *name → template*
    (after applying aliases).  Callers are responsible for registering the
    returned templates on a :class:`TemplateRegistry`.
    """
    try:
        mod = importlib.import_module(imp.module)
    except ModuleNotFoundError as exc:
        raise ValueError(
            f"Cannot import template module {imp.module!r}: {exc}"
        ) from exc

    registry_dict: Dict[str, DoxaTemplate] = getattr(mod, "DOXA_TEMPLATES", None)
    if registry_dict is None:
        raise ValueError(
            f"Module {imp.module!r} does not expose a DOXA_TEMPLATES dict."
        )

    if imp.names is None:
        return dict(registry_dict)

    resolved: Dict[str, DoxaTemplate] = {}
    for original_name, alias in imp.names:
        if original_name not in registry_dict:
            raise ValueError(
                f"Template {original_name!r} not found in module {imp.module!r}. "
                f"Available: {sorted(registry_dict.keys())}"
            )
        resolved[alias] = registry_dict[original_name]
    return resolved
