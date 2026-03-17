import json
import sys

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

from doxa.cli.commands import (
    cmd_dump,
    cmd_info,
    cmd_schema,
    cmd_load,
    cmd_unload,
    cmd_search,
    cmd_exit,
    dispatch,
    _load_file,
    _auto_fix_kinds,
    _branch_to_ax,
    _branch_to_dict,
    _parse_dump_args,
    HELP_TEXT,
)
from doxa.cli.terminal import TerminalState
from doxa.core.branch import Branch
from doxa.core.base_kinds import BaseKind


@pytest.fixture
def mock_state() -> TerminalState:
    branch = Branch.from_ax("""
        pred person/1.
        pred parent/2.
        
        person(alice).
        person(bob).
        parent(alice, bob).
        
        ancestor(X, Y) :- parent(X, Y).
        ancestor(X, Y) :- parent(X, Z), ancestor(Z, Y).
        
        !:- ancestor(X, X).
    """)

    return TerminalState(
        branch=branch,
        repo=MagicMock(),
        engine=MagicMock(),
        memory_kind="memory",
        engine_kind="memory",
    )


def test_parse_dump_args_defaults() -> None:
    fmt, flags = _parse_dump_args([])

    assert fmt == "ax"
    assert flags["predicates"] is True
    assert flags["belief_records"] is True
    assert flags["rules"] is True
    assert flags["constraints"] is True


def test_parse_dump_args_json_format() -> None:
    fmt, flags = _parse_dump_args(["--json"])

    assert fmt == "json"


def test_parse_dump_args_no_predicates() -> None:
    fmt, flags = _parse_dump_args(["--no-predicates"])

    assert flags["predicates"] is False
    assert flags["belief_records"] is True


def test_parse_dump_args_multiple_flags() -> None:
    fmt, flags = _parse_dump_args(["--json", "--no-predicates", "--no-rules"])

    assert fmt == "json"
    assert flags["predicates"] is False
    assert flags["rules"] is False
    assert flags["belief_records"] is True
    assert flags["constraints"] is True


def test_branch_to_ax(mock_state: TerminalState) -> None:
    result = _branch_to_ax(mock_state)

    assert "person(alice)." in result
    assert "person(bob)." in result
    assert "parent(alice, bob)." in result
    assert "ancestor(X, Y) :- parent(X, Y)." in result
    assert "!:- ancestor(X, X)." in result


def test_branch_to_ax_no_predicates(mock_state: TerminalState) -> None:
    result = _branch_to_ax(mock_state, predicates=False)

    assert "pred person/1" not in result
    assert "person(alice)." in result


def test_branch_to_ax_no_belief_records(mock_state: TerminalState) -> None:
    result = _branch_to_ax(mock_state, belief_records=False)

    assert "person(alice)." not in result
    assert "ancestor(X, Y) :- parent(X, Y)." in result


def test_branch_to_dict(mock_state: TerminalState) -> None:
    result = _branch_to_dict(mock_state)

    assert "predicates" in result
    assert "belief_records" in result
    assert "rules" in result
    assert "constraints" in result

    assert len(result["predicates"]) == 3
    assert len(result["belief_records"]) == 3
    assert len(result["rules"]) == 2
    assert len(result["constraints"]) == 1


def test_cmd_dump_ax_format(mock_state: TerminalState, capsys) -> None:
    cmd_dump(mock_state, ["--ax"])

    captured = capsys.readouterr()
    assert "person(alice)." in captured.out
    assert "ancestor(X, Y) :- parent(X, Y)." in captured.out


def test_cmd_dump_json_format(mock_state: TerminalState, capsys) -> None:
    cmd_dump(mock_state, ["--json"])

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "predicates" in data
    assert "belief_records" in data
    assert "rules" in data
    assert "constraints" in data


def test_cmd_dump_to_file(mock_state: TerminalState, tmp_path: Path, capsys) -> None:
    output_file = tmp_path / "output.doxa"
    cmd_dump(mock_state, ["--file", str(output_file)])

    assert output_file.exists()
    content = output_file.read_text()
    assert "person(alice)." in content

    captured = capsys.readouterr()
    assert "Dumped to" in captured.out


def test_cmd_info(mock_state: TerminalState, capsys) -> None:
    cmd_info(mock_state, [])

    captured = capsys.readouterr()
    assert "Doxa version" in captured.out
    assert "Memory backend : memory" in captured.out
    assert "Query engine   : memory" in captured.out
    assert "Predicates     : 3" in captured.out
    assert "Belief records : 3" in captured.out
    assert "Rules          : 2" in captured.out
    assert "Constraints    : 1" in captured.out


def test_cmd_schema_default(mock_state: TerminalState, capsys) -> None:
    cmd_schema(mock_state, [])

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "branch" in data
    assert "query" in data


