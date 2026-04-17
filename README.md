# doxa

> **Warning**
> Doxa is currently in an **early, unstable stage**.
> APIs, query semantics, file formats, and behavior may change without notice.
> It is not yet recommended for production use.

An epistemic knowledge representation language — Datalog/Prolog-grounded, temporally-aware, conflict-sensitive, and auditable.

## The Problem

Existing knowledge systems collapse important epistemic distinctions into a single dimension:

- **Classical Datalog / SQL** — facts are ground truth. Conflict is a bug, ignorance is absence, decay requires manual deletion.
- **Probabilistic systems** — a scalar *p ∈ [0,1]* cannot distinguish *no evidence* from *equal evidence both ways*; conflict, ignorance, and uncertainty all look the same.
- **Graph / triple stores** — no first-class uncertainty model at all.

None of these can represent: *"Source A strongly believes X, Source B strongly disbelieves X, valid between D1–D2, and the conflict is unresolved."*

## What Doxa Does

Every fact in Doxa is a **BeliefRecord** — a ground atom paired with:

- **b / d** — independent degrees of evidence *for* and *against* (b + d ≤ 1)
- **src** — who asserts this belief
- **vf / vt** — real-world validity period
- **et** — epistemic time (when the belief entered the KB)

This yields four qualitatively distinct epistemic states grounded in [Belnap's four-valued logic](https://en.wikipedia.org/wiki/Four-valued_logic):

| State     | b   | d   | Meaning                   |
|-----------|-----|-----|---------------------------|
| **None**  | 0   | 0   | No evidence either way    |
| **True**  | > 0 | 0   | Evidence for, not against |
| **False** | 0   | > 0 | Evidence against, not for |
| **Both**  | > 0 | > 0 | Conflicting evidence      |

No single confidence scalar can represent all four — the distinction between *None* and *Both* is categorical, not a matter of degree.

```doxa
bird(owl) @{b:0.98, src:"https://en.wikipedia.org/wiki/Owl", et:"2026-03-24"}.
weight_g(owl, 1500) @{b:0.98, src:"https://en.wikipedia.org/wiki/Owl", et:"2026-03-24"}.
wingspan_cm(owl, 110) @{b:0.97, src:"https://en.wikipedia.org/wiki/Owl", et:"2026-03-24"}.

bird(penguin) @{b:1.0, src:"https://en.wikipedia.org/wiki/Penguin", et:"2026-03-24"}.
weight_g(penguin, 30000) @{b:0.95, src:"https://en.wikipedia.org/wiki/Penguin", et:"2026-03-24"}.
wingspan_cm(penguin, 60) @{b:0.90, src:"https://en.wikipedia.org/wiki/Penguin", et:"2026-03-24"}.

can_fly(X) :-
    bird(X),
    weight_g(X, W),
    wingspan_cm(X, S),
    div(W, S, R),
    lt(R, 20) @{
        b:0.98, 
        src:"simplified heuristic inspired by wing loading (weight / wing area)", 
        et:"2026-03-24"
    }.
```

```bash
doxa> ?- can_fly(owl).
  1: b=0.913, d=0, status=true
doxa> ?- can_fly(penguin). 
  1: b=0, d=0, status=neither
```

## Key Properties

- **Conflict without corruption** — disagreeing sources produce *Both*, not an average; conflict is queryable, and the query policy (credulous/skeptical) resolves it at query time
- **Ignorance without inference** — unasserted facts return *None*, not a prior or default false
- **Time as a language primitive** — temporal validity and epistemic time are enforced uniformly via `asof` query semantics, not modeling conventions
- **Auditability built in** — derivation traces (`explain`) name every supporting BeliefRecord, its source, validity window, and belief degree
- **Guaranteed termination** — Datalog semantics ensure every query over a finite KB terminates

## Foundations

Doxa's parametric combination algebra follows [Lakshmanan & Shiri (2001)](https://doi.org/10.1109/69.929926). Its *(b, d)* semantics are grounded in [Belnap (1977)](https://link.springer.com/chapter/10.1007/978-94-010-1161-7_2) and instantiated with [Jøsang's subjective logic (2016)](https://link.springer.com/book/10.1007/978-3-319-42337-1). Doxa's contribution is the co-design of these elements into a single language with first-class provenance, temporal annotation, and audit traces — promoted from modeling conventions to language primitives enforced by the parser.

## Language Specification

For the full formal syntax, semantics, builtins, query options, and edge cases see the **[Language Specification](doxa/SPECIFICATION.md)**.

## Repository Layout

| Path                | Description                               |
|---------------------|-------------------------------------------|
| `doxa/core/`        | Core language model types and parsing     |
| `doxa/query/`       | Query execution engine                    |
| `doxa/persistence/` | Storage backends (memory, native, PostgreSQL) |
| `doxa/cli/`         | CLI entry points and interactive terminal |
| `tests/`            | Automated tests and fixtures              |

## Install

```bash
pip install doxa
```

Optional PostgreSQL dependencies:

```bash
pip install "doxa[postgres]"
```

For local development from source:

```bash
pip install -e ".[dev,postgres]"
pytest
```

## Native Build Prerequisites

- Python `>=3.11`
- Rust toolchain `1.77.2` (policy pinned in `rust-toolchain.toml`)
- A working C/C++ compiler toolchain (`build-essential` on Linux, Xcode CLT on macOS, MSVC Build Tools on Windows)

Prebuilt wheels are published for Linux/macOS/Windows. The prerequisites above are required when building from source.

## Backend Matrix

| `--memory` backend | `--engine` backend | Status |
|--------------------|--------------------|--------|
| `memory`           | `memory`           | supported |
| `memory`           | `native`           | supported |
| `native`           | `memory`           | supported |
| `native`           | `native`           | supported |
| `postgres`         | `postgres`         | supported |
| `memory`           | `postgres`         | not supported |
| `postgres`         | `memory`           | not supported |
| `postgres`         | `native`           | not supported |
| `native`           | `postgres`         | not supported |

## Environment Variables

- `DOXA_POSTGRES_URL` (default: `postgresql://localhost/doxa`): PostgreSQL connection URL used by `--memory postgres`.
- `DOXA_POSTGRES_NATIVE_SQL` (`1` to enable): route eligible PostgreSQL queries through the native SQL fast path.

## Quick Start

```bash
doxa --help
doxa
doxa --memory postgres --engine postgres
```

The CLI supports `memory`, `native`, and `postgres` backends via `--memory` and `--engine`.

## License

[MIT](LICENSE)
