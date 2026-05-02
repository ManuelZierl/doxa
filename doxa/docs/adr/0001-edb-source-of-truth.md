# ADR 0001 — EDB is the durable source of truth; IDB and snapshots are rebuildable

**Status:** accepted  
**Date:** 2026-05-02

## Context

Doxa's reasoning engine is split across three Rust crates in
`doxa-native/`:

- `doxa_edb` — append-only event log (the **Extensional Database**).
  Stores `AssertFact`, `AddRule`, `AddConstraint`, `RetractFact`, and
  `DeclarePredicate` events. Branch isolation is native. Watermarks
  are monotonic event ids.
- `doxa_idb` — sled-backed derived/materialised state (the
  **Intensional Database**). Stores compiled predicates, atom states,
  contributions, secondary indexes, and now a per-branch
  materialisation watermark.
- `doxa_engine` — compiler, semi-naive fixpoint, and session
  orchestrator that reads events from the EDB, materialises them into
  the IDB, and answers queries.

The conceptual contract is:

- The EDB is authoritative. It is the only component whose loss
  destroys knowledge.
- The IDB is disposable: it can be deleted and rebuilt from the EDB
  with identical query answers.

Prior to this ADR the **Python-facing** persistence layer did not
honour that contract. `NativeBranchRepository` persisted a full JSON
`Branch` snapshot alongside the native EDB writes and used the
snapshot as its primary reconstruction source. `get()` depended on a
name being present in an in-memory `_known_branches` set loaded from
`index.json`. If the snapshot directory was deleted:

- `list_names()` returned `[]` (index.json gone).
- `get()` returned `None` for any branch name (name not in
  `_known_branches`).
- Even when forced, reconstruction from the EDB only produced the
  belief records — rules and constraints were silently dropped
  (`rules=[]`, `constraints=[]`).

This violated the source-of-truth contract. The native EDB contained
the full append-only log — `AddRule` and `AddConstraint` events — but
the Python layer had no bindings to read them back.

## Decision

We make the Python-facing layer honour the invariant that the ADR
title asserts:

1. **Source of truth.** The native EDB is the only durable store.
   Branch snapshots written by `NativeBranchRepository` are an
   optimisation for exact round-trip (they carry timestamps and
   metadata that the EDB event log does not currently encode). They
   are not a durability layer.

2. **Branch discovery.** `NativeBranchRepository.list_names()` unions
   the snapshot index with branches discovered from the EDB event
   log via a new `NativeStore.list_branches()` binding. Losing the
   snapshot index does not hide branches.

3. **EDB reconstruction.** `NativeBranchRepository.get(name)` first
   tries the snapshot (fast, exact); if the snapshot is missing or
   corrupt, it calls `_reconstruct_branch_from_edb(name)`, which now
   populates **belief records, rules, and constraints** from the
   EDB. New Python/Rust bindings — `get_rules` and `get_constraints`
   — return structured dicts mirroring the shape accepted by
   `add_rule` / `add_constraint`.

4. **Consistent tagged encoding.** Rule head arguments, rule goal
   arguments, and constraint goal arguments are now interned with
   the same `ent:` / `lit:` / `predref:` prefix scheme that belief
   arguments already used. This is what lets us reverse-decode a
   symbol back to the original `RuleHead*Arg` / `RuleGoal*Arg` /
   `EntityArg` / `LiteralArg` / `PredRefArg` type instead of
   defaulting every ground value to `entity`.

5. **Watermark contract.** `DoxaStore` gains a `branch_watermark`
   sled tree. `EngineSession::materialize_with_options` records the
   EDB event id *at the start of materialization* as the IDB
   watermark for that branch. Python exposes
   `NativeStore.idb_watermark(branch)` and `edb_watermark()`.
   Queries can compare the two to detect stale materialisation.

6. **Python-visible split.** `doxa.persistence.split` introduces
   thin facade classes — `NativeEdb`, `NativeIdb`, `NativeRuntime` —
   over a shared `NativeStore`. They do not change the Rust-side
   composition, but they make the EDB/IDB contract visible and
   type-checkable at the Python boundary so future backends can slot
   in without redesigning the public API.

We explicitly **do not** address in this ADR:

- Full `PostgresEdb + NativeIdb` support.
- `MemoryEdb + NativeIdb` cross-backend composition (requires an
  `EdbSource` trait in `doxa_engine` and a PyO3 bridge).
- Renaming CLI flags `--memory` / `--engine` to `--edb` / `--idb`.
- Formalising `EdbStore` / `IdbStore` Python protocols.

Those are follow-up tickets. The v0.1 goal is to fix the immediate
source-of-truth violation and make the boundary visible so future
work can land without further restructuring.

## Consequences

### Positive

- Deleting the JSON snapshot no longer loses rules or constraints.
  Regression tests live in
  `tests/persistence/test_native_edb_source_of_truth.py`.
- `doxa.persistence.split.NativeRuntime` lets callers write code
  that refers to `rt.edb` and `rt.idb` as separate objects. This is
  the shape future backends will target.
- The durable IDB watermark enables a straightforward staleness
  check: compare `NativeStore.idb_watermark(branch)` with
  `NativeStore.edb_watermark()`. Staleness handling is not
  automatic yet, but the data model is now explicit.

### Negative

- The tagged interning scheme is an on-disk format change for rule
  and constraint arguments. Existing native stores written before
  this ADR will still load, but rules/constraints persisted with
  the old untagged scheme may decode to `RuleHeadEntityArg` for
  literal arguments. Doxa is v0.1 experimental so we accept this.
- The Rust sled `branch_watermark` tree is also new. Older IDB
  directories open fine; the watermark is simply absent until the
  next `materialize` call.
- Snapshots are still written on every `save()` / mutation. They
  are now correctly labelled as a cache rather than a source of
  truth, but the dual-write cost remains. Reducing it is a
  follow-up.

### Tests pinning this invariant

- `tests/persistence/test_native_edb_source_of_truth.py`
- `tests/persistence/test_native_split.py`
- `tests/persistence/test_native_repository.py` (existing regression
  tests for the snapshot path; unchanged semantics).