def test_cmd_schema_branch_only(mock_state: TerminalState, capsys) -> None:
    cmd_schema(mock_state, ["--branch"])

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "branch" in data
    assert "query" not in data


def test_cmd_schema_query_only(mock_state: TerminalState, capsys) -> None:
    cmd_schema(mock_state, ["--query"])

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert "query" in data
    assert "branch" not in data


def test_cmd_schema_to_file(mock_state: TerminalState, tmp_path: Path, capsys) -> None:
    output_file = tmp_path / "schema.json"
    cmd_schema(mock_state, ["--file", str(output_file)])

    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert "branch" in data
    assert "query" in data

    captured = capsys.readouterr()
    assert "Schema written to" in captured.out


def test_load_file_ax_format(tmp_path: Path) -> None:
    ax_file = tmp_path / "test.doxa"
    ax_file.write_text("person(alice). person(bob).")

    branch = _load_file(ax_file)

    assert len(branch.belief_records) == 2


def test_load_file_json_format(tmp_path: Path) -> None:
    json_file = tmp_path / "test.json"
    branch_data = Branch.from_ax("person(alice).")
    json_file.write_text(branch_data.model_dump_json())

    branch = _load_file(json_file)

    assert len(branch.belief_records) == 1


def test_load_file_with_encoding_fallback(tmp_path: Path) -> None:
    test_file = tmp_path / "test.doxa"
    test_file.write_bytes("person(alice).".encode("latin-1"))

    branch = _load_file(test_file)

    assert len(branch.belief_records) == 1


def test_auto_fix_kinds() -> None:
    data = {
        "predicates": [{"name": "person", "arity": 1}],
        "belief_records": [{"pred_name": "person", "pred_arity": 1, "args": []}],
        "rules": [],
        "constraints": [],
    }

    error = MagicMock(spec=ValidationError)
    fixed = _auto_fix_kinds(data, error)

    assert fixed["kind"] == BaseKind.branch
    assert fixed["predicates"][0]["kind"] == BaseKind.predicate
    assert fixed["belief_records"][0]["kind"] == BaseKind.belief_record


def test_auto_fix_kinds_adds_missing_branch_fields() -> None:
    data = {
        "predicates": [{"name": "person", "arity": 1}],
    }

    error = MagicMock(spec=ValidationError)
    fixed = _auto_fix_kinds(data, error)

    assert "name" in fixed
    assert fixed["name"] == "imported"
    assert "ephemeral" in fixed
    assert fixed["ephemeral"] is False
    assert "created_at" in fixed
    assert "belief_records" in fixed
    assert fixed["belief_records"] == []
    assert "rules" in fixed
    assert fixed["rules"] == []
    assert "constraints" in fixed
    assert fixed["constraints"] == []
    assert "entities" in fixed
    assert fixed["entities"] == []


def test_auto_fix_kinds_preserves_existing_fields() -> None:
    data = {
        "name": "custom_name",
        "ephemeral": True,
        "predicates": [{"name": "person", "arity": 1}],
        "belief_records": [],
        "rules": [],
        "constraints": [],
        "entities": [],
    }

    error = MagicMock(spec=ValidationError)
    fixed = _auto_fix_kinds(data, error)

    assert fixed["name"] == "custom_name"
    assert fixed["ephemeral"] is True


def test_auto_fix_kinds_adds_kinds_to_all_arrays() -> None:
    data = {
        "predicates": [{"name": "person", "arity": 1}],
        "belief_records": [{"pred_name": "person", "pred_arity": 1, "args": []}],
        "rules": [
            {
                "head_pred_name": "test",
                "head_pred_arity": 1,
                "head_args": [],
                "goals": [],
            }
        ],
        "constraints": [{"goals": []}],
        "entities": [{"name": "alice"}],
    }

    error = MagicMock(spec=ValidationError)
    fixed = _auto_fix_kinds(data, error)

    assert fixed["predicates"][0]["kind"] == BaseKind.predicate
    assert fixed["belief_records"][0]["kind"] == BaseKind.belief_record
    assert fixed["rules"][0]["kind"] == BaseKind.rule
    assert fixed["constraints"][0]["kind"] == BaseKind.constraint
    assert fixed["entities"][0]["kind"] == BaseKind.entity


def test_load_file_with_fix_mode(tmp_path: Path) -> None:
    json_file = tmp_path / "test.json"
    data = {
        "predicates": [{"name": "person", "arity": 1}],
        "belief_records": [],
        "rules": [],
        "constraints": [],
        "entities": [],
        "name": "test",
        "ephemeral": False,
    }
    json_file.write_text(json.dumps(data))

    branch = _load_file(json_file, fix_missing_kinds=True)

    assert branch.kind == BaseKind.branch
    assert len(branch.predicates) == 1


