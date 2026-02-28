from dataclasses import dataclass, field
from typing import Any

@dataclass
class Program:
    items: list[Any] = field(default_factory=list)

@dataclass
class FnDecl:
    name: str
    generics: list[str]
    params: list[tuple[str, str]]
    ret: str
    body: list[Any]

@dataclass
class LetStmt:
    name: str
    expr: Any

@dataclass
class ReturnStmt:
    expr: Any | None

@dataclass
class IfStmt:
    cond: Any
    then_body: list[Any]
    else_body: list[Any]

@dataclass
class WhileStmt:
    cond: Any
    body: list[Any]

@dataclass
class ExprStmt:
    expr: Any

@dataclass
class Call:
    fn: str
    args: list[Any]

@dataclass
class Name:
    value: str

@dataclass
class Literal:
    value: Any

@dataclass
class Binary:
    op: str
    left: Any
    right: Any
