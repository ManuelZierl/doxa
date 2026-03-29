from enum import Enum


class TermKind(str, Enum):
    var = "var"
    ent = "ent"
    lit = "lit"
    pred_ref = "pred_ref"
