from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from doxa.cli.main import _make_engine, _make_repo, cli


def test_cli_default_memory_backend() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, [], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["memory_kind"] == "memory"
        assert call_kwargs["engine_kind"] == "memory"


def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "ax" in result.output.lower() or "version" in result.output.lower()


def test_cli_help_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Doxa" in result.output
    assert "--memory" in result.output
    assert "--engine" in result.output


def test_cli_tmp_flag() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, ["--tmp"], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["memory_kind"] == "memory"
        assert call_kwargs["ephemeral"] is True


def test_cli_tmp_conflicts_with_memory() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--tmp", "--memory", "postgres"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_cli_edb_alias_for_memory() -> None:
    """``--edb`` is an additive synonym for ``--memory`` — wired the same
    way through ``_make_repo``."""
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        with patch("doxa.cli.main._make_repo") as mock_repo:
            with patch("doxa.cli.main._make_engine") as mock_engine:
                mock_repo.return_value = MagicMock()
                mock_engine.return_value = MagicMock()

                result = runner.invoke(cli, ["--edb", "memory"], input="\n")

                assert result.exit_code == 0, result.output
                mock_run.assert_called_once()
                assert mock_run.call_args.kwargs["memory_kind"] == "memory"


def test_cli_idb_alias_for_engine() -> None:
    """``--idb`` is an additive synonym for ``--engine``."""
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        with patch("doxa.cli.main._make_repo") as mock_repo:
            with patch("doxa.cli.main._make_engine") as mock_engine:
                mock_repo.return_value = MagicMock()
                mock_engine.return_value = MagicMock()

                result = runner.invoke(
                    cli, ["--edb", "memory", "--idb", "memory"], input="\n"
                )

                assert result.exit_code == 0, result.output
                mock_run.assert_called_once()
                assert mock_run.call_args.kwargs["engine_kind"] == "memory"


