# Doxa Language Specification - v0.2

Doxa is a Prolog/Datalog-inspired knowledge language with epistemic annotations.

A stored Doxa program is a sequence of predicate declarations, facts, rules, and constraints. These statements end with `.`. Queries are issued separately against a branch.

## Lexical Conventions

```doxa
% line comment
```

Lines whose trimmed text starts with `%` are ignored.

| Token          | Form                                                 | Examples                     |
|----------------|------------------------------------------------------|------------------------------|
| Variable       | Uppercase or `_`-prefix                              | `X`, `Person`, `_Tmp`        |
| Identifier     | Lowercase start, followed by letters, digits, or `_` | `parent`, `alice`, `my_pred` |
| Quoted entity  | Single quotes                                        | `'Thomas'`, `'Lama glama'`   |
| String literal | Double quotes                                        | `"hello world"`              |
| Integer        | Plain digits, optionally signed                      | `42`, `-3`                   |
| Float          | Digits with `.`                                      | `1.5`, `3.14`                |
| Date literal   | `d"YYYY-MM-DD"`                                      | `d"2024-06-15"`              |
| Datetime literal | `dt"YYYY-MM-DDTHH:MM:SSZ"`                         | `dt"2024-06-15T10:30:00Z"`   |
| Duration literal | `dur"P..."`  (ISO 8601)                             | `dur"P30D"`, `dur"PT2H30M"`  |
| Pred reference | `name/arity`                                         | `parent/2`, `alive/1`        |

Predicate names use the identifier form above.

String literal values may contain Unicode.

Predicate references use the syntax `name/arity` (e.g. `parent/2`) and are valid anywhere a ground value is accepted. They carry no automatic semantic hierarchy behavior; they are opaque literal values that happen to name a predicate.

Compound terms are forbidden. For example, `foo(bar(X))` is a syntax error; introduce a fresh entity instead.

## Statements

### 1. Predicate Declaration (built-in `pred` template)

```doxa
pred name/arity [type_list] [@{description:"..."}].
```

`pred` is a **built-in template** (see §Templates below) for schema and documentation. Predicates may always be introduced implicitly by facts, rules, or constraints — no prior `pred` declaration is required.

A statement such as `parent(alice, bob).` is always valid even if no `pred parent/2.` appears anywhere. The parser auto-creates predicates as statements are parsed.

`pred` declarations may appear before or after ordinary usage of the predicate. Their purpose is to attach metadata (description, type list) and to generate type-checking constraints. A bare `pred foo/2.` has no runtime effect beyond registering schema/metadata presence.

Examples:

```doxa
pred parent/2 @{description:"parent(P,C): P is a direct parent of C"}.
pred alive/1.
pred employee/2 [company, person] @{description:"employee(C,P): P works for company C"}.
pred euro_value/2 [entity, int].
```

Rules:

* `pred` is optional; predicates are auto-created when first used in a fact, rule, or constraint.
* `pred` declarations may appear before or after the predicate is first used.
* Duplicate `pred` declarations for the same name/arity are a hard error.
* `description` is the only annotation key accepted on `pred`. Any other annotation key is a hard error.
* `arity` must be at least 1.
* If a `type_list` is provided, its length must match the predicate arity.
* Each `type_list` entry names a unary predicate used for generated type-checking constraints.
* Common built-in choices are `entity`, `int`, `float`, `string`, and `predicate_ref`.
* If `type_list` is omitted, it is treated as an all-`entity` list for parsing and serialization.
* That default does not add generated type-checking constraints, because built-in type predicates such as `entity` are checked at runtime rather than through generated constraints.

Example expansion:

```doxa
pred employee/2 [company, person].
```

Expands to generated constraints equivalent to:

```doxa
pred employee/2.
!:- employee(X0, X1), not company(X0).
!:- employee(X0, X1), not person(X1).
```

### 2. Fact (BeliefRecord)

A fact asserts a ground atom. All arguments must already be ground; variables are not allowed in facts.

```doxa
name(arg1, ..., argN) [@{annotation-keys}].
```

Examples:

```doxa
parent(zeus, alice) @{b:0.99, d:0.0, src:registry, et:"2026-01-01T00:00:00Z"}.
name(alice, "Alice Smith") @{src:registry, et:"2026-01-01T00:00:00Z"}.
price(apple, 1.5) @{vf:"2026-01-01T00:00:00Z", vt:"2026-12-31T00:00:00Z"}.
```

### 3. Rule

A rule derives the head atom when all body goals hold. `not` (negation as failure) is allowed in the body. Builtin goals cannot be negated.

