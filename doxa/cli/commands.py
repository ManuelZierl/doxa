"""Built-in /- commands for the Doxa terminal REPL."""

from __future__ import annotations

import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from doxa.cli.io import BranchLoadError, load_branch_file
from doxa.cli.json_repair import repair_branch_json
from doxa.cli.serialization import branch_to_doxa

if TYPE_CHECKING:
    from doxa.cli.terminal import TerminalState
    from doxa.core.branch import Branch


# ── helpers ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedOutArgs:
    out_file: Path | None
    remaining: list[str]


def _extract_out_file_flag(args: list[str]) -> ParsedOutArgs:
    out_file: Path | None = None
    clean: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--file" and i + 1 < len(args):
            out_file = Path(args[i + 1])
            i += 2
        else:
            clean.append(args[i])
            i += 1
    return ParsedOutArgs(out_file=out_file, remaining=clean)


def _branch_to_doxa(
    state: "TerminalState",
    *,
    predicates=True,
    belief_records=True,
    rules=True,
    constraints=True,
) -> str:
    return branch_to_doxa(
        state.branch,
        predicates=predicates,
        belief_records=belief_records,
        rules=rules,
        constraints=constraints,
    )


def _branch_to_dict(
    state: "TerminalState",
    *,
    predicates=True,
    belief_records=True,
    rules=True,
    constraints=True,
) -> dict:
    b = state.branch
    out: dict = {}
    if predicates:
        out["predicates"] = [
            {"name": p.name, "arity": p.arity, "description": p.description}
            for p in b.predicates
        ]
    if belief_records:
        out["belief_records"] = [r.to_doxa() for r in b.belief_records]
    if rules:
        out["rules"] = [r.to_doxa() for r in b.rules]
    if constraints:
        out["constraints"] = [c.to_doxa() for c in b.constraints]
    return out


def _parse_dump_args(args: list[str]) -> tuple[str, dict[str, bool]]:
    """Returns (fmt, include_flags). fmt is 'ax' or 'json'."""
    fmt = "ax"
    flags = dict(predicates=True, belief_records=True, rules=True, constraints=True)

    for a in args:
        if a == "--ax":
            fmt = "ax"
        elif a == "--json":
            fmt = "json"
        elif a == "--no-predicates":
            flags["predicates"] = False
        elif a == "--no-belief-records":
            flags["belief_records"] = False
        elif a == "--no-rules":
            flags["rules"] = False
        elif a == "--no-constraints":
            flags["constraints"] = False
        elif a == "--no-entities":
            pass  # entities are implicit; flag accepted but no-op for dump
        elif a.startswith("--"):
            print(f"  Unknown dump flag: {a}")

    return fmt, flags


# ── command handlers ──────────────────────────────────────────────────────────


def cmd_dump(state: "TerminalState", args: list[str]) -> None:
    """/- dump [--ax|--json] [--no-predicates] [--no-belief-records] [--no-rules] [--no-constraints]"""
    parsed = _extract_out_file_flag(args)
    fmt, flags = _parse_dump_args(parsed.remaining)

    if fmt == "json":
        content = json.dumps(_branch_to_dict(state, **flags), indent=2)
    else:
        content = _branch_to_doxa(state, **flags)

    if parsed.out_file:
        parsed.out_file.write_text(content)
        print(f"  Dumped to {parsed.out_file}")
    else:
        print(content)


def cmd_info(state: "TerminalState", _args: list[str]) -> None:
    """/- info — show session info"""
    from doxa.__version__ import __version__

    b = state.branch
    print(f"  Doxa version : {__version__}")
    print(f"  Memory backend : {state.memory_kind}")
    print(f"  Query engine   : {state.engine_kind}")
    print(f"  Predicates     : {len(b.predicates)}")
    print(f"  Belief records : {len(b.belief_records)}")
    print(f"  Rules          : {len(b.rules)}")
    print(f"  Constraints    : {len(b.constraints)}")
    print(f"  Entities       : {len(b.entities)}")


def cmd_schema(state: "TerminalState", args: list[str]) -> None:
    """/- schema [--query] [--branch] [--branch.<sub>] [--file <filename>]"""
    from doxa.core.branch import Branch
    from doxa.core.query import Query

    parsed = _extract_out_file_flag(args)
    clean = parsed.remaining

    if not clean:
        # default: full combined schema
        result = {
            "branch": Branch.llm_schema(),
            "query": Query.llm_schema(),
        }
    else:
        result = {}
        for sel in clean:
            if sel == "--branch":
                result["branch"] = Branch.llm_schema()
            elif sel == "--query":
                result["query"] = Query.llm_schema()
            elif sel.startswith("--branch."):
                # Drill into branch schema by dotted path
                path = sel[len("--branch.") :].split(".")
                node = Branch.llm_schema()
                for part in path:
                    if isinstance(node, dict) and part in node:
                        node = node[part]
                    else:
                        print(f"  Path segment {part!r} not found in branch schema.")
                        node = None
                        break
                if node is not None:
                    result[sel[2:]] = node
            else:
                print(f"  Unknown schema selector: {sel}")

    content = json.dumps(result, indent=2, default=str)

    if parsed.out_file:
        parsed.out_file.write_text(content)
        print(f"  Schema written to {parsed.out_file}")
    else:
        print(content)


