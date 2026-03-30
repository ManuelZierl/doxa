"""Tests for the Doxa template system."""

from __future__ import annotations

import pytest

from doxa.core.base_kinds import BaseKind
from doxa.core.branch import Branch
from doxa.core.constraint import Constraint
from doxa.core.predicate import Predicate
from doxa.core.template import (
    DoxaStatement,
    EntityTemplateArg,
    FloatTemplateArg,
    IntTemplateArg,
    PredRefTemplateArg,
    StringTemplateArg,
    TemplateCall,
    TemplateContext,
    TemplateImport,
    TypeListTemplateArg,
    VarTemplateArg,
    parse_template_call,
    parse_use_templates,
)
from doxa.core.template_registry import TemplateRegistry
from doxa.core.templates.pred_template import PredTemplate


# ═══════════════════════════════════════════════════════════════════════════
# Template argument parsing
# ═══════════════════════════════════════════════════════════════════════════


class TestParseTemplateCall:
    def test_pred_ref_arg(self) -> None:
        call = parse_template_call("pred foo/2")
        assert call.name == "pred"
        assert len(call.args) == 1
        assert isinstance(call.args[0], PredRefTemplateArg)
        assert call.args[0].name == "foo"
        assert call.args[0].arity == 2

    def test_pred_ref_with_type_list(self) -> None:
        call = parse_template_call("pred foo/2 [int, entity]")
        assert call.name == "pred"
        assert len(call.args) == 2
        assert isinstance(call.args[0], PredRefTemplateArg)
        assert isinstance(call.args[1], TypeListTemplateArg)
        assert call.args[1].types == ["int", "entity"]

    def test_pred_ref_with_type_list_and_annotation(self) -> None:
        call = parse_template_call('pred foo/2 [int, entity] @{description:"test"}')
        assert call.name == "pred"
        assert len(call.args) == 2
        assert call.annotations == {"description": "test"}

    def test_entity_arg(self) -> None:
        call = parse_template_call("mytemplate alice")
        assert len(call.args) == 1
        assert isinstance(call.args[0], EntityTemplateArg)
        assert call.args[0].name == "alice"

    def test_quoted_entity_arg(self) -> None:
        call = parse_template_call("mytemplate 'Thomas'")
        assert len(call.args) == 1
        assert isinstance(call.args[0], EntityTemplateArg)
        assert call.args[0].name == "'Thomas'"

    def test_string_arg(self) -> None:
        call = parse_template_call('mytemplate "hello world"')
        assert len(call.args) == 1
        assert isinstance(call.args[0], StringTemplateArg)
        assert call.args[0].value == "hello world"

    def test_int_arg(self) -> None:
        call = parse_template_call("mytemplate 42")
        assert len(call.args) == 1
        assert isinstance(call.args[0], IntTemplateArg)
        assert call.args[0].value == 42

    def test_negative_int_arg(self) -> None:
        call = parse_template_call("mytemplate -3")
        assert len(call.args) == 1
        assert isinstance(call.args[0], IntTemplateArg)
        assert call.args[0].value == -3

    def test_float_arg(self) -> None:
        call = parse_template_call("mytemplate 3.14")
        assert len(call.args) == 1
        assert isinstance(call.args[0], FloatTemplateArg)
        assert call.args[0].value == pytest.approx(3.14)

    def test_var_arg(self) -> None:
        call = parse_template_call("mytemplate X")
        assert len(call.args) == 1
        assert isinstance(call.args[0], VarTemplateArg)
        assert call.args[0].name == "X"

    def test_underscore_var_arg(self) -> None:
        call = parse_template_call("mytemplate _Tmp")
        assert len(call.args) == 1
        assert isinstance(call.args[0], VarTemplateArg)
        assert call.args[0].name == "_Tmp"

    def test_empty_type_list(self) -> None:
        call = parse_template_call("mytemplate []")
        assert len(call.args) == 1
        assert isinstance(call.args[0], TypeListTemplateArg)
        assert call.args[0].types == []

    def test_multiple_args(self) -> None:
        call = parse_template_call("mytemplate foo/2 [int, string] alice 42")
        assert len(call.args) == 4
        assert isinstance(call.args[0], PredRefTemplateArg)
        assert isinstance(call.args[1], TypeListTemplateArg)
        assert isinstance(call.args[2], EntityTemplateArg)
        assert isinstance(call.args[3], IntTemplateArg)

    def test_no_args(self) -> None:
        call = parse_template_call("mytemplate")
        assert call.name == "mytemplate"
        assert len(call.args) == 0
        assert call.annotations == {}

    def test_annotation_only(self) -> None:
        call = parse_template_call('mytemplate @{description:"test"}')
        assert call.name == "mytemplate"
        assert len(call.args) == 0
        assert call.annotations == {"description": "test"}

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            parse_template_call("")

    def test_rejects_non_identifier(self) -> None:
        with pytest.raises(ValueError, match="expected lowercase identifier"):
            parse_template_call("123bad")

    def test_wildcard_in_type_list(self) -> None:
        call = parse_template_call("pred foo/2 [int, _]")
        assert isinstance(call.args[1], TypeListTemplateArg)
        assert call.args[1].types == ["int", "_"]


