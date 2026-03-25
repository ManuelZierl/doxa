"""Test that explicit assume(...) hypothetical assumptions work correctly."""

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.memory import InMemoryQueryEngine


def test_assume_basic():
    """Test that assume(...) injects temporary facts for rule derivation."""
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

    query = Query.from_doxa(
        "?- assume("
        "has_employee_count(my_company, 1200), "
        "has_net_turnover(my_company, 500000000)"
        "), "
        "subject_to_due_diligence(lksg, my_company, Y)"
    )

    results = engine.evaluate(branch, query)

    assert len(results.answers) == 2
    years = {binding.bindings["Y"] for binding in results.answers}
    assert years == {2024, 2027}


def test_assume_not_persisted():
    """Test that assumed facts are temporary and don't persist to the KB."""
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

    query1 = Query.from_doxa(
        "?- assume("
        "has_employee_count(my_company, 1200), "
        "has_net_turnover(my_company, 500000000)"
        "), "
        "subject_to_due_diligence(lksg, my_company, Y)"
    )

    results1 = engine.evaluate(branch, query1)
    assert len(results1.answers) == 1
    assert results1.answers[0].bindings["Y"] == 2024

    # Second query trying to look up the assumed fact
    query2 = Query.from_doxa("?- has_employee_count(my_company, X)")
    results2 = engine.evaluate(branch, query2)

    # Should have no results - the assumption was not persisted
    assert len(results2.answers) == 0

    # Verify the branch itself was not modified
    assert len(branch.belief_records) == 0


def test_assume_with_literals():
    """Test that assume(...) works with different literal types."""
    kb_text = """
pred has_value/2.
pred check_value/2.

check_value(X, V) :- has_value(X, V), geq(V, 100).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    query = Query.from_doxa(
        "?- assume(has_value(item1, 150)), check_value(item1, V)"
    )
    results = engine.evaluate(branch, query)

    assert len(results.answers) == 1
    assert results.answers[0].bindings["V"] == 150


def test_assume_ground_query_consistency():
    """Test the original bug: assume must work identically for ground
    and variable queries.

    Previously ground queries returned 'neither' while variable queries
    returned 'true'.  With explicit assume(...) this inconsistency is gone.
    """
    kb_text = """
pred employees/2.
pred company/1.
pred turnover_mio/2.
pred current_csrd_scope/1.
pred out_of_scope_under_current_csrd/1.

current_csrd_scope(X) :- 
    employees(X, E), 
    gt(E, 1000), 
    turnover_mio(X, R), 
    gt(R, 450).

out_of_scope_under_current_csrd(X) :-
    company(X),
    not current_csrd_scope(X).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Ground query (previously broken)
    query_ground = Query.from_doxa(
        "?- assume("
        "employees(nordwind, 450), "
        "company(nordwind), "
        "turnover_mio(nordwind, 55)"
        "), out_of_scope_under_current_csrd(nordwind)"
    )
    result_ground = engine.evaluate(branch, query_ground)

    # Variable query
    query_var = Query.from_doxa(
        "?- assume("
        "employees(nordwind, 450), "
        "company(nordwind), "
        "turnover_mio(nordwind, 55)"
        "), out_of_scope_under_current_csrd(X)"
    )
    result_var = engine.evaluate(branch, query_var)

    # Both must produce a true answer
    assert len(result_ground.answers) == 1
    assert result_ground.answers[0].b > 0
    assert result_ground.answers[0].belnap_status.value == "true"

    assert len(result_var.answers) == 1
    assert result_var.answers[0].bindings["X"] == "nordwind"
    assert result_var.answers[0].b > 0
    assert result_var.answers[0].belnap_status.value == "true"


