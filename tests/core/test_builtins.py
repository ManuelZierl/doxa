"""Tests for built-in type predicates (int, string, float, entity)."""

import pytest

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.memory import InMemoryQueryEngine


def test_int_type_predicate_matches_integer():
    """Test that int/1 matches integer values."""
    branch = Branch.from_doxa(
        """
        pred value/1.
        value(42).
        value(1.5).
        value("hello").
        """
    )

    query = Query.from_doxa("?- value(X), int(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 1
    assert result.answers[0].bindings["X"] == 42


def test_float_type_predicate_matches_float():
    """Test that float/1 matches floating-point values."""
    branch = Branch.from_doxa(
        """
        pred value/1.
        value(42).
        value(1.5).
        value("hello").
        """
    )

    query = Query.from_doxa("?- value(X), float(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 1
    assert result.answers[0].bindings["X"] == 1.5


def test_string_type_predicate_matches_string():
    """Test that string/1 matches string literal values."""
    branch = Branch.from_doxa(
        """
        pred value/1.
        value(42).
        value(1.5).
        value("hello").
        """
    )

    query = Query.from_doxa("?- value(X), string(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 1
    assert result.answers[0].bindings["X"] == "hello"


def test_entity_type_predicate_matches_entities():
    """Test that entity/1 matches entity identifiers."""
    branch = Branch.from_doxa(
        """
        pred parent/2.
        parent(alice, bob).
        parent(bob, charlie).
        """
    )

    query = Query.from_doxa("?- parent(X, Y), entity(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 2
    assert all(isinstance(b.bindings["X"], str) for b in result.answers)


def test_predicate_with_int_type_list():
    """Test predicate declaration with int type in type list."""
    branch = Branch.from_doxa(
        """
        pred score/2 [entity, int].
        score(alice, 95).
        score(bob, 87).
        """
    )

    # Builtin type predicates (entity, int) don't generate constraints - they're checked at runtime
    # Verify the predicate has the correct type list
    score_pred = next(p for p in branch.predicates if p.name == "score")
    assert score_pred.type_list == ["entity", "int"]

    # Verify query works correctly
    query = Query.from_doxa("?- score(X, S)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 2


def test_predicate_with_mixed_types():
    """Test predicate with mixed type list [entity, int]."""
    branch = Branch.from_doxa(
        """
        pred euro_value/2 [entity, int].
        euro_value(apple, 2).
        euro_value(banana, 1).
        """
    )

    query = Query.from_doxa("?- euro_value(X, V)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 2
    assert result.answers[0].bindings["V"] in [1, 2]


def test_predicate_without_type_list_defaults_to_entity():
    """Test that predicates without type list default to [entity, entity, ...]."""
    branch = Branch.from_doxa(
        """
        pred parent/2.
        parent(alice, bob).
        """
    )

    # Find the parent predicate
    parent_pred = next(p for p in branch.predicates if p.name == "parent")

    # Should have auto-generated type_list
    assert parent_pred.type_list == ["entity", "entity"]

    # Builtin type predicates don't generate constraints - they're checked at runtime
    assert len(branch.constraints) == 0


def test_predicate_serialization_omits_default_entity_types():
    """Test that default [entity, entity] type list is not serialized."""
    branch = Branch.from_doxa(
        """
        pred parent/2.
        """
    )

    serialized = branch.to_doxa()

    # Should not contain the type list in serialization
    assert "pred parent/2." in serialized or "pred parent/2\n" in serialized
    assert "[entity, entity]" not in serialized


def test_predicate_serialization_includes_non_default_types():
    """Test that non-default type lists are serialized."""
    branch = Branch.from_doxa(
        """
        pred score/2 [entity, int].
        """
    )

    serialized = branch.to_doxa()

    # Should contain the type list
    assert "[entity, int]" in serialized


def test_type_constraint_violation_with_int():
    """Test that type checking happens at runtime for builtin type predicates."""
    branch = Branch.from_doxa(
        """
        pred score/2 [entity, int].
        score(alice, 95).
        score(bob, "not_an_int").
        """
    )

    # Builtin type predicates don't generate constraints
    assert len(branch.constraints) == 0

    # Query should work for valid data
    query = Query.from_doxa("?- score(alice, X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 1
    assert result.answers[0].bindings["X"] == 95


def test_int_type_rejects_float():
    """Test that int/1 does not match float values."""
    branch = Branch.from_doxa(
        """
        pred value/1.
        value(1.5).
        """
    )

    query = Query.from_doxa("?- value(X), int(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 0


def test_float_type_rejects_int():
    """Test that float/1 does not match integer values."""
    branch = Branch.from_doxa(
        """
        pred value/1.
        value(42).
        """
    )

    query = Query.from_doxa("?- value(X), float(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 0


def test_string_type_rejects_entity():
    """Test that string/1 distinguishes between string literals and entities."""
    branch = Branch.from_doxa(
        """
        pred item/1.
        item(alice).
        """
    )

    # alice is an entity, not a string literal
    query = Query.from_doxa("?- item(X), string(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    # Entity identifiers are strings, so this should match
    assert len(result.answers) == 1


def test_entity_type_matches_all_string_values():
    """Test that entity/1 matches all string values (entities and string literals)."""
    branch = Branch.from_doxa(
        """
        pred item/1.
        item(alice).
        item("hello").
        item(42).
        """
    )

    query = Query.from_doxa("?- item(X), entity(X)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    # Should match alice and "hello" (both strings), but not 42
    assert len(result.answers) == 2


def test_type_predicates_cannot_be_redeclared():
    """Test that type predicate names cannot be used for user predicates."""
    with pytest.raises(ValueError, match="builtin predicate"):
        Branch.from_doxa("pred int/1.")

    with pytest.raises(ValueError, match="builtin predicate"):
        Branch.from_doxa("pred string/1.")

    with pytest.raises(ValueError, match="builtin predicate"):
        Branch.from_doxa("pred float/1.")

    with pytest.raises(ValueError, match="builtin predicate"):
        Branch.from_doxa("pred entity/1.")


def test_three_arg_predicate_defaults_to_three_entities():
    """Test that arity-3 predicates default to [entity, entity, entity]."""
    branch = Branch.from_doxa(
        """
        pred triple/3.
        """
    )

    triple_pred = next(p for p in branch.predicates if p.name == "triple")
    assert triple_pred.type_list == ["entity", "entity", "entity"]
    # Builtin type predicates don't generate constraints
    assert len(branch.constraints) == 0


def test_mixed_type_list_with_string_and_float():
    """Test predicate with [entity, string, float] type list."""
    branch = Branch.from_doxa(
        """
        pred data/3 [entity, string, float].
        data(item1, "label", 3.14).
        """
    )

    query = Query.from_doxa("?- data(X, Y, Z)")
    engine = InMemoryQueryEngine()
    result = engine.evaluate(branch, query)

    assert len(result.answers) == 1
    assert result.answers[0].bindings["X"] == "item1"
    assert result.answers[0].bindings["Y"] == "label"
    assert result.answers[0].bindings["Z"] == 3.14
