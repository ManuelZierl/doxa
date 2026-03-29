import pytest
from pydantic import ValidationError

from doxa.core import Branch
from doxa.core.base_kinds import BaseKind
from doxa.core.predicate import Predicate


def test_predicate_from_doxa_parses_without_annotation() -> None:
    pred = Predicate.from_doxa("pred parent/2")

    assert pred.kind == BaseKind.predicate
    assert pred.name == "parent"
    assert pred.arity == 2
    assert pred.description is None


def test_predicate_from_doxa_parses_with_description_annotation() -> None:
    pred = Predicate.from_doxa(
        'pred source_document/1 @{description:"source_document(S): provenance source entity"}'
    )

    assert pred.kind == BaseKind.predicate
    assert pred.name == "source_document"
    assert pred.arity == 1
    assert pred.description == "source_document(S): provenance source entity"


def test_predicate_from_doxa_parses_description_with_escaped_quotes() -> None:
    pred = Predicate.from_doxa('pred quoted/1 @{description:"say \\"hello\\""}')

    assert pred.name == "quoted"
    assert pred.arity == 1
    assert pred.description == 'say "hello"'


def test_predicate_from_doxa_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Predicate.from_doxa("")


def test_predicate_from_doxa_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        Predicate.from_doxa(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "inp",
    [
        "parent/2",
        "pred",
        "pred parent",
        "pred parent/",
        "pred /2",
        "pred Parent/2",
        "pred _parent/2",
        "pred 9parent/2",
        "pred parent/-1",
        "pred parent/2.",
    ],
)
def test_predicate_from_doxa_rejects_invalid_declarations(inp: str) -> None:
    with pytest.raises(ValueError, match="Invalid predicate declaration"):
        Predicate.from_doxa(inp)


def test_predicate_from_doxa_rejects_unsupported_annotation_keys() -> None:
    with pytest.raises(ValueError, match="only allow"):
        Predicate.from_doxa("pred parent/2 @{b:0.9}")


def test_predicate_from_doxa_rejects_mixed_supported_and_unsupported_annotation_keys() -> (
    None
):
    with pytest.raises(ValueError, match="unsupported keys"):
        Predicate.from_doxa(
            'pred parent/2 @{description:"Parent relation", src:registry_2020}'
        )


def test_predicate_to_doxa_without_description() -> None:
    pred = Predicate(
        kind=BaseKind.predicate,
        name="parent",
        arity=2,
    )

    assert pred.to_doxa() == "pred parent/2"


def test_predicate_to_doxa_with_description() -> None:
    pred = Predicate(
        kind=BaseKind.predicate,
        name="source_document",
        arity=1,
        description="source_document(S): provenance source entity",
    )

    assert (
        pred.to_doxa()
        == 'pred source_document/1 @{description:"source_document(S): provenance source entity"}'
    )


def test_predicate_to_doxa_escapes_quotes_and_backslashes() -> None:
    pred = Predicate(
        kind=BaseKind.predicate,
        name="quoted",
        arity=1,
        description='path C:\\tmp says "hi"',
    )

    assert (
        pred.to_doxa() == 'pred quoted/1 @{description:"path C:\\\\tmp says \\"hi\\""}'
    )


def test_predicate_round_trip_without_description() -> None:
    original = Predicate(
        kind=BaseKind.predicate,
        name="parent",
        arity=2,
        type_list=["entity", "entity"],
    )

    reparsed = Predicate.from_doxa(original.to_doxa())

    assert reparsed == original


def test_predicate_round_trip_with_description() -> None:
    original = Predicate(
        kind=BaseKind.predicate,
        name="source_document",
        arity=1,
        description='source_document(S): provenance source entity for "facts"',
        type_list=["entity"],
    )

    reparsed = Predicate.from_doxa(original.to_doxa())

    assert reparsed == original


