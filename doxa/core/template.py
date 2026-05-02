"""Core template types for the Doxa template system.

Templates are expansion mechanisms that receive parsed Doxa arguments
and emit structured DoxaStatement objects (facts, rules, constraints,
predicate declarations).
"""

from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

from doxa.core._parsing.annotation_parser import parse_ax_annotation
from doxa.core._parsing.parsing_utils import (
    get_pred_ref_regex,
    parse_python_string_literal,
    split_annotation_suffix,
    split_top_level,
)

if TYPE_CHECKING:
    from doxa.core.belief_record import BeliefRecord
    from doxa.core.constraint import Constraint
    from doxa.core.predicate import Predicate
    from doxa.core.rule import Rule

# ---------------------------------------------------------------------------
# DoxaStatement – union of all statement types a template may emit
# ---------------------------------------------------------------------------

if TYPE_CHECKING:
    DoxaStatement = Union["Predicate", "BeliefRecord", "Rule", "Constraint"]
else:
    DoxaStatement = Any

# ---------------------------------------------------------------------------
# Template argument types
# ---------------------------------------------------------------------------

_PRED_REF_RE = get_pred_ref_regex()
_VAR_RE = re.compile(r"^[A-Z_][A-Za-z0-9_]*$")
_ENTITY_RE = re.compile(r"^[a-z][A-Za-z0-9_]*$")
_QUOTED_ENTITY_RE = re.compile(r"^'[A-Za-z0-9_ ]*'$")
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$")
_DQ_STR_RE = re.compile(r'^"(?:\\.|[^\\\"\n\r])*"$')


class PredRefTemplateArg:
    """A predicate reference argument like ``foo/2``."""

    __slots__ = ("name", "arity")

    def __init__(self, name: str, arity: int) -> None:
        self.name = name
        self.arity = arity

    def __repr__(self) -> str:
        return f"PredRefTemplateArg({self.name}/{self.arity})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PredRefTemplateArg):
            return NotImplemented
        return self.name == other.name and self.arity == other.arity


class TypeListTemplateArg:
    """A bracket-delimited type list like ``[int, entity]``."""

    __slots__ = ("types",)

    def __init__(self, types: List[str]) -> None:
        self.types = types

    def __repr__(self) -> str:
        return f"TypeListTemplateArg({self.types})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TypeListTemplateArg):
            return NotImplemented
        return self.types == other.types


class VarTemplateArg:
    """A variable argument like ``X`` or ``_Tmp``."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"VarTemplateArg({self.name})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VarTemplateArg):
            return NotImplemented
        return self.name == other.name


class EntityTemplateArg:
    """An entity argument like ``alice`` or ``'Thomas'``."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"EntityTemplateArg({self.name})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EntityTemplateArg):
            return NotImplemented
        return self.name == other.name