# ═══════════════════════════════════════════════════════════════════════════
# use templates parsing
# ═══════════════════════════════════════════════════════════════════════════


class TestParseUseTemplates:
    def test_bare_import(self) -> None:
        imp = parse_use_templates('use templates "doxa_std"')
        assert imp.module == "doxa_std"
        assert imp.names is None

    def test_selective_import(self) -> None:
        imp = parse_use_templates('use templates "my_pkg.billing" [money_pred, vat_rule]')
        assert imp.module == "my_pkg.billing"
        assert imp.names == [("money_pred", "money_pred"), ("vat_rule", "vat_rule")]

    def test_aliased_import(self) -> None:
        imp = parse_use_templates(
            'use templates "my_pkg.billing" [money_pred as money, vat_rule]'
        )
        assert imp.module == "my_pkg.billing"
        assert imp.names == [("money_pred", "money"), ("vat_rule", "vat_rule")]

    def test_rejects_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid 'use templates'"):
            parse_use_templates("use templates")

    def test_rejects_no_quotes(self) -> None:
        with pytest.raises(ValueError, match="Invalid 'use templates'"):
            parse_use_templates("use templates doxa_std")


# ═══════════════════════════════════════════════════════════════════════════
# PredTemplate
# ═══════════════════════════════════════════════════════════════════════════


class TestPredTemplate:
    def setup_method(self) -> None:
        self.template = PredTemplate()
        self.ctx = TemplateContext()

    def test_basic_pred(self) -> None:
        call = parse_template_call("pred parent/2")
        result = self.template.expand(call, self.ctx)

        assert len(result) >= 1
        pred = result[0]
        assert isinstance(pred, Predicate)
        assert pred.name == "parent"
        assert pred.arity == 2
        assert pred._explicitly_declared is True

    def test_pred_with_type_list(self) -> None:
        call = parse_template_call("pred employee/2 [company, person]")
        result = self.template.expand(call, self.ctx)

        # Should have: 1 Predicate + 2 Constraints
        assert len(result) == 3
        assert isinstance(result[0], Predicate)
        assert isinstance(result[1], Constraint)
        assert isinstance(result[2], Constraint)

    def test_pred_with_builtin_types_no_constraints(self) -> None:
        call = parse_template_call("pred foo/2 [entity, entity]")
        result = self.template.expand(call, self.ctx)

        # entity is a builtin type → no constraints generated
        assert len(result) == 1
        assert isinstance(result[0], Predicate)

    def test_pred_with_description(self) -> None:
        call = parse_template_call('pred parent/2 @{description:"parent relation"}')
        result = self.template.expand(call, self.ctx)

        pred = result[0]
        assert isinstance(pred, Predicate)
        assert pred.description == "parent relation"

    def test_pred_type_list_mismatch(self) -> None:
        call = parse_template_call("pred foo/2 [int]")
        with pytest.raises(ValueError, match="type list length.*does not match arity"):
            self.template.expand(call, self.ctx)

    def test_pred_no_args(self) -> None:
        call = TemplateCall(name="pred", args=[], annotations={})
        with pytest.raises(ValueError, match="requires at least one argument"):
            self.template.expand(call, self.ctx)

    def test_pred_wrong_first_arg(self) -> None:
        call = parse_template_call("pred alice")
        with pytest.raises(ValueError, match="requires a predicate reference"):
            self.template.expand(call, self.ctx)

    def test_pred_variable_first_arg(self) -> None:
        call = parse_template_call("pred X")
        with pytest.raises(ValueError, match="requires a predicate reference.*variable"):
            self.template.expand(call, self.ctx)

    def test_pred_wrong_second_arg(self) -> None:
        call = parse_template_call("pred foo/2 alice")
        with pytest.raises(ValueError, match="expects an optional type list"):
            self.template.expand(call, self.ctx)

    def test_pred_too_many_args(self) -> None:
        call = TemplateCall(
            name="pred",
            args=[
                PredRefTemplateArg("foo", 2),
                TypeListTemplateArg(["int", "string"]),
                EntityTemplateArg("extra"),
            ],
            annotations={},
        )
        with pytest.raises(ValueError, match="1 or 2 positional arguments"):
            self.template.expand(call, self.ctx)

    def test_pred_unsupported_annotation(self) -> None:
        call = TemplateCall(
            name="pred",
            args=[PredRefTemplateArg("foo", 2)],
            annotations={"description": "ok", "bogus": "bad"},
        )
        with pytest.raises(ValueError, match="unsupported keys"):
            self.template.expand(call, self.ctx)