@pytest.mark.parametrize(
    "name",
    [
        "",
        "Parent",
        "_parent",
        "9parent",
        "parent-name",
        "parent name",
    ],
)
def test_predicate_direct_model_rejects_invalid_name(name: str) -> None:
    with pytest.raises(ValidationError):
        Predicate(
            kind=BaseKind.predicate,
            name=name,
            arity=2,
        )


def test_predicate_direct_model_rejects_negative_arity() -> None:
    with pytest.raises(ValidationError):
        Predicate(
            kind=BaseKind.predicate,
            name="parent",
            arity=-1,
        )


@pytest.mark.parametrize(
    "reserved_name",
    ["not", "pred"],
)
def test_predicate_rejects_reserved_keywords(reserved_name: str) -> None:
    """Test that reserved keywords cannot be used as predicate names."""
    with pytest.raises(ValueError, match="reserved keyword"):
        Predicate.from_doxa(f"pred {reserved_name}/2")


@pytest.mark.parametrize(
    "builtin_name",
    ["eq", "ne", "lt", "leq", "gt", "geq", "add", "sub", "mul", "div", "between"],
)
def test_predicate_rejects_builtin_names(builtin_name: str) -> None:
    """Test that builtin predicate names cannot be redeclared."""
    with pytest.raises(ValueError, match="builtin predicate"):
        Predicate.from_doxa(f"pred {builtin_name}/2")


def test_predicate_with_type_list_parsing() -> None:
    """Test parsing predicate with type list."""
    pred = Predicate.from_doxa("pred parent/2 [person, person]")

    assert pred.name == "parent"
    assert pred.arity == 2
    assert pred.type_list == ["person", "person"]
    assert pred.description is None


def test_predicate_with_type_list_and_description() -> None:
    """Test parsing predicate with both type list and description."""
    pred = Predicate.from_doxa(
        'pred employee/2 [company, person] @{description:"employment relation"}'
    )

    assert pred.name == "employee"
    assert pred.arity == 2
    assert pred.type_list == ["company", "person"]
    assert pred.description == "employment relation"


def test_predicate_type_list_to_doxa() -> None:
    """Test serialization of predicate with type list."""
    pred = Predicate.from_doxa("pred parent/2 [person, person]")

    assert pred.to_doxa() == "pred parent/2 [person, person]"


def test_predicate_type_list_with_description_to_doxa() -> None:
    """Test serialization with both type list and description."""
    pred = Predicate.from_doxa(
        'pred employee/2 [company, person] @{description:"test"}'
    )

    assert pred.to_doxa() == 'pred employee/2 [company, person] @{description:"test"}'


def test_predicate_type_list_round_trip() -> None:
    """Test round-trip parsing and serialization."""
    original = Predicate.from_doxa("pred triple/3 [entity, relation, entity]")
    reparsed = Predicate.from_doxa(original.to_doxa())

    assert reparsed.name == original.name
    assert reparsed.arity == original.arity
    assert reparsed.type_list == original.type_list


def test_predicate_type_list_arity_mismatch() -> None:
    """Test that type list length must match arity."""
    with pytest.raises(ValueError, match="type_list length.*must match arity"):
        Predicate(
            kind=BaseKind.predicate,
            name="parent",
            arity=2,
            type_list=["person"],  # Only 1 type for arity 2
        )


def test_predicate_generate_type_constraints_basic() -> None:
    """Test constraint generation from type list."""
    pred = Predicate.from_doxa("pred parent/2 [person, person]")
    constraints = pred.generate_type_constraints()

    assert len(constraints) == 2

    # First constraint: !:- parent(X0, X1), not person(X0)
    c1 = constraints[0]
    assert len(c1.goals) == 2
    assert c1.goals[0].pred_name == "parent"
    assert c1.goals[0].pred_arity == 2
    assert c1.goals[0].negated is False
    assert c1.goals[1].pred_name == "person"
    assert c1.goals[1].pred_arity == 1
    assert c1.goals[1].negated is True
    assert c1.goals[1].goal_args[0].var.name == "X0"

    # Second constraint: !:- parent(X0, X1), not person(X1)
    c2 = constraints[1]
    assert c2.goals[1].goal_args[0].var.name == "X1"