def test_cmd_load_single_file(
    mock_state: TerminalState, tmp_path: Path, capsys
) -> None:
    ax_file = tmp_path / "test.doxa"
    ax_file.write_text("person(charlie).")

    initial_count = len(mock_state.branch.belief_records)
    cmd_load(mock_state, [str(ax_file)])

    assert len(mock_state.branch.belief_records) > initial_count

    captured = capsys.readouterr()
    assert "Loaded" in captured.out


def test_cmd_load_multiple_files(
    mock_state: TerminalState, tmp_path: Path, capsys
) -> None:
    file1 = tmp_path / "test1.doxa"
    file2 = tmp_path / "test2.doxa"
    file1.write_text("person(charlie).")
    file2.write_text("person(dave).")

    cmd_load(mock_state, [str(file1), str(file2)])

    captured = capsys.readouterr()
    assert captured.out.count("Loaded") == 2


def test_cmd_load_nonexistent_file(mock_state: TerminalState, capsys) -> None:
    cmd_load(mock_state, ["nonexistent.doxa"])

    captured = capsys.readouterr()
    assert "File not found" in captured.out


def test_cmd_load_with_fix_flag(
    mock_state: TerminalState, tmp_path: Path, capsys
) -> None:
    json_file = tmp_path / "test.json"
    data = {
        "predicates": [],
        "belief_records": [],
        "rules": [],
        "constraints": [],
        "entities": [],
        "name": "test",
        "ephemeral": False,
    }
    json_file.write_text(json.dumps(data))

    cmd_load(mock_state, [str(json_file), "--fix"])

    captured = capsys.readouterr()
    assert "Loaded" in captured.out


def test_cmd_load_no_args(mock_state: TerminalState, capsys) -> None:
    cmd_load(mock_state, [])

    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_cmd_unload_all(mock_state: TerminalState, capsys) -> None:
    assert len(mock_state.branch.belief_records) > 0

    cmd_unload(mock_state, ["all"])

    assert len(mock_state.branch.belief_records) == 0
    assert len(mock_state.branch.rules) == 0
    assert len(mock_state.branch.constraints) == 0

    captured = capsys.readouterr()
    assert "reset to empty" in captured.out


def test_cmd_unload_rules(mock_state: TerminalState, capsys) -> None:
    initial_rules = len(mock_state.branch.rules)
    assert initial_rules > 0

    cmd_unload(mock_state, ["rules"])

    assert len(mock_state.branch.rules) == 0
    assert len(mock_state.branch.belief_records) > 0

    captured = capsys.readouterr()
    assert f"Removed {initial_rules} rule(s)" in captured.out


def test_cmd_unload_constraints(mock_state: TerminalState, capsys) -> None:
    initial_constraints = len(mock_state.branch.constraints)
    assert initial_constraints > 0

    cmd_unload(mock_state, ["constraints"])

    assert len(mock_state.branch.constraints) == 0

    captured = capsys.readouterr()
    assert f"Removed {initial_constraints} constraint(s)" in captured.out


def test_cmd_unload_predicate(mock_state: TerminalState, capsys) -> None:
    cmd_unload(mock_state, ["predicate", "person/1"])

    captured = capsys.readouterr()
    assert "Unloaded predicate person/1" in captured.out


def test_cmd_unload_predicate_invalid_format(mock_state: TerminalState, capsys) -> None:
    cmd_unload(mock_state, ["predicate", "person"])

    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_cmd_unload_no_args(mock_state: TerminalState, capsys) -> None:
    cmd_unload(mock_state, [])

    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_cmd_search_finds_predicates(mock_state: TerminalState, capsys) -> None:
    cmd_search(mock_state, ["person"])

    captured = capsys.readouterr()
    assert "Predicates" in captured.out
    assert "person/1" in captured.out


def test_cmd_search_finds_belief_records(mock_state: TerminalState, capsys) -> None:
    cmd_search(mock_state, ["alice"])

    captured = capsys.readouterr()
    assert "Belief records" in captured.out
    assert "alice" in captured.out


def test_cmd_search_finds_rules(mock_state: TerminalState, capsys) -> None:
    cmd_search(mock_state, ["ancestor"])

    captured = capsys.readouterr()
    assert "Rules" in captured.out
    assert "ancestor" in captured.out


def test_cmd_search_no_matches(mock_state: TerminalState, capsys) -> None:
    cmd_search(mock_state, ["nonexistent"])

    captured = capsys.readouterr()
    assert "No matches" in captured.out


def test_cmd_search_no_args(mock_state: TerminalState, capsys) -> None:
    cmd_search(mock_state, [])

    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_cmd_exit(mock_state: TerminalState, capsys) -> None:
    with pytest.raises(SystemExit):
        cmd_exit(mock_state, [])

    captured = capsys.readouterr()
    assert "Goodbye" in captured.out


