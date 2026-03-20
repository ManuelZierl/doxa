"""Doxa CLI entry point.

Usage
-----
  doxa                                  Start terminal (in-memory backend)
  doxa --tmp                            Alias for in-memory (explicit ephemeral flag)
  doxa --memory postgres                Use PostgreSQL backend
  doxa --engine postgres                Use PostgreSQL query engine
  doxa --memory postgres --engine postgres
  doxa --file knowledge.doxa            Pre-load a file before starting
  doxa --file a.doxa --file b.json      Pre-load and merge multiple files
  doxa extract-prompt <resource>        Generate extraction prompt
  doxa query-prompt <question>          Generate query planner prompt
  doxa --version                        Print version and exit
  doxa --help                           Print this help and exit
"""

from __future__ import annotations

from pathlib import Path

import click

from doxa.__version__ import __version__
from doxa.cli.compat import ENGINE_KINDS, MEMORY_KINDS, check_compat, default_engine_for
from doxa.cli.merge import merge_command
from doxa.cli.prompt import extract_prompt_command, query_prompt_command


def _make_repo(memory_kind: str):
    if memory_kind == "memory":
        from doxa.persistence.memory import InMemoryBranchRepository

        return InMemoryBranchRepository()
    elif memory_kind == "postgres":
        import os

        from doxa.persistence.postgres import PostgresBranchRepository

        db_url = os.environ.get("DOXA_POSTGRES_URL", "postgresql://localhost/doxa")
        return PostgresBranchRepository(db_url)
    else:
        raise click.ClickException(f"Unknown memory backend: {memory_kind!r}")


def _make_engine(engine_kind: str):
    if engine_kind == "memory":
        from doxa.query.memory import InMemoryQueryEngine

        return InMemoryQueryEngine()
    elif engine_kind == "postgres":
        import os

        from doxa.query.postgres import PostgresQueryEngine

        db_url = os.environ.get("DOXA_POSTGRES_URL", "postgresql://localhost/doxa")
        return PostgresQueryEngine(db_url)
    else:
        raise click.ClickException(f"Unknown query engine: {engine_kind!r}")


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, "-V", "--version", prog_name="doxa")
@click.option(
    "--tmp",
    is_flag=True,
    default=False,
    help="Start an ephemeral in-memory session (overrides --memory).",
)
@click.option(
    "--memory",
    "memory_kind",
    default=None,
    type=click.Choice(MEMORY_KINDS, case_sensitive=False),
    metavar="BACKEND",
    help=f"Persistence backend [{', '.join(MEMORY_KINDS)}]. Default: memory.",
    show_default=False,
)
@click.option(
    "--engine",
    "engine_kind",
    default=None,
    type=click.Choice(ENGINE_KINDS, case_sensitive=False),
    metavar="ENGINE",
    help=f"Query engine [{', '.join(ENGINE_KINDS)}]. Default: matches --memory.",
    show_default=False,
)
@click.option(
    "--file",
    "-f",
    "files",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    metavar="FILE",
    help="Pre-load a .doxa or .json file. May be repeated to merge multiple files.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    tmp: bool,
    memory_kind: str | None,
    engine_kind: str | None,
    files: tuple[Path, ...],
) -> None:
    """Doxa — interactive knowledge-base terminal and utilities."""

    # If a subcommand was invoked, don't run the terminal
    if ctx.invoked_subcommand is not None:
        return

    # --tmp forces in-memory regardless of --memory
    if tmp:
        if memory_kind is not None and memory_kind != "memory":
            raise click.UsageError("--tmp and --memory are mutually exclusive.")
        memory_kind = "memory"

    # Apply defaults
    memory_kind = memory_kind or "memory"
    engine_kind = engine_kind or default_engine_for(memory_kind)

    # Validate compatibility
    try:
        check_compat(memory_kind, engine_kind)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    # Instantiate backends — catch NotImplementedError from placeholder backends
    try:
        repo = _make_repo(memory_kind)
    except NotImplementedError:
        raise click.ClickException(
            f"Memory backend {memory_kind!r} is not yet implemented. "
            "Set DOXA_POSTGRES_URL and ensure the backend is configured."
        )
    except Exception as exc:
        raise click.ClickException(f"Could not initialize memory backend: {exc}")

    try:
        engine = _make_engine(engine_kind)
    except NotImplementedError:
        raise click.ClickException(
            f"Query engine {engine_kind!r} is not yet implemented."
        )
    except Exception as exc:
        raise click.ClickException(f"Could not initialize query engine: {exc}")

    from doxa.cli.terminal import run_terminal

    run_terminal(
        memory_kind=memory_kind,
        engine_kind=engine_kind,
        repo=repo,
        engine=engine,
        preload_files=list(files),
        ephemeral=tmp,
    )


# Add subcommands
cli.add_command(extract_prompt_command, name="extract-prompt")
cli.add_command(query_prompt_command, name="query-prompt")
cli.add_command(merge_command, name="merge")


def main() -> None:
    """Setuptools entry point."""
    cli()


if __name__ == "__main__":
    main()