def cmd_load(state: "TerminalState", args: list[str]) -> None:
    """/- load <file> [<file2> ...] [--fix] — load and merge .doxa or .json files"""
    if not args:
        print("  Usage: /- load <file> [<file2> ...] [--fix]")
        return

    # Check for --fix flag
    fix_mode = "--fix" in args
    file_args = [a for a in args if a != "--fix"]

    for path_str in file_args:
        path = Path(path_str)
        if not path.exists():
            print(f"  File not found: {path}")
            continue
        try:
            branch = _load_file(path, fix_missing_kinds=fix_mode)
            state.branch = state.branch.merge(branch)
            if not state.ephemeral:
                state.repo.save(state.branch)
            print(
                f"  Loaded {path}  "
                f"(+{len(branch.belief_records)} facts, "
                f"+{len(branch.rules)} rules, "
                f"+{len(branch.constraints)} constraints)"
            )
        except BranchLoadError as exc:
            print(f"  Error loading {path}: {exc}")


def cmd_unload(state: "TerminalState", args: list[str]) -> None:
    """/- unload <what>

    Subcommands:
      predicate <name>/<arity>   remove a predicate and all facts/rules using it
      entity <name>              remove an entity and all facts referencing it
      rules                      remove all rules
      constraints                remove all constraints
      all                        reset branch to empty
    """
    from datetime import datetime, timezone

    from doxa.core.base_kinds import BaseKind
    from doxa.core.branch import Branch

    if not args:
        print(
            "  Usage: /- unload predicate <name>/<arity> | entity <name> | rules | constraints | all"
        )
        return

    subcmd = args[0]
    b = state.branch

    if subcmd == "all":
        state.branch = Branch(
            kind=BaseKind.branch,
            created_at=datetime.now(timezone.utc),
            name="main",
            ephemeral=b.ephemeral,
            belief_records=[],
            rules=[],
            constraints=[],
            predicates=[],
            entities=[],
        )
        print("  Branch reset to empty.")

    elif subcmd == "rules":
        state.branch = b.model_copy(update={"rules": []})
        print(f"  Removed {len(b.rules)} rule(s).")

    elif subcmd == "constraints":
        state.branch = b.model_copy(update={"constraints": []})
        print(f"  Removed {len(b.constraints)} constraint(s).")

    elif subcmd == "predicate" and len(args) >= 2:
        spec = args[1]
        if "/" not in spec:
            print("  Usage: /- unload predicate <name>/<arity>")
            return
        pred_name, arity_str = spec.rsplit("/", 1)
        try:
            arity = int(arity_str)
        except ValueError:
            print(f"  Invalid arity: {arity_str!r}")
            return

        new_predicates = [
            p for p in b.predicates if not (p.name == pred_name and p.arity == arity)
        ]
        new_brs = [
            r
            for r in b.belief_records
            if r.pred_name != pred_name or r.pred_arity != arity
        ]

        def _goal_refs_pred(goal) -> bool:
            return (
                getattr(goal, "pred_name", None) == pred_name
                and getattr(goal, "pred_arity", None) == arity
            )

        new_rules = [
            r
            for r in b.rules
            if not (
                (r.head_pred_name == pred_name and r.head_pred_arity == arity)
                or any(_goal_refs_pred(g) for g in r.goals)
            )
        ]
        new_constraints = [
            c for c in b.constraints if not any(_goal_refs_pred(g) for g in c.goals)
        ]
        removed = len(b.predicates) - len(new_predicates)
        removed_brs = len(b.belief_records) - len(new_brs)
        removed_rules = len(b.rules) - len(new_rules)
        state.branch = b.model_copy(
            update={
                "predicates": new_predicates,
                "belief_records": new_brs,
                "rules": new_rules,
                "constraints": new_constraints,
            }
        )
        print(
            f"  Unloaded predicate {pred_name}/{arity}: "
            f"{removed} declaration(s), {removed_brs} fact(s), "
            f"{removed_rules} rule(s) removed."
        )

    elif subcmd == "entity" and len(args) >= 2:
        ent_name = args[1]
        new_entities = [e for e in b.entities if e.name != ent_name]
        new_brs = []
        removed_brs = 0
        for r in b.belief_records:
            if any(getattr(a, "ent_name", None) == ent_name for a in r.args):
                removed_brs += 1
            else:
                new_brs.append(r)
        state.branch = b.model_copy(
            update={"entities": new_entities, "belief_records": new_brs}
        )
        removed_ents = len(b.entities) - len(new_entities)
        print(
            f"  Unloaded entity {ent_name!r}: "
            f"{removed_ents} entity declaration(s), {removed_brs} fact(s) removed."
        )

    else:
        print(f"  Unknown unload target: {subcmd!r}")
        print(
            "  Usage: /- unload predicate <name>/<arity> | entity <name> | rules | constraints | all"
        )
        return

    if not state.ephemeral:
        try:
            state.repo.save(state.branch)
        except Exception as exc:
            print(f"  Warning: could not persist branch: {exc}")


