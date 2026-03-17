from unittest.mock import MagicMock, patch

from doxa.cli.terminal import (
    run_terminal,
    TerminalState,
    _make_empty_branch,
    _collect_statement,
    _handle_statement,
    _run_query,
    _add_to_branch,
)
from doxa.core.branch import Branch
from doxa.core.base_kinds import BaseKind


def test_make_empty_branch() -> None:
    branch = _make_empty_branch()

    assert branch.kind == BaseKind.branch
    assert branch.name == "main"
    assert branch.ephemeral is False
    assert branch.created_at is not None
    assert len(branch.belief_records) == 0
    assert len(branch.rules) == 0
    assert len(branch.constraints) == 0
    assert len(branch.predicates) == 0
    assert len(branch.entities) == 0


def test_collect_statement_already_complete() -> None:
    result = _collect_statement("person(alice).")

    assert result == "person(alice)."


@patch("builtins.input", side_effect=[".", KeyboardInterrupt])
def test_collect_statement_query_multiline(mock_input) -> None:
    result = _collect_statement("?- person(X)")

    assert "?- person(X)" in result
    assert "." in result


@patch(
    "builtins.input",
    side_effect=["   supplies(X, Y),", "   risk_score(Y, R),", "   geq(R, 48)."],
)
def test_collect_statement_query_with_multiple_lines_and_commas(mock_input) -> None:
    result = _collect_statement("?- type(X, supplier),")

    assert "?- type(X, supplier)," in result
    assert "supplies(X, Y)," in result
    assert "risk_score(Y, R)," in result
    assert "geq(R, 48)." in result


@patch("builtins.input", side_effect=[".", KeyboardInterrupt])
def test_collect_statement_multiline(mock_input) -> None:
    result = _collect_statement("person(alice)")

    assert "person(alice)" in result
    assert "." in result


@patch("builtins.input", side_effect=KeyboardInterrupt)
def test_collect_statement_interrupted(mock_input) -> None:
    result = _collect_statement("person(alice)")

    assert result == "person(alice)"


def test_add_to_branch() -> None:
    state = TerminalState(
        branch=_make_empty_branch(),
        repo=MagicMock(),
        engine=MagicMock(),
        memory_kind="memory",
        engine_kind="memory",
    )

    _add_to_branch(state, "person(alice)")

    assert len(state.branch.belief_records) == 1


def test_add_to_branch_with_dot() -> None:
    state = TerminalState(
        branch=_make_empty_branch(),
        repo=MagicMock(),
        engine=MagicMock(),
        memory_kind="memory",
        engine_kind="memory",
    )

    _add_to_branch(state, "person(alice).")

    assert len(state.branch.belief_records) == 1


def test_add_to_branch_invalid_syntax(capsys) -> None:
    state = TerminalState(
        branch=_make_empty_branch(),
        repo=MagicMock(),
        engine=MagicMock(),
        memory_kind="memory",
        engine_kind="memory",
    )

    _add_to_branch(state, "invalid syntax (((")

    captured = capsys.readouterr()
    assert "Parse error" in captured.out


def test_add_to_branch_multiple_statements(capsys) -> None:
    state = TerminalState(
        branch=_make_empty_branch(),
        repo=MagicMock(),
        engine=MagicMock(),
        memory_kind="memory",
        engine_kind="memory",
    )

    _add_to_branch(state, "person(alice). person(bob).")

    assert len(state.branch.belief_records) == 2

    captured = capsys.readouterr()
    assert "Added:" in captured.out


def test_run_query(capsys) -> None:
    branch = Branch.from_ax("person(alice). person(bob).")
    mock_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.bindings = []
    mock_engine.evaluate.return_value = mock_result

    state = TerminalState(
        branch=branch,
        repo=MagicMock(),
        engine=mock_engine,
        memory_kind="memory",
        engine_kind="memory",
    )

    _run_query(state, "?- person(X)")

    mock_engine.evaluate.assert_called_once()


