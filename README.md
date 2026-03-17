# Doxa

A logic-programming knowledge base toolkit built on Pydantic. Doxa provides a Datalog-like language (doxa-lang) for defining predicates, belief records, rules, and integrity constraints — plus swappable persistence and query backends.

## Installation

```bash
pip install -e ".[dev]"
# With PostgreSQL support:
pip install -e ".[postgres]"
```

## Quick Start

```python
from doxa.core import Branch
from doxa.persistence.memory import InMemoryBranchRepository
from doxa.query.memory import InMemoryQueryEngine

branch = Branch.from_ax("""
    pred parent/2.
    parent(alice, bob).
    parent(bob, charlie).
    ancestor(X, Y) :- parent(X, Y).
    ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z).
""")

repo = InMemoryBranchRepository()
repo.save(branch)

engine = InMemoryQueryEngine()
results = engine.query(branch, "ancestor(alice, Z)?")
```

## CLI

```
doxa                                  Start interactive terminal (in-memory)
doxa --memory postgres                Use PostgreSQL backend
doxa --file knowledge.doxa            Pre-load a file before starting
doxa --file a.doxa --file b.json      Pre-load and merge multiple files
doxa prompt <resource>                Generate an extraction prompt
doxa --version / --help
```

Set `DOXA_POSTGRES_URL` to configure the PostgreSQL connection (default: `postgresql://localhost/doxa`).

## Doxa Language

| Syntax | Meaning |
|---|---|
| `pred name/arity.` | Declare a predicate |
| `parent(alice, bob).` | Belief record (ground fact) |
| `ancestor(X,Z) :- parent(X,Y), ancestor(Y,Z).` | Derivation rule |
| `!:- sibling(X, X).` | Integrity constraint |
| `sig(name/1, entity/1).` | Signature shorthand (expands to constraints) |
| `@{src:s, b:0.9}` | Annotation on any statement |

## Architecture

| Package | Role |
|---|---|
| `doxa.core` | Pydantic domain models — `Branch`, `BeliefRecord`, `Rule`, `Constraint`, `Predicate`, `Entity` |
| `doxa.persistence` | Abstract `BranchRepository` with in-memory and PostgreSQL backends |
| `doxa.query` | Abstract `QueryEngine` with in-memory (pure Python Datalog) and PostgreSQL backends |
| `doxa.cli` | Click-based interactive terminal and `prompt` subcommand |

## Development

```bash
pytest          # run tests
ruff check doxa # lint
```
