# Doxa Language Specification — v0.1

Doxa is a Prolog/Datalog-inspired knowledge language with epistemic annotations.
A Doxa program is a sequence of statements; each statement ends with `.`

---

## Lexical Conventions

```
% line comment
/* block comment */
```

| Token          | Form                            | Examples                     |
|----------------|---------------------------------|------------------------------|
| Variable       | Uppercase or `_`-prefix         | `X`, `Person`, `_Tmp`        |
| Identifier     | Lowercase start, `[a-zA-Z0-9_]` | `parent`, `alice`, `my_pred` |
| Quoted atom    | Single quotes                   | `'Thomas'`, `'Lama glama'`   |
| String literal | Double quotes                   | `"hello world"`              |
| Integer        | Plain digits                    | `42`, `-3`                   |
| Float          | Digits with `.`                 | `1.5`, `3.14`                |

Identifiers and predicate names must be **ASCII only**.
String literal *values* may contain Unicode.
**Compound terms are forbidden** — `foo(bar(X))` is a syntax error; introduce a fresh entity instead.

---

## Statements

### 1. Predicate Declaration

```
pred name/arity [type_list] [@{description:"..."}].
```

Must appear before the first use of the predicate.
The optional `[type_list]` specifies argument types and automatically generates type-checking constraints.
`description` is the **only** annotation key accepted on `pred` — any other key is a hard error.

```doxa
pred parent/2 @{description:"parent(P,C): P is a direct parent of C"}.
pred alive/1.
pred employee/2 [company, person] @{description:"employee(C,P): P works for company C"}.
```

When a type list is provided, Doxa automatically generates type-checking constraints. Type-checking is always done with predicates of arity 1.
```doxa
pred employee/2 [company, person].
```
Expands to:
```doxa
pred employee/2.
!:- employee(X0, X1), not company(X0).
!:- employee(X0, X1), not person(X1).
```

### 2. Fact (BeliefRecord)

Asserts a ground atom. All arguments must be bound (no variables).

```
name(arg1, ..., argN) [@{annotation-keys}].
```

```doxa
parent(thomas, alice) @{b:0.99, d:0.0, src:registry, et:"2026-01-01T00:00:00Z"}.
name(alice, "Alice Smith") @{src:registry, et:"2026-01-01T00:00:00Z"}.
price(apple, 1.5) @{vf:"2026-01-01", vt:"2026-12-31"}.
```

### 3. Rule

Derives the head atom when all body goals hold. `not` (negation as failure) is allowed in the body.
Builtin goals cannot be negated.
Multiple rules with the same head are implicitly unioned.

```
head(args) :- goal1, goal2, ... [@{annotation-keys}].
```

```doxa
ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z)
    @{src:internal, et:"2026-01-01T00:00:00Z",
      description:"ancestor(X,Z): X is an indirect ancestor of Z"}.

unemployed(X) :- person(X), not employed(X), not student(X)
    @{src:internal, et:"2026-01-01T00:00:00Z",
      description:"unemployed(X): not employed and not a student"}.
```

### 4. Constraint

Emits a violation when the body is satisfiable. Does not derive new facts.

```
!:- goal1, goal2, ... [@{annotation-keys}].
```

```doxa
!:- approved(X), not registered(X) @{name:"approved_must_be_registered"}.
```

### 5. Query

Retrieves bindings satisfying the body goals.

```
?- goal1, goal2, ... [@{query-options}].
```

```doxa
?- ancestor(thomas, X).
?- score(X, S), geq(S, 80) @{order_by:"S", distinct:true, limit:10}.
?- event(X) @{asof:"2024-06-15"}.
```

---

## Annotation Keys

Facts, rules, and constraints all accept the same set of annotation keys (all optional):

