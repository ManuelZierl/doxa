from enum import Enum


class TermKind(str, Enum):
    var = "var"
    ent = "ent"
    lit = "lit"
