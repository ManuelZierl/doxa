"""Built-in Doxa templates."""

from doxa.core.templates.pred_template import PredTemplate


def register_builtin_templates(registry) -> None:
    registry.register("pred", PredTemplate())


__all__ = ["PredTemplate", "register_builtin_templates"]
