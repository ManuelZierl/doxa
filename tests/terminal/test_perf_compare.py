"""
Temporary performance comparison: memory engine vs native engine.

Benchmarks large KBs using engine APIs directly (no CLI overhead).
The in-memory engine uses top-down (depth-limited) evaluation; the native
engine uses bottom-up fixpoint.  We set max_depth high enough for the
workloads so both produce the same answers.

Run with:
    python -m pytest tests/terminal/test_perf_compare.py -v -s

Remove this file once the benchmark is done.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from doxa.core.branch import Branch  # noqa: E402
from doxa.core.query import Query  # noqa: E402
from doxa.query.evaluator import InMemoryQueryEngine  # noqa: E402


def _has_native_engine() -> bool:
    try:
        from doxa import _native  # noqa: F401

        return True
    except ImportError:
        return False


def _get_engines():
    from doxa.query.native import NativeQueryEngine

    return InMemoryQueryEngine(), NativeQueryEngine()


def _bench(engine, branch, query, rounds=3):
    """Return (avg_seconds, result) over `rounds` runs."""
    times = []
    result = None
    for _ in range(rounds):
        t0 = time.perf_counter()
        result = engine.evaluate(branch, query)
        times.append(time.perf_counter() - t0)
    return sum(times) / len(times), result


def _report(label, mem_time, nat_time, mem_n, nat_n):
    speedup = mem_time / nat_time if nat_time > 0 else float("inf")
    marker = "[+]" if nat_time <= mem_time else "[-]"
    print(
        f"\n  {marker} {label}\n"
        f"      memory: {mem_time * 1000:10.2f} ms  ({mem_n} answers)\n"
        f"      native: {nat_time * 1000:10.2f} ms  ({nat_n} answers)\n"
        f"      speedup: {speedup:.2f}x"
    )


# ---------------------------------------------------------------------------
# 1. Wide fan-out -- star graph  (1 hub, N leaves, rule derives NxN pairs)
#    Non-recursive: single rule firing, no depth issues.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [50, 100, 200, 500])
def test_wide_fanout(n):
    if not _has_native_engine():
        pytest.skip("doxa_native not installed")
    mem_eng, nat_eng = _get_engines()

    facts = "\n".join(f"link(hub, leaf{i})." for i in range(n))
    doxa = facts + "\npair(A, B) :- link(hub, A), link(hub, B)."
    branch = Branch.from_doxa(doxa)
    query = Query.from_doxa("?- pair(A, B)")

    mt, mr = _bench(mem_eng, branch, query)
    nt, nr = _bench(nat_eng, branch, query)
    _report(f"wide_fanout  N={n}", mt, nt, len(mr.answers), len(nr.answers))
    assert len(mr.answers) == len(nr.answers)


# ---------------------------------------------------------------------------
# 2. Arithmetic derivation -- N facts, rule adds computed column
#    Non-recursive: single rule firing with builtin.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [100, 500, 1000, 2000])
def test_arithmetic_derivation(n):
    if not _has_native_engine():
        pytest.skip("doxa_native not installed")
    mem_eng, nat_eng = _get_engines()

    facts = "\n".join(f"val(item{i}, {i})." for i in range(n))
    doxa = facts + "\ndoubled(X, D) :- val(X, V), add(V, V, D)."
    branch = Branch.from_doxa(doxa)
    query = Query.from_doxa("?- doubled(X, D)")

    mt, mr = _bench(mem_eng, branch, query)
    nt, nr = _bench(nat_eng, branch, query)
    _report(f"arithmetic_derivation  N={n}", mt, nt, len(mr.answers), len(nr.answers))
    assert len(mr.answers) == len(nr.answers)


# ---------------------------------------------------------------------------
# 3. Multi-rule chain -- N facts, 3 layers of non-recursive rules
#    Each layer joins/filters, stressing the join engine.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [100, 500, 1000, 2000])
def test_multi_rule_chain(n):
    if not _has_native_engine():
        pytest.skip("doxa_native not installed")
    mem_eng, nat_eng = _get_engines()

    facts = "\n".join(f"data(e{i}, {i})." for i in range(n))
    doxa = (
        facts
        + "\nstep1(X, V) :- data(X, V)."
        + "\nstep2(X, V) :- step1(X, V)."
        + "\nstep3(X, V) :- step2(X, V)."
    )
    branch = Branch.from_doxa(doxa)
    query = Query.from_doxa("?- step3(X, V)")

    mt, mr = _bench(mem_eng, branch, query)
    nt, nr = _bench(nat_eng, branch, query)
    _report(f"multi_rule_chain  N={n}", mt, nt, len(mr.answers), len(nr.answers))
    assert len(mr.answers) == len(nr.answers)


# ---------------------------------------------------------------------------
# 4. Many facts, simple scan -- no rules, just large predicate scan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [500, 1000, 5000, 10000])
def test_large_scan(n):
    if not _has_native_engine():
        pytest.skip("doxa_native not installed")
    mem_eng, nat_eng = _get_engines()

    facts = "\n".join(f"record(id{i}, val{i})." for i in range(n))
    branch = Branch.from_doxa(facts)
    query = Query.from_doxa("?- record(X, Y)")

    mt, mr = _bench(mem_eng, branch, query)
    nt, nr = _bench(nat_eng, branch, query)
    _report(f"large_scan  N={n}", mt, nt, len(mr.answers), len(nr.answers))
    assert len(mr.answers) == len(nr.answers)


# ---------------------------------------------------------------------------
# 5. Transitive closure -- short chain, high max_depth so both agree
#    N kept small (<=20) so in-memory depth limit (set to N+5) is enough.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [10, 15, 20])
def test_transitive_closure(n):
    if not _has_native_engine():
        pytest.skip("doxa_native not installed")
    mem_eng, nat_eng = _get_engines()

    facts = "\n".join(f"edge(n{i}, n{i + 1})." for i in range(n))
    doxa = facts + "\npath(X, Y) :- edge(X, Y).\npath(X, Z) :- edge(X, Y), path(Y, Z)."
    branch = Branch.from_doxa(doxa)
    # Set max_depth high enough for the in-memory engine to find all paths
    query = Query.from_doxa(f"?- path(X, Y) @{{max_depth:{n + 5}}}")

    mt, mr = _bench(mem_eng, branch, query)
    nt, nr = _bench(nat_eng, branch, query)
    _report(f"transitive_closure  N={n}", mt, nt, len(mr.answers), len(nr.answers))
    assert len(mr.answers) == len(nr.answers)


# ---------------------------------------------------------------------------
# 6. Join-heavy -- two large predicates, rule joins them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [100, 500, 1000])
def test_binary_join(n):
    if not _has_native_engine():
        pytest.skip("doxa_native not installed")
    mem_eng, nat_eng = _get_engines()

    left = "\n".join(f"left(k{i}, lv{i})." for i in range(n))
    right = "\n".join(f"right(k{i}, rv{i})." for i in range(n))
    doxa = left + "\n" + right + "\njoined(K, L, R) :- left(K, L), right(K, R)."
    branch = Branch.from_doxa(doxa)
    query = Query.from_doxa("?- joined(K, L, R)")

    mt, mr = _bench(mem_eng, branch, query)
    nt, nr = _bench(nat_eng, branch, query)
    _report(f"binary_join  N={n}", mt, nt, len(mr.answers), len(nr.answers))
    assert len(mr.answers) == len(nr.answers)