def test_predicate_generate_type_constraints_three_args() -> None:
    """Test constraint generation with three arguments."""
    pred = Predicate.from_doxa("pred triple/3 [entity, relation, entity]")
    constraints = pred.generate_type_constraints()

    # Only 'relation' generates a constraint; 'entity' is a builtin type predicate
    assert len(constraints) == 1
    assert constraints[0].goals[1].pred_name == "relation"


def test_predicate_generate_type_constraints_none_when_no_type_list() -> None:
    """Test that no constraints are generated without type list."""
    pred = Predicate.from_doxa("pred parent/2")
    constraints = pred.generate_type_constraints()

    assert len(constraints) == 0


def test_branch_auto_generates_constraints_from_pred_type_list() -> None:
    """Test that Branch automatically generates constraints from predicate type lists."""
    branch = Branch.from_doxa(
        """
        pred person/1.
        pred parent/2 [person, person].

        person(alice).
        person(bob).
        parent(alice, bob).
        """
    )

    # Should have 2 constraints auto-generated from parent type list
    assert len(branch.constraints) == 2

    # Both constraints should be about parent predicate
    for c in branch.constraints:
        assert len(c.goals) == 2
        assert c.goals[0].pred_name == "parent"
        assert c.goals[0].pred_arity == 2
        assert c.goals[1].pred_name == "person"
        assert c.goals[1].pred_arity == 1
        assert c.goals[1].negated is True


def test_branch_type_list_with_multiple_predicates() -> None:
    """Test multiple predicates with type lists."""
    branch = Branch.from_doxa(
        """
        pred person/1.
        pred relation/1.
        pred parent/2 [person, person].
        pred triple/3 [person, relation, person].
        """
    )

    # parent generates 2 constraints (person, person), triple generates 3 (person, relation, person)
    assert len(branch.constraints) == 5


def test_branch_mixed_predicates_with_and_without_types() -> None:
    """Test that predicates without type lists don't generate constraints."""
    branch = Branch.from_doxa(
        """
        pred person/1.
        pred parent/2 [person, person].
        pred ancestor/2.
        """
    )

    # Only parent has type list, so only 2 constraints
    assert len(branch.constraints) == 2
    assert len(branch.predicates) == 3


def test_branch_type_constraints_round_trip() -> None:
    """Test that auto-generated constraints survive round-trip."""
    original = Branch.from_doxa(
        """
        pred person/1.
        pred parent/2 [person, person].
        """
    )

    # Serialize to AX - this will include both predicates and constraints
    ax_output = original.to_doxa()

    # The serialized output should contain the predicate with type list
    assert "pred parent/2 [person, person]" in ax_output

    # The serialized output should also contain the generated constraints
    assert "!:- parent(X0, X1), not person(X0)" in ax_output
    assert "!:- parent(X0, X1), not person(X1)" in ax_output

    # Reparse - this will generate constraints again from the predicate
    reparsed = Branch.from_doxa(ax_output)

    # The predicates should be preserved
    assert len(reparsed.predicates) == 2
    parent_pred = next(p for p in reparsed.predicates if p.name == "parent")
    assert parent_pred.type_list == ["person", "person"]

    # The constraints will be duplicated (2 from serialized + 2 from predicate parsing)
    # This is expected behavior - when you serialize a branch with type-checked predicates,
    # the constraints are explicit in the output
    assert len(reparsed.constraints) >= 2


def test_predicate_type_list_single_arg() -> None:
    """Test type list with single argument."""
    pred = Predicate.from_doxa("pred person/1 [entity]")
    constraints = pred.generate_type_constraints()

    # 'entity' is a builtin type predicate, so no constraints are generated
    assert len(constraints) == 0


# ── pred-is-optional tests ──────────────────────────────────────────────────