```doxa
head(args) :- goal1, goal2, ... [@{annotation-keys}].
```

Examples:

```doxa
ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z)
    @{src:internal, et:"2026-01-01T00:00:00Z",
      description:"ancestor(X,Z): X is an indirect ancestor of Z"}.

unemployed(X) :- person(X), not employed(X), not student(X)
    @{src:internal, et:"2026-01-01T00:00:00Z",
      description:"unemployed(X): not employed and not a student"}.
```

Multiple rules with the same head predicate contribute support to the same derived answers.

### 4. Constraint

A constraint emits a violation when its body is satisfiable. It does not derive new facts.

```doxa
!:- goal1, goal2, ... [@{annotation-keys}].
```

Example:

```doxa
!:- approved(X), not registered(X) @{name:"approved_must_be_registered"}.
```

### 5. Query

Queries retrieve epistemic answer rows for bindings satisfying the body goals.

```doxa
?- goal1, goal2, ... [@{query-options}]
```

Examples:

```doxa
?- ancestor(zeus, X)
?- score(X, S), geq(S, 80) @{order_by:"S", limit:10}
?- event(X) @{valid_at:"2024-06-15T00:00:00Z"}
?- person(X) @{focus:"support"}
```

A query answer contains:

* projected variable bindings
* answer-level `b`
* answer-level `d`
* a derived Belnap status

### Hypothetical Assumptions (`assume`)

The `assume(...)` goal is query-only syntax that injects temporary facts into the evaluation context for the duration of that query. Assumed facts are not persisted to the branch.

```doxa
?- assume(fact1, fact2, ...), goal1, goal2, ...
```

Examples:

```doxa
?- assume(employees(nordwind, 450), company(nordwind), turnover_mio(nordwind, 55)),
   out_of_scope_under_current_csrd(nordwind).

?- assume(has_employee_count(my_company, 1200), has_net_turnover(my_company, 500000000)),
   subject_to_due_diligence(lksg, my_company, Year).
```

Rules:

* `assume(...)` is valid only in queries, not in rules, constraints, or `.doxa` files.
* Each argument inside `assume(...)` must be a valid atom goal (same syntax as a fact).
* Assumed facts are injected with `b=1.0, d=0.0` before the rest of the query is evaluated.
* Assumed facts are temporary and do not modify the branch or persist after query evaluation.
* `assume(...)` works identically for ground and open queries.
* Variables inside `assume(...)` that remain unbound are silently skipped (the assumption is incomplete and cannot be injected).
* Multiple `assume(...)` goals in the same query are allowed; all are injected before solving begins.

## Templates

Templates are a **core language feature**. They are expansion mechanisms that receive parsed Doxa arguments and emit one or more valid Doxa statements (facts, rules, constraints, or predicate declarations).

Built-in constructs such as `pred` are implemented as predefined templates. Users can define and import custom templates.

### Template invocation syntax

A template invocation is a dedicated statement form:

```doxa
template_name arg1 arg2 ... [@{annotations}].
```

The template name must be a registered template (either built-in or imported). Arguments are space-separated and parsed into typed objects from `doxa.core`:

| Syntax              | Parsed as               | Examples                          |
|---------------------|-------------------------|-----------------------------------|
| `name/arity`        | Predicate reference     | `parent/2`, `alive/1`             |
| `[t1, t2, ...]`     | Type list               | `[int, entity]`, `[string, _]`    |
| `"text"`            | String literal          | `"hello world"`                   |
| `42`, `-3`          | Integer literal         | `42`, `-3`                        |
| `1.5`, `3.14`       | Float literal           | `1.5`, `3.14`                     |
| lowercase id        | Entity / identifier     | `alice`, `my_pred`                |
| `'quoted'`          | Quoted entity           | `'Thomas'`, `'Lama glama'`        |
| Uppercase / `_`     | Variable                | `X`, `Person`, `_Tmp`             |

Templates receive these as **structured parsed objects**, not raw source strings. Whether a variable is allowed in a given argument position is determined by the template.

### Template imports

Templates are imported explicitly via `use templates`:

```doxa
use templates "doxa_std".
use templates "my_pkg.billing".
use templates "my_pkg.billing" [money_pred, vat_rule].
use templates "my_pkg.billing" [money_pred as money, vat_rule].
```

Rules:

* `use templates` must reference a Python module path.
* The target module must expose a `DOXA_TEMPLATES` dict mapping names to `DoxaTemplate` instances.
* An optional bracket list selects specific templates from the module.
* The `as` keyword allows aliasing an imported template to a different name.
* `use templates` statements are processed in order; imported templates become available for subsequent statements.