def test_dispatch_help(mock_state: TerminalState, capsys) -> None:
    dispatch(mock_state, "/- help")

    captured = capsys.readouterr()
    assert "Built-in /- commands:" in captured.out
    assert "/- dump" in captured.out
    assert "/- load" in captured.out


def test_dispatch_empty_command(mock_state: TerminalState, capsys) -> None:
    dispatch(mock_state, "/-")

    captured = capsys.readouterr()
    assert "Built-in /- commands:" in captured.out


def test_dispatch_unknown_command(mock_state: TerminalState, capsys) -> None:
    dispatch(mock_state, "/- unknown")

    captured = capsys.readouterr()
    assert "Unknown command" in captured.out


def test_dispatch_info_command(mock_state: TerminalState, capsys) -> None:
    dispatch(mock_state, "/- info")

    captured = capsys.readouterr()
    assert "Doxa version" in captured.out


def test_dispatch_with_quoted_args(
    mock_state: TerminalState, tmp_path: Path, capsys
) -> None:
    test_file = tmp_path / "test file.doxa"
    test_file.write_text("person(alice).")

    dispatch(mock_state, f'/- load "{test_file}"')

    captured = capsys.readouterr()
    assert "Loaded" in captured.out


def test_dispatch_parse_error(mock_state: TerminalState, capsys) -> None:
    dispatch(mock_state, '/- load "unterminated')

    captured = capsys.readouterr()
    assert "Parse error" in captured.out


def test_help_text_contains_all_commands() -> None:
    assert "/- dump" in HELP_TEXT
    assert "/- info" in HELP_TEXT
    assert "/- schema" in HELP_TEXT
    assert "/- load" in HELP_TEXT
    assert "/- unload" in HELP_TEXT
    assert "/- search" in HELP_TEXT
    assert "/- exit" in HELP_TEXT
    assert "/- help" in HELP_TEXT


def test_help_text_mentions_fix_flag() -> None:
    assert "--fix" in HELP_TEXT


def test_help_text_mentions_comments() -> None:
    assert "%" in HELP_TEXT


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path behavior")
@patch("sys.platform", "win32")
def test_dispatch_windows_path_with_backslashes(
    mock_state: TerminalState, tmp_path: Path, capsys
) -> None:
    test_file = tmp_path / "test.doxa"
    test_file.write_text("person(alice).")

    # Use Windows-style path with backslashes
    windows_path = str(test_file).replace("/", "\\")
    dispatch(mock_state, f"/- load {windows_path}")

    captured = capsys.readouterr()
    assert "Loaded" in captured.out


@patch("sys.platform", "linux")
def test_dispatch_unix_path_with_forward_slashes(
    mock_state: TerminalState, tmp_path: Path, capsys
) -> None:
    test_file = tmp_path / "test.doxa"
    test_file.write_text("person(alice).")

    # Use forward slashes so posix=True shlex parsing doesn't mangle the path
    unix_path = str(test_file).replace("\\", "/")
    dispatch(mock_state, f"/- load {unix_path}")

    captured = capsys.readouterr()
    assert "Loaded" in captured.out


def test_load_file_minimal_json_with_fix(tmp_path: Path) -> None:
    """Test that --fix can load a JSON file with only predicates."""
    json_file = tmp_path / "minimal.json"
    data = {
        "predicates": [{"name": "person", "arity": 1}],
    }
    json_file.write_text(json.dumps(data))

    branch = _load_file(json_file, fix_missing_kinds=True)

    assert branch.kind == BaseKind.branch
    assert branch.name == "imported"
    assert branch.ephemeral is False
    assert len(branch.predicates) == 1
    assert len(branch.belief_records) == 0
    assert len(branch.rules) == 0
    assert len(branch.constraints) == 0


def test_cmd_load_minimal_json_with_fix_flag(
    mock_state: TerminalState, tmp_path: Path, capsys
) -> None:
    """Test loading a minimal JSON file using the --fix flag via cmd_load."""
    json_file = tmp_path / "minimal.json"
    data = {
        "predicates": [{"name": "test_pred", "arity": 2}],
    }
    json_file.write_text(json.dumps(data))

    initial_pred_count = len(mock_state.branch.predicates)
    cmd_load(mock_state, [str(json_file), "--fix"])

    assert len(mock_state.branch.predicates) > initial_pred_count

    captured = capsys.readouterr()
    assert "Loaded" in captured.out


def test_load_file_without_fix_flag_fails_on_incomplete_json(tmp_path: Path) -> None:
    """Test that loading incomplete JSON without --fix raises an error."""
    json_file = tmp_path / "incomplete.json"
    data = {
        "predicates": [{"name": "person", "arity": 1}],
    }
    json_file.write_text(json.dumps(data))

    with pytest.raises(Exception):
        _load_file(json_file, fix_missing_kinds=False)
