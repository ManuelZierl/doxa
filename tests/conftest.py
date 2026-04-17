import json
import os
import subprocess
import warnings

import pytest


def _ensure_docker_host():
    """Set DOCKER_HOST from the active Docker CLI context if not already set.

    The Python ``docker`` library does not read Docker CLI contexts, so on
    Docker Desktop (Windows/macOS) the default named pipe may differ from
    the active context (e.g. ``dockerDesktopLinuxEngine`` vs ``docker_engine``).
    In CI (Linux) the default ``/var/run/docker.sock`` usually works as-is.
    """
    if os.environ.get("DOCKER_HOST"):
        return
    try:
        out = subprocess.check_output(
            ["docker", "context", "inspect"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        ctx = json.loads(out)
        endpoint = ctx[0]["Endpoints"]["docker"]["Host"]
        if endpoint:
            os.environ["DOCKER_HOST"] = endpoint
    except Exception:
        pass


def pytest_configure(config):
    """Spin up a PostgreSQL testcontainer before test collection.

    This runs early enough that module-level guards like
    ``os.environ.get("DOXA_POSTGRES_TEST_URL")`` see the URL.
    The container is stored on the config object and torn down in
    ``pytest_unconfigure``.
    """
    try:
        _ensure_docker_host()

        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16")
        container.start()
        # psycopg-style URL (driver not in scheme)
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        os.environ["DOXA_POSTGRES_TEST_URL"] = url
        config._pg_container = container
    except Exception:
        # Docker not available or testcontainers not installed — tests
        # that need Postgres will be skipped by their own guards.
        config._pg_container = None
        warnings.warn(
            pytest.PytestWarning(
                "Could not start PostgreSQL test container; tests requiring Postgres may be skipped."
            )
        )


def pytest_unconfigure(config):
    """Stop the PostgreSQL container after all tests have run."""
    container = getattr(config, "_pg_container", None)
    if container is not None:
        container.stop()