### Built-in templates

The following templates are always available without an explicit import:

| Template | Purpose                                              |
|----------|------------------------------------------------------|
| `pred`   | Predicate declaration with optional type list        |

### Template API (Python)

Templates are defined in Python and satisfy the `DoxaTemplate` protocol:

```python
class DoxaTemplate(Protocol):
    def expand(self, call: TemplateCall, ctx: TemplateContext) -> list[DoxaStatement]:
        ...
```

Where:

* `TemplateCall` contains the template name, parsed arguments, and annotations.
* `TemplateContext` provides module and source location information.
* `DoxaStatement` is a union of `Predicate`, `BeliefRecord`, `Rule`, and `Constraint`.

### Failure behaviour

Templates must fail fast on invalid usage:

* Wrong number of arguments
* Wrong argument kind (e.g. variable where ground value required)
* Unsupported annotation keys
* Structurally invalid emitted statements

Templates must not silently coerce, repair, or reinterpret invalid input.

### Non-goals

* Templates do not introduce automatic reasoning behaviour.
* Templates do not imply new runtime semantics unless they expand to statements that do so.
* Templates do not add general list literals or compound terms to Doxa.
* Templates are Python-defined only.

## Annotation Keys

Facts, rules, and constraints all accept the same annotation keys.

| Key           | Type                     |                                        Default | Meaning           |
|---------------|--------------------------|-----------------------------------------------:|-------------------|
| `b`           | float in `[0,1]`         |                                          `1.0` | Belief degree     |
| `d`           | float in `[0,1]`         |                                          `0.0` | Disbelief degree  |
| `src`         | identifier or string     |                                           none | Source identifier |
| `et`          | ISO-8601 datetime string | current UTC evaluation time                    | Epistemic time    |
| `vf`          | ISO-8601 datetime string |                                           none | Valid-from        |
| `vt`          | ISO-8601 datetime string |                                           none | Valid-to          |
| `name`        | string                   |                                           none | Label             |
| `description` | string                   |                                           none | Description       |

Notes:

* `note` is accepted as an alias for `description`.
* `pred` declarations accept only `description`. All other annotation keys cause a hard error.
* `vf` and `vt` are parsed as datetimes.

## Body Goals

A body is a comma-separated list of goals. Each goal is one of the following.

### Atom Goal

```doxa
predicate_name(term1, ..., termN)
```

### Negation as Failure (`not`)

```doxa
not predicate_name(term1, ..., termN)
```

`not` is a proof-level operator, not a builtin predicate.

Rules:

* `not` may be applied only to atom goals
* builtin goals cannot be negated
* variables in a negated goal must already be bound
* `not` operates on provability, not on boolean values

## Builtins

Builtins are evaluated directly by the query engine.

### Comparators (arity 2)

Both arguments must be bound, except `eq`, which can bind one unbound variable.

| Builtin     | Meaning                |
| ----------- | ---------------------- |
| `eq(A, B)`  | equality / unification |
| `ne(A, B)`  | inequality             |
| `lt(A, B)`  | less than              |
| `leq(A, B)` | less than or equal     |
| `gt(A, B)`  | greater than           |
| `geq(A, B)` | greater than or equal  |

### Arithmetic (arity 3)

Arithmetic builtins solve for any one unknown argument.

| Builtin              | Meaning                                                |
| -------------------- | ------------------------------------------------------ |
| `add(A, B, C)`       | `A + B = C`                                            |
| `sub(A, B, C)`       | `A - B = C`                                            |
| `mul(A, B, C)`       | `A * B = C`                                            |
| `div(A, B, C)`       | `A / B = C`                                            |
| `between(X, Lo, Hi)` | range check; all three arguments must already be bound |

`between` is a check only. It does not enumerate values.

### Built-in Type Predicates (arity 1)

These builtins check runtime value kinds.

| Builtin              | Meaning                             |
| -------------------- | ----------------------------------- |
| `int(X)`             | `X` is an integer                   |
| `float(X)`           | `X` is a floating-point number      |
| `string(X)`          | `X` is a string literal             |
| `entity(X)`          | `X` is an entity identifier         |
| `predicate_ref(X)`   | `X` is a predicate reference value  |
| `date(X)`            | `X` is a date value                 |
| `datetime(X)`        | `X` is a datetime value             |
| `duration(X)`        | `X` is a duration value             |

