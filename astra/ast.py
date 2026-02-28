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
    pub: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class LetStmt:
    name: str
    expr: Any
    mut: bool = False
    type_name: str | None = None
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ForStmt:
    init: Any
    cond: Any
    step: Any
    body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class BreakStmt:
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ContinueStmt:
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AssignStmt:
    target: Any
    op: str
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ImportDecl:
    path: list[str]
    alias: str | None = None
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class StructDecl:
    name: str
    generics: list[str]
    fields: list[tuple[str, str]]
    methods: list[Any]
    pub: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class EnumDecl:
    name: str
    generics: list[str]
    variants: list[tuple[str, list[str]]]
    pub: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class TypeAliasDecl:
    name: str
    generics: list[str]
    target: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MatchStmt:
    expr: Any
    arms: list[tuple[Any, list[Any]]]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ReturnStmt:
    expr: Any | None
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class IfStmt:
    cond: Any
    then_body: list[Any]
    else_body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class WhileStmt:
    cond: Any
    body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ExprStmt:
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Call:
    fn: Any
    args: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Name:
    value: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Literal:
    value: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class BoolLit:
    value: bool
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class NilLit:
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Binary:
    op: str
    left: Any
    right: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Unary:
    op: str
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class IndexExpr:
    obj: Any
    index: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class FieldExpr:
    obj: Any
    field: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ArrayLit:
    elements: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class StructLit:
    name: str
    fields: list[tuple[str, Any]]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class TypeAnnotated:
    expr: Any
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0
