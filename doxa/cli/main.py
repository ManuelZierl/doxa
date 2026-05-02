"""Doxa CLI entry point.

Usage
-----
  doxa                                  Start terminal (in-memory backend)
  doxa --tmp                            Alias for in-memory (explicit ephemeral flag)
  doxa --memory native                  Use native Rust backend (persists to .doxa_native/)
  doxa --memory postgres                Use PostgreSQL backend
  doxa --engine postgres                Use PostgreSQL query engine
  doxa --memory postgres --engine postgres
  doxa --edb native --idb native        Same as --memory native (new, EDB/IDB-explicit)
  doxa --file knowledge.doxa            Pre-load a file before starting
  doxa --file a.doxa --file b.json      Pre-load and merge multiple files
  doxa extract-prompt <resource>        Generate extraction prompt
  doxa query-prompt <question>          Generate query planner prompt
  doxa --version                        Print version and exit
  doxa --help                           Print this help and exit

Flag aliases
------------
``--edb`` and ``--idb`` are additive synonyms for ``--memory`` and
``--engine`` respectively.  They reflect Doxa's architecture more
honestly (the "memory" in ``--memory`` is really the Extensional DB; the
"engine" in ``--engine`` is really the Intensional-DB materialiser).

The existing ``--memory`` / ``--engine`` flags remain supported for
backwards compatibility.  See ``doxa/docs/adr/0001-edb-source-of-truth.md``
for the rationale.
"""

from __future__ import annotations

from pathlib import Path

import click

from doxa.__version__ import __version__
from doxa.cli.compat import ENGINE_KINDS, MEMORY_KINDS, check_compat, default_engine_for
from doxa.cli.merge import merge_command
from doxa.cli.prompt import extract_prompt_command, query_prompt_command


def _make_memory_repo():
    from doxa.persistence.memory import InMemoryBranchRepository

    return InMemoryBranchRepository()


def _make_native_repo():
    import os
    import tempfile

    from doxa.persistence.native import NativeBranchRepository

    native_dir = os.environ.get("DOXA_NATIVE_DIR")
    if native_dir:
        base = Path(native_dir)
        edb_path = base / "edb"
        idb_path = base / "idb"
        edb_path.mkdir(parents=True, exist_ok=True)
        idb_path.mkdir(parents=True, exist_ok=True)
    else:
        edb_path = Path(tempfile.mkdtemp(prefix="doxa_edb_"))
        idb_path = Path(tempfile.mkdtemp(prefix="doxa_idb_"))
    return NativeBranchRepository(str(edb_path), str(idb_path))


def _make_postgres_repo():
    import os

    from doxa.persistence.postgres import PostgresBranchRepository

    db_url = os.environ.get("DOXA_POSTGRES_URL", "postgresql://localhost/doxa")
    return PostgresBranchRepository(db_url)


def _make_memory_engine(_repo=None):
    from doxa.query.memory import InMemoryQueryEngine

    return InMemoryQueryEngine()


def _make_native_engine(_repo=None):
    from doxa.query.native import NativeQueryEngine

    return NativeQueryEngine()


def _make_postgres_engine(repo):
    from doxa.query.postgres import PostgresQueryEngine

    if repo is None:
        raise click.ClickException(
            "PostgresQueryEngine requires a PostgresBranchRepository. "
            "Use --memory postgres to create one automatically."
        )
    return PostgresQueryEngine(repo)


BACKEND_REGISTRY = {
    "memory": {
        "repo_factory": _make_memory_repo,
        "engine_factory": _make_memory_engine,
        "default_engine": "memory",
    },
    "native": {
        "repo_factory": _make_native_repo,
        "engine_factory": _make_native_engine,
        "default_engine": "native",
    },
    "postgres": {
        "repo_factory": _make_postgres_repo,
        "engine_factory": _make_postgres_engine,
        "default_engine": "postgres",
    },
}


ENGINE_REGISTRY = {
    "memory": _make_memory_engine,
    "native": _make_native_engine,
    "postgres": _make_postgres_engine,
}


def _make_repo(memory_kind: str):
    try:
        return BACKEND_REGISTRY[memory_kind]["repo_factory"]()
    except KeyError as exc:
        raise click.ClickException(f"Unknown memory backend: {memory_kind!r}") from exc


def _make_engine(engine_kind: str, repo=None):
    try:
        return ENGINE_REGISTRY[engine_kind](repo)
    except KeyError as exc:
        raise click.ClickException(f"Unknown query engine: {engine_kind!r}") from exc


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
    "--edb",
    "edb_kind",
    default=None,
    type=click.Choice(MEMORY_KINDS, case_sensitive=False),
    metavar="BACKEND",
    help=(
        "EDB (Extensional Database) backend — additive synonym for "
        f"--memory. [{', '.join(MEMORY_KINDS)}]."
    ),
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
    "--idb",
    "idb_kind",
    default=None,
    type=click.Choice(ENGINE_KINDS, case_sensitive=False),
    metavar="ENGINE",
    help=(
        "IDB (Intensional Database) / materialiser backend — additive "
        f"synonym for --engine. [{', '.join(ENGINE_KINDS)}]."
    ),
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
    edb_kind: str | None,
    engine_kind: str | None,
    idb_kind: str | None,
    files: tuple[Path, ...],
) -> None:
    """Doxa — interactive knowledge-base terminal and utilities."""

    # If a subcommand was invoked, don't run the terminal
    if ctx.invoked_subcommand is not None:
        return

    # Resolve --edb / --idb as additive synonyms for --memory / --engine.
    # Mixing both on the same side is a usage error unless they agree.
    if edb_kind is not None:
        if memory_kind is not None and memory_kind != edb_kind:
            raise click.UsageError(
                f"--memory {memory_kind!r} and --edb {edb_kind!r} disagree; pick one."
            )
        memory_kind = edb_kind
    if idb_kind is not None:
        if engine_kind is not None and engine_kind != idb_kind:
            raise click.UsageError(
                f"--engine {engine_kind!r} and --idb {idb_kind!r} disagree; pick one."
            )
        engine_kind = idb_kind

    # --tmp forces in-memory regardless of --memory / --edb
    if tmp:
        if memory_kind is not None and memory_kind != "memory":
            raise click.UsageError("--tmp and --memory/--edb are mutually exclusive.")
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
        engine = _make_engine(engine_kind, repo=repo)
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