# ═══════════════════════════════════════════════════════════════════════════
# TemplateRegistry
# ═══════════════════════════════════════════════════════════════════════════


class TestTemplateRegistry:
    def test_has_builtin_pred(self) -> None:
        reg = TemplateRegistry()
        assert reg.has("pred")

    def test_names(self) -> None:
        reg = TemplateRegistry()
        assert "pred" in reg.names()

    def test_get_unknown_raises(self) -> None:
        reg = TemplateRegistry()
        with pytest.raises(ValueError, match="Unknown template"):
            reg.get("nonexistent")

    def test_register_custom(self) -> None:
        reg = TemplateRegistry()

        class MyTemplate:
            def expand(self, call, ctx):
                return []

        reg.register("my_tmpl", MyTemplate())
        assert reg.has("my_tmpl")

    def test_expand(self) -> None:
        reg = TemplateRegistry()
        call = parse_template_call("pred parent/2")
        result = reg.expand(call)
        assert len(result) >= 1
        assert isinstance(result[0], Predicate)

    def test_import_missing_module_raises(self) -> None:
        reg = TemplateRegistry()
        imp = TemplateImport(module="nonexistent_module_xyz_123")
        with pytest.raises(ValueError, match="Cannot import template module"):
            reg.import_templates(imp)


# ═══════════════════════════════════════════════════════════════════════════
# Branch integration
# ═══════════════════════════════════════════════════════════════════════════


