from enum import Enum
from typing import Dict


class Builtin(str, Enum):
    eq = "eq"
    ne = "ne"
    lt = "lt"
    leq = "leq"
    gt = "gt"
    geq = "geq"
    add = "add"
    sub = "sub"
    mul = "mul"
    div = "div"
    between = "between"


# Expected argument count per builtin.
# Used by both BuiltinGoal (query goals) and RuleBuiltinGoal (rule body goals).
BUILTIN_ARITY: Dict[str, int] = {
    "eq": 2,
    "ne": 2,
    "lt": 2,
    "leq": 2,
    "gt": 2,
    "geq": 2,
    "add": 3,
    "sub": 3,
    "mul": 3,
    "div": 3,
    "between": 3,
}
