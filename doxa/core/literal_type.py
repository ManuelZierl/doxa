from enum import Enum


class LiteralType(str, Enum):
    str = "str"
    int = "int"
    float = "float"
    bool = "bool"
