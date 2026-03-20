import pytest

from doxa.core.base_kinds import BaseKind
from doxa.core.branch import Branch
from doxa.core.belief_record import BeliefRecord
from doxa.core.constraint import Constraint
from doxa.core.rule import Rule


def test_branch_from_doxa_parses_single_belief_record() -> None:
    branch = Branch.from_doxa("parent(thomas, manuel).")

    assert branch.kind == BaseKind.branch
    assert branch.name == "main"
    assert branch.ephemeral is False
    assert branch.created_at is not None
    assert len(branch.belief_records) == 1
    assert len(branch.rules) == 0
    assert len(branch.constraints) == 0
    assert isinstance(branch.belief_records[0], BeliefRecord)


def test_branch_from_doxa_parses_single_rule() -> None:
    branch = Branch.from_doxa("ancestor(X, Y) :- parent(X, Y).")

    assert len(branch.belief_records) == 0
    assert len(branch.rules) == 1
    assert len(branch.constraints) == 0
    assert isinstance(branch.rules[0], Rule)


def test_branch_from_doxa_parses_single_constraint() -> None:
    branch = Branch.from_doxa("!:- ancestor(X, X).")

    assert len(branch.belief_records) == 0
    assert len(branch.rules) == 0
    assert len(branch.constraints) == 1
    assert isinstance(branch.constraints[0], Constraint)


def test_branch_from_doxa_parses_mixed_statements_in_any_order() -> None:
    branch = Branch.from_doxa(
        """
        !:- ancestor(X, X).
        parent(thomas, manuel).
        ancestor(X, Y) :- parent(X, Y).
        """
    )

    assert len(branch.belief_records) == 1
    assert len(branch.rules) == 1
    assert len(branch.constraints) == 1

    assert isinstance(branch.belief_records[0], BeliefRecord)
    assert isinstance(branch.rules[0], Rule)
    assert isinstance(branch.constraints[0], Constraint)


def test_branch_from_doxa_parses_multiple_belief_records_rules_and_constraints() -> (
    None
):
    branch = Branch.from_doxa(
        """
        parent(thomas, manuel).
        parent(manuel, anna).
        ancestor(X, Y) :- parent(X, Y).
        ancestor(X, Y) :- parent(X, Z), ancestor(Z, Y).
        !:- ancestor(X, X).
        !:- parent(X, Y), not person(X).
        """
    )

    assert len(branch.belief_records) == 2
    assert len(branch.rules) == 2
    assert len(branch.constraints) == 2


def test_branch_to_doxa_serializes_all_statements_with_dots() -> None:
    branch = Branch.from_doxa(
        """
        parent(thomas, manuel).
        ancestor(X, Y) :- parent(X, Y).
        !:- ancestor(X, X).
        """
    )

    out = branch.to_doxa()

    assert "parent(thomas, manuel)" in out
    assert "ancestor(X, Y) :- parent(X, Y)" in out
    assert "!:- ancestor(X, X)" in out


# todo: ...
# def test_branch_to_doxa_emits_canonical_grouped_order() -> None:
#     branch = Branch.from_doxa(
#         """
#         !:- ancestor(X, X).
#         parent(thomas, manuel).
#         ancestor(X, Y) :- parent(X, Y).
#         """
#     )
#
#     out = branch.to_doxa().splitlines()
#
#     assert out == [
#         "parent(thomas, manuel).",
#         "ancestor(X, Y) :- parent(X, Y).",
#         "!:- ancestor(X, X).",
#     ]


def test_branch_round_trip_simple_program() -> None:
    original = Branch.from_doxa(
        """
        parent(thomas, manuel).
        ancestor(X, Y) :- parent(X, Y).
        !:- ancestor(X, X).
        """
    )
    reparsed = Branch.from_doxa(original.to_doxa())

    assert reparsed.to_doxa() == original.to_doxa()
    assert len(reparsed.belief_records) == len(original.belief_records)
    assert len(reparsed.rules) == len(original.rules)
    assert len(reparsed.constraints) == len(original.constraints)


