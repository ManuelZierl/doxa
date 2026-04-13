"""SQL-native evaluator for a positive recursive Postgres fragment.

This evaluator is intentionally narrower than the shared Python evaluator.
It targets a production-oriented baseline for PostgreSQL:

- relevant predicates are evaluated SCC-by-SCC
- cyclic SCCs use semi-naive delta iteration
- atom state is kept separate from derivation witness state
- visibility filtering is materialized once before recursion starts
- recursive witnesses are acyclic: revisiting the same grounded SCC atom does
  not count as fresh evidence

The current native fragment supports:

- positive atom queries
- positive atom rule bodies
- no constraints
- no explain output

For recursive SCCs, only ``rule_applicability="body_truth_only"`` is currently
accepted. That keeps witness contributions monotone so the SCC fixpoint can be
computed with monotone witness/atom updates.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from psycopg.types.json import Jsonb

from doxa.core._parsing.parsing_utils import render_duration_literal
from doxa.core.branch import Branch
from doxa.core.epistemic_semantics import (
    BodyFalsitySemantics,
    BodyTruthSemantics,
    RuleApplicabilitySemantics,
    SupportAggregationSemantics,
)
from doxa.core.goal import AtomGoal, Goal
from doxa.core.query import Query
from doxa.core.rule import Rule, RuleAtomGoal
from doxa.query.engine import QueryAnswer, QueryResult
from doxa.query.evaluator import (
    _apply_focus,
    _derive_belnap_status,
    _query_var_names,
    _resolve_effective_times,
    _sort_answers,
)


Signature = Tuple[str, int]


@dataclass(frozen=True)
class _SqlTerm:
    kind: str
    value: Any


@dataclass(frozen=True)
class _SqlAtom:
    pred_name: str
    pred_arity: int
    args: Tuple[_SqlTerm, ...]


@dataclass(frozen=True)
class _SqlRule:
    rule_idx: int
    head_pred_name: str
    head_pred_arity: int
    head_args: Tuple[_SqlTerm, ...]
    body: Tuple[_SqlAtom, ...]
    b: float
    d: float


@dataclass(frozen=True)
class _SqlScc:
    scc_id: int
    signatures: Tuple[Signature, ...]
    recursive: bool


def try_evaluate_native(conn, branch: Branch, query: Query) -> Optional[QueryResult]:
    native = _NativeSqlEvaluator(branch, query)
    if not native.supported:
        return None
    return native.evaluate(conn)


class _NativeSqlEvaluator:
    def __init__(self, branch: Branch, query: Query) -> None:
        self.branch = branch
        self.query = query
        self.query_atoms: List[_SqlAtom] = []
        self.relevant_rules: List[_SqlRule] = []
        self.reachable_signatures: Set[Signature] = set()
        self.max_arity = 0
        self.query_vars: Set[str] = set()
        self.sccs: List[_SqlScc] = []
        self.signature_to_scc: Dict[Signature, int] = {}
        self.supported = self._prepare()

    def _prepare(self) -> bool:
        if self.branch.constraints:
            return False
        if self.query.options.explain != "false":
            return False

        query_atoms: List[_SqlAtom] = []
        for goal in self.query.goals:
            atom = self._goal_to_atom(goal)
            if atom is None:
                return False
            query_atoms.append(atom)

        self.query_atoms = query_atoms
        self.query_vars = _query_var_names(self.query)

        rules_by_head: dict[Signature, List[Tuple[int, Rule]]] = defaultdict(list)
        for rule_idx, rule in enumerate(self.branch.rules):
            key = (rule.head_pred_name, rule.head_pred_arity)
            rules_by_head[key].append((rule_idx, rule))

        queue = deque({(atom.pred_name, atom.pred_arity) for atom in self.query_atoms})
        seen: Set[Signature] = set()
        relevant_rules: List[_SqlRule] = []

        while queue:
            signature = queue.popleft()
            if signature in seen:
                continue
            seen.add(signature)

            for rule_idx, rule in rules_by_head.get(signature, ()):
                native_rule = self._rule_to_sql(rule_idx, rule)
                if native_rule is None:
                    return False
                relevant_rules.append(native_rule)
                for body_atom in native_rule.body:
                    body_sig = (body_atom.pred_name, body_atom.pred_arity)
                    if body_sig not in seen:
                        queue.append(body_sig)

        self.relevant_rules = relevant_rules
        self.reachable_signatures = seen
        self.max_arity = max(
            [atom.pred_arity for atom in self.query_atoms]
            + [rule.head_pred_arity for rule in self.relevant_rules]
            + [atom.pred_arity for rule in self.relevant_rules for atom in rule.body]
            + [rec.pred_arity for rec in self.branch.belief_records]
            + [1]
        )

        self._build_sccs()

        if (
            any(scc.recursive for scc in self.sccs)
            and self.query.options.epistemic_semantics.rule_applicability
            != RuleApplicabilitySemantics.body_truth_only
        ):
            return False

        return True

    def evaluate(self, conn) -> QueryResult:
        effective_query_time, effective_valid_at, effective_known_at = (
            _resolve_effective_times(self.query)
        )
        prefix = f"doxa_native_{int(time.time() * 1000)}"
        tables = {
            "known": f"{prefix}_known",
            "delta": f"{prefix}_delta",
            "next_delta": f"{prefix}_next_delta",
            "witness": f"{prefix}_witness",
        }

        try:
            with conn.cursor() as cur:
                self._create_temp_tables(cur, tables)
                self._load_visible_facts(
                    cur,
                    tables,
                    effective_valid_at=effective_valid_at,
                    effective_known_at=effective_known_at,
                )
                self._evaluate_sccs(cur, tables)
                answers = self._query_answers(cur, tables["known"])
        finally:
            with conn.cursor() as cur:
                self._drop_temp_tables(cur, tables)

        if not self.query_vars and not answers:
            answers = [
                QueryAnswer(
                    bindings={},
                    b=0.0,
                    d=0.0,
                    belnap_status=_derive_belnap_status(0.0, 0.0, self.query),
                )
            ]

        answers = _apply_focus(answers, self.query.options.focus)
        answers = _sort_answers(answers, self.query.options.order_by)
        if self.query.options.offset:
            answers = answers[self.query.options.offset :]
        if self.query.options.limit is not None:
            answers = answers[: self.query.options.limit]

        return QueryResult(
            answers=tuple(answers),
            effective_query_time=effective_query_time,
            effective_valid_at=effective_valid_at,
            effective_known_at=effective_known_at,
            epistemic_semantics=self.query.options.epistemic_semantics,
            explain=None,
        )

    def _build_sccs(self) -> None:
        graph: Dict[Signature, Set[Signature]] = {
            signature: set() for signature in self.reachable_signatures
        }

        for rule in self.relevant_rules:
            head_sig = (rule.head_pred_name, rule.head_pred_arity)
            for atom in rule.body:
                body_sig = (atom.pred_name, atom.pred_arity)
                graph.setdefault(body_sig, set()).add(head_sig)
                graph.setdefault(head_sig, set())

        components = self._tarjan_scc(graph)
        signature_to_scc: Dict[Signature, int] = {}
        for scc_id, component in enumerate(components):
            for signature in component:
                signature_to_scc[signature] = scc_id

        dag: Dict[int, Set[int]] = {scc_id: set() for scc_id in range(len(components))}
        indegree: Dict[int, int] = {scc_id: 0 for scc_id in range(len(components))}

        for src, targets in graph.items():
            src_scc = signature_to_scc[src]
            for dst in targets:
                dst_scc = signature_to_scc[dst]
                if src_scc == dst_scc or dst_scc in dag[src_scc]:
                    continue
                dag[src_scc].add(dst_scc)
                indegree[dst_scc] += 1

        ready = deque(sorted(scc_id for scc_id, deg in indegree.items() if deg == 0))
        ordered_ids: List[int] = []
        while ready:
            scc_id = ready.popleft()
            ordered_ids.append(scc_id)
            for dst_scc in sorted(dag[scc_id]):
                indegree[dst_scc] -= 1
                if indegree[dst_scc] == 0:
                    ready.append(dst_scc)

        sccs: List[_SqlScc] = []
        for ordered_scc_id in ordered_ids:
            signatures = tuple(sorted(components[ordered_scc_id]))
            recursive = len(signatures) > 1 or any(
                signature in graph.get(signature, set()) for signature in signatures
            )
            sccs.append(
                _SqlScc(
                    scc_id=ordered_scc_id,
                    signatures=signatures,
                    recursive=recursive,
                )
            )

        self.sccs = sccs
        self.signature_to_scc = signature_to_scc

    def _tarjan_scc(
        self, graph: Dict[Signature, Set[Signature]]
    ) -> List[Set[Signature]]:
        index = 0
        indices: Dict[Signature, int] = {}
        lowlinks: Dict[Signature, int] = {}
        stack: List[Signature] = []
        on_stack: Set[Signature] = set()
        components: List[Set[Signature]] = []

        def strongconnect(node: Signature) -> None:
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for successor in graph.get(node, ()):
                if successor not in indices:
                    strongconnect(successor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[successor])
                elif successor in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[successor])

            if lowlinks[node] != indices[node]:
                return

            component: Set[Signature] = set()
            while True:
                popped = stack.pop()
                on_stack.discard(popped)
                component.add(popped)
                if popped == node:
                    break
            components.append(component)

        for node in sorted(graph):
            if node not in indices:
                strongconnect(node)

        return components

    def _create_temp_tables(self, cur, tables: Dict[str, str]) -> None:
        arg_cols = ", ".join(f"arg_{idx} jsonb" for idx in range(self.max_arity))
        atom_columns = (
            "pred_name text NOT NULL, "
            "pred_arity integer NOT NULL, "
            "arg_key text NOT NULL, "
            "b double precision NOT NULL, "
            "d double precision NOT NULL, "
            f"{arg_cols}, "
            "PRIMARY KEY (pred_name, pred_arity, arg_key)"
        )
        witness_columns = (
            "witness_key text NOT NULL, "
            "pred_name text NOT NULL, "
            "pred_arity integer NOT NULL, "
            "arg_key text NOT NULL, "
            "b double precision NOT NULL, "
            "d double precision NOT NULL, "
            "visited_atoms text[] NOT NULL, "
            f"{arg_cols}, "
            "PRIMARY KEY (witness_key)"
        )

        cur.execute(f"CREATE TEMP TABLE {tables['known']} ({atom_columns})")
        for key in ("delta", "next_delta", "witness"):
            cur.execute(f"CREATE TEMP TABLE {tables[key]} ({witness_columns})")

        lookup_cols = ", ".join(
            ["pred_name", "pred_arity"]
            + [f"arg_{idx}" for idx in range(self.max_arity)]
        )
        cur.execute(
            f"CREATE INDEX {tables['known']}_lookup_idx ON {tables['known']} ({lookup_cols})"
        )
        for key in ("delta", "next_delta", "witness"):
            cur.execute(
                f"CREATE INDEX {tables[key]}_lookup_idx ON {tables[key]} ({lookup_cols})"
            )
            cur.execute(
                f"CREATE INDEX {tables[key]}_atom_idx "
                f"ON {tables[key]} (pred_name, pred_arity, arg_key)"
            )

    def _drop_temp_tables(self, cur, tables: Dict[str, str]) -> None:
        for name in tables.values():
            cur.execute(f"DROP TABLE IF EXISTS {name}")

    def _load_visible_facts(
        self,
        cur,
        tables: Dict[str, str],
        *,
        effective_valid_at,
        effective_known_at,
    ) -> None:
        arg_names = ", ".join(f"arg_{idx}" for idx in range(self.max_arity))
        arg_exprs = ", ".join(self._base_arg_expr(idx) for idx in range(self.max_arity))
        witness_cols = ", ".join(
            [
                "witness_key",
                "pred_name",
                "pred_arity",
                "arg_key",
                "b",
                "d",
                "visited_atoms",
            ]
            + [f"arg_{idx}" for idx in range(self.max_arity)]
        )
        atom_cols = ", ".join(
            ["pred_name", "pred_arity", "arg_key", "b", "d"]
            + [f"arg_{idx}" for idx in range(self.max_arity)]
        )
        visible_arg_key = self._arg_key_sql("visible")
        visible_atom_identity = (
            f"(visible.pred_name || '/' || visible.pred_arity::text || '|' || "
            f"{visible_arg_key})"
        )

        sql = f"""
            WITH visible AS (
                SELECT id, pred_name, pred_arity, b, d, {arg_exprs}
                FROM doxa_belief_records
                WHERE branch_name = %s
                  AND et <= %s
                  AND (vf IS NULL OR vf <= %s)
                  AND (vt IS NULL OR vt >= %s)
                  AND ({self._predicate_filter_sql(sorted(self.reachable_signatures))})
            ),
            fact_witnesses AS (
                SELECT md5('fact|' || id::text) AS witness_key,
                       pred_name,
                       pred_arity,
                       {visible_arg_key} AS arg_key,
                       b,
                       d,
                       ARRAY[{visible_atom_identity}]::text[] AS visited_atoms,
                       {arg_names}
                FROM visible
            )
            INSERT INTO {tables["witness"]} ({witness_cols})
            SELECT {witness_cols}
            FROM fact_witnesses
        """
        params: List[Any] = [
            self.branch.name,
            effective_known_at,
            effective_valid_at,
            effective_valid_at,
        ]
        for pred_name, pred_arity in sorted(self.reachable_signatures):
            params.extend([pred_name, pred_arity])
        cur.execute(sql, params)

        cur.execute(
            f"INSERT INTO {tables['delta']} ({witness_cols}) "
            f"SELECT {witness_cols} FROM {tables['witness']}"
        )
        cur.execute(
            f"""
            INSERT INTO {tables["known"]} ({atom_cols})
            SELECT pred_name,
                   pred_arity,
                   arg_key,
                   {self._aggregate_sql("b")} AS b,
                   {self._aggregate_sql("d")} AS d,
                   {arg_names}
            FROM {tables["witness"]}
            GROUP BY pred_name, pred_arity, arg_key, {arg_names}
            """
        )

        self._analyze_tables(cur, tables["known"], tables["delta"], tables["witness"])

    def _evaluate_sccs(self, cur, tables: Dict[str, str]) -> None:
        rules_by_scc: Dict[int, List[_SqlRule]] = defaultdict(list)
        for rule in self.relevant_rules:
            scc_id = self.signature_to_scc[(rule.head_pred_name, rule.head_pred_arity)]
            rules_by_scc[scc_id].append(rule)

        for scc in self.sccs:
            scc_rules = rules_by_scc.get(scc.scc_id, [])
            if not scc_rules:
                continue

            recursive_variants: List[Tuple[_SqlRule, int]] = []
            seed_variants: List[Tuple[_SqlRule, Optional[int]]] = []
            scc_signatures = set(scc.signatures)

            for rule in scc_rules:
                recursive_positions = [
                    pos
                    for pos, atom in enumerate(rule.body)
                    if (atom.pred_name, atom.pred_arity) in scc_signatures
                ]
                if recursive_positions:
                    recursive_variants.extend(
                        (rule, pos) for pos in recursive_positions
                    )
                else:
                    seed_variants.append((rule, None))

            cur.execute(f"TRUNCATE {tables['delta']}")
            if scc.recursive:
                self._prime_delta_from_witness(
                    cur,
                    tables["witness"],
                    tables["delta"],
                    scc.signatures,
                )

            if seed_variants:
                self._apply_rule_batch(
                    cur,
                    tables,
                    seed_variants,
                    target_delta=tables["delta"],
                )

            if not scc.recursive:
                cur.execute(f"TRUNCATE {tables['delta']}")
                continue

            rounds = 0
            while rounds < self.query.options.max_depth and self._table_has_rows(
                cur, tables["delta"]
            ):
                rounds += 1
                cur.execute(f"TRUNCATE {tables['next_delta']}")
                self._apply_rule_batch(
                    cur,
                    tables,
                    recursive_variants,
                    target_delta=tables["next_delta"],
                )
                cur.execute(f"TRUNCATE {tables['delta']}")
                cur.execute(
                    f"""
                    INSERT INTO {tables["delta"]}
                    SELECT * FROM {tables["next_delta"]}
                    """
                )
                self._analyze_tables(
                    cur,
                    tables["delta"],
                    tables["known"],
                    tables["witness"],
                )

            cur.execute(f"TRUNCATE {tables['delta']}")

    def _prime_delta_from_witness(
        self,
        cur,
        witness_table: str,
        delta_table: str,
        signatures: Sequence[Signature],
    ) -> None:
        filter_sql = self._predicate_filter_sql(signatures, alias="w")
        cur.execute(
            f"""
            INSERT INTO {delta_table}
            SELECT w.*
            FROM {witness_table} w
            WHERE {filter_sql}
            """,
            self._predicate_filter_params(signatures),
        )

    def _apply_rule_batch(
        self,
        cur,
        tables: Dict[str, str],
        variants: Sequence[Tuple[_SqlRule, Optional[int]]],
        *,
        target_delta: str,
    ) -> None:
        if not variants:
            return

        candidate_parts: List[str] = []
        params: List[Any] = []
        for rule, delta_pos in variants:
            sql, sql_params = self._compile_rule_candidate(
                rule,
                delta_pos=delta_pos,
                known_table=tables["known"],
                witness_table=tables["witness"],
                delta_table=tables["delta"],
            )
            candidate_parts.append(sql)
            params.extend(sql_params)

        arg_names = ", ".join(f"arg_{idx}" for idx in range(self.max_arity))
        atom_cols = ", ".join(
            ["pred_name", "pred_arity", "arg_key", "b", "d"]
            + [f"arg_{idx}" for idx in range(self.max_arity)]
        )
        witness_cols = ", ".join(
            [
                "witness_key",
                "pred_name",
                "pred_arity",
                "arg_key",
                "b",
                "d",
                "visited_atoms",
            ]
            + [f"arg_{idx}" for idx in range(self.max_arity)]
        )

        sql = f"""
            WITH candidate_witnesses AS (
                {" UNION ALL ".join(candidate_parts)}
            ),
            grouped_candidates AS (
                SELECT witness_key,
                       pred_name,
                       pred_arity,
                       arg_key,
                       MAX(b) AS b,
                       MAX(d) AS d,
                       visited_atoms,
                       {arg_names}
                FROM candidate_witnesses
                WHERE b > 0.0 OR d > 0.0
                GROUP BY witness_key, pred_name, pred_arity, arg_key, visited_atoms, {arg_names}
            ),
            upserted_witnesses AS (
                INSERT INTO {tables["witness"]} AS w ({witness_cols})
                SELECT {witness_cols}
                FROM grouped_candidates
                ON CONFLICT (witness_key) DO UPDATE
                SET b = GREATEST(w.b, EXCLUDED.b),
                    d = GREATEST(w.d, EXCLUDED.d)
                WHERE EXCLUDED.b > w.b OR EXCLUDED.d > w.d
                RETURNING witness_key, pred_name, pred_arity, arg_key, b, d, visited_atoms, {arg_names}
            ),
            changed_atoms AS (
                SELECT DISTINCT pred_name, pred_arity, arg_key, {arg_names}
                FROM upserted_witnesses
            ),
            relevant_witnesses AS (
                SELECT w.pred_name,
                       w.pred_arity,
                       w.arg_key,
                       w.b,
                       w.d,
                       {", ".join(f"w.arg_{idx} AS arg_{idx}" for idx in range(self.max_arity))}
                FROM {tables["witness"]} w
                JOIN changed_atoms c
                  ON w.pred_name = c.pred_name
                 AND w.pred_arity = c.pred_arity
                 AND w.arg_key = c.arg_key
                LEFT JOIN upserted_witnesses uw
                  ON uw.witness_key = w.witness_key
                WHERE uw.witness_key IS NULL

                UNION ALL

                SELECT uw.pred_name,
                       uw.pred_arity,
                       uw.arg_key,
                       uw.b,
                       uw.d,
                       {", ".join(f"uw.arg_{idx} AS arg_{idx}" for idx in range(self.max_arity))}
                FROM upserted_witnesses uw
            ),
            recomputed_atoms AS (
                SELECT rw.pred_name,
                       rw.pred_arity,
                       rw.arg_key,
                       {self._aggregate_sql("rw.b")} AS b,
                       {self._aggregate_sql("rw.d")} AS d,
                       {", ".join(f"rw.arg_{idx} AS arg_{idx}" for idx in range(self.max_arity))}
                FROM relevant_witnesses rw
                GROUP BY rw.pred_name, rw.pred_arity, rw.arg_key, {", ".join(f"rw.arg_{idx}" for idx in range(self.max_arity))}
            ),
            upserted_atoms AS (
                INSERT INTO {tables["known"]} AS k ({atom_cols})
                SELECT {atom_cols}
                FROM recomputed_atoms
                ON CONFLICT (pred_name, pred_arity, arg_key) DO UPDATE
                SET b = GREATEST(k.b, EXCLUDED.b),
                    d = GREATEST(k.d, EXCLUDED.d)
                WHERE EXCLUDED.b > k.b OR EXCLUDED.d > k.d
                RETURNING pred_name, pred_arity, arg_key, b, d, {arg_names}
            )
            INSERT INTO {target_delta} ({witness_cols})
            SELECT witness_key, pred_name, pred_arity, arg_key, b, d, visited_atoms, {arg_names}
            FROM upserted_witnesses
            ON CONFLICT (witness_key) DO UPDATE
            SET b = GREATEST({target_delta}.b, EXCLUDED.b),
                d = GREATEST({target_delta}.d, EXCLUDED.d)
            WHERE EXCLUDED.b > {target_delta}.b OR EXCLUDED.d > {target_delta}.d
        """
        cur.execute(sql, params)

    def _compile_rule_candidate(
        self,
        rule: _SqlRule,
        *,
        delta_pos: Optional[int],
        known_table: str,
        witness_table: str,
        delta_table: str,
    ) -> Tuple[str, List[Any]]:
        from_clauses: List[str] = []
        where_clauses: List[str] = []
        params: List[Any] = []
        var_bindings: dict[str, str] = {}
        body_b_terms: List[str] = []
        body_d_terms: List[str] = []
        body_identity_terms: List[str] = ["CAST(%s AS text)"]
        recursive_path_terms: List[str] = []
        head_scc = self.signature_to_scc[(rule.head_pred_name, rule.head_pred_arity)]

        for goal_idx, goal in enumerate(rule.body):
            alias = f"r{rule.rule_idx}_{goal_idx}"
            goal_scc = self.signature_to_scc.get((goal.pred_name, goal.pred_arity))
            recursive_goal = goal_scc == head_scc
            if recursive_goal:
                source_table = delta_table if delta_pos == goal_idx else witness_table
                recursive_path_terms.append(f"{alias}.visited_atoms")
            else:
                source_table = known_table
            from_clauses.append(f"{source_table} {alias}")
            body_b_terms.append(f"{alias}.b")
            body_d_terms.append(f"{alias}.d")
            if recursive_goal:
                body_identity_terms.append(f"{alias}.witness_key")
            else:
                body_identity_terms.extend(
                    [
                        f"{alias}.pred_name",
                        f"{alias}.pred_arity::text",
                        f"{alias}.arg_key",
                    ]
                )
            where_clauses.append(f"{alias}.pred_name = %s")
            params.append(goal.pred_name)
            where_clauses.append(f"{alias}.pred_arity = %s")
            params.append(goal.pred_arity)

            for pos, term in enumerate(goal.args):
                col = f"{alias}.arg_{pos}"
                self._bind_term(term, col, var_bindings, where_clauses, params)

        body_b = self._combine_truth_sql(body_b_terms)
        body_d = self._combine_falsity_sql(body_d_terms)
        applicability = self._rule_applicability_sql(body_b, body_d)
        witness_raw = f"concat_ws('|', {', '.join(body_identity_terms)})"
        carried_visited_atoms = self._merge_text_array_sql(recursive_path_terms)

        head_args: List[str] = []
        head_params: List[Any] = []
        for term in rule.head_args:
            if term.kind == "var":
                binding = var_bindings.get(str(term.value))
                if binding is None:
                    raise ValueError("Unbound head variable in native SQL rule.")
                head_args.append(binding)
            else:
                head_args.append("%s")
                head_params.append(self._jsonb_constant(term.value))

        for _ in range(len(rule.head_args), self.max_arity):
            head_args.append("NULL::jsonb")

        select_arg_cols = ", ".join(
            f"{expr} AS arg_{idx}" for idx, expr in enumerate(head_args)
        )

        inner_sql = f"""
            SELECT {witness_raw} AS witness_key_raw,
                   %s AS pred_name,
                   %s AS pred_arity,
                   ({applicability}) * %s AS b,
                   ({applicability}) * %s AS d,
                   {carried_visited_atoms} AS visited_atoms,
                   {select_arg_cols}
            FROM {" CROSS JOIN ".join(from_clauses)}
            WHERE {" AND ".join(where_clauses)}
        """
        inner_params: List[Any] = [
            str(rule.rule_idx),
            rule.head_pred_name,
            rule.head_pred_arity,
            rule.b,
            rule.d,
            *head_params,
            *params,
        ]

        arg_names = ", ".join(f"cand.arg_{idx}" for idx in range(self.max_arity))
        head_atom_identity = self._atom_identity_sql(
            "cand",
            arg_key_sql=self._arg_key_sql("cand"),
        )
        outer_sql = f"""
            SELECT md5(cand.witness_key_raw) AS witness_key,
                   cand.pred_name,
                   cand.pred_arity,
                   {self._arg_key_sql("cand")} AS arg_key,
                   cand.b,
                   cand.d,
                   array_append(cand.visited_atoms, {head_atom_identity}) AS visited_atoms,
                   {arg_names}
            FROM ({inner_sql}) cand
            WHERE NOT ({head_atom_identity} = ANY(cand.visited_atoms))
        """
        return outer_sql, inner_params

    def _query_answers(self, cur, known_table: str) -> List[QueryAnswer]:
        sql, params, projected_vars = self._compile_query_sql(known_table)
        cur.execute(sql, params)
        rows = cur.fetchall()
        answers: List[QueryAnswer] = []
        for row in rows:
            bindings = {
                var_name: row[idx] for idx, var_name in enumerate(projected_vars)
            }
            b = float(row[len(projected_vars)])
            d = float(row[len(projected_vars) + 1])
            answers.append(
                QueryAnswer(
                    bindings=bindings,
                    b=b,
                    d=d,
                    belnap_status=_derive_belnap_status(b, d, self.query),
                )
            )
        return answers

    def _compile_query_sql(self, table_name: str) -> Tuple[str, List[Any], List[str]]:
        from_clauses: List[str] = []
        where_clauses: List[str] = []
        params: List[Any] = []
        var_bindings: dict[str, str] = {}
        body_b_terms: List[str] = []
        body_d_terms: List[str] = []

        for goal_idx, goal in enumerate(self.query_atoms):
            alias = f"q{goal_idx}"
            from_clauses.append(f"{table_name} {alias}")
            body_b_terms.append(f"{alias}.b")
            body_d_terms.append(f"{alias}.d")
            where_clauses.append(f"{alias}.pred_name = %s")
            params.append(goal.pred_name)
            where_clauses.append(f"{alias}.pred_arity = %s")
            params.append(goal.pred_arity)

            for pos, term in enumerate(goal.args):
                col = f"{alias}.arg_{pos}"
                self._bind_term(term, col, var_bindings, where_clauses, params)

        row_b = self._combine_truth_sql(body_b_terms)
        row_d = self._combine_falsity_sql(body_d_terms)

        projected_vars = sorted(self.query_vars)
        select_vars = [f"{var_bindings[name]} AS {name}" for name in projected_vars]
        group_by = ", ".join(projected_vars)
        inner_select = ", ".join(
            select_vars + [f"{row_b} AS row_b", f"{row_d} AS row_d"]
        )

        if projected_vars:
            sql = f"""
                SELECT {group_by},
                       {self._aggregate_sql("row_b")} AS b,
                       {self._aggregate_sql("row_d")} AS d
                FROM (
                    SELECT {inner_select}
                    FROM {" CROSS JOIN ".join(from_clauses)}
                    WHERE {" AND ".join(where_clauses)}
                ) answer_rows
                GROUP BY {group_by}
            """
        else:
            sql = f"""
                SELECT {self._aggregate_sql("row_b")} AS b,
                       {self._aggregate_sql("row_d")} AS d
                FROM (
                    SELECT {row_b} AS row_b, {row_d} AS row_d
                    FROM {" CROSS JOIN ".join(from_clauses)}
                    WHERE {" AND ".join(where_clauses)}
                ) answer_rows
            """

        return sql, params, projected_vars

    def _goal_to_atom(self, goal: Goal) -> Optional[_SqlAtom]:
        if not isinstance(goal, AtomGoal) or goal.negated:
            return None
        return self._atom_from_parts(goal.pred_name, goal.pred_arity, goal.goal_args)

    def _rule_to_sql(self, rule_idx: int, rule: Rule) -> Optional[_SqlRule]:
        body: List[_SqlAtom] = []
        bound_vars: Set[str] = set()

        for goal in rule.goals:
            if not isinstance(goal, RuleAtomGoal) or goal.negated:
                return None
            atom = self._atom_from_parts(
                goal.pred_name, goal.pred_arity, goal.goal_args
            )
            if atom is None:
                return None
            body.append(atom)
            for term in atom.args:
                if term.kind == "var":
                    bound_vars.add(str(term.value))

        head_terms = self._terms_from_args(rule.head_args)
        if head_terms is None:
            return None

        for term in head_terms:
            if term.kind == "var" and str(term.value) not in bound_vars:
                return None

        return _SqlRule(
            rule_idx=rule_idx,
            head_pred_name=rule.head_pred_name,
            head_pred_arity=rule.head_pred_arity,
            head_args=head_terms,
            body=tuple(body),
            b=rule.b,
            d=rule.d,
        )

    def _atom_from_parts(
        self, pred_name: str, pred_arity: int, args: Sequence[Any]
    ) -> Optional[_SqlAtom]:
        terms = self._terms_from_args(args)
        if terms is None:
            return None
        return _SqlAtom(pred_name=pred_name, pred_arity=pred_arity, args=terms)

    def _terms_from_args(self, args: Sequence[Any]) -> Optional[Tuple[_SqlTerm, ...]]:
        terms: List[_SqlTerm] = []
        for arg in args:
            term = self._term_from_arg(arg)
            if term is None:
                return None
            terms.append(term)
        return tuple(terms)

    def _term_from_arg(self, arg: Any) -> Optional[_SqlTerm]:
        if hasattr(arg, "var"):
            return _SqlTerm("var", arg.var.name)
        if hasattr(arg, "ent_name"):
            return _SqlTerm("const", arg.ent_name)
        if hasattr(arg, "value"):
            return _SqlTerm("const", arg.value)
        if hasattr(arg, "pred_ref_name") and hasattr(arg, "pred_ref_arity"):
            return _SqlTerm("const", f"{arg.pred_ref_name}/{arg.pred_ref_arity}")
        return None

    def _bind_term(
        self,
        term: _SqlTerm,
        column_sql: str,
        var_bindings: dict[str, str],
        where_clauses: List[str],
        params: List[Any],
    ) -> None:
        if term.kind == "var":
            var_name = str(term.value)
            existing = var_bindings.get(var_name)
            if existing is None:
                var_bindings[var_name] = column_sql
            else:
                where_clauses.append(f"{column_sql} = {existing}")
            return

        where_clauses.append(f"{column_sql} = %s")
        params.append(self._jsonb_constant(term.value))

    def _jsonb_constant(self, value: Any) -> Jsonb:
        if isinstance(value, datetime):
            text = value.isoformat()
            if text.endswith("+00:00"):
                text = text[:-6] + "Z"
            return Jsonb(text)
        if isinstance(value, date):
            return Jsonb(value.isoformat())
        if isinstance(value, timedelta):
            rendered = render_duration_literal(value)
            return Jsonb(rendered[4:-1])
        return Jsonb(value)

    def _combine_truth_sql(self, terms: Sequence[str]) -> str:
        semantics = self.query.options.epistemic_semantics.body_truth
        if not terms:
            return "1.0"
        if semantics == BodyTruthSemantics.product:
            return " * ".join(f"({term})" for term in terms)
        if semantics == BodyTruthSemantics.minimum:
            return f"LEAST({', '.join(terms)})"
        raise ValueError(f"Unsupported body truth semantics: {semantics!r}")

    def _combine_falsity_sql(self, terms: Sequence[str]) -> str:
        semantics = self.query.options.epistemic_semantics.body_falsity
        if not terms:
            return "0.0"
        if semantics == BodyFalsitySemantics.maximum:
            return f"GREATEST({', '.join(terms)})"
        if semantics == BodyFalsitySemantics.noisy_or:
            factors = " * ".join(f"(1.0 - ({term}))" for term in terms)
            return f"1.0 - ({factors})"
        raise ValueError(f"Unsupported body falsity semantics: {semantics!r}")

    def _rule_applicability_sql(self, body_b_sql: str, body_d_sql: str) -> str:
        semantics = self.query.options.epistemic_semantics.rule_applicability
        if semantics == RuleApplicabilitySemantics.body_truth_only:
            return body_b_sql
        if (
            semantics
            == RuleApplicabilitySemantics.body_truth_discounted_by_body_falsity
        ):
            return f"({body_b_sql}) * (1.0 - ({body_d_sql}))"
        raise ValueError(f"Unsupported rule applicability semantics: {semantics!r}")

    def _aggregate_sql(self, column_sql: str) -> str:
        semantics = self.query.options.epistemic_semantics.support_aggregation
        if semantics == SupportAggregationSemantics.maximum:
            return f"MAX({column_sql})"
        if semantics == SupportAggregationSemantics.capped_sum:
            return f"LEAST(1.0, SUM({column_sql}))"
        if semantics == SupportAggregationSemantics.noisy_or:
            bounded = f"LEAST(GREATEST({column_sql}, 0.0), 1.0)"
            complement = f"1.0 - ({bounded})"
            return (
                "CASE "
                f"WHEN COUNT(*) = 0 THEN 0.0 "
                f"WHEN BOOL_OR(({column_sql}) >= 1.0) THEN 1.0 "
                f"ELSE 1.0 - EXP(SUM(LN(GREATEST({complement}, 1e-12)))) "
                "END"
            )
        raise ValueError(f"Unsupported support aggregation semantics: {semantics!r}")

    def _arg_key_sql(self, alias: str) -> str:
        cols = ", ".join(f"{alias}.arg_{idx}" for idx in range(self.max_arity))
        return f"jsonb_build_array({cols})::text"

    def _atom_identity_sql(
        self,
        alias: str,
        *,
        arg_key_sql: Optional[str] = None,
    ) -> str:
        atom_arg_key = arg_key_sql if arg_key_sql is not None else f"{alias}.arg_key"
        return f"({alias}.pred_name || '/' || {alias}.pred_arity::text || '|' || {atom_arg_key})"

    def _merge_text_array_sql(self, terms: Sequence[str]) -> str:
        if not terms:
            return "ARRAY[]::text[]"
        merged = terms[0]
        for term in terms[1:]:
            merged = f"array_cat({merged}, {term})"
        return merged

    def _base_arg_expr(self, idx: int) -> str:
        return (
            f"CASE WHEN pred_arity > {idx} THEN "
            f"CASE "
            f"WHEN data->'args'->{idx}->>'term_kind' = 'ent' "
            f"THEN to_jsonb(data->'args'->{idx}->>'ent_name') "
            f"WHEN data->'args'->{idx}->>'term_kind' = 'lit' "
            f"THEN data->'args'->{idx}->'value' "
            f"WHEN data->'args'->{idx}->>'term_kind' = 'pred_ref' "
            f"THEN to_jsonb((data->'args'->{idx}->>'pred_ref_name') || '/' || "
            f"(data->'args'->{idx}->>'pred_ref_arity')) "
            f"ELSE NULL END "
            f"ELSE NULL END AS arg_{idx}"
        )

    def _predicate_filter_sql(
        self,
        signatures: Sequence[Signature],
        *,
        alias: Optional[str] = None,
    ) -> str:
        if not signatures:
            return "FALSE"
        prefix = f"{alias}." if alias else ""
        clauses = [
            f"({prefix}pred_name = %s AND {prefix}pred_arity = %s)" for _ in signatures
        ]
        return " OR ".join(clauses)

    def _predicate_filter_params(self, signatures: Sequence[Signature]) -> List[Any]:
        params: List[Any] = []
        for pred_name, pred_arity in signatures:
            params.extend([pred_name, pred_arity])
        return params

    def _table_has_rows(self, cur, table_name: str) -> bool:
        cur.execute(f"SELECT 1 FROM {table_name} LIMIT 1")
        return cur.fetchone() is not None

    def _analyze_tables(self, cur, *table_names: str) -> None:
        for table_name in table_names:
            cur.execute(f"ANALYZE {table_name}")