These names may be used in predicate `type_list` declarations.

Infix operators such as `>=` or `<` are not part of the documented Doxa surface syntax. Use builtin forms such as `geq(A, B)` and `lt(A, B)`.

### Temporal Values

Doxa supports first-class temporal values: **date**, **datetime**, and **duration**.

#### Literal Syntax

| Type     | Syntax                         | Python type          | Example                          |
|----------|--------------------------------|----------------------|----------------------------------|
| date     | `d"YYYY-MM-DD"`                 | `datetime.date`      | `d"2024-06-15"`                   |
| datetime | `dt"YYYY-MM-DDTHH:MM:SSZ"`     | `datetime.datetime`  | `dt"2024-06-15T10:30:00Z"`       |
| duration | `dur"P..."`  (ISO 8601)         | `datetime.timedelta` | `dur"P30D"`, `dur"P1Y6M"`, `dur"PT2H30M"` |

Duration uses fixed-unit conversion: 1 year = 365 days, 1 month = 30 days.

#### Comparisons

Comparison builtins (`lt`, `leq`, `gt`, `geq`, `eq`, `ne`) work on temporal values of the **same kind**. Comparing across kinds (e.g. date vs. datetime) is a type error and yields no results.

#### Arithmetic

`add` and `sub` support temporal operands. `mul` and `div` are not supported for temporal values.

| Expression                    | Result type | Example                                       |
|-------------------------------|-------------|-----------------------------------------------|
| `date + duration`             | date        | `add(d"2024-01-01", dur"P30D", Result)`        |
| `date - duration`             | date        | `sub(d"2024-01-31", dur"P30D", Result)`        |
| `date - date`                 | duration    | `sub(d"2024-01-31", d"2024-01-01", Result)`    |
| `datetime + duration`         | datetime    | `add(dt"2024-01-01T00:00:00Z", dur"PT1H", R)`  |
| `datetime - duration`         | datetime    | `sub(dt"2024-01-01T01:00:00Z", dur"PT1H", R)`  |
| `datetime - datetime`         | duration    | `sub(dt"2024-01-02T00:00:00Z", dt"2024-01-01T00:00:00Z", R)` |
| `duration + duration`         | duration    | `add(dur"P1D", dur"PT12H", Result)`             |
| `duration - duration`         | duration    | `sub(dur"P2D", dur"P1D", Result)`               |

As with numeric arithmetic, temporal arithmetic can solve for any one unknown argument.

Invalid temporal operations (e.g. `date + date`, `mul` on temporal values) yield no results (fail-fast, no silent coercion).

## Query Options

Query options are specified in the query annotation `@{...}`.
Unknown query-option keys are rejected.

| Option       | Type                              |                     Default | Meaning                                         |
| ------------ | --------------------------------- | --------------------------: | ----------------------------------------------- |
| `query_time` | ISO-8601 datetime string          | current UTC evaluation time | Default time anchor for omitted time cutoffs    |
| `valid_at`   | ISO-8601 datetime string          |                `query_time` | Validity-time cutoff applied to `[vf, vt]`      |
| `known_at`   | ISO-8601 datetime string          |                `query_time` | Knowledge-time cutoff applied to `et`           |
| `epistemic_semantics` | object via Python API              | engine default semantics config | Per-query semantics override in the Python API; textual `@{...}` queries currently pass semantics fields flat rather than as nested object literals |
| `limit`      | int `>= 0`                        |                        none | Return at most N answers                        |
| `offset`     | int `>= 0`                        |                         `0` | Skip the first N answers                        |
| `order_by`   | string                            |                       empty | Comma-separated variable names used for sorting |
| `max_depth`  | int `> 0`                         |                        `24` | Hard cap on recursive rule depth                |
| `explain`    | `"false"`, `"true"`, or `"human"` |                   `"false"` | Explanation mode                                |
| `focus`      | string                            |                     `"all"` | Post-filtering and ranking mode                 |

Unknown query option keys are rejected.

### Focus Values

| Value             | Behaviour                                       |
| ----------------- | ----------------------------------------------- |
| `"all"`           | Do not filter answers                           |
| `"support"`       | Keep answers with positive support              |
| `"disbelief"`     | Keep answers with positive disbelief            |
| `"contradiction"` | Keep answers with both support and disbelief    |
| `"ignorance"`     | Keep answers with neither support nor disbelief |

### Time Resolution

The engine resolves time options as follows:

* `effective_query_time = query_time or current UTC time`
* `effective_valid_at = valid_at or effective_query_time`
* `effective_known_at = known_at or effective_query_time`

