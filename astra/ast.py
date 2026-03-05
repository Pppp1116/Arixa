from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArbitraryIntType:
    signed: bool
    width: int

    def __str__(self) -> str:
        return f"{'i' if self.signed else 'u'}{self.width}"


def type_text(typ: Any) -> str:
    if isinstance(typ, ArbitraryIntType):
        return str(typ)
    return str(typ)


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
    where: dict[str, list[str]] = field(default_factory=dict)
    is_impl: bool = False
    pub: bool = False
    async_fn: bool = False
    unsafe: bool = False
    multiversion: bool = False
    symbol: str = ""
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ExternFnDecl:
    lib: str
    name: str
    params: list[tuple[str, str]]
    ret: str
    unsafe: bool = False
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
    fixed: bool = False


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
class DeferStmt:
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ComptimeStmt:
    body: list[Any]
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
    source: str | None = None


@dataclass
class StructDecl:
    name: str
    generics: list[str]
    fields: list[tuple[str, str]]
    methods: list[Any]
    pub: bool = False
    packed: bool = False
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
class DropStmt:
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class UnsafeStmt:
    body: list[Any]
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
    resolved_name: str | None = None


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
class WildcardPattern:
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class BindPattern:
    name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class VariantPattern:
    enum_name: str
    variant: str
    args: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class GuardPattern:
    pattern: Any
    cond: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AwaitExpr:
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


@dataclass
class CastExpr:
    expr: Any
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class SizeOfTypeExpr:
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AlignOfTypeExpr:
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class SizeOfValueExpr:
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AlignOfValueExpr:
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class BitSizeOfTypeExpr:
    type_name: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MaxValTypeExpr:
    type_name: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MinValTypeExpr:
    type_name: Any
    pos: int = 0
    line: int = 0
    col: int = 0
