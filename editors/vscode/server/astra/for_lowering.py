"""Lowering pass that rewrites high-level `for` loops into core constructs."""

from __future__ import annotations

from astra.ast import (
    AssignStmt,
    Binary,
    BreakStmt,
    Call,
    ComptimeStmt,
    ContinueStmt,
    ExprStmt,
    FnDecl,
    IteratorForStmt,
    IfStmt,
    IndexExpr,
    LetStmt,
    Literal,
    MatchStmt,
    Name,
    Program,
    RangeExpr,
    ReturnStmt,
    UnsafeStmt,
    WhileStmt,
)


def lower_for_loops(prog: Program) -> Program:
    """Execute the `lower_for_loops` routine.
    
    Parameters:
        prog: Program AST to read or mutate.
    
    Returns:
        Value described by the function return annotation.
    """
    if getattr(prog, "_for_lowered", False):
        return prog
    counter = {"n": 0}

    def _fresh(base: str) -> str:
        counter["n"] += 1
        return f"__for_{base}_{counter['n']}"

    def _patch_continues(stmts: list[object], step: AssignStmt) -> list[object]:
        out: list[object] = []
        for st in stmts:
            if isinstance(st, (WhileStmt, IteratorForStmt)):
                out.append(st)
                continue
            if isinstance(st, ContinueStmt):
                out.append(
                    AssignStmt(
                        Name(step.target.value, step.target.pos, step.target.line, step.target.col),
                        step.op,
                        Literal(step.expr.value, step.expr.pos, step.expr.line, step.expr.col),
                        step.pos,
                        step.line,
                        step.col,
                    )
                )
                out.append(st)
                continue
            if isinstance(st, IfStmt):
                st.then_body = _patch_continues(st.then_body, step)
                st.else_body = _patch_continues(st.else_body, step)
                out.append(st)
                continue
            if isinstance(st, MatchStmt):
                st.arms = [(pat, _patch_continues(body, step)) for (pat, body) in st.arms]
                out.append(st)
                continue
            if isinstance(st, UnsafeStmt):
                st.body = _patch_continues(st.body, step)
                out.append(st)
                continue
            if isinstance(st, ComptimeStmt):
                st.body = _patch_continues(st.body, step)
                out.append(st)
                continue
            out.append(st)
        return out

    def _lower_stmt(st: object) -> list[object]:
        if isinstance(st, IfStmt):
            st.then_body = _lower_block(st.then_body)
            st.else_body = _lower_block(st.else_body)
            return [st]
        if isinstance(st, WhileStmt):
            st.body = _lower_block(st.body)
            return [st]
        if isinstance(st, MatchStmt):
            st.arms = [(pat, _lower_block(body) if isinstance(body, list) else body) for (pat, body) in st.arms]
            return [st]
        if isinstance(st, UnsafeStmt):
            st.body = _lower_block(st.body)
            return [st]
        if isinstance(st, ComptimeStmt):
            st.body = _lower_block(st.body)
            return [st]
        if not isinstance(st, IteratorForStmt):
            return [st]

        lowered_body = _lower_block(st.body)

        if isinstance(st.iterable, RangeExpr):
            end_name = _fresh("end")
            idx_name = _fresh("idx")
            end_init = LetStmt(end_name, st.iterable.end, False, None, st.pos, st.line, st.col)
            idx_init = LetStmt(idx_name, st.iterable.start, True, None, st.pos, st.line, st.col)
            cond = Binary(
                "<=" if st.iterable.inclusive else "<",
                Name(idx_name, st.pos, st.line, st.col),
                Name(end_name, st.pos, st.line, st.col),
                st.pos,
                st.line,
                st.col,
            )
            step = AssignStmt(
                Name(idx_name, st.pos, st.line, st.col),
                "+=",
                Literal(1, st.pos, st.line, st.col),
                st.pos,
                st.line,
                st.col,
            )
            loop_var = LetStmt(st.var, Name(idx_name, st.pos, st.line, st.col), False, None, st.pos, st.line, st.col)
            patched = _patch_continues(lowered_body, step)
            w = WhileStmt(cond, [loop_var, *patched, step], st.pos, st.line, st.col)
            return [end_init, idx_init, w]

        iter_name = _fresh("iter")
        len_name = _fresh("len")
        idx_name = _fresh("idx")
        iter_init = LetStmt(iter_name, st.iterable, False, None, st.pos, st.line, st.col)
        len_init = LetStmt(
            len_name,
            Call(Name("len", st.pos, st.line, st.col), [Name(iter_name, st.pos, st.line, st.col)], st.pos, st.line, st.col),
            False,
            None,
            st.pos,
            st.line,
            st.col,
        )
        idx_init = LetStmt(idx_name, Literal(0, st.pos, st.line, st.col), True, None, st.pos, st.line, st.col)
        cond = Binary(
            "<",
            Name(idx_name, st.pos, st.line, st.col),
            Name(len_name, st.pos, st.line, st.col),
            st.pos,
            st.line,
            st.col,
        )
        step = AssignStmt(
            Name(idx_name, st.pos, st.line, st.col),
            "+=",
            Literal(1, st.pos, st.line, st.col),
            st.pos,
            st.line,
            st.col,
        )
        elem_expr = IndexExpr(
            Name(iter_name, st.pos, st.line, st.col),
            Name(idx_name, st.pos, st.line, st.col),
            st.pos,
            st.line,
            st.col,
        )
        loop_var = LetStmt(st.var, elem_expr, False, None, st.pos, st.line, st.col)
        patched = _patch_continues(lowered_body, step)
        w = WhileStmt(cond, [loop_var, *patched, step], st.pos, st.line, st.col)
        return [iter_init, len_init, idx_init, w]

    def _lower_block(stmts: list[object]) -> list[object]:
        out: list[object] = []
        for st in stmts:
            out.extend(_lower_stmt(st))
        return out

    for item in prog.items:
        if isinstance(item, FnDecl):
            item.body = _lower_block(item.body)
    setattr(prog, "_for_lowered", True)
    return prog