def test_backward_compatibility():
    """Test that existing queries without assume(...) still work."""
    kb_text = """
pred subject_to_due_diligence/3.

subject_to_due_diligence(lksg, company_over_3000_employees, 2023).
subject_to_due_diligence(lksg, company_over_1000_employees, 2024).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    query = Query.from_doxa("?- subject_to_due_diligence(lksg, C, Year)")
    results = engine.evaluate(branch, query)

    assert len(results.answers) == 2
    companies = {binding.bindings["C"] for binding in results.answers}
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

    query = Query.from_doxa("?- p(_, X), q(_, Y)")
    results = engine.evaluate(branch, query)

    assert len(results.answers) == 4

    xy_pairs = {(b.bindings["X"], b.bindings["Y"]) for b in results.answers}
    assert xy_pairs == {(1, 10), (1, 20), (2, 10), (2, 20)}

    for answer in results.answers:
        assert "_0" not in answer.bindings
        assert "_1" not in answer.bindings


def test_assume_with_variable_in_derivation():
    """Test that assume(...) with a concrete entity works through rule derivation,
    and that variable queries also bind properly."""
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

    # Concrete entity in assume
    query_ent = Query.from_doxa(
        "?- assume("
        "has_employee_count(acme, 1200), "
        "has_net_turnover(acme, 60000000)"
        "), is_large_company(acme)"
    )
    results_ent = engine.evaluate(branch, query_ent)

    assert len(results_ent.answers) == 1
    assert results_ent.answers[0].b > 0

    # Variable derivation goal should also work
    query_var = Query.from_doxa(
        "?- assume("
        "has_employee_count(acme, 1200), "
        "has_net_turnover(acme, 60000000)"
        "), is_large_company(X)"
    )
    results_var = engine.evaluate(branch, query_var)

    assert len(results_var.answers) == 1
    assert results_var.answers[0].bindings["X"] == "acme"


def test_pure_lookup_queries_still_work():
    """Variables in non-assume atom goals should still do normal KB lookups."""
    kb_text = """
pred has_employee_count/2.

has_employee_count(company_a, 500).
has_employee_count(company_b, 3000).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    query = Query.from_doxa("?- has_employee_count(C, E)")
    results = engine.evaluate(branch, query)

    assert len(results.answers) == 2
    companies = {b.bindings["C"] for b in results.answers}
    assert companies == {"company_a", "company_b"}

    query2 = Query.from_doxa("?- has_employee_count(company_a, X)")
    results2 = engine.evaluate(branch, query2)

    assert len(results2.answers) == 1
    assert results2.answers[0].bindings["X"] == 500


def test_assume_parsing_roundtrip():
    """Test that assume(...) can be parsed and serialized back to doxa."""
    query = Query.from_doxa(
        "?- assume(p(a, 1), q(b)), r(X)"
    )

    assert len(query.goals) == 2  # assume goal + r(X)

    doxa = query.to_doxa()
    assert "assume(" in doxa
    assert "r(X)" in doxa

    # Re-parse the serialized form
    reparsed = Query.from_doxa(doxa)
    assert len(reparsed.goals) == 2


def test_assume_with_negation_in_rules():
    """Test that assume works with rules containing negation (not)."""
    kb_text = """
pred registered/1.
pred approved/1.
pred pending_approval/1.

pending_approval(X) :- registered(X), not approved(X).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Assume company is registered but NOT approved
    query = Query.from_doxa(
        "?- assume(registered(acme)), pending_approval(X)"
    )
    results = engine.evaluate(branch, query)

    assert len(results.answers) == 1
    assert results.answers[0].bindings["X"] == "acme"

    # Now assume both registered and approved — should NOT be pending
    query2 = Query.from_doxa(
        "?- assume(registered(acme), approved(acme)), pending_approval(X)"
    )
    results2 = engine.evaluate(branch, query2)

    assert len(results2.answers) == 0


def test_assume_does_not_shadow_existing_facts():
    """Assume adds to (not replaces) existing facts."""
    kb_text = """
pred score/2.

score(alice, 80).
"""

    branch = Branch.from_doxa(kb_text)
    engine = InMemoryQueryEngine()

    # Assume an additional fact
    query = Query.from_doxa(
        "?- assume(score(bob, 90)), score(X, Y)"
    )
    results = engine.evaluate(branch, query)

    names = {b.bindings["X"] for b in results.answers}
    assert names == {"alice", "bob"}