class StringTemplateArg:
    """A string literal argument like ``"hello"``."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"StringTemplateArg({self.value!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StringTemplateArg):
            return NotImplemented
        return self.value == other.value


class IntTemplateArg:
    """An integer literal argument like ``42``."""

    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"IntTemplateArg({self.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IntTemplateArg):
            return NotImplemented
        return self.value == other.value


class FloatTemplateArg:
    """A float literal argument like ``3.14``."""

    __slots__ = ("value",)

    def __init__(self, value: float) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"FloatTemplateArg({self.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FloatTemplateArg):
            return NotImplemented
        return self.value == other.value


TemplateArg = Union[
    PredRefTemplateArg,
    TypeListTemplateArg,
    VarTemplateArg,
    EntityTemplateArg,
    StringTemplateArg,
    IntTemplateArg,
    FloatTemplateArg,
]

# ---------------------------------------------------------------------------
# TemplateCall / TemplateContext
# ---------------------------------------------------------------------------


class TemplateCall:
    """Parsed template invocation."""

    __slots__ = ("name", "args", "annotations")

    def __init__(
        self,
        name: str,
        args: List[TemplateArg],
        annotations: Dict[str, Any],
    ) -> None:
        self.name = name
        self.args = args
        self.annotations = annotations

    def __repr__(self) -> str:
        return f"TemplateCall(name={self.name!r}, args={self.args}, annotations={self.annotations})"


class TemplateContext:
    """Context information passed to templates during expansion."""

    __slots__ = ("module", "source_location")

    def __init__(
        self,
        module: str = "",
        source_location: Optional[str] = None,
    ) -> None:
        self.module = module
        self.source_location = source_location


# ---------------------------------------------------------------------------
# DoxaTemplate protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DoxaTemplate(Protocol):
    """Protocol for template implementations."""

    def expand(self, call: TemplateCall, ctx: TemplateContext) -> List[DoxaStatement]:
        """Expand a template call into a list of Doxa statements."""
        ...


# ---------------------------------------------------------------------------
# Template argument tokeniser
# ---------------------------------------------------------------------------


def _tokenise_template_args(raw: str) -> List[str]:
    """Split a template argument string into top-level tokens.

    Tokens are separated by whitespace at the top level.  Bracket groups
    ``[...]``, quoted strings ``"..."`` / ``'...'``, and annotation blocks
    ``@{...}`` are kept as single tokens.
    """
    tokens: List[str] = []
    buf: List[str] = []
    i = 0
    in_double = False
    in_single = False
    escape = False
    depth_bracket = 0

    while i < len(raw):
        ch = raw[i]

        if escape:
            buf.append(ch)
            escape = False
            i += 1
            continue

        if ch == "\\" and in_double:
            buf.append(ch)
            escape = True
            i += 1
            continue

        if ch == '"' and not in_single and depth_bracket == 0:
            buf.append(ch)
            in_double = not in_double
            i += 1
            continue

        if ch == "'" and not in_double and depth_bracket == 0:
            buf.append(ch)
            in_single = not in_single
            i += 1
            continue

        if in_double or in_single:
            buf.append(ch)
            i += 1
            continue

        if ch == "[":
            depth_bracket += 1
            buf.append(ch)
            i += 1
            continue

        if ch == "]":
            depth_bracket -= 1
            if depth_bracket < 0:
                raise ValueError("Unbalanced brackets in template arguments.")
            buf.append(ch)
            i += 1
            continue

        if depth_bracket > 0:
            buf.append(ch)
            i += 1
            continue

        # whitespace at top level → emit token
        if ch in (" ", "\t", "\n", "\r"):
            token = "".join(buf).strip()
            if token:
                tokens.append(token)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    if in_double or in_single:
        raise ValueError("Unterminated string in template arguments.")
    if depth_bracket != 0:
        raise ValueError("Unbalanced brackets in template arguments.")

    tail = "".join(buf).strip()
    if tail:
        tokens.append(tail)

    return tokens


def _parse_single_template_arg(token: str) -> TemplateArg:
    """Parse a single template argument token into a typed object."""
    # Bracket group → TypeListTemplateArg
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return TypeListTemplateArg(types=[])
        parts = split_top_level(inner)
        return TypeListTemplateArg(types=[p.strip() for p in parts])

    # Double-quoted string → StringTemplateArg
    if _DQ_STR_RE.fullmatch(token):
        return StringTemplateArg(value=parse_python_string_literal(token))

    # Predicate reference → PredRefTemplateArg
    if _PRED_REF_RE.fullmatch(token):
        name, arity_str = token.rsplit("/", 1)
        return PredRefTemplateArg(name=name, arity=int(arity_str))

    # Integer (before float, before entity)
    if _INT_RE.fullmatch(token):
        return IntTemplateArg(value=int(token))

    # Float
    if _FLOAT_RE.fullmatch(token):
        return FloatTemplateArg(value=float(token))

    # Variable
    if _VAR_RE.fullmatch(token):
        return VarTemplateArg(name=token)

    # Quoted entity
    if _QUOTED_ENTITY_RE.fullmatch(token):
        return EntityTemplateArg(name=token)

    # Unquoted entity / identifier
    if _ENTITY_RE.fullmatch(token):
        return EntityTemplateArg(name=token)

    raise ValueError(f"Invalid template argument token: {token!r}")


def parse_template_call(stmt: str) -> TemplateCall:
    """Parse a raw statement string into a TemplateCall.

    Expected form::

        template_name arg1 arg2 ... [@{key:val, ...}]

    The template name is the first whitespace-delimited token (must be a
    lowercase identifier).  The remaining string is split into positional
    arguments and an optional trailing annotation block.
    """
    s = stmt.strip()
    if not s:
        raise ValueError("Template call must not be empty.")

    # Extract template name (first token)
    m = re.match(r"^([a-z][A-Za-z0-9_]*)\b", s)
    if not m:
        raise ValueError(
            f"Invalid template call: expected lowercase identifier, got {s!r}"
        )

    name = m.group(1)
    rest = s[m.end() :].strip()

    # Split off annotation suffix
    body, annotation_str = split_annotation_suffix(rest)

    # Parse annotations
    annotations: Dict[str, Any] = {}
    if annotation_str:
        annotations = parse_ax_annotation(annotation_str)

    # Tokenise and parse positional arguments
    args: List[TemplateArg] = []
    if body.strip():
        tokens = _tokenise_template_args(body.strip())
        for token in tokens:
            args.append(_parse_single_template_arg(token))

    return TemplateCall(name=name, args=args, annotations=annotations)


# ---------------------------------------------------------------------------
# use templates import parsing
# ---------------------------------------------------------------------------

_USE_TEMPLATES_RE = re.compile(
    r"""
    ^\s*use\s+templates\s+
    "(?P<module>[^"]+)"
    (?:\s+\[(?P<imports>[^\]]*)\])?
    \s*$
    """,
    re.VERBOSE,
)


class TemplateImport:
    """Parsed ``use templates`` statement."""

    __slots__ = ("module", "names")

    def __init__(
        self, module: str, names: Optional[List[tuple[str, str]]] = None
    ) -> None:
        self.module = module
        # names is a list of (original_name, alias) tuples; None means import all
        self.names = names

    def __repr__(self) -> str:
        return f"TemplateImport(module={self.module!r}, names={self.names})"


def parse_use_templates(stmt: str) -> TemplateImport:
    """Parse a ``use templates "module" [optional imports]`` statement."""
    m = _USE_TEMPLATES_RE.fullmatch(stmt.strip())
    if not m:
        raise ValueError(f"Invalid 'use templates' statement: {stmt!r}")

    module = m.group("module")
    imports_str = m.group("imports")

    if imports_str is None:
        return TemplateImport(module=module, names=None)

    # Parse the import list: name1, name2 as alias2, ...
    names: List[tuple[str, str]] = []
    if imports_str.strip():
        parts = split_top_level(imports_str.strip())
        for part in parts:
            part = part.strip()
            # Check for "name as alias"
            as_match = re.fullmatch(
                r"([a-z][A-Za-z0-9_]*)\s+as\s+([a-z][A-Za-z0-9_]*)", part
            )
            if as_match:
                names.append((as_match.group(1), as_match.group(2)))
            elif re.fullmatch(r"[a-z][A-Za-z0-9_]*", part):
                names.append((part, part))
            else:
                raise ValueError(f"Invalid template import name: {part!r}")

    return TemplateImport(module=module, names=names)