def test_run_query_with_results(capsys) -> None:
    branch = Branch.from_ax("person(alice). person(bob).")
    mock_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_binding = MagicMock()
    mock_binding.values = {"X": "alice"}
    mock_result.bindings = [mock_binding]
    mock_engine.evaluate.return_value = mock_result

    state = TerminalState(
        branch=branch,
        repo=MagicMock(),
        engine=mock_engine,
        memory_kind="memory",
        engine_kind="memory",
    )

    _run_query(state, "?- person(X)")

    captured = capsys.readouterr()
    assert "1:" in captured.out


def test_run_query_no_results(capsys) -> None:
    branch = Branch.from_ax("person(alice).")
    mock_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.bindings = []
    mock_engine.evaluate.return_value = mock_result

    state = TerminalState(
        branch=branch,
        repo=MagicMock(),
        engine=mock_engine,
        memory_kind="memory",
        engine_kind="memory",
    )

    _run_query(state, "?- person(charlie)")

    captured = capsys.readouterr()
    assert "No results" in captured.out


def test_run_query_parse_error(capsys) -> None:
    state = TerminalState(
        branch=_make_empty_branch(),
        repo=MagicMock(),
        engine=MagicMock(),
        memory_kind="memory",
        engine_kind="memory",
    )

    _run_query(state, "?- invalid (((")

    captured = capsys.readouterr()
    assert "Parse error" in captured.out


def test_run_query_engine_error(capsys) -> None:
    branch = Branch.from_ax("person(alice).")
    mock_engine = MagicMock()
    mock_engine.evaluate.side_effect = Exception("Engine error")

    state = TerminalState(
        branch=branch,
        repo=MagicMock(),
        engine=mock_engine,
        memory_kind="memory",
        engine_kind="memory",
    )

    _run_query(state, "?- person(X)")

    captured = capsys.readouterr()
    assert "Query error" in captured.out


def test_run_query_not_implemented(capsys) -> None:
    branch = Branch.from_ax("person(alice).")
    mock_engine = MagicMock()
    mock_engine.evaluate.side_effect = NotImplementedError()

    state = TerminalState(
        branch=branch,
        repo=MagicMock(),
        engine=mock_engine,
        memory_kind="memory",
        engine_kind="memory",
    )

    _run_query(state, "?- person(X)")

    captured = capsys.readouterr()
    assert "not implemented" in captured.out


def test_handle_statement_query() -> None:
    branch = Branch.from_ax("person(alice).")
    mock_engine = MagicMock()
    mock_result = MagicMock()
    mock_result.success = False
    mock_engine.evaluate.return_value = mock_result

    state = TerminalState(
        branch=branch,
        repo=MagicMock(),
        engine=mock_engine,
        memory_kind="memory",
        engine_kind="memory",
    )

    _handle_statement(state, "?- person(X)")

    mock_engine.evaluate.assert_called_once()


def test_handle_statement_belief_record() -> None:
    state = TerminalState(
        branch=_make_empty_branch(),
        repo=MagicMock(),
        engine=MagicMock(),
        memory_kind="memory",
        engine_kind="memory",
    )

    initial_count = len(state.branch.belief_records)
    _handle_statement(state, "person(alice).")

    assert len(state.branch.belief_records) == initial_count + 1


@patch("builtins.input", side_effect=["person(alice).", "/- exit", EOFError])
@patch("sys.exit")
def test_run_terminal_basic_flow(mock_exit, mock_input, capsys) -> None:
    mock_repo = MagicMock()
    mock_engine = MagicMock()

    run_terminal(
        memory_kind="memory",
        engine_kind="memory",
        repo=mock_repo,
        engine=mock_engine,
        preload_files=[],
        ephemeral=False,
    )

    captured = capsys.readouterr()
    assert "Doxa Terminal" in captured.out


@patch("builtins.input", side_effect=["", "   ", "/- exit", EOFError])
@patch("sys.exit")
def test_run_terminal_ignores_empty_lines(mock_exit, mock_input, capsys) -> None:
    mock_repo = MagicMock()
    mock_engine = MagicMock()

    run_terminal(
        memory_kind="memory",
        engine_kind="memory",
        repo=mock_repo,
        engine=mock_engine,
        preload_files=[],
        ephemeral=False,
    )

    captured = capsys.readouterr()
    assert "Doxa Terminal" in captured.out


