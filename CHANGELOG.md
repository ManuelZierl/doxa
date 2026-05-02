# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

## [0.1.0] - 2026-04-17

### Added
- CI smoke test for built wheel artifacts before PyPI upload.
- Initial changelog for release tracking.

### Changed
- README backend documentation now reflects `memory`, `native`, and `postgres` support.
- README native build prerequisites now match Rust toolchain pinning and document wheel targets for CPython 3.11-3.13.
- Public package docstrings consistently use Doxa branding.
- `.gitignore` now excludes common Python packaging outputs.
- Release workflow now publishes with PyPI Trusted Publishing (OIDC) instead of API token uploads.
- Wheel build matrix now covers Linux/macOS/Windows for CPython 3.11, 3.12, and 3.13.
- CLI backend compatibility errors now list all supported `--memory`/`--engine` pairs.

### Fixed
- Postgres testcontainer setup emits an explicit pytest warning when startup fails.
- Postgres fixture comparison no longer silently ignores query/statement parse errors.

## [0.0.1] - 2026-04-17

### Added
- Initial public package release with core language model, query engine abstraction, persistence backends, and CLI entrypoint.