def test_fact_valid_without_prior_pred_declaration() -> None:
    """A fact like parent(a, b). is valid even if no pred parent/2. appears."""
    branch = Branch.from_doxa("parent(alice, bob).")

    assert len(branch.belief_records) == 1
    assert branch.belief_records[0].pred_name == "parent"
    assert branch.belief_records[0].pred_arity == 2
    # Predicate should be auto-created
    pred_names = {p.name for p in branch.predicates}
    assert "parent" in pred_names


def test_rule_valid_without_prior_pred_declaration() -> None:
    """Rules can introduce predicates implicitly without any pred declaration."""
    branch = Branch.from_doxa(
        """
        parent(alice, bob).
        ancestor(X, Y) :- parent(X, Y).
        """
    )

    assert len(branch.rules) == 1
    pred_names = {p.name for p in branch.predicates}
    assert "parent" in pred_names
    assert "ancestor" in pred_names


def test_constraint_valid_without_prior_pred_declaration() -> None:
    """Constraints can reference predicates without prior pred declaration."""
    branch = Branch.from_doxa(
        """
        approved(alice).
        registered(alice).
        !:- approved(X), not registered(X).
        """
    )

    assert len(branch.constraints) == 1
    pred_names = {p.name for p in branch.predicates}
    assert "approved" in pred_names
    assert "registered" in pred_names


def test_pred_after_fact_usage() -> None:
    """pred declaration is allowed after the predicate is already used in a fact."""
    branch = Branch.from_doxa(
        """
        parent(alice, bob).
        pred parent/2 @{description:"parent(P,C): P is parent of C"}.
        """
    )

    assert len(branch.belief_records) == 1
    # The explicit pred declaration should upgrade the auto-created one
    parent_pred = next(p for p in branch.predicates if p.name == "parent")
    assert parent_pred.description == "parent(P,C): P is parent of C"
    assert parent_pred._explicitly_declared is True


def test_pred_after_rule_usage() -> None:
    """pred declaration is allowed after the predicate is used in a rule."""
    branch = Branch.from_doxa(
        """
        parent(alice, bob).
        ancestor(X, Y) :- parent(X, Y).
        pred ancestor/2 @{description:"transitive ancestry"}.
        """
    )

    ancestor_pred = next(p for p in branch.predicates if p.name == "ancestor")
    assert ancestor_pred.description == "transitive ancestry"
    assert ancestor_pred._explicitly_declared is True


def test_pred_before_fact_usage() -> None:
    """pred declaration before usage works as before."""
    branch = Branch.from_doxa(
        """
        pred parent/2 @{description:"parent relation"}.
        parent(alice, bob).
        """
    )

    parent_pred = next(p for p in branch.predicates if p.name == "parent")
    assert parent_pred.description == "parent relation"
    assert parent_pred._explicitly_declared is True
    assert len(branch.belief_records) == 1


def test_bare_pred_no_runtime_effect_beyond_metadata() -> None:
    """A bare pred foo/2. has no runtime effect beyond metadata/schema presence."""
    branch_with_pred = Branch.from_doxa(
        """
        pred parent/2.
        parent(alice, bob).
        """
    )
    branch_without_pred = Branch.from_doxa(
        """
        parent(alice, bob).
        """
    )

    # Both branches should have the same belief records
    assert len(branch_with_pred.belief_records) == len(
        branch_without_pred.belief_records
    )
    r1 = branch_with_pred.belief_records[0]
    r2 = branch_without_pred.belief_records[0]
    assert r1.pred_name == r2.pred_name
    assert r1.pred_arity == r2.pred_arity
    assert len(r1.args) == len(r2.args)

    # Both branches should have the parent predicate
    assert any(p.name == "parent" for p in branch_with_pred.predicates)
    assert any(p.name == "parent" for p in branch_without_pred.predicates)

    # Neither should generate constraints (no custom type_list)
    assert len(branch_with_pred.constraints) == 0
    assert len(branch_without_pred.constraints) == 0


# ── duplicate pred declaration error tests ──────────────────────────────────


