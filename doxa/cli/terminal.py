"""Doxa interactive terminal (REPL)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from doxa.core.branch import Branch
from doxa.persistence.repository import BranchRepository
from doxa.query.engine import QueryEngine, QueryResult
from doxa.cli.commands import dispatch, _load_file

# Try to enable readline history/completion
try:
    import readline  # noqa: F401

    _READLINE = True
except ImportError:
    _READLINE = False


BANNER = """\
╔══════════════════════════════════════════╗
║ Doxa Terminal  (type /- help for help)   ║
╚══════════════════════════════════════════╝
"""

PROMPT_MAIN = "doxa> "
PROMPT_CONT = "... "  # continuation prompt for multi-line input


@dataclass
class TerminalState:
    branch: Branch
    repo: BranchRepository
    engine: QueryEngine
    memory_kind: str
    engine_kind: str


def _make_empty_branch() -> Branch:
    from doxa.core.base_kinds import BaseKind
    from datetime import datetime, timezone

    return Branch(
        kind=BaseKind.branch,
        created_at=datetime.now(timezone.utc),
        name="main",
        ephemeral=False,
        belief_records=[],
        rules=[],
        constraints=[],
        predicates=[],
        entities=[],
    )


def _collect_statement(first_line: str) -> str:
    """Read additional continuation lines until we have a complete '.' terminated input."""
    buf = first_line
    stripped = buf.strip()

    # If already complete (ends with '.'), return immediately
    if stripped.endswith("."):
        return buf

    # Multi-line: keep reading until the accumulated buffer ends with '.'
    while True:
        try:
            line = input(PROMPT_CONT)
        except (EOFError, KeyboardInterrupt):
            return buf  # best-effort: return what we have
        buf = buf + "\n" + line
        if buf.strip().endswith("."):
            return buf


def _handle_statement(state: TerminalState, text: str) -> None:
    """Parse Doxa text and either run a query or add a statement to the branch."""
    stripped = text.strip()

    # Strip trailing dot for non-query statements before parsing
    is_query = stripped.startswith("?-")

    if is_query:
        _run_query(state, stripped)
    else:
        _add_to_branch(state, stripped)


def _run_query(state: TerminalState, text: str) -> None:
    from doxa.core.query import Query

    # Strip trailing dot if present
    q_text = text.rstrip(".").strip()
    try:
        query = Query.from_ax(q_text)
    except Exception as exc:
        print(f"  Parse error: {exc}")
        return

    try:
        result: QueryResult = state.engine.evaluate(state.branch, query)
    except NotImplementedError:
        print("  [Query engine not implemented for this backend yet]")
        _echo_query(query)
        return
    except Exception as exc:
        print(f"  Query error: {exc}")
        return

    if not result.success:
        print("  No results.")
    else:
        for i, binding in enumerate(result.bindings, 1):
            print(f"  {i}: {binding.values}")

    if result.explain is not None:
        print()
        print("  Explain trace:")
        for event in result.explain:
            etype = event.get("type", "?")
            parts = {k: v for k, v in event.items() if k != "type"}
            print(f"    [{etype}] {parts}")


def _echo_query(query) -> None:
    print(f"  Query parsed: {query.to_ax()}")


def _add_to_branch(state: TerminalState, text: str) -> None:
    """Parse and merge Doxa statements into the branch."""
    # Ensure text is dot-terminated for Branch.from_ax
    clean = text.strip()
    if not clean.endswith("."):
        clean += "."
    try:
        new_branch = Branch.from_ax(clean)
    except Exception as exc:
        print(f"  Parse error: {exc}")
        return

    state.branch = state.branch.merge(new_branch)

    counts = []
    if new_branch.predicates:
        counts.append(f"{len(new_branch.predicates)} predicate(s)")
    if new_branch.belief_records:
        counts.append(f"{len(new_branch.belief_records)} fact(s)")
    if new_branch.rules:
        counts.append(f"{len(new_branch.rules)} rule(s)")
    if new_branch.constraints:
        counts.append(f"{len(new_branch.constraints)} constraint(s)")

    if counts:
        print("  Added: " + ", ".join(counts))
    else:
        print("  (nothing new added)")


def run_terminal(
    memory_kind: str,
    engine_kind: str,
    repo: BranchRepository,
    engine: QueryEngine,
    preload_files: list[Path],
    ephemeral: bool = False,
) -> None:
    """Start the interactive Doxa terminal."""
    # Ensure UTF-8 output on Windows to avoid charmap errors
    if sys.platform == "win32":
        import io

        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    branch = _make_empty_branch()

    # Pre-load files
    for path in preload_files:
        try:
            loaded = _load_file(path)
            branch = branch.merge(loaded)
            print(
                f"  Loaded {path}  "
                f"({len(loaded.belief_records)} facts, "
                f"{len(loaded.rules)} rules, "
                f"{len(loaded.constraints)} constraints)"
            )
        except Exception as exc:
            print(f"  Warning: could not load {path}: {exc}", file=sys.stderr)

    state = TerminalState(
        branch=branch,
        repo=repo,
        engine=engine,
        memory_kind=memory_kind,
        engine_kind=engine_kind,
    )

    print(BANNER)

    while True:
        try:
            line = input(PROMPT_MAIN)
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print("\n  Goodbye.")
            break

        line = line.strip()
        if not line:
            continue

        # Ignore comments starting with %
        if line.startswith("%"):
            continue

        # Built-in /- commands
        if line.startswith("/-"):
            dispatch(state, line)
            continue

        # Collect multi-line input if incomplete
        full = _collect_statement(line)
        if full.strip():
            _handle_statement(state, full)
