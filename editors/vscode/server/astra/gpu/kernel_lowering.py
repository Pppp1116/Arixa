"""Lowering pass that extracts ASTRA `gpu fn` declarations into kernel IR."""

from __future__ import annotations

from astra.ast import (
    ArrayLit,
    AssignStmt,
    Binary,
    BreakStmt,
    Call,
    CastExpr,
    ContinueStmt,
    ExprStmt,
    FieldExpr,
    FnDecl,
    ForStmt,
    IfStmt,
    IndexExpr,
    LetStmt,
    MatchStmt,
    Name,
    Program,
    ReturnStmt,
    StructLit,
    Unary,
    WhileStmt,
)
from astra.gpu.kernel_ir import KernelIR, KernelParamIR, KernelProgramIR
from astra.semantic import GPU_KERNEL_BUILTINS


def _walk_expr(expr, *, builtins: set[str]) -> None:
    if isinstance(expr, Call):
        if isinstance(expr.fn, FieldExpr) and isinstance(expr.fn.obj, Name) and expr.fn.obj.value == "gpu":
            if expr.fn.field in GPU_KERNEL_BUILTINS:
                builtins.add(expr.fn.field)
        _walk_expr(expr.fn, builtins=builtins)
        for arg in expr.args:
            _walk_expr(arg, builtins=builtins)
        return
    if isinstance(expr, FieldExpr):
        _walk_expr(expr.obj, builtins=builtins)
        return
    if isinstance(expr, IndexExpr):
        _walk_expr(expr.obj, builtins=builtins)
        _walk_expr(expr.index, builtins=builtins)
        return
    if isinstance(expr, Binary):
        _walk_expr(expr.left, builtins=builtins)
        _walk_expr(expr.right, builtins=builtins)
        return
    if isinstance(expr, Unary):
        _walk_expr(expr.expr, builtins=builtins)
        return
    if isinstance(expr, CastExpr):
        _walk_expr(expr.expr, builtins=builtins)
        return
    if isinstance(expr, ArrayLit):
        for el in expr.elements:
            _walk_expr(el, builtins=builtins)
        return
    if isinstance(expr, StructLit):
        for _, value in expr.fields:
            _walk_expr(value, builtins=builtins)
        return


def _walk_stmt(stmt, *, builtins: set[str]) -> int:
    count = 1
    if isinstance(stmt, LetStmt):
        _walk_expr(stmt.expr, builtins=builtins)
        return count
    if isinstance(stmt, AssignStmt):
        _walk_expr(stmt.target, builtins=builtins)
        _walk_expr(stmt.expr, builtins=builtins)
        return count
    if isinstance(stmt, ExprStmt):
        _walk_expr(stmt.expr, builtins=builtins)
        return count
    if isinstance(stmt, ReturnStmt):
        if stmt.expr is not None:
            _walk_expr(stmt.expr, builtins=builtins)
        return count
    if isinstance(stmt, IfStmt):
        _walk_expr(stmt.cond, builtins=builtins)
        for sub in stmt.then_body:
            count += _walk_stmt(sub, builtins=builtins)
        for sub in stmt.else_body:
            count += _walk_stmt(sub, builtins=builtins)
        return count
    if isinstance(stmt, WhileStmt):
        _walk_expr(stmt.cond, builtins=builtins)
        for sub in stmt.body:
            count += _walk_stmt(sub, builtins=builtins)
        return count
    if isinstance(stmt, ForStmt):
        _walk_expr(stmt.iterable, builtins=builtins)
        for sub in stmt.body:
            count += _walk_stmt(sub, builtins=builtins)
        return count
    if isinstance(stmt, MatchStmt):
        _walk_expr(stmt.expr, builtins=builtins)
        for pat, arm in stmt.arms:
            _walk_expr(pat, builtins=builtins)
            for sub in arm:
                count += _walk_stmt(sub, builtins=builtins)
        return count
    if isinstance(stmt, (BreakStmt, ContinueStmt)):
        return count
    return count


def lower_gpu_kernels(prog: Program) -> KernelProgramIR:
    """Extract kernel metadata from analyzed AST programs."""

    kernels: list[KernelIR] = []
    for item in prog.items:
        if not isinstance(item, FnDecl):
            continue
        if not bool(getattr(item, "gpu_kernel", False)):
            continue
        builtins: set[str] = set()
        statement_count = 0
        for stmt in item.body:
            statement_count += _walk_stmt(stmt, builtins=builtins)
        kernels.append(
            KernelIR(
                name=item.name,
                symbol=item.symbol or item.name,
                params=tuple(KernelParamIR(name=n, type_name=t) for n, t in item.params),
                ret=item.ret,
                source_file=getattr(item, "_source_filename", "<input>"),
                line=item.line,
                col=item.col,
                builtin_calls=tuple(sorted(builtins)),
                statement_count=statement_count,
            )
        )
    return KernelProgramIR(kernels=tuple(kernels))
