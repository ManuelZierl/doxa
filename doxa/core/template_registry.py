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
    User templates are added via :meth:`import_templates`.
    """

    def __init__(self) -> None:
        self._templates: Dict[str, DoxaTemplate] = {}
        self._register_builtins()

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

    def import_templates(self, imp: TemplateImport) -> None:
        """Import templates from a Python module based on a parsed
        ``use templates`` statement.

        The target module must expose a ``DOXA_TEMPLATES`` dict mapping
        lowercase template names to ``DoxaTemplate`` instances.
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
            # Import all
            for name, template in registry_dict.items():
                self.register(name, template)
        else:
            for original_name, alias in imp.names:
                if original_name not in registry_dict:
                    raise ValueError(
                        f"Template {original_name!r} not found in module {imp.module!r}. "
                        f"Available: {sorted(registry_dict.keys())}"
                    )
                self.register(alias, registry_dict[original_name])

    # ------------------------------------------------------------------
    # Built-in templates
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        from doxa.core.templates.pred_template import PredTemplate

        self._templates["pred"] = PredTemplate()
