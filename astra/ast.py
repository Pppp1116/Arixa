"""Core abstract syntax tree node definitions used across the compiler pipeline."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArbitraryIntType:
    """AST node representing arbitrary int type.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    signed: bool
    width: int

    def __str__(self) -> str:
        return f"{'i' if self.signed else 'u'}{self.width}"


def type_text(typ: Any) -> str:
    """Execute the `type_text` routine.
    
    Parameters:
        typ: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    if isinstance(typ, ArbitraryIntType):
        return str(typ)
    return str(typ)


@dataclass
class Program:
    """AST node representing program.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    items: list[Any] = field(default_factory=list)
    ffi_libs: set[str] = field(default_factory=set)


@dataclass
class FnDecl:
    """AST node representing fn decl.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    generics: list[str]
    params: list[tuple[str, str]]
    ret: str
    body: list[Any]
    pub: bool = False
    async_fn: bool = False
    unsafe: bool = False
    symbol: str = ""
    doc: str = ""
    where_bounds: list[tuple[str, str]] = field(default_factory=list)
    gpu_kernel: bool = False
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ExternFnDecl:
    """AST node representing extern fn decl.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    params: list[tuple[str, str]]
    ret: str
    is_variadic: bool = False
    link_libs: list[str] = field(default_factory=list)
    lib: str = ""
    unsafe: bool = False
    pub: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0

    @property
    def return_type(self) -> str:
        return self.ret

    @property
    def legacy_lib(self) -> str:
        if self.lib:
            return self.lib
        if self.link_libs:
            return self.link_libs[0]
        return "c"

    def __post_init__(self) -> None:
        if self.lib and self.lib not in self.link_libs:
            self.link_libs.insert(0, self.lib)


@dataclass
class LetStmt:
    """AST node representing binding declaration stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    expr: Any
    mut: bool = False
    type_name: str | None = None
    pos: int = 0
    line: int = 0
    col: int = 0
    # For `x = ...` (without `mut`/`set`), semantic analysis decides whether this
    # is a declaration or reassignment (dual mode) based on prior bindings.
    reassign_if_exists: bool = False


@dataclass
class ForStmt:
    """AST node representing for stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    var: str
    iterable: Any
    body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class BreakStmt:
    """AST node representing break stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ContinueStmt:
    """AST node representing continue stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class DeferStmt:
    """AST node representing defer stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ComptimeStmt:
    """AST node representing comptime stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AssignStmt:
    """AST node representing assign stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    target: Any
    op: str
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0
    explicit_set: bool = False


@dataclass
class ImportDecl:
    """AST node representing import decl.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    path: list[str]
    alias: str | None = None
    pos: int = 0
    line: int = 0
    col: int = 0
    source: str | None = None


