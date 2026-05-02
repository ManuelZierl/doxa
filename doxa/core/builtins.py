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
    int = "int"
    string = "string"
    float = "float"
    entity = "entity"
    predicate_ref = "predicate_ref"
    date = "date"
    datetime = "datetime"
    duration = "duration"


# Expected argument count per builtin.
# Used by both BuiltinGoal (query goals) and RuleBuiltinGoal (rule body goals).
BUILTIN_ARITY: Dict[Builtin, int] = {
    Builtin.eq: 2,
    Builtin.ne: 2,
    Builtin.lt: 2,
    Builtin.leq: 2,
    Builtin.gt: 2,
    Builtin.geq: 2,
    Builtin.add: 3,
    Builtin.sub: 3,
    Builtin.mul: 3,
    Builtin.div: 3,
    Builtin.between: 3,
    Builtin.int: 1,
    Builtin.string: 1,
    Builtin.float: 1,
    Builtin.entity: 1,
    Builtin.predicate_ref: 1,
    Builtin.date: 1,
    Builtin.datetime: 1,
    Builtin.duration: 1,
}
