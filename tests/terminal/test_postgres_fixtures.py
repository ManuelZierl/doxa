"""
Fixture-based comparison test: InMemoryQueryEngine vs PostgresQueryEngine.

For every terminal fixture that contains queries (?- ...),  this test:
  1. Builds the branch by merging all non-query statements.
  2. Runs each query through both engines.
  3. Asserts the results are identical (same answers, same b/d/status).

Requires a running PostgreSQL instance.  Set DOXA_POSTGRES_TEST_URL or
the test is automatically skipped.

    DOXA_POSTGRES_TEST_URL="postgresql://user:pass@localhost/doxa_test" pytest tests/query/test_postgres_fixtures.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

import pytest

from doxa.core.branch import Branch
from doxa.core.query import Query
from doxa.query.engine import QueryAnswer, QueryResult

FIXTURES_DIR = Path(__file__).parent.parent / "terminal" / "fixtures"
COMPARISON_CATEGORIES = {
    "basics",
    "builtins",
    "constraints",
    "hypotheticals",
    "postprocessing",
    "regressions",
    "rules",
}

# ---------------------------------------------------------------------------
# Skip if no postgres
# ---------------------------------------------------------------------------

_PG_URL = os.environ.get("DOXA_POSTGRES_TEST_URL", "")

try:
    import psycopg as _psycopg

    _HAS_PSYCOPG = True
except ImportError:
    _psycopg = None
    _HAS_PSYCOPG = False


def _can_connect() -> bool:
    """Try to actually connect to the database."""
    if not _PG_URL or not _HAS_PSYCOPG or _psycopg is None:
        return False
    try:
        assert _psycopg is not None
        conn = _psycopg.connect(_PG_URL, autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


_PG_AVAILABLE = _can_connect()

pytestmark = pytest.mark.skipif(
    not _PG_AVAILABLE,
    reason="PostgreSQL not available (set DOXA_POSTGRES_TEST_URL)",
)


# ---------------------------------------------------------------------------
# Fixture collection
# ---------------------------------------------------------------------------


def _split_input(input_text: str) -> Tuple[List[str], List[str]]:
    """Split fixture input into (statement_texts, query_texts)."""
    statements: List[str] = []
    queries: List[str] = []

    for line in input_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("%") or line.startswith("/-"):
            continue
        if line.startswith("?-"):
            queries.append(line)
        else:
            statements.append(line)

    return statements, queries


def _build_branch(statements: List[str]) -> Branch:
    """Build a Branch by parsing and merging all statements."""
    from datetime import datetime, timezone

    from doxa.core.base_kinds import BaseKind

    branch = Branch(
        kind=BaseKind.branch,
        created_at=datetime.now(timezone.utc),
        updated_at=None,
        name="fixture_test",
        ephemeral=False,
        belief_records=[],
        rules=[],
        constraints=[],
        predicates=[],
        entities=[],
    )

    for stmt in statements:
        clean = stmt.strip()
        if not clean.endswith("."):
            clean += "."
        try:
            new_branch = Branch.from_doxa(clean)
            branch = branch.merge(new_branch)
        except Exception as exc:
            raise ValueError(f"Could not parse fixture statement: {stmt!r}") from exc

    return branch


def _parse_queries(query_texts: List[str]) -> List[Query]:
    """Parse query strings into Query objects."""
    out = []
    for text in query_texts:
        q_text = text.rstrip(".").strip()
        try:
            out.append(Query.from_doxa(q_text))
        except Exception as exc:
            raise ValueError(f"Could not parse fixture query: {text!r}") from exc
    return out


def _answers_equal(a: Tuple[QueryAnswer, ...], b: Tuple[QueryAnswer, ...]) -> bool:
    """Compare two answer tuples for semantic equality."""
    if len(a) != len(b):
        return False
    for aa, bb in zip(a, b):
        if dict(aa.bindings) != dict(bb.bindings):
            return False
        if abs(aa.b - bb.b) > 1e-9:
            return False
        if abs(aa.d - bb.d) > 1e-9:
            return False
        if aa.belnap_status != bb.belnap_status:
            return False
    return True


def _collect_fixtures() -> List[Tuple[str, Path]]:
    if not FIXTURES_DIR.exists():
        return []
    results = []
    for category in sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir()):
        if category.name not in COMPARISON_CATEGORIES:
            continue
        for fixture in sorted(p for p in category.iterdir() if p.is_dir()):
            input_file = fixture / "input.doxa"
            if input_file.exists():
                # Only include fixtures that actually have queries
                text = input_file.read_text(encoding="utf-8-sig")
                if "?-" in text:
                    label = f"{category.name}/{fixture.name}"
                    results.append((label, fixture))
    return results


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
    """Create a PostgresQueryEngine for the test module."""
    from doxa.persistence.postgres import PostgresBranchRepository
    from doxa.query.postgres import PostgresQueryEngine

    repo = PostgresBranchRepository(_PG_URL)
    engine = PostgresQueryEngine(repo)
    yield engine, repo
    repo.close()


@pytest.mark.parametrize(
    "name,fixture_dir",
    _collect_fixtures(),
    ids=[n for n, _ in _collect_fixtures()],
)
def test_fixture_postgres_matches_memory(
    name: str,
    fixture_dir: Path,
    pg_engine,
) -> None:
    from doxa.query.evaluator import InMemoryQueryEngine

    engine_pg, _repo_pg = pg_engine
    engine_mem = InMemoryQueryEngine()

    input_text = (fixture_dir / "input.doxa").read_text(encoding="utf-8-sig")
    statements, query_texts = _split_input(input_text)

    branch = _build_branch(statements)
    queries = _parse_queries(query_texts)

    if not queries:
        pytest.skip("No parseable queries in fixture")

    for i, query in enumerate(queries):
        result_mem: QueryResult = engine_mem.evaluate(branch, query)
        result_pg: QueryResult = engine_pg.evaluate(branch, query)

        assert _answers_equal(result_mem.answers, result_pg.answers), (
            f"Fixture {name}, query #{i + 1}: answers differ.\n"
            f"  Memory:   {result_mem.answers}\n"
            f"  Postgres: {result_pg.answers}"
        )
