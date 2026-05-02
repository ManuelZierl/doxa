from enum import Enum


class LiteralType(str, Enum):
    str = "str"
    int = "int"
    float = "float"
    date = "date"
    datetime = "datetime"
    duration = "duration"