A visible belief record must satisfy both:

* `record.et <= effective_known_at`
* `effective_valid_at` falls inside the record validity window `[vf, vt]`, when those bounds are present

### Advanced Epistemic-Semantics Options

Queries also accept flat advanced options matching the epistemic-semantics configuration:

The current `QueryOptions` model includes `epistemic_semantics`. In the Python API, this field accepts a mapping/object with any subset of the fields below. In textual `@{...}` query annotations, pass these fields flat (for example `@{body_truth:"minimum"}`); nested object literals for `epistemic_semantics` are not currently parsed.

For textual queries, use the flat form, for example: `?- p(X) @{body_truth:"minimum"}`.

| Option                     | Supported values in the current model                      |
| -------------------------- | ---------------------------------------------------------- |
| `body_truth`               | `product`, `minimum`                                       |
| `body_falsity`             | `noisy_or`, `maximum`                                      |
| `rule_propagation`         | `body_times_rule_weights`                                  |
| `constraint_propagation`   | `body_times_constraint_weights_to_violation`               |
| `support_aggregation`      | `noisy_or`, `maximum`, `capped_sum`                        |
| `belnap_status`            | `nonzero`                                                  |
| `non_atom`                 | `crisp_filters`                                            |
| `rule_applicability`       | `body_truth_only`, `body_truth_discounted_by_body_falsity` |
| `constraint_applicability` | `body_truth_only`, `body_truth_discounted_by_body_falsity` |

These options control how evidence is propagated and aggregated during evaluation.

## Anonymous Variables

A bare `_` is an anonymous wildcard variable.

Current behavior:

* each `_` occurrence is internally renamed to a distinct generated variable such as `_0`, `_1`, `_2`, ...
* anonymous variables are not projected into answer bindings
* answer aggregation operates on projected bindings, so anonymous variables do not create visible output columns

Examples:

```doxa
?- edge(a, _)
?- edge(_, _)
```

## Terminal Slash Commands

Interactive-mode only. Prefix is `/-`.

| Command                                          | Effect                                                         |
| ------------------------------------------------ | -------------------------------------------------------------- |
| `/- dump [--ax\|--json] [--file <path>]`         | Print the current branch                                       |
| `/- dump --no-predicates`                        | Exclude predicate declarations from dump                       |
| `/- dump --no-belief-records`                    | Exclude facts from dump                                        |
| `/- dump --no-rules`                             | Exclude rules from dump                                        |
| `/- dump --no-constraints`                       | Exclude constraints from dump                                  |
| `/- info`                                        | Show session info: engine, backend, counts                     |
| `/- schema [--branch] [--query] [--file <path>]` | Print JSON schema for Branch and/or Query                      |
| `/- load <file> [--fix]`                         | Load and merge a `.doxa` or `.json` file                       |
| `/- unload predicate <name>/<arity>`             | Remove a predicate and related facts, rules, and constraints   |
| `/- unload entity <name>`                        | Remove an entity and facts referencing it                      |
| `/- unload rules`                                | Remove all rules                                               |
| `/- unload constraints`                          | Remove all constraints                                         |
| `/- unload all`                                  | Reset the branch to empty                                      |
| `/- search <pattern>`                            | Substring search over predicates, entities, belief records, and rules |
| `/- help`                                        | Show help                                                      |
| `/- exit` / `/- quit`                            | Exit the terminal                                              |

## Hard Constraints

* Facts must be ground; variables are not allowed as fact arguments.
* Compound terms are forbidden everywhere.
* Predicate arity must be at least 1.
* `pred` annotations accept `description` only.
* Duplicate `pred` declarations for the same name/arity are a hard error.
* If a `pred` type list is provided, it must match the declared arity.
* Builtin goals cannot be negated with `not`.
* `between` does not enumerate values; all three arguments must already be bound.
* Predicate names cannot reuse builtin names.
* Queries reject unknown option keys.

## Why No Compound Terms?

Doxa forbids compound terms because epistemic annotations attach to explicit propositions. A flat atom such as:

```doxa
parent(zeus, heracles) @{b:0.7, d:0.1}.
```

has a clear epistemic status. A nested term such as:

```doxa
owns(zeus, car(bmw, blue)) @{b:0.7, d:0.1}.
```

would hide additional semantic structure inside a single annotated record and make it unclear how inner structure should relate to belief, disbelief, provenance, explanation, and validation.

By keeping atoms flat, Doxa makes epistemic semantics and provenance handling substantially simpler.
