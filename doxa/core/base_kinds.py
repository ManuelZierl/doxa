from enum import Enum


class BaseKind(str, Enum):
    belief_arg = "belief_arg"
    belief_record = "belief_record"
    branch = "branch"
    constraint = "constraint"
    constraint_goal = "constraint_goal"  # deprecated, use goal
    constraint_goal_arg = "constraint_goal_arg"  # deprecated, use goal_arg
    goal = "goal"
    goal_arg = "goal_arg"
    entity = "entity"
    literal = "literal"
    predicate = "predicate"
    query = "query"
    rule = "rule"
    rule_head_arg = "rule_head_arg"
    rule_goal = "rule_goal"
    rule_goal_arg = "rule_goal_arg"
    var = "var"