@patch("builtins.input", side_effect=["% this is a comment", "/- exit", EOFError])
@patch("sys.exit")
def test_run_terminal_ignores_comments(mock_exit, mock_input, capsys) -> None:
    mock_repo = MagicMock()
    mock_engine = MagicMock()

    run_terminal(
        memory_kind="memory",
        engine_kind="memory",
        repo=mock_repo,
        engine=mock_engine,
        preload_files=[],
        ephemeral=False,
    )

    captured = capsys.readouterr()
    assert "Doxa Terminal" in captured.out


@patch("builtins.input", side_effect=KeyboardInterrupt)
def test_run_terminal_keyboard_interrupt(mock_input, capsys) -> None:
    mock_repo = MagicMock()
    mock_engine = MagicMock()

    with patch("builtins.input", side_effect=[KeyboardInterrupt, EOFError]):
        run_terminal(
            memory_kind="memory",
            engine_kind="memory",
            repo=mock_repo,
            engine=mock_engine,
            preload_files=[],
            ephemeral=False,
        )

    captured = capsys.readouterr()
    assert "Goodbye" in captured.out


@patch("builtins.input", side_effect=EOFError)
def test_run_terminal_eof(mock_input, capsys) -> None:
    mock_repo = MagicMock()
    mock_engine = MagicMock()

    run_terminal(
        memory_kind="memory",
        engine_kind="memory",
        repo=mock_repo,
        engine=mock_engine,
        preload_files=[],
        ephemeral=False,
    )

    captured = capsys.readouterr()
    assert "Goodbye" in captured.out


@patch("builtins.input", side_effect=["/- info", "/- exit", EOFError])
@patch("sys.exit")
def test_run_terminal_dispatches_commands(mock_exit, mock_input, capsys) -> None:
    mock_repo = MagicMock()
    mock_engine = MagicMock()

    run_terminal(
        memory_kind="memory",
        engine_kind="memory",
        repo=mock_repo,
        engine=mock_engine,
        preload_files=[],
        ephemeral=False,
    )

    captured = capsys.readouterr()
    assert "Doxa version" in captured.out


def test_run_terminal_preloads_files(tmp_path, capsys) -> None:
    test_file = tmp_path / "test.doxa"
    test_file.write_text("person(alice).")

    mock_repo = MagicMock()
    mock_engine = MagicMock()

    with patch("builtins.input", side_effect=EOFError):
        run_terminal(
            memory_kind="memory",
            engine_kind="memory",
            repo=mock_repo,
            engine=mock_engine,
            preload_files=[test_file],
            ephemeral=False,
        )

    captured = capsys.readouterr()
    assert "Loaded" in captured.out
    assert str(test_file) in captured.out


def test_run_terminal_preload_error(tmp_path, capsys) -> None:
    test_file = tmp_path / "invalid.doxa"
    test_file.write_text("invalid syntax (((")

    mock_repo = MagicMock()
    mock_engine = MagicMock()

    with patch("builtins.input", side_effect=EOFError):
        run_terminal(
            memory_kind="memory",
            engine_kind="memory",
            repo=mock_repo,
            engine=mock_engine,
            preload_files=[test_file],
            ephemeral=False,
        )

    captured = capsys.readouterr()
    assert "Warning" in captured.err or "could not load" in captured.err


@patch("sys.platform", "win32")
@patch("builtins.input", side_effect=EOFError)
def test_run_terminal_configures_utf8_on_windows(mock_input, capsys) -> None:
    mock_repo = MagicMock()
    mock_engine = MagicMock()

    with patch("sys.stdout") as mock_stdout:
        mock_stdout.reconfigure = MagicMock()
        run_terminal(
            memory_kind="memory",
            engine_kind="memory",
            repo=mock_repo,
            engine=mock_engine,
            preload_files=[],
            ephemeral=False,
        )


def test_terminal_state_creation() -> None:
    branch = _make_empty_branch()
    repo = MagicMock()
    engine = MagicMock()

    state = TerminalState(
        branch=branch,
        repo=repo,
        engine=engine,
        memory_kind="memory",
        engine_kind="memory",
    )

    assert state.branch == branch
    assert state.repo == repo
    assert state.engine == engine
    assert state.memory_kind == "memory"
    assert state.engine_kind == "memory"
