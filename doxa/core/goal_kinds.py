from enum import Enum


class GoalKind(str, Enum):
    atom = "atom"
    builtin = "builtin"
