"""Test that inline ground goal assumptions work correctly and don't persist."""

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.memory import InMemoryQueryEngine


def test_inline_assumptions_work():
    """Test that fully ground query goals work as inline assumptions."""
    # Create a simple knowledge base with rules but no facts about my_company
    kb_text = """
pred has_employee_count/2.
pred has_net_turnover/2.
pred subject_to_due_diligence/3.

subject_to_due_diligence(lksg, C, 2024) :- 
    has_employee_count(C, E), 
    geq(E, 1000).

subject_to_due_diligence(lksg, C, 2027) :- 
    has_employee_count(C, E), 
    geq(E, 500),
    has_net_turnover(C, T),
    geq(T, 150000000).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Query with inline assumptions (fully ground goals)
    query = Query.from_doxa(
        "?- has_employee_count(my_company, 1200), "
        "has_net_turnover(my_company, 500000000), "
        "subject_to_due_diligence(lksg, my_company, Y)"
    )

    results = engine.evaluate(branch, query)

    # Should find results using the inline assumptions
    assert results.success
    assert len(results.bindings) == 2
    years = {binding.values["Y"] for binding in results.bindings}
    assert years == {2024, 2027}


def test_inline_assumptions_not_persisted():
    """Test that inline assumptions are temporary and don't persist to the KB."""
    # Create a simple knowledge base
    kb_text = """
pred has_employee_count/2.
pred has_net_turnover/2.
pred subject_to_due_diligence/3.

subject_to_due_diligence(lksg, C, 2024) :- 
    has_employee_count(C, E), 
    geq(E, 1000).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # First query with inline assumptions
    query1 = Query.from_doxa(
        "?- has_employee_count(my_company, 1200), "
        "has_net_turnover(my_company, 500000000), "
        "subject_to_due_diligence(lksg, my_company, Y)"
    )

    results1 = engine.evaluate(branch, query1)
    assert results1.success
    assert len(results1.bindings) == 1
    assert results1.bindings[0].values["Y"] == 2024

    # Second query trying to look up the inline assumption
    # This should fail because the inline assumption was temporary
    query2 = Query.from_doxa("?- has_employee_count(my_company, X)")
    results2 = engine.evaluate(branch, query2)

    # Should have no results - the inline assumption was not persisted
    assert not results2.success
    assert len(results2.bindings) == 0

    # Verify the branch itself was not modified
    assert len(branch.belief_records) == 0  # No facts were added


def test_inline_assumptions_vs_variables():
    """Test that only fully ground goals are treated as inline assumptions."""
    kb_text = """
pred has_employee_count/2.

has_employee_count(company_a, 1000).
has_employee_count(company_b, 2000).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Query with variables - should do KB lookup
    query = Query.from_doxa("?- has_employee_count(C, E)")
    results = engine.evaluate(branch, query)

    # Should find the two facts in the KB
    assert results.success
    assert len(results.bindings) == 2
    companies = {binding.values["C"] for binding in results.bindings}
    assert companies == {"company_a", "company_b"}


def test_inline_assumptions_with_literals():
    """Test that inline assumptions work with different literal types."""
    kb_text = """
pred has_value/2.
pred check_value/2.

check_value(X, V) :- has_value(X, V), geq(V, 100).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Test with integer literal
    query = Query.from_doxa("?- has_value(item1, 150), check_value(item1, V)")
    results = engine.evaluate(branch, query)

    assert results.success
    assert len(results.bindings) == 1
    assert results.bindings[0].values["V"] == 150


def test_backward_compatibility():
    """Test that existing queries without inline assumptions still work."""
    kb_text = """
pred subject_to_due_diligence/3.

subject_to_due_diligence(lksg, company_over_3000_employees, 2023).
subject_to_due_diligence(lksg, company_over_1000_employees, 2024).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Traditional query with variables
    query = Query.from_doxa("?- subject_to_due_diligence(lksg, C, Year)")
    results = engine.evaluate(branch, query)

    assert results.success
    assert len(results.bindings) == 2
    companies = {binding.values["C"] for binding in results.bindings}
    assert companies == {"company_over_3000_employees", "company_over_1000_employees"}


def test_anonymous_variables_are_distinct():
    """Test that each occurrence of _ is treated as a distinct anonymous variable."""
    kb_text = """
pred p/2.
pred q/2.

p(a, 1).
p(b, 2).
q(x, 10).
q(y, 20).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Query with multiple _ - each should be independent
    query = Query.from_doxa("?- p(_, X), q(_, Y)")
    results = engine.evaluate(branch, query)

    # Should get all combinations: 2 p facts × 2 q facts = 4 results
    assert results.success
    assert len(results.bindings) == 4

    # Verify we get all combinations of X and Y
    xy_pairs = {(b.values["X"], b.values["Y"]) for b in results.bindings}
    assert xy_pairs == {(1, 10), (1, 20), (2, 10), (2, 20)}

    # Verify that the anonymous variables are NOT projected into output
    # (bare _ is anonymous and should be hidden from user-facing results)
    for binding in results.bindings:
        assert "_0" not in binding.values
        assert "_1" not in binding.values


def test_variable_in_inline_assumptions_skolemized():
    """Test that a variable shared across EDB assumption goals and an IDB
    derivation goal is automatically skolemized so the query works the same
    as when a concrete entity name is used.

    Regression test for the bug where:
      ?- has_employee_count(C, 1200), is_derived(C).   → No results
      ?- has_employee_count(comp, 1200), is_derived(comp). → results
    """
    kb_text = """
pred has_employee_count/2.
pred has_net_turnover/2.
pred is_large_company/1.

is_large_company(C) :-
    has_employee_count(C, E),
    geq(E, 1000),
    has_net_turnover(C, T),
    geq(T, 50000000).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Query with a variable C (was broken before skolemization fix)
    query_var = Query.from_doxa(
        "?- has_employee_count(C, 1200), "
        "has_net_turnover(C, 60000000), "
        "is_large_company(C)"
    )
    results_var = engine.evaluate(branch, query_var)

    # Query with a concrete entity name (always worked)
    query_ent = Query.from_doxa(
        "?- has_employee_count(acme, 1200), "
        "has_net_turnover(acme, 60000000), "
        "is_large_company(acme)"
    )
    results_ent = engine.evaluate(branch, query_ent)

    # Both must succeed with the same number of results
    assert results_ent.success
    assert results_var.success
    assert len(results_var.bindings) == len(results_ent.bindings)

    # The variable query should bind C to the Skolem entity name
    assert all("C" in b.values for b in results_var.bindings)


def test_skolemization_does_not_affect_pure_queries():
    """Variables that only appear in EDB goals (no IDB goal) must NOT be
    skolemized — they should still do normal KB lookups."""
    kb_text = """
pred has_employee_count/2.

has_employee_count(company_a, 500).
has_employee_count(company_b, 3000).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Pure lookup query — C and E are variables, no IDB goals
    query = Query.from_doxa("?- has_employee_count(C, E)")
    results = engine.evaluate(branch, query)

    assert results.success
    assert len(results.bindings) == 2
    companies = {b.values["C"] for b in results.bindings}
    assert companies == {"company_a", "company_b"}

    # Single-variable lookup with one ground arg — still a query, not an assumption
    query2 = Query.from_doxa("?- has_employee_count(company_a, X)")
    results2 = engine.evaluate(branch, query2)

    assert results2.success
    assert len(results2.bindings) == 1
    assert results2.bindings[0].values["X"] == 500
