"""PostgreSQL persistence backend using psycopg (v3).

Schema
------
Two tables are created automatically on first use:

``doxa_branches``
    Stores the full branch JSON (rules, constraints, predicates, entities)
    with ``name TEXT PRIMARY KEY`` and ``data JSONB``.

``doxa_belief_records``
    Stores each belief record individually for fast indexed lookups.
    Columns: branch_name, pred_name, pred_arity, et, vf, vt, data (JSONB).
    Indexed on (branch_name, pred_name, pred_arity) and temporal columns.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from doxa.core.belief_record import BeliefRecord
from doxa.core.branch import Branch
from doxa.core._parsing.parsing_utils import parse_iso_duration
from doxa.persistence.repository import BranchRepository

if TYPE_CHECKING:
    import psycopg


# ---------------------------------------------------------------------------
# SQL DDL
# ---------------------------------------------------------------------------

_DDL = """\
CREATE TABLE IF NOT EXISTS doxa_branches (
    name  TEXT PRIMARY KEY,
    data  JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS doxa_belief_records (
    id           BIGSERIAL PRIMARY KEY,
    branch_name  TEXT    NOT NULL REFERENCES doxa_branches(name) ON DELETE CASCADE,
    pred_name    TEXT    NOT NULL,
    pred_arity   INTEGER NOT NULL,
    et           TIMESTAMPTZ NOT NULL,
    vf           TIMESTAMPTZ,
    vt           TIMESTAMPTZ,
    b            DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    d            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    data         JSONB   NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_belief_branch_pred
    ON doxa_belief_records (branch_name, pred_name, pred_arity);

CREATE INDEX IF NOT EXISTS idx_belief_et
    ON doxa_belief_records (branch_name, et);

CREATE INDEX IF NOT EXISTS idx_belief_vf
    ON doxa_belief_records (branch_name, vf);

CREATE INDEX IF NOT EXISTS idx_belief_vt
    ON doxa_belief_records (branch_name, vt);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _branch_without_beliefs(branch: Branch) -> dict:
    """Serialize the branch but strip belief_records (stored separately)."""
    data = branch.model_dump(mode="json")
    data["belief_records"] = []
    return data


def _restore_temporal_belief_arg(arg_data: dict) -> dict:
    if arg_data.get("term_kind") != "lit":
        return arg_data

    lit_type = arg_data.get("lit_type")
    value = arg_data.get("value")
    if not isinstance(value, str):
        return arg_data

    restored = dict(arg_data)
    if lit_type == "date":
        restored["value"] = date.fromisoformat(value)
    elif lit_type == "datetime":
        restored["value"] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif lit_type == "duration":
        restored["value"] = parse_iso_duration(value)
    return restored


def _restore_belief_record_data(record_data: dict) -> dict:
    restored = dict(record_data)
    restored["args"] = [
        _restore_temporal_belief_arg(arg) for arg in record_data.get("args", [])
    ]
    return restored


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class PostgresBranchRepository(BranchRepository):
    """PostgreSQL-backed branch storage using *psycopg* (v3).

    Usage::

        from doxa.persistence.postgres import PostgresBranchRepository

        repo = PostgresBranchRepository("postgresql://user:pass@localhost/doxa")
        repo.save(branch)
        branch = repo.get("main")

    The constructor accepts anything that ``psycopg.connect()`` understands:
    a DSN string, a ``connection_factory`` keyword, or individual keywords
    (``host``, ``port``, ``dbname``, ``user``, ``password``).

    Pass an already-open ``psycopg.Connection`` via *connection* to reuse an
    existing connection instead of creating a new one.
    """

    def __init__(
        self,
        conninfo: str = "",
        *,
        connection: Optional["psycopg.Connection"] = None,
        autocommit: bool = True,
        **connect_kwargs,
    ) -> None:
        import psycopg  # noqa: F811 – deferred import

        if connection is not None:
            self._conn: psycopg.Connection = connection
            self._owns_conn = False
        else:
            self._conn = psycopg.connect(
                conninfo, autocommit=autocommit, **connect_kwargs
            )
            self._owns_conn = True

        self._ensure_schema()

    # -- schema bootstrap ---------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_DDL)
        if not self._conn.autocommit:
            self._conn.commit()

    # -- core CRUD ----------------------------------------------------------

    def get(self, name: str) -> Optional[Branch]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT data FROM doxa_branches WHERE name = %s", (name,))
            row = cur.fetchone()
            if row is None:
                return None
            branch_data = row[0]

            # Attach belief records
            cur.execute(
                "SELECT data FROM doxa_belief_records WHERE branch_name = %s ORDER BY id",
                (name,),
            )
            belief_rows = cur.fetchall()
            branch_data["belief_records"] = [
                _restore_belief_record_data(r[0]) for r in belief_rows
            ]

        return Branch.model_validate(branch_data)

    def save(self, branch: Branch) -> None:
        data = _branch_without_beliefs(branch)

        with self._conn.cursor() as cur:
            # Upsert branch metadata
            cur.execute(
                """
                INSERT INTO doxa_branches (name, data)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (name) DO UPDATE SET data = EXCLUDED.data
                """,
                (branch.name, Branch.model_validate(data).model_dump_json()),
            )

            # Replace all belief records for this branch
            cur.execute(
                "DELETE FROM doxa_belief_records WHERE branch_name = %s",
                (branch.name,),
            )

            if branch.belief_records:
                from psycopg.types.json import Jsonb

                args = []
                for rec in branch.belief_records:
                    rec_data = rec.model_dump(mode="json")
                    args.append(
                        (
                            branch.name,
                            rec.pred_name,
                            rec.pred_arity,
                            _utc(rec.et),
                            _utc(rec.vf) if rec.vf is not None else None,
                            _utc(rec.vt) if rec.vt is not None else None,
                            rec.b,
                            rec.d,
                            Jsonb(rec_data),
                        )
                    )

                cur.executemany(
                    """
                    INSERT INTO doxa_belief_records
                        (branch_name, pred_name, pred_arity, et, vf, vt, b, d, data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    args,
                )

        if not self._conn.autocommit:
            self._conn.commit()

    def delete(self, name: str) -> None:
        with self._conn.cursor() as cur:
            # Belief records cascade-deleted via FK
            cur.execute("DELETE FROM doxa_branches WHERE name = %s", (name,))
        if not self._conn.autocommit:
            self._conn.commit()

    def list_names(self) -> List[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT name FROM doxa_branches ORDER BY name")
            return [row[0] for row in cur.fetchall()]

    # -- fine-grained accessors (fast SQL overrides) ------------------------

    def get_belief_records(
        self,
        branch_name: str,
        *,
        pred_name: Optional[str] = None,
    ) -> List[BeliefRecord]:
        clauses = ["branch_name = %s"]
        params: list = [branch_name]

        if pred_name is not None:
            clauses.append("pred_name = %s")
            params.append(pred_name)

        sql = (
            "SELECT data FROM doxa_belief_records WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                BeliefRecord.model_validate(_restore_belief_record_data(row[0]))
                for row in cur.fetchall()
            ]

    def get_visible_belief_records(
        self,
        branch_name: str,
        *,
        valid_at: datetime,
        known_at: datetime,
        pred_name: Optional[str] = None,
        pred_arity: Optional[int] = None,
    ) -> List[BeliefRecord]:
        """Return only time-visible belief records using SQL filtering.

        This is the fast path used by ``PostgresQueryEngine`` to push temporal
        filtering down to the database instead of loading all records.
        """
        clauses = [
            "branch_name = %s",
            "et <= %s",  # knowledge-time cutoff
            "(vf IS NULL OR vf <= %s)",  # validity-from check
            "(vt IS NULL OR vt >= %s)",  # validity-to check
        ]
        params: list = [branch_name, known_at, valid_at, valid_at]

        if pred_name is not None:
            clauses.append("pred_name = %s")
            params.append(pred_name)

        if pred_arity is not None:
            clauses.append("pred_arity = %s")
            params.append(pred_arity)

        sql = (
            "SELECT data FROM doxa_belief_records WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                BeliefRecord.model_validate(_restore_belief_record_data(row[0]))
                for row in cur.fetchall()
            ]

    def add_belief_record(self, branch_name: str, record: BeliefRecord) -> None:
        from psycopg.types.json import Jsonb

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO doxa_belief_records
                    (branch_name, pred_name, pred_arity, et, vf, vt, b, d, data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    branch_name,
                    record.pred_name,
                    record.pred_arity,
                    _utc(record.et),
                    _utc(record.vf) if record.vf is not None else None,
                    _utc(record.vt) if record.vt is not None else None,
                    record.b,
                    record.d,
                    Jsonb(record.model_dump(mode="json")),
                ),
            )
        if not self._conn.autocommit:
            self._conn.commit()

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying connection if we own it."""
        if self._owns_conn:
            self._conn.close()

    def __enter__(self) -> "PostgresBranchRepository":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def connect_postgres(
    conninfo: str = "",
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    dbname: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    **kwargs,
) -> PostgresBranchRepository:
    """Create a :class:`PostgresBranchRepository` with a simple API.

    Examples::

        # DSN string
        repo = connect_postgres("postgresql://user:pass@localhost:5432/doxa")

        # Keyword arguments
        repo = connect_postgres(host="localhost", dbname="doxa", user="me")

    All tables and indexes are created automatically on first connection.
    """
    connect_kwargs = {
        k: v
        for k, v in dict(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
        ).items()
        if v is not None
    }
    connect_kwargs.update(kwargs)
    return PostgresBranchRepository(conninfo, **connect_kwargs)