@dataclass
class StructDecl:
    """AST node representing struct decl.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    generics: list[str]
    fields: list[tuple[str, str]]
    methods: list[Any]
    derives: list[str] = field(default_factory=list)
    pub: bool = False
    packed: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class EnumDecl:
    """AST node representing enum decl.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    generics: list[str]
    variants: list[tuple[str, list[str]]]
    derives: list[str] = field(default_factory=list)
    pub: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class TypeAliasDecl:
    """AST node representing type alias decl.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    generics: list[str]
    target: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ConstDecl:
    """AST node representing const decl.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    expr: Any
    pub: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class TraitDecl:
    """AST node representing trait declaration."""
    name: str
    methods: list[tuple[str, list[tuple[str, str]], str]]
    pub: bool = False
    doc: str = ""
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MatchStmt:
    """AST node representing match stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    arms: list[tuple[Any, list[Any]]]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ReturnStmt:
    """AST node representing return stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any | None
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class IfStmt:
    """AST node representing if stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    cond: Any
    then_body: list[Any]
    else_body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class WhileStmt:
    """AST node representing while stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    cond: Any
    body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class EnhancedWhileStmt:
    """AST node representing enhanced while stmt with inline variable declaration.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    var_decl: Any  # Variable declaration (LetStmt or None)
    cond: Any      # Condition expression
    body: list[Any]  # Loop body
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class EnhancedForStmt:
    """AST node representing enhanced for stmt with init, cond, step.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    var_name: str      # Loop variable name
    init_expr: Any     # Initialization expression
    cond_expr: Any     # Condition expression
    step_expr: Any     # Step expression
    body: list[Any]    # Loop body
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class IteratorForStmt:
    """AST node representing iterator-style for loop.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    var_name: str      # Iterator variable name
    iterable: Any      # Iterable expression
    body: list[Any]    # Loop body
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MethodCall:
    """AST node representing method call.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    obj: Any
    method: str
    args: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class VectorLiteral:
    """AST node representing vector literal.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    elements: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MapLiteral:
    """AST node representing map literal.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pairs: list[tuple[Any, Any]]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class SetLiteral:
    """AST node representing set literal.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    elements: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class StructLiteral:
    """AST node representing struct literal with positional arguments.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    struct_name: str
    args: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class DestructuringPattern:
    """AST node representing destructuring pattern.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    struct_name: str
    fields: list[tuple[str, str]]  # (field_name, bind_name)
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class EnhancedPattern:
    """AST node representing enhanced pattern with guards.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    patterns: list[Any]
    guard: Any  # Guard expression or None
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class IfExpression:
    """AST node representing if expression.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    cond: Any
    then_expr: Any
    else_expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class DeferStmt:
    """AST node representing defer statement.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ExprStmt:
    """AST node representing expr stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class UnsafeStmt:
    """AST node representing unsafe stmt.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    body: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Call:
    """AST node representing call.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    fn: Any
    args: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0
    resolved_name: str | None = None


@dataclass
class Name:
    """AST node representing name.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    value: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Literal:
    """AST node representing literal.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    value: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class BoolLit:
    """AST node representing bool lit.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    value: bool
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class NilLit:
    """AST node representing nil lit.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Binary:
    """AST node representing binary.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    op: str
    left: Any
    right: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class Unary:
    """AST node representing unary.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    op: str
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class WildcardPattern:
    """AST node representing wildcard pattern.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class OrPattern:
    """AST node representing `p1 | p2 | ...` match pattern alternatives.

    This type is part of Astra's public compiler/tooling surface.
    """
    patterns: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class GuardedPattern:
    """AST node representing `pattern if <expr>` in match arms.

    This type is part of Astra's public compiler/tooling surface.
    """
    pattern: Any
    guard: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AwaitExpr:
    """AST node representing await expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class TryExpr:
    """AST node representing try expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class StringInterpolation:
    """AST node representing string interpolation.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    parts: list[str]  # String literal parts
    exprs: list[Any]  # Interpolated expressions
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class IndexExpr:
    """AST node representing index expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    obj: Any
    index: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class FieldExpr:
    """AST node representing field expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    obj: Any
    field: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class ArrayLit:
    """AST node representing array lit.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    elements: list[Any]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class StructLit:
    """AST node representing struct lit.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    name: str
    fields: list[tuple[str, Any]]
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class TypeAnnotated:
    """AST node representing type annotated.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class CastExpr:
    """AST node representing cast expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class SizeOfTypeExpr:
    """AST node representing size of type expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AlignOfTypeExpr:
    """AST node representing align of type expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    type_name: str
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class SizeOfValueExpr:
    """AST node representing size of value expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class AlignOfValueExpr:
    """AST node representing align of value expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    expr: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class BitSizeOfTypeExpr:
    """AST node representing bit size of type expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    type_name: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MaxValTypeExpr:
    """AST node representing max val type expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    type_name: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class MinValTypeExpr:
    """AST node representing min val type expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    type_name: Any
    pos: int = 0
    line: int = 0
    col: int = 0


@dataclass
class RangeExpr:
    """AST node representing range expr.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    start: Any
    end: Any
    inclusive: bool = False
    pos: int = 0
    line: int = 0
    col: int = 0