class TestBranchTemplateIntegration:
    def test_pred_through_template_system(self) -> None:
        """pred should work the same as before, now routed through templates."""
        branch = Branch.from_doxa("pred parent/2.\nparent(alice, bob).")

        assert len(branch.predicates) >= 1
        pred = next(p for p in branch.predicates if p.name == "parent")
        assert pred.arity == 2
        assert pred._explicitly_declared is True

        assert len(branch.belief_records) == 1

    def test_pred_with_type_list_generates_constraints(self) -> None:
        branch = Branch.from_doxa("pred employee/2 [company, person].")
        constraints = branch.constraints
        assert len(constraints) == 2

    def test_pred_with_description_through_template(self) -> None:
        branch = Branch.from_doxa(
            'pred parent/2 @{description:"parent(P,C): P is parent of C"}.'
        )
        pred = next(p for p in branch.predicates if p.name == "parent")
        assert pred.description == "parent(P,C): P is parent of C"

    def test_pred_before_and_after_usage(self) -> None:
        """pred can appear before or after the predicate is used in facts."""
        branch = Branch.from_doxa(
            """
            parent(alice, bob).
            pred parent/2.
            """
        )
        pred = next(p for p in branch.predicates if p.name == "parent")
        assert pred._explicitly_declared is True

    def test_duplicate_pred_raises(self) -> None:
        with pytest.raises(ValueError, match="Duplicate predicate declaration"):
            Branch.from_doxa("pred foo/2.\npred foo/2.")

    def test_pred_default_type_list(self) -> None:
        branch = Branch.from_doxa("pred foo/2.")
        pred = next(p for p in branch.predicates if p.name == "foo")
        assert pred.type_list == ["entity", "entity"]

    def test_pred_template_backwards_compatible(self) -> None:
        """The new template-based pred produces the same results as old direct parsing."""
        branch = Branch.from_doxa(
            """
            pred person/1.
            pred age/2 [entity, int].
            person(alice).
            age(alice, 30).
            """
        )
        assert any(p.name == "person" for p in branch.predicates)
        assert any(p.name == "age" for p in branch.predicates)
        assert len(branch.belief_records) == 2

    def test_custom_template_via_registry(self) -> None:
        """A custom template can be passed via a pre-built registry."""

        class TagTemplate:
            def expand(self, call, ctx):
                from datetime import datetime, timezone

                from doxa.core.belief_record import (
                    BeliefEntityArg,
                    BeliefRecord,
                    belief_arg_from_doxa,
                )
                from doxa.core.term_kinds import TermKind

                if len(call.args) != 1 or not isinstance(
                    call.args[0], EntityTemplateArg
                ):
                    raise ValueError("tag requires one entity argument")

                name = call.args[0].name
                rec = BeliefRecord(
                    kind=BaseKind.belief_record,
                    created_at=datetime.now(timezone.utc),
                    pred_name="tagged",
                    pred_arity=1,
                    args=[
                        BeliefEntityArg(
                            kind=BaseKind.belief_arg,
                            term_kind=TermKind.ent,
                            ent_name=name,
                        )
                    ],
                )
                return [rec]

        reg = TemplateRegistry()
        reg.register("tag", TagTemplate())

        branch = Branch.from_doxa("tag alice.", registry=reg)
        assert len(branch.belief_records) == 1
        assert branch.belief_records[0].pred_name == "tagged"

    def test_normal_facts_unaffected(self) -> None:
        """Normal facts/rules/constraints still work alongside templates."""
        branch = Branch.from_doxa(
            """
            pred person/1.
            person(alice).
            ancestor(X, Z) :- parent(X, Y), parent(Y, Z).
            !:- person(X), not alive(X).
            """
        )
        assert len(branch.belief_records) == 1
        assert len(branch.rules) == 1
        assert len(branch.constraints) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Template argument type equality and repr
# ═══════════════════════════════════════════════════════════════════════════


class TestTemplateArgTypes:
    def test_pred_ref_eq(self) -> None:
        a = PredRefTemplateArg("foo", 2)
        b = PredRefTemplateArg("foo", 2)
        c = PredRefTemplateArg("bar", 2)
        assert a == b
        assert a != c

    def test_type_list_eq(self) -> None:
        a = TypeListTemplateArg(["int", "entity"])
        b = TypeListTemplateArg(["int", "entity"])
        c = TypeListTemplateArg(["string"])
        assert a == b
        assert a != c

    def test_var_eq(self) -> None:
        assert VarTemplateArg("X") == VarTemplateArg("X")
        assert VarTemplateArg("X") != VarTemplateArg("Y")

    def test_entity_eq(self) -> None:
        assert EntityTemplateArg("alice") == EntityTemplateArg("alice")
        assert EntityTemplateArg("alice") != EntityTemplateArg("bob")

    def test_string_eq(self) -> None:
        assert StringTemplateArg("hello") == StringTemplateArg("hello")
        assert StringTemplateArg("hello") != StringTemplateArg("world")

    def test_int_eq(self) -> None:
        assert IntTemplateArg(42) == IntTemplateArg(42)
        assert IntTemplateArg(42) != IntTemplateArg(99)

    def test_float_eq(self) -> None:
        assert FloatTemplateArg(3.14) == FloatTemplateArg(3.14)
        assert FloatTemplateArg(3.14) != FloatTemplateArg(2.71)

    def test_repr(self) -> None:
        assert "foo/2" in repr(PredRefTemplateArg("foo", 2))
        assert "int" in repr(TypeListTemplateArg(["int"]))
        assert "X" in repr(VarTemplateArg("X"))
        assert "alice" in repr(EntityTemplateArg("alice"))
        assert "hello" in repr(StringTemplateArg("hello"))
        assert "42" in repr(IntTemplateArg(42))
        assert "3.14" in repr(FloatTemplateArg(3.14))