def cmd_search(state: "TerminalState", args: list[str]) -> None:
    """/- search <pattern> — substring search across predicates, entities, belief records"""
    if not args:
        print("  Usage: /- search <pattern>")
        return

    pattern = " ".join(args).lower()
    b = state.branch
    found = False

    hits_pred = [p for p in b.predicates if pattern in p.name.lower()]
    if hits_pred:
        found = True
        print(f"  Predicates ({len(hits_pred)}):")
        for p in hits_pred:
            desc = f"  — {p.description}" if p.description else ""
            print(f"    pred {p.name}/{p.arity}{desc}")

    hits_ent = [e for e in b.entities if pattern in e.name.lower()]
    if hits_ent:
        found = True
        print(f"  Entities ({len(hits_ent)}):")
        for e in hits_ent:
            print(f"    {e.name}")

    hits_br = [r for r in b.belief_records if pattern in r.to_doxa().lower()]
    if hits_br:
        found = True
        print(f"  Belief records ({len(hits_br)}):")
        for r in hits_br:
            print(f"    {r.to_doxa()}")

    hits_rules = [r for r in b.rules if pattern in r.to_doxa().lower()]
    if hits_rules:
        found = True
        print(f"  Rules ({len(hits_rules)}):")
        for r in hits_rules:
            print(f"    {r.to_doxa()}")

    if not found:
        print(f"  No matches for {pattern!r}.")


def _auto_fix_kinds(data: dict, _error: object | None = None) -> dict:
    """Backward-compatible wrapper around :func:`repair_branch_json`."""
    return repair_branch_json(data)


def _fix_nested_kinds(obj, parent_context=None):
    """Deprecated compatibility shim; nested fixing lives in json_repair."""
    _ = parent_context
    repaired = repair_branch_json(obj) if isinstance(obj, dict) else None
    if repaired is not None and isinstance(obj, dict):
        obj.clear()
        obj.update(repaired)


# ── file loading helper (also used by load command) ──────────────────────────


def _load_file(path: Path, fix_missing_kinds: bool = False) -> "Branch":
    return load_branch_file(path, fix_missing_kinds=fix_missing_kinds)


# ── dispatch table ────────────────────────────────────────────────────────────


def cmd_exit(state: "TerminalState", args: list[str]) -> None:
    """/- exit — exit the terminal"""
    print("  Goodbye.")
    import sys

    sys.exit(0)


COMMANDS: dict[str, callable] = {
    "dump": cmd_dump,
    "info": cmd_info,
    "schema": cmd_schema,
    "load": cmd_load,
    "unload": cmd_unload,
    "search": cmd_search,
    "exit": cmd_exit,
    "quit": cmd_exit,
}

HELP_TEXT = """\
Built-in /- commands:

  /- dump [--ax|--json] [--file <path>]
          [--no-predicates] [--no-belief-records] [--no-rules] [--no-constraints]
      Dump the current branch.

  /- info
      Show session info: engine, memory backend, counts.

  /- schema [--branch] [--query] [--branch.<sub.path>] [--file <path>]
      Print the LLM-friendly JSON schema for Branch and/or Query.

  /- load <file> [<file2> ...] [--fix]
      Load and merge one or more .doxa or .json files into the current branch.
      Use --fix to auto-fix missing 'kind' fields in JSON files.

  /- unload predicate <name>/<arity>
  /- unload entity <name>
  /- unload rules
  /- unload constraints
  /- unload all
      Remove items from the current branch.

  /- search <pattern>
      Substring search over predicates, entities, belief records, and rules.

  /- exit | /- quit
      Exit the terminal.

  /- help
      Show this help text.

Regular input is interpreted as Doxa statements (add to branch) or queries (?- ...).
Lines starting with % are treated as comments and ignored.
"""


def dispatch(state: "TerminalState", raw: str) -> None:
    """Parse and dispatch a /- command line."""
    # Strip leading /-
    body = raw.lstrip("/- ").strip()
    if not body:
        print(HELP_TEXT)
        return

    try:
        # Use posix=False on Windows to preserve backslashes in paths
        parts = shlex.split(body, posix=(sys.platform != "win32"))
    except ValueError as exc:
        print(f"  Parse error: {exc}")
        return

    if not parts:
        print(HELP_TEXT)
        return

    cmd_name = parts[0].lower()
    # posix=False (Windows) leaves surrounding quotes in tokens — strip them
    cmd_args = [
        a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in ('"', "'") else a
        for a in parts[1:]
    ]

    if cmd_name == "help":
        print(HELP_TEXT)
        return

    handler = COMMANDS.get(cmd_name)
    if handler is None:
        print(
            f"  Unknown command: {cmd_name!r}. Type '/- help' for a list of commands."
        )
        return

    try:
        handler(state, cmd_args)
    except Exception as exc:
        print(f"  Command error: {exc}")