def test_duplicate_pred_declaration_in_single_input_errors() -> None:
    """Two pred declarations for the same name/arity in one input is an error."""
    with pytest.raises(ValueError, match="Duplicate predicate declaration"):
        Branch.from_doxa(
            """
            pred parent/2.
            pred parent/2.
            """
        )


def test_duplicate_pred_declaration_with_different_descriptions_errors() -> None:
    """Two pred declarations for same name/arity error even with different metadata."""
    with pytest.raises(ValueError, match="Duplicate predicate declaration"):
        Branch.from_doxa(
            """
            pred parent/2 @{description:"first"}.
            pred parent/2 @{description:"second"}.
            """
        )


def test_duplicate_pred_declaration_via_merge_errors() -> None:
    """Merging two branches with explicit pred for the same name/arity is an error."""
    branch1 = Branch.from_doxa("pred parent/2.")
    branch2 = Branch.from_doxa("pred parent/2.")

    with pytest.raises(ValueError, match="Duplicate predicate declaration"):
        branch1.merge(branch2)


def test_different_arity_pred_declarations_allowed() -> None:
    """pred foo/1 and pred foo/2 are distinct predicates, not duplicates."""
    branch = Branch.from_doxa(
        """
        pred foo/1.
        pred foo/2.
        """
    )

    assert len([p for p in branch.predicates if p.name == "foo"]) == 2


def test_merge_auto_created_with_explicit_pred_succeeds() -> None:
    """Merging an auto-created predicate with an explicit pred declaration should upgrade it."""
    branch_facts = Branch.from_doxa("parent(alice, bob).")
    branch_pred = Branch.from_doxa('pred parent/2 @{description:"parent relation"}.')

    merged = branch_facts.merge(branch_pred)

    parent_pred = next(p for p in merged.predicates if p.name == "parent")
    assert parent_pred.description == "parent relation"
    assert parent_pred._explicitly_declared is True


def test_merge_explicit_pred_with_auto_created_succeeds() -> None:
    """Merging in the other direction: explicit first, auto-created second."""
    branch_pred = Branch.from_doxa('pred parent/2 @{description:"parent relation"}.')
    branch_facts = Branch.from_doxa("parent(alice, bob).")

    merged = branch_pred.merge(branch_facts)

    parent_pred = next(p for p in merged.predicates if p.name == "parent")
    # The explicit one should be preserved (it was in self)
    assert parent_pred.description == "parent relation"
    assert parent_pred._explicitly_declared is True


def test_merge_two_auto_created_predicates_succeeds() -> None:
    """Merging two auto-created predicates for the same name/arity is fine."""
    branch1 = Branch.from_doxa("parent(alice, bob).")
    branch2 = Branch.from_doxa("parent(charlie, dave).")

    merged = branch1.merge(branch2)

    parent_preds = [p for p in merged.predicates if p.name == "parent"]
    assert len(parent_preds) == 1


# ── explicitly_declared tracking tests ──────────────────────────────────────


def test_predicate_from_doxa_sets_explicitly_declared() -> None:
    """Predicate.from_doxa sets _explicitly_declared to True."""
    pred = Predicate.from_doxa("pred parent/2")
    assert pred._explicitly_declared is True


def test_predicate_constructor_defaults_explicitly_declared_false() -> None:
    """Direct Predicate construction defaults _explicitly_declared to False."""
    pred = Predicate(
        kind=BaseKind.predicate,
        name="parent",
        arity=2,
    )
    assert pred._explicitly_declared is False


def test_pred_with_type_list_after_usage_generates_constraints() -> None:
    """A pred with type_list appearing after usage still generates type constraints."""
    branch = Branch.from_doxa(
        """
        pred person/1.
        parent(alice, bob).
        pred parent/2 [person, person].
        """
    )

    # Should have 2 constraints from parent's type_list
    assert len(branch.constraints) == 2
    for c in branch.constraints:
        assert c.goals[0].pred_name == "parent"
        assert c.goals[1].pred_name == "person"
        assert c.goals[1].negated is True