| Key           | Type            | Default | Meaning                                   |
|---------------|-----------------|---------|-------------------------------------------|
| `b`           | float [0,1]     | 1.0     | Belief degree                             |
| `d`           | float [0,1]     | 0.0     | Disbelief degree                          |
| `src`         | identifier      | —       | Source entity id                          |
| `et`          | ISO-8601 string | —       | Epistemic time                            |
| `vf`          | ISO-8601 string | —       | Valid-from                                |
| `vt`          | ISO-8601 string | —       | Valid-to                                  |
| `name`        | string          | —       | Label                                     |
| `description` | string          | —       | Description (`note` is an accepted alias) |

`pred` declarations accept **only** `description`. All other keys cause a hard error.

---

## Body Goals

A body is a comma-separated list of goals. Each goal is one of:

### Atom goal
```
predicate_name(term1, ..., termN)
```

### Proof-level Operators

#### Negation as Failure (`not`)
```
not predicate_name(term1, ..., termN)
```

`not` is a **proof-level operator**, not a builtin predicate. It implements negation-as-failure (NAF): `not goal` succeeds if and only if `goal` cannot be proven. This is fundamentally different from boolean negation.

**Important distinctions:**
- `not` is a reserved operator that modifies atom goals
- `not` cannot be applied to builtin goals
- `not` does not bind new variables — all variables in a negated goal must already be bound
- `not` operates at the proof search level, not on boolean values

### Builtins

Builtins are special predicates evaluated directly by the query engine, not through rule derivation.

#### Built-in: comparators (arity 2)

Both arguments must be bound, except `eq` which can unify one unbound variable.

| Builtin     | Meaning |
|-------------|---------|
| `eq(A, B)`  | A = B   |
| `ne(A, B)`  | A ≠ B   |
| `lt(A, B)`  | A < B   |
| `leq(A, B)` | A ≤ B   |
| `gt(A, B)`  | A > B   |
| `geq(A, B)` | A ≥ B   |

### Built-in: arithmetic (arity 3)

Solves for any one unknown argument.

| Builtin              | Meaning                                                           |
|----------------------|-------------------------------------------------------------------|
| `add(A, B, C)`       | A + B = C                                                         |
| `sub(A, B, C)`       | A − B = C                                                         |
| `mul(A, B, C)`       | A × B = C                                                         |
| `div(A, B, C)`       | A / B = C                                                         |
| `between(X, Lo, Hi)` | Lo ≤ X ≤ Hi — all three must be bound; check only, no enumeration |

### Built-in: type predicates (arity 1)

Type predicates check the runtime type of their argument. The argument must be bound.

| Builtin      | Meaning                                          |
|--------------|--------------------------------------------------|
| `int(X)`     | X is an integer value                            |
| `float(X)`   | X is a floating-point value                      |
| `string(X)`  | X is a string literal value                      |
| `entity(X)`  | X is an entity (any string identifier)           |

**Type predicates in predicate declarations:**

Type predicates can be used in predicate type lists to automatically generate type-checking constraints:

```doxa
pred euro_value/2 [entity, int].
```

This automatically generates:
```doxa
!:- euro_value(X0, X1), not entity(X0).
!:- euro_value(X0, X1), not int(X1).
```

**Default type annotation:**

When a predicate is declared without a type list, it automatically defaults to `[entity, entity, ...]` for all argument positions:

```doxa
pred parent/2.
```

is equivalent to:

```doxa
pred parent/2 [entity, entity].
```

Infix operators (`>=`, `<`, etc.) are **not valid syntax** in rule bodies or queries.

---

## Query Options

Specified in the query annotation `@{...}`:

| Option      | Type            | Default    | Meaning                                                        |
|-------------|-----------------|------------|----------------------------------------------------------------|
| `limit`     | int ≥ 0         | —          | Return at most N results                                       |
| `offset`    | int ≥ 0         | 0          | Skip first N results                                           |
| `order_by`  | string          | —          | Comma-separated variable names to sort by                      |
| `distinct`  | bool            | false      | Deduplicate result rows                                        |
| `asof`      | ISO-8601 string | —          | Filter facts to those whose `[vf, vt]` window covers this time |
| `max_depth` | int > 0         | 24         | Hard cap on recursive rule-application depth                   |
| `policy`    | string          | `"report"` | Evidence filter — see below                                    |
| `explain`   | string          | `"false"`  | Derivation trace: `"false"`, `"true"`, or `"human"`            |