def test_branch_round_trip_with_annotations() -> None:
    original = Branch.from_doxa(
        """
        parent(thomas, manuel) @{name:"registry_fact", description:"from registry", b:0.9, d:0.01}.
        ancestor(X, Y) :- parent(X, Y) @{name:"seed_rule", description:"seed"}.
        !:- ancestor(X, X) @{name:"no_self_ancestor", description:"integrity check"}.
        """
    )
    reparsed = Branch.from_doxa(original.to_doxa())

    assert reparsed.to_doxa() == original.to_doxa()
    assert len(reparsed.belief_records) == 1
    assert len(reparsed.rules) == 1
    assert len(reparsed.constraints) == 1


def test_branch_from_doxa_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        Branch.from_doxa(None)  # type: ignore[arg-type]


def test_branch_from_doxa_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Branch.from_doxa("")


def test_branch_from_doxa_rejects_missing_statement_terminator() -> None:
    with pytest.raises(ValueError, match="must terminate each statement with"):
        Branch.from_doxa("parent(thomas, manuel)")


def test_branch_from_doxa_rejects_empty_statement_between_dots() -> None:
    with pytest.raises(ValueError, match="Empty AX statement"):
        Branch.from_doxa("parent(thomas, manuel)..")


def test_branch_from_doxa_rejects_unbalanced_parentheses() -> None:
    with pytest.raises(ValueError, match="Unbalanced parentheses"):
        Branch.from_doxa("parent(thomas, manuel. ")


def test_branch_from_doxa_rejects_unterminated_quoted_string() -> None:
    with pytest.raises(ValueError, match="Unterminated quoted string"):
        Branch.from_doxa('label(thomas, "hello).')


def test_branch_from_doxa_handles_dot_inside_double_quoted_string() -> None:
    branch = Branch.from_doxa('label(thomas, "hello.world").')

    assert len(branch.belief_records) == 1
    assert branch.belief_records[0].to_doxa().startswith('label(thomas, "hello.world")')


def test_branch_from_doxa_handles_multiple_lines_and_whitespace() -> None:
    branch = Branch.from_doxa(
        """

            parent(thomas, manuel).

            ancestor(X, Y) :- parent(X, Y).

            !:- ancestor(X, X).

        """
    )

    assert len(branch.belief_records) == 1
    assert len(branch.rules) == 1
    assert len(branch.constraints) == 1


def test_branch_direct_model_construction() -> None:
    belief = BeliefRecord.from_doxa("parent(thomas, manuel)")
    rule = Rule.from_doxa("ancestor(X, Y) :- parent(X, Y)")
    constraint = Constraint.from_doxa("!:- ancestor(X, X)")

    branch = Branch(
        kind=BaseKind.branch,
        created_at=belief.created_at,
        name="main",
        ephemeral=False,
        belief_records=[belief],
        rules=[rule],
        constraints=[constraint],
    )

    assert branch.name == "main"
    assert branch.ephemeral is False
    assert len(branch.belief_records) == 1
    assert len(branch.rules) == 1
    assert len(branch.constraints) == 1


def test_branch_round_trip_preserves_statement_text() -> None:
    source = """
    parent(thomas, manuel) @{b:1.0, d:0.0, et:"2026-03-20T08:12:58.268915Z"}.
    label(thomas, "hello.world") @{b:1.0, d:0.0, et:"2026-03-20T08:12:58.268915Z"}.
    ancestor(X, Y) :- parent(X, Y)  @{b:1.0, d:0.0, et:"2026-03-20T08:13:21.598665Z"}.
    !:- ancestor(X, X) @{et:"2026-03-20T08:13:35.468002Z"}.
    """
    reparsed = Branch.from_doxa(Branch.from_doxa(source).to_doxa())

    assert reparsed.to_doxa() == Branch.from_doxa(source).to_doxa()