def test_cli_edb_memory_conflict_is_usage_error() -> None:
    """Specifying both ``--memory`` and ``--edb`` with disagreeing values
    is rejected rather than silently picking one."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--memory", "memory", "--edb", "native"], input="\n")
    assert result.exit_code != 0
    assert "disagree" in result.output.lower()


def test_cli_memory_backend_postgres() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        with patch("doxa.cli.main._make_repo") as mock_repo:
            with patch("doxa.cli.main._make_engine") as mock_engine:
                mock_repo.return_value = MagicMock()
                mock_engine.return_value = MagicMock()

                result = runner.invoke(cli, ["--memory", "postgres"], input="\n")

                assert result.exit_code == 0, result.output
                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs["memory_kind"] == "postgres"


def test_cli_engine_backend_postgres() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        with patch("doxa.cli.main._make_repo") as mock_repo:
            with patch("doxa.cli.main._make_engine") as mock_engine:
                mock_repo.return_value = MagicMock()
                mock_engine.return_value = MagicMock()

                result = runner.invoke(
                    cli, ["--memory", "postgres", "--engine", "postgres"], input="\n"
                )

                assert result.exit_code == 0, result.output
                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs["engine_kind"] == "postgres"


def test_cli_incompatible_backends() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--memory", "memory", "--engine", "postgres"])

    assert result.exit_code != 0
    assert "incompatible" in result.output.lower()


def test_cli_preload_single_file(tmp_path: Path) -> None:
    runner = CliRunner()
    test_file = tmp_path / "test.doxa"
    test_file.write_text("person(alice).")

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, ["--file", str(test_file)], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert len(call_kwargs["preload_files"]) == 1
        assert call_kwargs["preload_files"][0] == test_file


def test_cli_preload_multiple_files(tmp_path: Path) -> None:
    runner = CliRunner()
    file1 = tmp_path / "test1.doxa"
    file2 = tmp_path / "test2.doxa"
    file1.write_text("person(alice).")
    file2.write_text("person(bob).")

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(
            cli, ["--file", str(file1), "--file", str(file2)], input="\n"
        )

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert len(call_kwargs["preload_files"]) == 2


def test_cli_preload_nonexistent_file() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--file", "nonexistent.doxa"])

    assert result.exit_code != 0


def test_cli_short_file_flag(tmp_path: Path) -> None:
    runner = CliRunner()
    test_file = tmp_path / "test.doxa"
    test_file.write_text("person(alice).")

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, ["-f", str(test_file)], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert len(call_kwargs["preload_files"]) == 1


def test_make_repo_memory() -> None:
    repo = _make_repo("memory")

    from doxa.persistence.memory import InMemoryBranchRepository

    assert isinstance(repo, InMemoryBranchRepository)


def test_make_repo_postgres() -> None:
    with patch.dict("os.environ", {"DOXA_POSTGRES_URL": "postgresql://localhost/test"}):
        with patch(
            "doxa.persistence.postgres.PostgresBranchRepository"
        ) as mock_postgres:
            mock_postgres.return_value = MagicMock()
            _make_repo("postgres")

            mock_postgres.assert_called_once_with("postgresql://localhost/test")


def test_make_repo_postgres_default_url() -> None:
    with patch.dict("os.environ", {}, clear=True):
        with patch(
            "doxa.persistence.postgres.PostgresBranchRepository"
        ) as mock_postgres:
            mock_postgres.return_value = MagicMock()
            _make_repo("postgres")

            mock_postgres.assert_called_once_with("postgresql://localhost/doxa")


def test_make_repo_unknown() -> None:
    from click import ClickException

    with pytest.raises(ClickException, match="Unknown memory backend"):
        _make_repo("unknown")


def test_make_engine_memory() -> None:
    engine = _make_engine("memory")

    assert engine.__class__.__name__ == "InMemoryQueryEngine"


def test_make_engine_postgres() -> None:
    mock_repo = MagicMock()
    with patch("doxa.query.postgres.PostgresQueryEngine") as mock_postgres:
        mock_postgres.return_value = MagicMock()
        _make_engine("postgres", repo=mock_repo)

        mock_postgres.assert_called_once_with(mock_repo)


def test_make_engine_postgres_no_repo() -> None:
    from click import ClickException

    with pytest.raises(ClickException, match="requires a PostgresBranchRepository"):
        _make_engine("postgres")


def test_make_engine_unknown() -> None:
    from click import ClickException

    with pytest.raises(ClickException, match="Unknown query engine"):
        _make_engine("unknown")


def test_cli_handles_repo_not_implemented() -> None:
    runner = CliRunner()

    with patch("doxa.cli.main._make_repo") as mock_repo:
        mock_repo.side_effect = NotImplementedError()
        result = runner.invoke(cli, [])

        assert result.exit_code != 0
        assert "not yet implemented" in result.output.lower()


def test_cli_handles_engine_not_implemented() -> None:
    runner = CliRunner()

    with patch("doxa.cli.main._make_repo") as mock_repo:
        with patch("doxa.cli.main._make_engine") as mock_engine:
            mock_repo.return_value = MagicMock()
            mock_engine.side_effect = NotImplementedError()
            result = runner.invoke(cli, [])

            assert result.exit_code != 0
            assert "not yet implemented" in result.output.lower()


def test_cli_handles_repo_initialization_error() -> None:
    runner = CliRunner()

    with patch("doxa.cli.main._make_repo") as mock_repo:
        mock_repo.side_effect = Exception("Connection failed")
        result = runner.invoke(cli, [])

        assert result.exit_code != 0
        assert "Could not initialize" in result.output


def test_cli_handles_engine_initialization_error() -> None:
    runner = CliRunner()

    with patch("doxa.cli.main._make_repo") as mock_repo:
        with patch("doxa.cli.main._make_engine") as mock_engine:
            mock_repo.return_value = MagicMock()
            mock_engine.side_effect = Exception("Connection failed")
            result = runner.invoke(cli, [])

            assert result.exit_code != 0
            assert "Could not initialize" in result.output


def test_cli_default_engine_matches_memory() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, ["--memory", "memory"], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["memory_kind"] == "memory"
        assert call_kwargs["engine_kind"] == "memory"


def test_cli_default_engine_matches_postgres() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        with patch("doxa.cli.main._make_repo") as mock_repo:
            with patch("doxa.cli.main._make_engine") as mock_engine:
                mock_repo.return_value = MagicMock()
                mock_engine.return_value = MagicMock()

                result = runner.invoke(cli, ["--memory", "postgres"], input="\n")

                assert result.exit_code == 0, result.output
                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args.kwargs
                assert call_kwargs["memory_kind"] == "postgres"
                assert call_kwargs["engine_kind"] == "postgres"


def test_cli_combined_flags(tmp_path: Path) -> None:
    runner = CliRunner()
    test_file = tmp_path / "test.doxa"
    test_file.write_text("person(alice).")

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, ["--tmp", "--file", str(test_file)], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["memory_kind"] == "memory"
        assert call_kwargs["ephemeral"] is True
        assert len(call_kwargs["preload_files"]) == 1


def test_cli_case_insensitive_backends() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, ["--memory", "MEMORY"], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()


def test_cli_ephemeral_false_by_default() -> None:
    runner = CliRunner()

    with patch("doxa.cli.terminal.run_terminal") as mock_run:
        result = runner.invoke(cli, [], input="\n")

        assert result.exit_code == 0, result.output
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["ephemeral"] is False