### Policy values

| Value         | Behaviour                         |
|---------------|-----------------------------------|
| `"report"`    | No belief filter — all facts pass |
| `"credulous"` | Only facts where `b > d`          |
| `"skeptical"` | Only facts where `b > d`          |

---

## Anonymous Variables

A bare `_` in a query is a wildcard. Each `_` is renamed internally to `_0`, `_1`, etc.
and appears by that name in the output.

```doxa
?- edge(a, _).
?- edge(_, _) @{distinct:true}.
```

---

## Terminal Slash Commands

Interactive-mode only. Prefix is `/-`:

| Command                                          | Effect                                                   |
|--------------------------------------------------|----------------------------------------------------------|
| `/- dump [--ax\|--json] [--file <path>]`         | Print the current branch                                 |
| `/- dump --no-predicates`                        | Exclude predicate declarations from dump                 |
| `/- dump --no-belief-records`                    | Exclude facts from dump                                  |
| `/- dump --no-rules`                             | Exclude rules from dump                                  |
| `/- dump --no-constraints`                       | Exclude constraints from dump                            |
| `/- info`                                        | Show session info: engine, backend, counts               |
| `/- schema [--branch] [--query] [--file <path>]` | Print JSON schema for Branch / Query                     |
| `/- load <file> [--fix]`                         | Load and merge a `.doxa` or `.json` file                 |
| `/- unload predicate <name>/<arity>`             | Remove a predicate and all its facts and rules           |
| `/- unload entity <name>`                        | Remove an entity and all facts referencing it            |
| `/- unload rules`                                | Remove all rules                                         |
| `/- unload constraints`                          | Remove all constraints                                   |
| `/- unload all`                                  | Reset the branch to empty                                |
| `/- search <pattern>`                            | Substring search over predicates, entities, facts, rules |
| `/- help`                                        | Show help                                                |
| `/- exit` / `/- quit`                            | Exit the terminal                                        |

---

## Hard Constraints

- Facts must be **ground** — no variables as arguments.
- No compound terms anywhere — `foo(bar(X))` is always a syntax error.
- Predicate arity must be ≥ 1 — zero-arity predicate declarations are rejected.
- Every predicate must be declared before its first use.
- `pred` annotations accept `description` only — any other key is a parse error.
- `pred` type lists are optional; when provided, they must match the declared arity.
- **Predicate names cannot be reserved keywords** (`not`, `pred`) or builtin names (`eq`, `ne`, `lt`, `leq`, `gt`, `geq`, `add`, `sub`, `mul`, `div`, `between`, `int`, `string`, `float`, `entity`).
- Identifiers (predicate names, entity ids) must be ASCII only.
- `between` does not enumerate — all three arguments must already be bound.
- Builtin goals cannot be negated with `not`.

## Why no compound terms?

Doxa should probably disallow compound terms not mainly because of parsing complexity, but because they clash with its belief-record model. In Doxa, annotations like `b` and `d` attach to explicit propositions, so a flat atom such as `parent(thomas, manuel) @{b:0.7, d:0.1}.` is clear: the epistemic status belongs to exactly that statement. With compound terms like `owns(thomas, car(bmw, blue)) @{...}.`, nested structure would smuggle additional semantic content into a single annotated record, and it becomes unclear whether and how the inner parts should inherit, derive, or expose their own belief/disbelief values. By forbidding compound terms, Doxa keeps every meaningful proposition explicit, which makes epistemic semantics, provenance, explanation, and validation much cleaner.
