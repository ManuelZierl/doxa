# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

## [0.1.0] - 2026-05-04

First public release of Doxa on PyPI as `doxa-lang`.

### Added

#### Language and core model
- Core language model: `Branch`, `BeliefRecord`, `Rule`, `Constraint`, `Predicate`, `Entity`, `Query` with explicit Belnap (b, d) belief degrees, source provenance (`src`), and temporal annotations (`vf`, `vt`, `et`).
- First-class temporal literals: `d"YYYY-MM-DD"` (date), `dt"...Z"` (datetime), `dur"P..."` (ISO-8601 duration), with parsing, validation, and use as ground arguments and builtin operands.
- Builtin predicates: equality/comparison (`eq`, `ne`, `lt`, `leq`, `gt`, `geq`, `between`), arithmetic (`add`, `sub`, `mul`, `div`) including temporal arithmetic, and type predicates (`int`, `float`, `string`, `entity`, `predicate_ref`, `date`, `datetime`, `duration`).
- `pred` template for predicate declarations with optional type lists and `@{description:...}` metadata, plus a user-extensible template registry.
- Negation-as-failure (`!atom`) and assumption goals (`assume(...)`) for hypothetical query evaluation.
- Anonymous variables (`_`, `_Tmp`) excluded from answer projection.
- Pluggable epistemic semantics: body truth (`product` / `minimum`), body falsity (`noisy_or` / `maximum`), support aggregation (`noisy_or` / `maximum` / `capped_sum`), rule and constraint applicability, and Belnap status derivation.
- Full language specification under `doxa/SPECIFICATION.md`.

#### Query engines (Intensional Database)
- `InMemoryQueryEngine` with Datalog/Prolog-style fixpoint evaluation, builtin handling, and explain support.
- `NativeQueryEngine` backed by the Rust `doxa-native` workspace, with parity coverage for the core language, semantics, builtins, and aggregation.
- `PostgresQueryEngine` with optional native SQL fast path (gated by `DOXA_POSTGRES_NATIVE_SQL`) and explicit, opt-in strict mode (`DOXA_POSTGRES_NATIVE_SQL_STRICT`) for benchmarking and coverage testing.
- Engine capability advertisement via `EngineInfo.supported_epistemic_semantics`.

#### Persistence backends (Extensional Database)
- `InMemoryBranchRepository` for ephemeral / test usage.
- `NativeBranchRepository` backed by an append-only EDB event log plus a sled-based IDB, with the EDB as the durable source of truth and the JSON branch snapshot as a rebuildable cache. Architectural rationale documented in `doxa/docs/adr/0001-edb-source-of-truth.md`.
- `PostgresBranchRepository` (optional `[postgres]` extra) for branch storage in PostgreSQL.
- Explicit EDB / IDB / Runtime split surfaced via `doxa.persistence.split` for tests and downstream tooling that need to assert source-of-truth invariants.
- Incremental `add_belief_record`, `add_rule`, `add_constraint` paths on the native repository with explicit flushes for crash durability.

#### CLI
- `doxa` entrypoint with an interactive terminal, `--memory` / `--engine` backend selection, `--edb` / `--idb` synonyms aligned with the architectural split, and `--tmp` for ephemeral sessions.
- `doxa --file ...` pre-loads (and merges) one or more `.doxa` / `.json` files before the terminal starts.
- `doxa merge` to merge multiple `.doxa` / `.json` knowledge files into one.
- `doxa extract-prompt` and `doxa query-prompt` to generate LLM prompts from a knowledge base and packaged Markdown templates.
- Backend compatibility checks that list every supported `--memory` / `--engine` pair on mismatch.

#### Packaging, build, and CI
- Maturin-based mixed Python/Rust build producing prebuilt wheels for Linux, macOS, and Windows on CPython 3.11, 3.12, and 3.13, plus a sdist.
- CI wheel smoke test (`import doxa`, `import doxa._native`, `doxa --help`) on every wheel before PyPI upload.
- Release workflow publishes to PyPI via Trusted Publishing (OIDC), with version consistency enforced between the git tag, `pyproject.toml`, and `doxa/__version__.py`.
- Pre-commit hooks for `ruff format`, `isort`, `ruff check`, `cargo fmt`, and `cargo clippy -D warnings`, also enforced in CI.
- Rust test and coverage job for the `doxa-native` workspace.

### Documentation
- README documents the supported backend matrix and all `DOXA_*` environment variables: `DOXA_POSTGRES_URL`, `DOXA_POSTGRES_NATIVE_SQL`, `DOXA_POSTGRES_NATIVE_SQL_STRICT`, `DOXA_NATIVE_DIR`.
- README native build prerequisites match the pinned Rust toolchain and the wheel target matrix.
- ADR `0001-edb-source-of-truth.md` describes the EDB/IDB split and the durability contract.

### Fixed
- Native query engine constraint and builtin regressions exposed by terminal fixtures.
- Postgres fixture comparison no longer silently ignores query/statement parse errors.
- Postgres testcontainer setup emits an explicit pytest warning when startup fails so that Postgres-dependent tests are visibly skipped instead of silently passing.
- CLI on Windows no longer crashes with `UnicodeEncodeError` (cp1252) when commands such as `extract-prompt` emit non-ASCII characters; stdio is reconfigured to UTF-8 at entry.
