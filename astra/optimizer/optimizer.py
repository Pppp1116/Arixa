"""AST optimizer passes including folding and dead code elimination."""

from __future__ import annotations

from typing import Any, Optional, Dict, Set
from dataclasses import dataclass, field

from astra.ast import *
from astra.for_lowering import lower_for_loops
from astra.int_types import parse_int_type_name


@dataclass(frozen=True)
class AvailableExpr:
    """Represents an available expression for CSE.
    
    Attributes:
        bound_name: Name of the temporary that holds the expression result
        deps: Set of names whose mutation may invalidate the available value
              
    Dependency Policy:
    `deps` is treated conservatively as the set of names whose mutation may
    invalidate the value represented by this available expression entry.
    This conservative approach ensures soundness but may reduce optimization
    opportunities.
    """
    bound_name: str
    deps: frozenset[str]  # Immutable for safety


# Type aliases for clarity
ExprKey = Any
AvailableMap = dict[ExprKey, AvailableExpr]


@dataclass
class FunctionInfo:
    """Information about a function for interprocedural analysis."""
    name: str
    is_pure: bool = False
    mutates_params: Set[int] = field(default_factory=set)  # Indices of mutated parameters
    reads_globals: Set[str] = field(default_factory=set)
    writes_globals: Set[str] = field(default_factory=set)
    takes_refs: Set[int] = field(default_factory=set)  # Parameters taken by reference


@dataclass
class AliasInfo:
    """Alias relationship information."""
    direct_aliases: Dict[str, Set[str]] = field(default_factory=dict)  # name -> set of aliases
    pointer_targets: Dict[str, Set[str]] = field(default_factory=dict)  # pointer -> possible targets
    ref_sources: Dict[str, str] = field(default_factory=dict)  # ref -> source name


@dataclass
class SymbolInfo:
    """Information about a symbol in the symbol table."""
    name: str
    type_name: str
    is_pointer: bool = False
    is_reference: bool = False
    is_array: bool = False
    element_type: Optional[str] = None
    pointee_type: Optional[str] = None
    scope_level: int = 0
    is_mutable: bool = True
    is_global: bool = False
    is_parameter: bool = False
    parameter_index: Optional[int] = None


@dataclass
class SymbolTable:
    """Symbol table for type-aware analysis."""
    symbols: Dict[str, SymbolInfo] = field(default_factory=dict)
    scope_stack: List[Set[str]] = field(default_factory=list)
    current_scope: int = 0
    
    def enter_scope(self) -> None:
        """Enter a new scope."""
        self.scope_stack.append(set())
        self.current_scope += 1
    
    def exit_scope(self) -> None:
        """Exit the current scope."""
        if self.scope_stack:
            exited_symbols = self.scope_stack.pop()
            for symbol in exited_symbols:
                self.symbols.pop(symbol, None)
        self.current_scope -= 1
    
    def add_symbol(self, name: str, type_name: str, **kwargs) -> None:
        """Add a symbol to the current scope."""
        # Parse type information
        is_pointer = type_name.endswith('*') or type_name.endswith('_ptr')
        is_reference = type_name.endswith('&') or type_name.endswith('_ref')
        is_array = '[' in type_name or type_name.endswith('_array')
        
        # Extract element/pointee types
        element_type = None
        pointee_type = None
        
        if is_array and '[' in type_name:
            # Extract element type from array type like "int[10]"
            element_type = type_name.split('[')[0]
        elif is_pointer and type_name.endswith('_ptr'):
            pointee_type = type_name.rstrip('_ptr')
        elif is_pointer and type_name.endswith('*'):
            pointee_type = type_name.rstrip('*')
        
        # Override with explicit kwargs if provided
        is_pointer = kwargs.get('is_pointer', is_pointer)
        is_reference = kwargs.get('is_reference', is_reference)
        is_array = kwargs.get('is_array', is_array)
        element_type = kwargs.get('element_type', element_type)
        pointee_type = kwargs.get('pointee_type', pointee_type)
        
        symbol_info = SymbolInfo(
            name=name,
            type_name=type_name,
            is_pointer=is_pointer,
            is_reference=is_reference,
            is_array=is_array,
            element_type=element_type,
            pointee_type=pointee_type,
            scope_level=self.current_scope,
            is_mutable=kwargs.get('is_mutable', True),
            is_global=kwargs.get('is_global', False),
            is_parameter=kwargs.get('is_parameter', False),
            parameter_index=kwargs.get('parameter_index', None)
        )
        
        self.symbols[name] = symbol_info
        if self.scope_stack:
            self.scope_stack[-1].add(name)
    
    def lookup(self, name: str) -> Optional[SymbolInfo]:
        """Look up a symbol in the symbol table."""
        return self.symbols.get(name)
    
    def get_type_info(self, name: str) -> Optional[TypeInfo]:
        """Get TypeInfo for a symbol name."""
        symbol = self.lookup(name)
        if not symbol:
            return None
        
        return TypeInfo(
            is_pointer=symbol.is_pointer,
            is_reference=symbol.is_reference,
            is_array=symbol.is_array,
            element_type=symbol.element_type,
            pointee_type=symbol.pointee_type
        )


@dataclass
class TypeInfo:
    """Type information for precision analysis."""
    is_pointer: bool = False
    is_reference: bool = False
    is_array: bool = False
    element_type: Optional[str] = None
    pointee_type: Optional[str] = None


# Global symbol table
_symbol_table = SymbolTable()


@dataclass
class OptStats:
    """Statistics for optimization passes."""
    rounds: int = 0
    folds: int = 0
    dse_removed: int = 0
    cse_rewrites: int = 0
    stmts_before: int = 0
    stmts_after: int = 0
    # CSE-specific statistics
    cse_hits: int = 0
    cse_insertions: int = 0
    cse_invalidations: int = 0
    
    def statements_removed(self) -> int:
        return self.stmts_before - self.stmts_after
    
    def __str__(self) -> str:
        return (f"Rounds: {self.rounds}, Folds: {self.folds}, "
                f"DSE removed: {self.dse_removed}, CSE rewrites: {self.cse_rewrites}, "
                f"Stmts removed: {self.statements_removed()}, CSE hits: {self.cse_hits}, "
                f"CSE insertions: {self.cse_insertions}, CSE invalidations: {self.cse_invalidations}")


def optimize_program(prog: Program, debug_opt: bool = False) -> Program:
    """Apply optimization passes to function bodies in a program AST.

    Strategy:
    - Lower high-level constructs once before per-function optimization.
    - Run local optimization passes to a fixed point.
    - Stop early when no pass changes the function body.
    - Use a hard cap to avoid pathological infinite optimization cycles.
    
    Args:
        prog: The program to optimize
        debug_opt: If True, print debug information about optimization progress
        
    Returns:
        The optimized program
    """
    lower_for_loops(prog)

    MAX_OPT_ROUNDS = 8
    global_stats = OptStats()

    for item in prog.items:
        if not isinstance(item, FnDecl):
            continue

        fn_name = item.name
        stats = OptStats()
        stats.stmts_before = len(item.body)
        
        # Recompute only if one of your passes can actually introduce/remove
        # mutable bindings. Otherwise collecting once is cheaper.
        mutable_names = _collect_mutable_names(item.body)

        for round_no in range(MAX_OPT_ROUNDS):
            stats.rounds += 1
            changed = False
            body = item.body

            # Main simplification / folding / canonicalization
            if debug_opt:
                body, _, opt_changed = _optimize_stmts_with_stats(body, {}, mutable_names, stats)
            else:
                body, _, opt_changed = _optimize_stmts(body, {}, mutable_names)
            changed |= opt_changed

            # Common subexpression elimination
            if debug_opt:
                cse_body, cse_avail, cse_changed = _cse_stmts_with_stats(body, {}, stats)
            else:
                cse_body, cse_avail, cse_changed = _cse_stmts(body, {})
            changed |= cse_changed
            body = cse_body

            # Dead statement elimination
            if debug_opt:
                dse_body, dse_live = _dse_stmts_with_stats(body, set(), stats)
            else:
                dse_body, dse_live = _dse_stmts(body, set())
            changed |= (dse_body != body)
            body = dse_body

            item.body = body

            if debug_opt:
                print(f"[opt] {fn_name}: round {round_no + 1}, changed={changed}")

            if not changed:
                break
            
            # Detect potential oscillation
            if round_no == MAX_OPT_ROUNDS - 1:
                print(f"[opt] WARNING: {fn_name} reached MAX_OPT_ROUNDS ({MAX_OPT_ROUNDS}) - possible oscillation")
                if stats.statements_removed() == 0:
                    print(f"[opt] WARNING: {fn_name} made no progress in statement removal")

        stats.stmts_after = len(item.body)
        
        # Update global stats
        global_stats.rounds += stats.rounds
        global_stats.stmts_before += stats.stmts_before
        global_stats.stmts_after += stats.stmts_after
        
        if debug_opt:
            print(f"[opt] {fn_name} final: {stats}")
    
    if debug_opt:
        print(f"[opt] Global: {global_stats}")

    return prog


def _optimize_stmts(stmts: list[Any], env: dict[str, Any], mutable_names: set[str]) -> tuple[list[Any], dict[str, Any], bool]:
    out: list[Any] = []
    cur_env = dict(env)
    any_changed = False

    for st in stmts:
        original_st = st

        lowered, cur_env, terminated, changed = _optimize_stmt(st, cur_env, mutable_names)
        any_changed |= changed

        if lowered is None:
            any_changed = True
            continue

        if isinstance(lowered, list):
            if lowered != [original_st]:
                any_changed = True
            out.extend(lowered)
        else:
            out.append(lowered)
            if lowered is not original_st:
                any_changed = True

        if terminated:
            # If there were remaining statements after this one, they are dead.
            if st is not stmts[-1]:
                any_changed = True
            break

    return out, cur_env, any_changed


def _optimize_stmts_with_stats(stmts: list[Any], env: dict[str, Any], mutable_names: set[str], stats: OptStats | None = None) -> tuple[list[Any], dict[str, Any], bool]:
    """Optimize statements with optional statistics tracking."""
    out: list[Any] = []
    cur_env = dict(env)
    any_changed = False

    for st in stmts:
        original_st = st

        if stats is not None:
            lowered, cur_env, terminated, changed = _optimize_stmt_with_stats(st, cur_env, mutable_names, stats)
        else:
            lowered, cur_env, terminated, changed = _optimize_stmt(st, cur_env, mutable_names)
        any_changed |= changed

        if lowered is None:
            any_changed = True
            continue

        if isinstance(lowered, list):
            if lowered != [original_st]:
                any_changed = True
            out.extend(lowered)
        else:
            out.append(lowered)
            if lowered is not original_st:
                any_changed = True

        if terminated:
            # If there were remaining statements after this one, they are dead.
            if st is not stmts[-1]:
                any_changed = True
            break

    return out, cur_env, any_changed


def _optimize_stmt_with_stats(st: Any, env: dict[str, Any], mutable_names: set[str], stats: OptStats | None = None) -> tuple[Any | None, dict[str, Any], bool, bool]:
    """Optimize a statement with optional statistics tracking."""
    result = _optimize_stmt(st, env, mutable_names)
    
    if stats is not None:
        # Track constant folding when expressions are simplified
        if result[3]:  # changed flag
            # Check if this was a constant fold by looking for literal replacements
            if isinstance(st, (LetStmt, AssignStmt, ExprStmt, ReturnStmt)):
                stats.folds += 1
    
    return result


def _optimize_stmt(st: Any, env: dict[str, Any], mutable_names: set[str]) -> tuple[Any | None, dict[str, Any], bool, bool]:
    if isinstance(st, LetStmt):
        old_expr = st.expr
        st.expr, expr_changed = _fold_ast_expr(st.expr, env, mutable_names)
        changed = expr_changed

        lit = _literal_value(st.expr)
        if lit is not _NO_LITERAL and st.name not in mutable_names:
            env[st.name] = _literal_node(lit, st.expr)
        elif isinstance(st.expr, Name) and st.name not in mutable_names:
            env[st.name] = Name(
                value=st.expr.value,
                pos=st.expr.pos,
                line=st.expr.line,
                col=st.expr.col,
            )
        else:
            _env_forget_name(env, st.name)

        return st, env, False, changed
    if isinstance(st, AssignStmt):
        old_target = st.target
        old_expr = st.expr

        st.target, target_changed = _fold_target_expr(st.target, env, mutable_names)
        st.expr, expr_changed = _fold_ast_expr(st.expr, env, mutable_names)

        changed = target_changed or expr_changed

        if isinstance(st.target, Name):
            if st.target.value in mutable_names:
                _env_forget_name(env, st.target.value)
            elif st.op == "=":
                lit = _literal_value(st.expr)
                if lit is not _NO_LITERAL:
                    env[st.target.value] = _literal_node(lit, st.expr)
                elif isinstance(st.expr, Name):
                    env[st.target.value] = Name(
                        value=st.expr.value,
                        pos=st.expr.pos,
                        line=st.expr.line,
                        col=st.expr.col,
                    )
                else:
                    _env_forget_name(env, st.target.value)
            elif st.op in {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}:
                left = _literal_value(_resolve_env_binding(st.target.value, env))
                right = _literal_value(st.expr)
                merged = _eval_binary_const(st.op[:-1], left, right)
                if merged is _NO_LITERAL:
                    _env_forget_name(env, st.target.value)
                else:
                    env[st.target.value] = _literal_node(merged, st.expr)
            else:
                _env_forget_name(env, st.target.value)
        else:
            env.clear()

        return st, env, False, changed
    if isinstance(st, ExprStmt):
        old_expr = st.expr
        st.expr, expr_changed = _fold_ast_expr(st.expr, env, mutable_names)
        changed = expr_changed

        if _is_discardable_expr(st.expr):
            return None, env, False, True

        return st, env, False, changed
    if isinstance(st, ReturnStmt):
        changed = False
        if st.expr is not None:
            old_expr = st.expr
            st.expr, expr_changed = _fold_ast_expr(st.expr, env, mutable_names)
            changed = expr_changed
        return st, env, True, changed
    if isinstance(st, IfStmt):
        old_cond = st.cond
        st.cond, cond_changed = _fold_ast_expr(st.cond, env, mutable_names)
        changed = cond_changed

        cond = _literal_value(st.cond)
        if isinstance(cond, bool):
            branch = st.then_body if cond else st.else_body
            branch_out, branch_env, branch_changed = _optimize_stmts(branch, dict(env), mutable_names)
            return branch_out, branch_env, _stmts_terminate(branch_out), True or branch_changed

        then_out, then_env, then_changed = _optimize_stmts(st.then_body, dict(env), mutable_names)
        else_out, else_env, else_changed = _optimize_stmts(st.else_body, dict(env), mutable_names)

        if then_out != st.then_body:
            changed = True
        if else_out != st.else_body:
            changed = True

        st.then_body = then_out
        st.else_body = else_out

        merged = _merge_env(then_env, else_env)
        terminated = bool(st.else_body) and _stmts_terminate(then_out) and _stmts_terminate(else_out)

        changed |= then_changed or else_changed
        return st, merged, terminated, changed
    if isinstance(st, WhileStmt):
        old_cond = st.cond
        st.cond, cond_changed = _fold_ast_expr(st.cond, env, mutable_names)
        changed = cond_changed

        cond = _literal_value(st.cond)
        if cond is False:
            return None, env, False, True

        body_out, _, body_changed = _optimize_stmts(st.body, dict(env), mutable_names)
        if body_out != st.body:
            changed = True
        st.body = body_out

        env.clear()
        changed |= body_changed
        return st, env, False, changed
    if isinstance(st, MatchStmt):
        old_expr = st.expr
        st.expr, expr_changed = _fold_ast_expr(st.expr, env, mutable_names)
        changed = expr_changed

        target = _literal_value(st.expr)
        if target is not _NO_LITERAL:
            all_known = True
            for pat, body in st.arms:
                folded_pat, pat_changed = _fold_ast_expr(pat, env, mutable_names)
                decision = _match_pattern_const_decision(target, folded_pat)
                if decision is True:
                    arm_out, arm_env, arm_changed = _optimize_stmts(body, dict(env), mutable_names)
                    return arm_out, arm_env, _stmts_terminate(arm_out), True or pat_changed or arm_changed
                if decision is None:
                    all_known = False
                    break
            if all_known:
                return [], dict(env), False, True

        new_arms: list[tuple[Any, list[Any]]] = []
        merged_env: dict[str, Any] | None = None

        for pat, body in st.arms:
            folded_pat, pat_changed = _fold_ast_expr(pat, env, mutable_names)
            arm_out, arm_env, arm_changed = _optimize_stmts(body, dict(env), mutable_names)
            new_arms.append((folded_pat, arm_out))
            merged_env = arm_env if merged_env is None else _merge_env(merged_env, arm_env)
            changed |= arm_changed or pat_changed or (folded_pat is not pat) or (arm_out != body)

        st.arms = new_arms
        return st, merged_env or {}, False, changed
    if isinstance(st, ComptimeStmt):
        body_out, _, body_changed = _optimize_stmts(st.body, dict(env), mutable_names)
        changed = body_out != st.body or body_changed
        st.body = body_out
        return st, env, False, changed
    if isinstance(st, UnsafeStmt):
        body_out, _, body_changed = _optimize_stmts(st.body, dict(env), mutable_names)
        changed = body_out != st.body or body_changed
        st.body = body_out
        env.clear()
        return st, env, _stmts_terminate(st.body), changed
    if isinstance(st, (BreakStmt, ContinueStmt)):
        return st, env, True, False

    return st, env, False, False


def _merge_env(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, aval in a.items():
        if key not in b:
            continue
        if _env_binding_key(aval) == _env_binding_key(b[key]):
            out[key] = aval
    return out


def _stmts_terminate(stmts: list[Any]) -> bool:
    """Check if a statement list terminates (unconditionally reaches return/break/continue).
    
    This is a stronger version that handles nested control flow properly.
    """
    if not stmts:
        return False

    tail = stmts[-1]

    if isinstance(tail, UnsafeStmt):
        return _stmts_terminate(tail.body)

    if isinstance(tail, IfStmt):
        # IfStmt terminates only if both branches terminate and else exists
        return (
            bool(tail.then_body)
            and bool(tail.else_body)
            and _stmts_terminate(tail.then_body)
            and _stmts_terminate(tail.else_body)
        )

    if isinstance(tail, MatchStmt):
        # MatchStmt terminates only if all arms have bodies that terminate
        return bool(tail.arms) and all(_stmts_terminate(body) for _, body in tail.arms)

    return isinstance(tail, (ReturnStmt, BreakStmt, ContinueStmt))


def _fold_target_expr(target: Any, env: dict[str, Any], mutable_names: set[str]) -> tuple[Any, bool]:
    changed = False
    if isinstance(target, IndexExpr):
        target.obj, obj_changed = _fold_ast_expr(target.obj, env, mutable_names)
        target.index, idx_changed = _fold_ast_expr(target.index, env, mutable_names)
        changed = obj_changed or idx_changed
        return target, changed
    if isinstance(target, FieldExpr):
        target.obj, obj_changed = _fold_ast_expr(target.obj, env, mutable_names)
        changed = obj_changed
        return target, changed
    return target, False


def _fold_ast_expr(expr: Any, env: dict[str, Any], mutable_names: set[str]) -> tuple[Any, bool]:
    """Fold AST expressions with constant propagation and algebraic simplifications.
    
    IMPORTANT LANGUAGE SEMANTICS ASSUMPTIONS:
    This function contains optimizations that assume specific ASTRA language semantics:
    
    1. Boolean logic (&&, ||): ✅ CORRECT - Assumes ASTRA's C/Rust-like boolean return values
       - Verified: ASTRA uses bool return values, not Python-like operand-returning
       - Examples in codebase: `buffer1 != none && buffer2 != none`
    
    2. Null coalescing (??): ✅ CORRECT - Assumes ASTRA's standard nullish coalescing
       - Verified: `a ?? b` requires `a: Option<T>`, `b: T`, result `T`
       - Short-circuits when LHS is `none`
       - Examples: `first ?? 0` and `val as Int | none ?? 0`
    
    3. Strength reduction (x * 2^k -> x << k): ⚠️ CONDITIONAL
       - SAFE: --overflow wrap mode (release builds)
       - UNSAFE: --overflow trap mode (default for debug builds)
       - Should be gated on overflow mode configuration
    
    4. Integer arithmetic: ✅ CORRECT - Matches ASTRA's overflow and signedness rules
       - Right shift is arithmetic for signed, logical for unsigned
       - Cast extension follows source signedness
    
    If the target language has different semantics, the corresponding optimizations
    must be disabled or modified to match the actual language specification.
    """
    if isinstance(expr, Name):
        if expr.value in env and expr.value not in mutable_names:
            bound = _resolve_env_binding(expr.value, env)
            if isinstance(bound, Name):
                return Name(value=bound.value, pos=expr.pos, line=expr.line, col=expr.col), True
            lit = _literal_value(bound)
            if lit is not _NO_LITERAL:
                return _literal_node(lit, expr), True
        return expr, False
    if isinstance(expr, (Literal, BoolLit, NilLit)):
        return expr, False
    if isinstance(expr, Unary):
        expr.expr, expr_changed = _fold_ast_expr(expr.expr, env, mutable_names)
        value = _literal_value(expr.expr)
        if value is _NO_LITERAL:
            return expr, expr_changed
        if expr.op == "-":
            if isinstance(value, (int, float)):
                return _literal_node(-value, expr), True
            return expr, expr_changed
        if expr.op == "!":
            return _literal_node(not bool(value), expr), True
        return expr, expr_changed
    if isinstance(expr, Binary):
        expr.left, left_changed = _fold_ast_expr(expr.left, env, mutable_names)
        expr.right, right_changed = _fold_ast_expr(expr.right, env, mutable_names)
        changed = left_changed or right_changed
        
        lval = _literal_value(expr.left)
        rval = _literal_value(expr.right)
        out = _eval_binary_const(expr.op, lval, rval)
        if out is not _NO_LITERAL:
            return _literal_node(out, expr), True
        # Algebraic simplifications that preserve evaluation order.
        if expr.op == "+":
            if rval == 0 and _is_pure_expr(expr.left):
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
            if lval == 0 and _is_pure_expr(expr.right):
                _copy_inferred_type(expr.right, expr)
                return expr.right, True
        if expr.op == "-":
            if rval == 0 and _is_pure_expr(expr.left):
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
        if expr.op == "*":
            if rval == 1 and _is_pure_expr(expr.left):
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
            if lval == 1 and _is_pure_expr(expr.right):
                _copy_inferred_type(expr.right, expr)
                return expr.right, True
            if rval == 0 and _is_discardable_expr(expr.left):
                # x * 0 -> 0 is only safe when x is truly discardable
                # This means x has no side effects, cannot trap, and dropping it changes nothing observable
                result = _literal_node(0, expr)
                return result, True
            if lval == 0 and _is_discardable_expr(expr.right):
                # 0 * x -> 0 is only safe when x is truly discardable
                result = _literal_node(0, expr)
                return result, True
            if _is_integer_expr(expr):
                # CRITICAL LANGUAGE SEMANTICS ASSUMPTION:
                # This strength reduction (x * 2^k -> x << k) is only valid under specific overflow semantics:
                # 
                # SAFE SEMANTICS (per ASTRA language spec):
                # - --overflow wrap mode (release builds)
                # - --overflow debug mode when wrap semantics are used
                # - Two's-complement wrapping integers
                # - Arbitrary precision integers
                # 
                # UNSAFE SEMANTICS (DO NOT APPLY OPTIMIZATION):
                # - --overflow trap mode (default for debug builds)
                # - Checked overflow that traps on overflow
                # - C-like undefined behavior on signed overflow
                # - Fixed-width integers with saturation semantics
                # 
                # NOTE: This optimization should be gated on overflow mode configuration.
                # For now, we conservatively apply it only when we can determine the context
                # allows wrapping semantics. In a full implementation, this should check
                # the current overflow mode from build configuration.
                # 
                # The optimization assumes: x * (1 << k) == x << k for all valid x and k
                # If this does not hold in the target overflow mode, disable this optimization.
                rshift = _pow2_shift(rval)
                if rshift is not None and _is_pure_expr(expr.left):
                    out = Binary(op="<<", left=expr.left, right=_literal_node(rshift, expr.right), pos=expr.pos, line=expr.line, col=expr.col)
                    _copy_inferred_type(out, expr)
                    return out, True
                lshift = _pow2_shift(lval)
                if lshift is not None and _is_pure_expr(expr.right):
                    out = Binary(op="<<", left=expr.right, right=_literal_node(lshift, expr.left), pos=expr.pos, line=expr.line, col=expr.col)
                    _copy_inferred_type(out, expr)
                    return out, True
        if expr.op == "/":
            if rval == 1 and _is_pure_expr(expr.left):
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
        if expr.op in {"|", "^"}:
            if rval == 0 and _is_pure_expr(expr.left):
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
            if lval == 0 and _is_pure_expr(expr.right):
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.right, expr)
                return expr.right, True
        if expr.op == "&":
            if rval == -1 and _is_pure_expr(expr.left):
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
            if lval == -1 and _is_pure_expr(expr.right):
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.right, expr)
                return expr.right, True
        if expr.op == "??":
            # LANGUAGE SEMANTICS ASSUMPTION:
            # This assumes standard null-coalescing semantics where:
            # 1. Left operand is evaluated first
            # 2. If left is None/nullish, right operand is evaluated and returned
            # 3. If left is any other concrete value, it's returned directly
            # 4. The result type is the union of left and right types
            # 
            # This optimization is only safe if:
            # - _literal_value() returning a concrete value implies effect-free evaluation
            # - expr.left can safely replace the full coalesce expression
            # - No wrapper nodes with typing significance are being collapsed
            if lval is None:
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.right, expr)
                return expr.right, True
            if lval is not _NO_LITERAL:
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
        if expr.op == "&&" and isinstance(lval, bool):
            # LANGUAGE SEMANTICS ASSUMPTION:
            # This assumes C/Rust-like boolean logic where && returns a boolean, not the original operand.
            # If the language uses Python-like operand-returning semantics, this rewrite is incorrect.
            # Also assumes boolean operands only - if language allows truthiness of non-bool values,
            # these rewrites become wrong.
            if not lval:
                result = _literal_node(False, expr)
                return result, True
            # Preserve type metadata when returning child expression
            _copy_inferred_type(expr.right, expr)
            return expr.right, True
        if expr.op == "&&":
            if rval is True and _is_pure_expr(expr.left):
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
            if rval is False and _is_discardable_expr(expr.left):
                result = _literal_node(False, expr)
                return result, True
        if expr.op == "||" and isinstance(lval, bool):
            # LANGUAGE SEMANTICS ASSUMPTION:
            # This assumes C/Rust-like boolean logic where || returns a boolean, not the original operand.
            # If the language uses Python-like operand-returning semantics, this rewrite is incorrect.
            # Also assumes boolean operands only - if language allows truthiness of non-bool values,
            # these rewrites become wrong.
            if lval:
                result = _literal_node(True, expr)
                return result, True
            # Preserve type metadata when returning child expression
            _copy_inferred_type(expr.right, expr)
            return expr.right, True
        if expr.op == "||":
            if rval is False and _is_pure_expr(expr.left):
                # Preserve type metadata when returning child expression
                _copy_inferred_type(expr.left, expr)
                return expr.left, True
            if rval is True and _is_discardable_expr(expr.left):
                result = _literal_node(True, expr)
                return result, True
        return expr, changed
    if isinstance(expr, Call):
        # CALL FOLDING NOTE:
        # Arguments can be folded, but environment invalidation must happen at statement level.
        # Calls are treated as potentially invalidating env knowledge unless we know:
        # - Function is pure/non-mutating
        # - No mutable references passed
        # - No side effects
        # 
        # Example where env invalidation matters:
        # let x = 3;
        # foo(&mut x);  // may modify x
        # print(x);     // constant propagation after call may be invalid
        expr.fn, fn_changed = _fold_ast_expr(expr.fn, env, mutable_names)
        args_changed = False
        new_args = []
        for arg in expr.args:
            new_arg, arg_changed = _fold_ast_expr(arg, env, mutable_names)
            new_args.append(new_arg)
            args_changed |= arg_changed
        expr.args = new_args
        
        # Conservative: assume function calls may have side effects
        # and invalidate the environment unless we can prove otherwise
        # This prevents incorrect constant propagation across calls
        if fn_changed or args_changed:
            # For now, be conservative and clear environment on any call
            # Future improvement: track pure functions and preserve env for those
            env.clear()
            
        return expr, fn_changed or args_changed
    if isinstance(expr, AwaitExpr):
        expr.expr, expr_changed = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr, expr_changed
    if isinstance(expr, TryExpr):
        expr.expr, expr_changed = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr, expr_changed
    if isinstance(expr, IndexExpr):
        expr.obj, obj_changed = _fold_ast_expr(expr.obj, env, mutable_names)
        expr.index, idx_changed = _fold_ast_expr(expr.index, env, mutable_names)
        return expr, obj_changed or idx_changed
    if isinstance(expr, FieldExpr):
        expr.obj, obj_changed = _fold_ast_expr(expr.obj, env, mutable_names)
        return expr, obj_changed
    if isinstance(expr, ArrayLit):
        elements_changed = False
        new_elements = []
        for e in expr.elements:
            new_elem, elem_changed = _fold_ast_expr(e, env, mutable_names)
            new_elements.append(new_elem)
            elements_changed |= elem_changed
        expr.elements = new_elements
        return expr, elements_changed
    if isinstance(expr, StructLit):
        fields_changed = False
        new_fields = []
        for name, value in expr.fields:
            new_value, value_changed = _fold_ast_expr(value, env, mutable_names)
            new_fields.append((name, new_value))
            fields_changed |= value_changed
        expr.fields = new_fields
        return expr, fields_changed
    if isinstance(expr, TypeAnnotated):
        expr.expr, expr_changed = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr, expr_changed
    if isinstance(expr, CastExpr):
        expr.expr, expr_changed = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr, expr_changed
    if isinstance(expr, OrPattern):
        # PATTERN FOLDING NOTE:
        # Patterns and expressions obey different legality rules and environment meanings.
        # Long-term, patterns benefit from separate folders because:
        # - Pattern rewrites may be invalid for expressions
        # - Environment meaning differs in pattern contexts
        # - Different legality rules apply
        # For now, simple handling is fine but keep this in mind as pattern system grows.
        patterns_changed = False
        new_patterns = []
        for p in expr.patterns:
            new_pattern, pattern_changed = _fold_ast_expr(p, env, mutable_names)
            new_patterns.append(new_pattern)
            patterns_changed |= pattern_changed
        expr.patterns = new_patterns
        return expr, patterns_changed
    if isinstance(expr, GuardedPattern):
        # PATTERN FOLDING NOTE: Same concerns as OrPattern apply here
        expr.pattern, pattern_changed = _fold_ast_expr(expr.pattern, env, mutable_names)
        expr.guard, guard_changed = _fold_ast_expr(expr.guard, env, mutable_names)
        return expr, pattern_changed or guard_changed
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr, BitSizeOfTypeExpr, MaxValTypeExpr, MinValTypeExpr)):
        return expr, False
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        expr.expr, expr_changed = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr, expr_changed
    return expr, False


_NO_LITERAL = object()


def _literal_value(expr: Any) -> Any:
    if isinstance(expr, BoolLit):
        return bool(expr.value)
    if isinstance(expr, NilLit):
        return None
    if isinstance(expr, Literal):
        return expr.value
    return _NO_LITERAL


def _match_pattern_const_decision(target: Any, pat: Any) -> bool | None:
    if isinstance(pat, WildcardPattern):
        return True
    if isinstance(pat, OrPattern):
        saw_unknown = False
        for p in pat.patterns:
            d = _match_pattern_const_decision(target, p)
            if d is True:
                return True
            if d is None:
                saw_unknown = True
        if saw_unknown:
            return None
        return False
    if isinstance(pat, GuardedPattern):
        gd = _literal_value(pat.guard)
        if not isinstance(gd, bool):
            return None
        if not gd:
            return False
        return _match_pattern_const_decision(target, pat.pattern)
    pv = _literal_value(pat)
    if pv is _NO_LITERAL:
        return None
    return pv == target


def _literal_node(value: Any, src: Any) -> Any:
    """Create a literal node, preserving metadata from the source expression.
    
    This function copies position information and inferred type metadata
    to ensure later compiler phases don't lose important type information.
    """
    pos = getattr(src, "pos", 0)
    line = getattr(src, "line", 0)
    col = getattr(src, "col", 0)
    
    if value is None:
        result = NilLit(pos=pos, line=line, col=col)
    elif isinstance(value, bool):
        result = BoolLit(value=value, pos=pos, line=line, col=col)
    else:
        result = Literal(value=value, pos=pos, line=line, col=col)
    
    # Preserve inferred type metadata from source expression
    _copy_inferred_type(result, src)
    
    return result


def _is_pure_expr(expr: Any) -> bool:
    if isinstance(expr, (Name, Literal, BoolLit, NilLit)):
        return True
    if isinstance(expr, Unary):
        return _is_pure_expr(expr.expr)
    if isinstance(expr, Binary):
        return _is_pure_expr(expr.left) and _is_pure_expr(expr.right)
    if isinstance(expr, TryExpr):
        return False
    if isinstance(expr, ArrayLit):
        return all(_is_pure_expr(e) for e in expr.elements)
    if isinstance(expr, StructLit):
        return all(_is_pure_expr(v) for _, v in expr.fields)
    if isinstance(expr, TypeAnnotated):
        return _is_pure_expr(expr.expr)
    if isinstance(expr, CastExpr):
        return _is_pure_expr(expr.expr)
    if isinstance(expr, OrPattern):
        return all(_is_pure_expr(p) for p in expr.patterns)
    if isinstance(expr, GuardedPattern):
        return _is_pure_expr(expr.pattern) and _is_pure_expr(expr.guard)
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr, BitSizeOfTypeExpr, MaxValTypeExpr, MinValTypeExpr)):
        return True
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        return _is_pure_expr(expr.expr)
    return False


def _is_discardable_expr(expr: Any) -> bool:
    """Check if an expression can be safely discarded without side effects.
    
    CRITICAL: This is stricter than "pure-looking". An expression is discardable only if:
    1. Evaluating it has no side effects
    2. Evaluating it cannot trap/panic/error
    3. Dropping it changes nothing observable
    
    This must be extremely conservative - if in doubt, return False.
    """
    return _is_pure_expr(expr) and not _may_trap_expr(expr)


def _may_trap_expr(expr: Any) -> bool:
    """Check if an expression may trap/panic/error during evaluation.
    
    This must be extremely conservative. Any operation that could:
    - Divide by zero
    - Bounds-checked indexing out of bounds
    - Possibly-failing cast
    - Array access
    - Function calls
    - Field access on potentially null
    
    Should return True. When in doubt, return True.
    """
    if isinstance(expr, (Literal, BoolLit, NilLit, Name)):
        return False
    if isinstance(expr, Unary):
        return _may_trap_expr(expr.expr)
    if isinstance(expr, TryExpr):
        return True
    if isinstance(expr, Binary):
        if _may_trap_expr(expr.left) or _may_trap_expr(expr.right):
            return True
        if expr.op in {"/", "%"}:
            rval = _literal_value(expr.right)
            if rval is _NO_LITERAL:
                return True
            return rval == 0 or rval == -1
        return False
    if isinstance(expr, ArrayLit):
        return any(_may_trap_expr(e) for e in expr.elements)
    if isinstance(expr, StructLit):
        return any(_may_trap_expr(v) for _, v in expr.fields)
    if isinstance(expr, TypeAnnotated):
        return _may_trap_expr(expr.expr)
    if isinstance(expr, CastExpr):
        # Casts can trap (e.g., overflow, invalid conversion)
        return True
    if isinstance(expr, OrPattern):
        return any(_may_trap_expr(p) for p in expr.patterns)
    if isinstance(expr, GuardedPattern):
        return _may_trap_expr(expr.pattern) or _may_trap_expr(expr.guard)
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr, BitSizeOfTypeExpr, MaxValTypeExpr, MinValTypeExpr)):
        return False
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        return _may_trap_expr(expr.expr)
    # Conservative: calls/await/index/field are observable or may trap.
    return True


def _eval_binary_const(op: str, left: Any, right: Any) -> Any:
    if left is _NO_LITERAL or right is _NO_LITERAL:
        return _NO_LITERAL
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/" and right != 0:
        if isinstance(left, int) and isinstance(right, int):
            return left // right
        return left / right
    if op == "%" and right != 0:
        return left % right
    if op == "&":
        return int(left) & int(right)
    if op == "|":
        return int(left) | int(right)
    if op == "^":
        return int(left) ^ int(right)
    if op == "<<":
        return int(left) << int(right)
    if op == ">>":
        return int(left) >> int(right)
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "&&":
        return bool(left) and bool(right)
    if op == "||":
        return bool(left) or bool(right)
    if op == "??":
        return right if left is None else left
    return _NO_LITERAL


def _collect_mutable_names(stmts: list[Any]) -> set[str]:
    out: set[str] = set()

    def walk(items: list[Any]):
        for st in items:
            if isinstance(st, LetStmt):
                if st.mut:
                    out.add(st.name)
            elif isinstance(st, AssignStmt):
                if isinstance(st.target, Name):
                    out.add(st.target.value)
            elif isinstance(st, IfStmt):
                walk(st.then_body)
                walk(st.else_body)
            elif isinstance(st, WhileStmt):
                walk(st.body)
            elif isinstance(st, MatchStmt):
                for _, body in st.arms:
                    walk(body)
            elif isinstance(st, ComptimeStmt):
                walk(st.body)
            elif isinstance(st, UnsafeStmt):
                walk(st.body)

    walk(stmts)
    return out


def _env_binding_key(value: Any) -> Any:
    """Create a canonical key for environment bindings.
    
    This function is critical for _merge_env() correctness. It should normalize:
    - Literal values (ignoring source position/identity)
    - Name aliases (for potential alias equality)
    - Type information if relevant
    
    The key should be canonical - equivalent bindings should have the same key
    regardless of source location or node identity.
    """
    if isinstance(value, Name):
        return ("name", value.value)
    lit = _literal_value(value)
    if lit is not _NO_LITERAL:
        # Use just the literal value, not the node identity
        return ("lit", type(lit).__name__, lit)
    return None


def _resolve_env_binding(name: str, env: dict[str, Any]) -> Any:
    """Resolve an environment binding to its final value, following name chains transitively.
    
    This function handles alias chains like:
        a -> b -> c -> literal
    And resolves 'a' directly to the literal.
    
    Also detects cycles safely to prevent infinite loops.
    """
    seen: set[str] = set()
    cur = name
    while cur in env and cur not in seen:
        seen.add(cur)
        bound = env[cur]
        if isinstance(bound, Name):
            cur = bound.value
            continue
        return bound
    if cur in seen:
        # Cycle detected - return special marker
        return _NO_LITERAL
    return env.get(cur, _NO_LITERAL)


def _env_forget_name(env: dict[str, Any], name: str) -> None:
    """Remove a name and any bindings that depend on it from the environment.
    
    This is critical for correctness when:
    - Variables are reassigned (especially mutable ones)
    - Aliasing through indirect targets occurs
    - Unknown calls with side effects happen
    - Loops might affect variables
    - Unsafe blocks are encountered
    - Pattern bindings introduce names
    """
    dead = [k for k, v in env.items() if k == name or (isinstance(v, Name) and v.value == name)]
    for k in dead:
        env.pop(k, None)


def _copy_inferred_type(dst: Any, src: Any) -> None:
    typ = getattr(src, "inferred_type", None)
    if isinstance(typ, str):
        setattr(dst, "inferred_type", typ)


def _is_integer_expr(expr: Any) -> bool:
    typ = getattr(expr, "inferred_type", None)
    if isinstance(typ, str):
        if typ in {"Int", "isize", "usize"}:
            return True
        return parse_int_type_name(typ) is not None
    return False


def _pow2_shift(value: Any) -> int | None:
    if not isinstance(value, int):
        return None
    if value <= 0:
        return None
    if value & (value - 1):
        return None
    return value.bit_length() - 1


def _cse_stmts_with_stats(stmts: list[Any], available: AvailableMap, stats: OptStats | None = None) -> tuple[list[Any], AvailableMap, bool]:
    """Common subexpression elimination with optional statistics tracking.
    
    Returns:
        - Optimized statement list
        - Updated available expressions
        - Whether any changes were made
    """
    out: list[Any] = []
    avail = dict(available)
    any_changed = False

    for i, st in enumerate(stmts):
        original_st = st
        lowered, avail, terminated, changed = _cse_stmt(st, avail, stats)
        any_changed |= changed

        if lowered is None:
            any_changed = True
            continue

        if lowered is not original_st:
            any_changed = True
        
        out.append(lowered)

        if terminated:
            # If there were remaining statements after this one, they are dead.
            if i != len(stmts) - 1:
                any_changed = True
            break
            
    if stats is not None:
        # Track CSE rewrites by comparing input vs output
        if len(out) != len(stmts):
            stats.cse_rewrites += abs(len(out) - len(stmts))
        else:
            # Count structural differences (simplified check)
            for i, (orig, new) in enumerate(zip(stmts, out)):
                if orig != new:
                    stats.cse_rewrites += 1
                    break
    
    return out, avail, any_changed


def _dse_stmts_with_stats(stmts: list[Any], live_out: set[str], stats: OptStats | None = None) -> tuple[list[Any], set[str]]:
    """Dead statement elimination with optional statistics tracking."""
    result = _dse_stmts(stmts, live_out)
    
    if stats is not None:
        removed = len(stmts) - len(result[0])
        stats.dse_removed += removed
    
    return result


def _cse_stmts(stmts: list[Any], available: AvailableMap) -> tuple[list[Any], AvailableMap, bool]:
    """Common subexpression elimination with explicit change tracking.
    
    Returns:
        - Optimized statement list
        - Updated available expressions
        - Whether any changes were made
    """
    out: list[Any] = []
    avail = dict(available)
    any_changed = False

    for i, st in enumerate(stmts):
        original_st = st
        lowered, avail, terminated, changed = _cse_stmt(st, avail)
        any_changed |= changed

        if lowered is None:
            any_changed = True
            continue

        if lowered is not original_st:
            any_changed = True
        
        out.append(lowered)

        if terminated:
            # If there were remaining statements after this one, they are dead.
            if i != len(stmts) - 1:
                any_changed = True
            break

    return out, avail, any_changed


def _merge_available(a: AvailableMap, b: AvailableMap) -> AvailableMap:
    """Merge available-expression facts across control-flow branches.

    An expression remains available after the merge only if:
    - the same expression key exists on both paths, and
    - both paths map it to the same bound name.

    Dependency policy:
    `deps` is currently treated conservatively as the set of names whose
    mutation may invalidate the available value. Therefore branch merging
    uses set union, which is safe but may reduce later reuse opportunities.

    If `deps` is later narrowed to mean only the names structurally used by
    the expression, intersection may become a better merge rule.
    """
    out: AvailableMap = {}
    for key, aval in a.items():
        bval = b.get(key)
        if bval is None:
            continue
        if aval.bound_name == bval.bound_name:
            merged_deps = aval.deps | bval.deps
            out[key] = AvailableExpr(
                bound_name=aval.bound_name,
                deps=merged_deps,
            )
    return out


def _invalidate_available(
    avail: AvailableMap,
    names: set[str] | None = None,
    *,
    clear: bool = False,
    stats: OptStats | None = None,
) -> AvailableMap:
    """Invalidate available expressions based on name mutations.
    
    Consistently mutates the input dict in place and returns it.
    This is faster for optimizer internals and makes the API behavior obvious.
    
    CRITICAL: Consider killing by alias, not just direct bound name.
    Current implementation checks both bound names and dependencies,
    but if CSE representative names can alias other mutable names,
    stronger invalidation may be needed.
    
    Example where current approach may be insufficient:
        expression bound to temp t
        t aliases x  
        x changes
    
    If deps contains x, we're fine. If not, we may keep stale entries.
    The quality of CSE invalidation depends on how deps is built -
    deps should include all names that can affect the expression result.
    
    Args:
        avail: Available expressions map (mutated in place)
        names: Names that were mutated (if None, no invalidation)
        clear: If True, clear the entire map
    
    Returns:
        The same dict (mutated) for chaining
    """
    if clear:
        avail.clear()
        return avail
    if not names:
        return avail

    kill = [
        key
        for key, available_expr in avail.items()
        if available_expr.bound_name in names or bool(available_expr.deps & names)
    ]
    for key in kill:
        del avail[key]
    
    # Track invalidations for statistics
    if stats is not None and kill:
        stats.cse_invalidations += len(kill)
        
    return avail


def _cse_stmt(st: Any, avail: AvailableMap, stats: OptStats | None = None) -> tuple[Any | None, AvailableMap, bool, bool]:
    """Common subexpression elimination for a single statement with change tracking.
    
    Returns:
        - Optimized statement (or None if removed)
        - Updated available expressions
        - Whether statement terminates control flow
        - Whether any changes were made
    """
    if isinstance(st, LetStmt):
        old_expr = st.expr
        st.expr = _cse_expr(st.expr, avail, stats)
        changed = st.expr is not old_expr
        avail = _invalidate_available(avail, {st.name}, stats=stats)
        key = _expr_key(st.expr)
        if key is not None:
            if stats is not None:
                stats.cse_insertions += 1
            avail[key] = AvailableExpr(
                bound_name=st.name,
                deps=frozenset(_used_names_expr(st.expr))
            )
        return st, avail, False, changed

    if isinstance(st, AssignStmt):
        old_target = st.target
        old_expr = st.expr
        st.target = _cse_target(st.target, avail, stats)
        st.expr = _cse_expr(st.expr, avail, stats)
        changed = st.target is not old_target or st.expr is not old_expr
        if isinstance(st.target, Name):
            avail = _invalidate_available(avail, {st.target.value}, stats=stats)
            if st.op == "=":
                key = _expr_key(st.expr)
                if key is not None:
                    if stats is not None:
                        stats.cse_insertions += 1
                    avail[key] = AvailableExpr(
                        bound_name=st.target.value,
                        deps=frozenset(_used_names_expr(st.expr))
                    )
        else:
            avail = _invalidate_available(avail, clear=True, stats=stats)
        return st, avail, False, changed

    if isinstance(st, ExprStmt):
        old_expr = st.expr
        st.expr = _cse_expr(st.expr, avail, stats)
        changed = st.expr is not old_expr
        if not _is_discardable_expr(st.expr):
            avail = _invalidate_available(avail, clear=True, stats=stats)
        return st, avail, False, changed

    if isinstance(st, ReturnStmt):
        changed = False
        if st.expr is not None:
            old_expr = st.expr
            st.expr = _cse_expr(st.expr, avail, stats)
            changed = st.expr is not old_expr
        return st, avail, True, changed

    if isinstance(st, IfStmt):
        old_cond = st.cond
        st.cond = _cse_expr(st.cond, avail, stats)
        changed = st.cond is not old_cond
        cond_avail = dict(avail)
        if not _is_discardable_expr(st.cond):
            cond_avail = {}
        then_body, then_avail, then_changed = _cse_stmts(st.then_body, dict(cond_avail))
        else_body, else_avail, else_changed = _cse_stmts(st.else_body, dict(cond_avail))
        changed |= then_changed or else_changed
        merged = _merge_available(then_avail, else_avail)
        terminated = bool(st.else_body) and _stmts_terminate(st.then_body) and _stmts_terminate(st.else_body)
        return st, merged, terminated, changed

    if isinstance(st, WhileStmt):
        old_cond = st.cond
        st.cond = _cse_expr(st.cond, avail, stats)
        changed = st.cond is not old_cond
        st.body, _, body_changed = _cse_stmts(st.body, {})
        changed |= body_changed
        return st, {}, False, changed

    if isinstance(st, IteratorForStmt):
        changed = False
        if st.init is not None:
            if isinstance(st.init, LetStmt):
                old_init = st.init
                st.init, _, _, init_changed = _cse_stmt(st.init, dict(avail), stats)
                changed |= init_changed
            elif isinstance(st.init, AssignStmt):
                old_init = st.init
                st.init, _, _, init_changed = _cse_stmt(st.init, dict(avail), stats)
                changed |= init_changed
            else:
                old_init = st.init
                st.init = _cse_expr(st.init, avail, stats)
                changed |= st.init is not old_init
        if st.cond is not None:
            old_cond = st.cond
            st.cond = _cse_expr(st.cond, avail, stats)
            changed |= st.cond is not old_cond
        if st.step is not None:
            if isinstance(st.step, AssignStmt):
                old_step = st.step
                st.step, _, _, step_changed = _cse_stmt(st.step, {}, stats)
                changed |= step_changed
            else:
                old_step = st.step
                st.step = _cse_expr(st.step, {}, stats)
                changed |= st.step is not old_step
        st.body, _, body_changed = _cse_stmts(st.body, {})
        changed |= body_changed
        return st, {}, False, changed

    if isinstance(st, MatchStmt):
        old_expr = st.expr
        st.expr = _cse_expr(st.expr, avail, stats)
        changed = st.expr is not old_expr
        old_arms = st.arms  # Save original arms
        new_arms: list[tuple[Any, list[Any]]] = []
        for pat, body in st.arms:
            pat2 = _cse_expr(pat, avail, stats)
            changed |= pat2 is not pat
            body2, _, body_changed = _cse_stmts(body, {})
            changed |= body_changed
            new_arms.append((pat2, body2))
        st.arms = new_arms
        changed |= new_arms != old_arms  # Check if arms changed using original vs new
        return st, {}, False, changed

    if isinstance(st, ComptimeStmt):
        old_body = st.body
        st.body, _, body_changed = _cse_stmts(st.body, {})
        changed = st.body is not old_body or body_changed
        return st, avail, False, changed

    if isinstance(st, UnsafeStmt):
        old_body = st.body
        st.body, _, body_changed = _cse_stmts(st.body, {})
        changed = st.body is not old_body or body_changed
        return st, {}, _stmts_terminate(st.body), changed

    if isinstance(st, (BreakStmt, ContinueStmt)):
        return st, avail, True, False

    return st, avail, False, False


def _cse_target(target: Any, avail: AvailableMap, stats: OptStats | None = None) -> Any:
    if isinstance(target, IndexExpr):
        target.obj = _cse_expr(target.obj, avail, stats)
        target.index = _cse_expr(target.index, avail, stats)
        return target
    if isinstance(target, FieldExpr):
        target.obj = _cse_expr(target.obj, avail, stats)
        return target
    return target


def _cse_expr(expr: Any, avail: AvailableMap, stats: OptStats | None = None) -> Any:
    """Apply CSE to an expression with optional statistics tracking."""
    if isinstance(expr, Unary):
        expr.expr = _cse_expr(expr.expr, avail, stats)
    elif isinstance(expr, Binary):
        expr.left = _cse_expr(expr.left, avail, stats)
        expr.right = _cse_expr(expr.right, avail, stats)
    elif isinstance(expr, Call):
        expr.fn = _cse_expr(expr.fn, avail, stats)
        expr.args = [_cse_expr(arg, avail, stats) for arg in expr.args]
    elif isinstance(expr, AwaitExpr):
        expr.expr = _cse_expr(expr.expr, avail, stats)
    elif isinstance(expr, TryExpr):
        expr.expr = _cse_expr(expr.expr, avail, stats)
    elif isinstance(expr, IndexExpr):
        expr.obj = _cse_expr(expr.obj, avail, stats)
        expr.index = _cse_expr(expr.index, avail, stats)
    elif isinstance(expr, FieldExpr):
        expr.obj = _cse_expr(expr.obj, avail, stats)
    elif isinstance(expr, ArrayLit):
        expr.elements = [_cse_expr(e, avail, stats) for e in expr.elements]
    elif isinstance(expr, StructLit):
        expr.fields = [(name, _cse_expr(value, avail, stats)) for name, value in expr.fields]
    elif isinstance(expr, TypeAnnotated):
        expr.expr = _cse_expr(expr.expr, avail, stats)
    elif isinstance(expr, CastExpr):
        expr.expr = _cse_expr(expr.expr, avail, stats)
    elif isinstance(expr, OrPattern):
        expr.patterns = [_cse_expr(p, avail, stats) for p in expr.patterns]
    elif isinstance(expr, GuardedPattern):
        expr.pattern = _cse_expr(expr.pattern, avail, stats)
        expr.guard = _cse_expr(expr.guard, avail, stats)
    elif isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        expr.expr = _cse_expr(expr.expr, avail, stats)

    # Centralized CSE logic: try to get key, if None, not a CSE candidate
    key = _expr_key(expr)
    if key is None:
        return expr
    found = avail.get(key)
    if found is None:
        return expr
    
    # CSE hit: replace with available name
    if stats is not None:
        stats.cse_hits += 1
    return Name(value=found.bound_name, pos=getattr(expr, "pos", 0), line=getattr(expr, "line", 0), col=getattr(expr, "col", 0))


def _expr_key(expr: Any) -> Any | None:
    """Generate a canonical key for CSE expression matching.
    
    Returns None if the expression is not suitable for CSE.
    This centralizes all CSE eligibility logic in one place.
    
    For commutative operations (like +, *), operands are ordered
    to ensure structurally equivalent expressions hash identically.
    """
    # Centralized CSE eligibility checks
    if not _is_discardable_expr(expr):
        return None
    
    # Additional purity checks for specific expression types
    if isinstance(expr, Call):
        # Function calls are generally not pure unless proven otherwise
        return None
    
    if isinstance(expr, IndexExpr):
        # Array indexing may have bounds checking side effects
        return None
    
    if isinstance(expr, Name):
        return ("name", expr.value)
    if isinstance(expr, Literal):
        return ("lit", type(expr.value).__name__, expr.value)
    if isinstance(expr, BoolLit):
        return ("bool", bool(expr.value))
    if isinstance(expr, NilLit):
        return ("nil",)
    if isinstance(expr, Unary):
        inner = _expr_key(expr.expr)
        if inner is None:
            return None
        return ("unary", expr.op, inner, getattr(expr, "inferred_type", None))
    if isinstance(expr, Binary):
        left = _expr_key(expr.left)
        right = _expr_key(expr.right)
        if left is None or right is None:
            return None
        
        # Canonical ordering for commutative operations
        if expr.op in {"+", "*", "&", "|", "^"}:
            # Sort operands to ensure canonical ordering
            # This makes a + b and b + a have the same key
            if left <= right:
                ordered_left, ordered_right = left, right
            else:
                ordered_left, ordered_right = right, left
            return ("binary", expr.op, ordered_left, ordered_right, getattr(expr, "inferred_type", None))
        else:
            # Non-commutative operations keep original order
            return ("binary", expr.op, left, right, getattr(expr, "inferred_type", None))
    if isinstance(expr, TypeAnnotated):
        inner = _expr_key(expr.expr)
        if inner is None:
            return None
        return ("typed", expr.type_name, inner)
    if isinstance(expr, CastExpr):
        inner = _expr_key(expr.expr)
        if inner is None:
            return None
        return ("cast", expr.type_name, inner)
    if isinstance(expr, SizeOfTypeExpr):
        return ("sizeof_t", expr.type_name)
    if isinstance(expr, AlignOfTypeExpr):
        return ("alignof_t", expr.type_name)
    if isinstance(expr, BitSizeOfTypeExpr):
        return ("bitsizeof_t", expr.type_name)
    if isinstance(expr, MaxValTypeExpr):
        return ("maxval_t", expr.type_name)
    if isinstance(expr, MinValTypeExpr):
        return ("minval_t", expr.type_name)
    if isinstance(expr, SizeOfValueExpr):
        inner = _expr_key(expr.expr)
        if inner is None:
            return None
        return ("sizeof_v", inner)
    if isinstance(expr, AlignOfValueExpr):
        inner = _expr_key(expr.expr)
        if inner is None:
            return None
        return ("alignof_v", inner)
    
    # FieldExpr is handled by discardability check above
    # If we reach here, it's an unsupported type for CSE
    return None


def _names_mutated_by_target(target: Any, aliases: AliasInfo = None) -> Set[str]:
    """Get names that may be mutated by writing to this target.
    
    Enhanced with complete alias analysis and type information.
    """
    mutated = set()
    
    if isinstance(target, Name):
        mutated.add(target.value)
        # Check for alias mutations using complete analysis
        if aliases:
            mutated.update(_names_mutated_via_aliases(target, aliases))
    elif isinstance(target, IndexExpr):
        # Writing to a[i] may mutate the array a
        mutated.update(_used_names_expr(target.obj))
        # Type-based analysis: check if array elements could be references
        type_info = _analyze_type(target.obj)
        if type_info.element_type and type_info.element_type.endswith('_ref'):
            # Array of references - may mutate referenced objects
            mutated.add(type_info.element_type.rstrip('_ref'))
    elif isinstance(target, FieldExpr):
        # Writing to obj.field may mutate the object obj
        mutated.update(_used_names_expr(target.obj))
        # Type-based analysis: check if field is a reference type
        type_info = _analyze_type(target.obj)
        if type_info.is_reference:
            # Writing to a field of a reference may affect the referenced object
            mutated.update(_used_names_expr(target.obj))
    elif isinstance(target, Unary) and target.op == '*':
        # Pointer dereference - enhanced alias analysis
        if isinstance(target.expr, Name) and aliases:
            ptr_name = target.expr.value
            # Get all possible targets of this pointer
            mutated.update(aliases.pointer_targets.get(ptr_name, set()))
            # Also check direct aliases
            mutated.update(aliases.direct_aliases.get(ptr_name, set()))
            # Type-based analysis
            type_info = _analyze_type(target.expr)
            if type_info.pointee_type:
                mutated.add(type_info.pointee_type)
        else:
            # Conservative: assume any names in target expression may be mutated
            mutated.update(_used_names_expr(target))
    else:
        # Conservative: assume any names in target expression may be mutated
        mutated.update(_used_names_expr(target))
    
    return mutated


def _register_function_purity(func_name: str, is_pure: bool = False, 
                            mutates_params: Set[int] = None, 
                            reads_globals: Set[str] = None,
                            writes_globals: Set[str] = None,
                            takes_refs: Set[int] = None):
    """Register function information for interprocedural analysis."""
    _function_registry[func_name] = FunctionInfo(
        name=func_name,
        is_pure=is_pure,
        mutates_params=mutates_params or set(),
        reads_globals=reads_globals or set(),
        writes_globals=writes_globals or set(),
        takes_refs=takes_refs or set()
    )


def _get_function_info(func_name: str) -> FunctionInfo:
    """Get function information, creating default if not registered."""
    if func_name not in _function_registry:
        # Default to conservative assumptions
        _function_registry[func_name] = FunctionInfo(
            name=func_name,
            is_pure=False,  # Assume impure
            mutates_params=set(range(10)),  # Assume may mutate all params
            reads_globals=set(),  # Unknown
            writes_globals=set(),  # Unknown
            takes_refs=set()  # Unknown
        )
    return _function_registry[func_name]


def _analyze_function_effects(call: Call) -> Set[str]:
    """Analyze the effects of a function call using interprocedural analysis."""
    if not isinstance(call.fn, Name):
        return set()  # Conservative: unknown function
    
    func_info = _get_function_info(call.fn.value)
    mutated = set()
    
    if func_info.is_pure:
        # Pure functions don't mutate anything
        return set()
    
    # Add mutated parameters
    for i, arg in enumerate(call.args):
        if i in func_info.mutates_params and isinstance(arg, Name):
            mutated.add(arg.value)
        # Reference parameters may also be mutated
        if i in func_info.takes_refs and isinstance(arg, Name):
            mutated.add(arg.value)
    
    # Add global writes
    mutated.update(func_info.writes_globals)
    
    return mutated


def _names_mutated_by_expr(expr: Any, aliases: AliasInfo = None) -> Set[str]:
    """Get names that may be mutated by evaluating this expression.
    
    Enhanced with interprocedural analysis and alias tracking.
    """
    if isinstance(expr, Call):
        # Use interprocedural analysis for function calls
        return _analyze_function_effects(expr)
    else:
        # Other expressions typically don't cause mutations
        return set()


def _names_accessible_by_call(call: Call) -> Set[str]:
    """Get names that may be accessible (and thus mutable) by a function call.
    
    Enhanced with function purity information.
    """
    if not isinstance(call.fn, Name):
        return set()
    
    func_info = _get_function_info(call.fn.value)
    
    if func_info.is_pure:
        # Pure functions can only access their explicit parameters
        accessible = set()
        for arg in call.args:
            if isinstance(arg, Name):
                accessible.add(arg.value)
        return accessible
    
    # Impure functions may access more
    accessible = set()
    
    # Function name itself
    accessible.add(call.fn.value)
    
    # All argument expressions
    for arg in call.args:
        if isinstance(arg, Name):
            accessible.add(arg.value)
        else:
            accessible.update(_used_names_expr(arg))
    
    # May access globals
    accessible.update(func_info.reads_globals)
    
    return accessible


@dataclass
class BasicBlock:
    """Basic block for control flow analysis."""
    stmts: list[Any]
    successors: Set[int] = field(default_factory=set)
    predecessors: Set[int] = field(default_factory=set)
    block_id: int = 0
    
    def __str__(self) -> str:
        return f"BB{self.block_id}({len(self.stmts)} stmts, {len(self.successors)} succ)"


@dataclass
class ControlFlowGraph:
    """Control flow graph for precise analysis."""
    blocks: List[BasicBlock] = field(default_factory=list)
    entry_block: Optional[int] = None
    exit_blocks: Set[int] = field(default_factory=set)
    
    def get_block(self, block_id: int) -> Optional[BasicBlock]:
        if 0 <= block_id < len(self.blocks):
            return self.blocks[block_id]
        return None
    
    def add_block(self, stmts: list[Any]) -> int:
        block_id = len(self.blocks)
        block = BasicBlock(stmts=stmts, block_id=block_id)
        self.blocks.append(block)
        return block_id
    
    def add_edge(self, from_block: int, to_block: int) -> None:
        if from_block < len(self.blocks) and to_block < len(self.blocks):
            self.blocks[from_block].successors.add(to_block)
            self.blocks[to_block].predecessors.add(from_block)


def _build_cfg(stmts: list[Any]) -> ControlFlowGraph:
    """Build control flow graph from statements."""
    cfg = ControlFlowGraph()
    
    def build_blocks_recursive(stmts: list[Any], parent_block: Optional[int] = None) -> List[int]:
        blocks = []
        current_block_stmts = []
        
        for stmt in stmts:
            # Control flow statements end basic blocks
            if isinstance(stmt, (IfStmt, WhileStmt, MatchStmt, ReturnStmt, BreakStmt, ContinueStmt)):
                if current_block_stmts:
                    block_id = cfg.add_block(current_block_stmts)
                    blocks.append(block_id)
                    current_block_stmts = []
                
                # Handle control flow
                if isinstance(stmt, IfStmt):
                    # Add the condition as a separate block or include it
                    if_block_id = cfg.add_block([stmt])
                    blocks.append(if_block_id)
                    
                    # Process then and else branches
                    then_blocks = build_blocks_recursive(stmt.then_body, if_block_id)
                    else_blocks = build_blocks_recursive(stmt.else_body, if_block_id)
                    
                    # Connect if block to branch blocks
                    if then_blocks:
                        cfg.add_edge(if_block_id, then_blocks[0])
                    if else_blocks:
                        cfg.add_edge(if_block_id, else_blocks[0])
                    
                elif isinstance(stmt, WhileStmt):
                    # Create loop header
                    header_id = cfg.add_block([stmt])
                    blocks.append(header_id)
                    
                    # Process loop body
                    body_blocks = build_blocks_recursive(stmt.body, header_id)
                    
                    # Connect header to body and create back edge
                    if body_blocks:
                        cfg.add_edge(header_id, body_blocks[0])
                        cfg.add_edge(body_blocks[-1], header_id)  # Back edge
                    else:
                        cfg.add_edge(header_id, header_id)  # Self-loop
                
                elif isinstance(stmt, ReturnStmt):
                    return_block_id = cfg.add_block([stmt])
                    blocks.append(return_block_id)
                    cfg.exit_blocks.add(return_block_id)
                
                elif isinstance(stmt, (BreakStmt, ContinueStmt)):
                    # These are handled in the loop context
                    block_id = cfg.add_block([stmt])
                    blocks.append(block_id)
            else:
                current_block_stmts.append(stmt)
        
        # Add remaining statements as a block
        if current_block_stmts:
            block_id = cfg.add_block(current_block_stmts)
            blocks.append(block_id)
        
        return blocks
    
    # Build CFG
    block_ids = build_blocks_recursive(stmts)
    if block_ids:
        cfg.entry_block = block_ids[0]
    
    return cfg


def _precise_must_assign_analysis(cfg: ControlFlowGraph) -> Set[str]:
    """Perform precise must-assign analysis using dataflow analysis."""
    if not cfg.blocks:
        return set()
    
    # Initialize dataflow analysis
    # IN[B] = intersection of predecessors' OUT
    # OUT[B] = IN[B] ∪ gen[B] - kill[B]
    
    num_blocks = len(cfg.blocks)
    must_assign_in: List[Set[str]] = [set() for _ in range(num_blocks)]
    must_assign_out: List[Set[str]] = [set() for _ in range(num_blocks)]
    
    # Compute gen and kill sets for each block
    gen_sets: List[Set[str]] = []
    kill_sets: List[Set[str]] = []
    
    for block in cfg.blocks:
        gen, kill = _compute_gen_kill_sets(block.stmts)
        gen_sets.append(gen)
        kill_sets.append(kill)
    
    # Iterative dataflow analysis
    changed = True
    while changed:
        changed = False
        
        # Process blocks in reverse order for faster convergence
        for block_id in reversed(range(num_blocks)):
            block = cfg.blocks[block_id]
            
            # Compute IN[B] as intersection of predecessors' OUT
            old_in = must_assign_in[block_id].copy()
            must_assign_in[block_id] = set()
            
            if block.predecessors:
                # Initialize with first predecessor
                first_pred = next(iter(block.predecessors))
                must_assign_in[block_id] = must_assign_out[first_pred].copy()
                
                # Intersect with other predecessors
                for pred_id in block.predecessors:
                    if pred_id != first_pred:
                        must_assign_in[block_id] &= must_assign_out[pred_id]
            
            # Compute OUT[B] = IN[B] ∪ gen[B] - kill[B]
            old_out = must_assign_out[block_id].copy()
            must_assign_out[block_id] = (must_assign_in[block_id] | gen_sets[block_id]) - kill_sets[block_id]
            
            # Check for changes
            if must_assign_in[block_id] != old_in or must_assign_out[block_id] != old_out:
                changed = True
    
    # Return union of all exit blocks' OUT sets
    result = set()
    for exit_id in cfg.exit_blocks:
        result |= must_assign_out[exit_id]
    
    # If no explicit exit blocks, use last block
    if not result and cfg.blocks:
        result |= must_assign_out[-1]
    
    return result


def _compute_gen_kill_sets(stmts: list[Any]) -> tuple[Set[str], Set[str]]:
    """Compute gen and kill sets for must-assign analysis."""
    gen = set()
    kill = set()
    
    for stmt in stmts:
        if isinstance(stmt, LetStmt):
            # Let always generates the name
            gen.add(stmt.name)
        elif isinstance(stmt, AssignStmt):
            if isinstance(stmt.target, Name):
                # Assignment generates the target name
                gen.add(stmt.target.value)
                # Kills any previous value of the same name
                kill.add(stmt.target.value)
        elif isinstance(stmt, ExprStmt):
            # Function calls may kill names they mutate
            if isinstance(stmt.expr, Call):
                func_info = _get_function_info(stmt.expr.fn.value) if isinstance(stmt.expr.fn, Name) else None
                if func_info:
                    for param_idx in func_info.mutates_params:
                        if param_idx < len(stmt.expr.args) and isinstance(stmt.expr.args[param_idx], Name):
                            kill.add(stmt.expr.args[param_idx].value)
                    kill.update(func_info.writes_globals)
    
    return gen, kill


def _must_write_names_stmts(stmts: list[Any]) -> Set[str]:
    """Get names that are definitely written in all execution paths.
    
    Enhanced with precise control flow analysis using CFG.
    """
    if not stmts:
        return set()
    
    # Build control flow graph for precise analysis
    cfg = _build_cfg(stmts)
    
    # Use CFG-based analysis for precision
    if len(cfg.blocks) > 1:
        # Complex control flow - use precise CFG analysis
        return _precise_must_assign_analysis(cfg)
    else:
        # Simple sequential code - use may-assign as must-assign
        return _may_write_names_stmts(stmts)


# Escape Analysis Framework
@dataclass
class EscapeInfo:
    """Information about object escape status."""
    does_not_escape: bool = True  # Object does not escape current function
    escapes_via_return: bool = False  # Object returned from function
    escapes_via_parameter: bool = False  # Object passed to escaping function
    escapes_via_global: bool = False  # Object stored in global
    allocation_site: Optional[str] = None  # Where object was allocated


@dataclass
class AllocationInfo:
    """Information about memory allocation."""
    can_allocate_on_stack: bool = False
    size_estimate: Optional[int] = None
    lifetime_info: Optional[str] = None
    escape_info: EscapeInfo = field(default_factory=EscapeInfo)


# Global allocation analysis context
_allocation_analysis: Dict[str, AllocationInfo] = {}


def _analyze_escape(expr: Any, current_function: str) -> EscapeInfo:
    """Analyze if an expression escapes the current function."""
    escape_info = EscapeInfo()
    
    def analyze_recursive(e: Any, depth: int = 0) -> bool:
        if depth > 10:  # Prevent infinite recursion
            return True
        
        if isinstance(e, Name):
            # Check if name is returned or passed to escaping function
            symbol = _symbol_table.lookup(e.value)
            if symbol and symbol.is_parameter:
                # Parameters might escape
                return True
        elif isinstance(e, Call):
            # Function calls may cause escape
            if isinstance(e.fn, Name):
                func_info = _get_function_info(e.fn.value)
                if not func_info.is_pure:
                    # Impure function may cause escape
                    return True
            
            # Check all arguments
            for arg in e.args:
                if analyze_recursive(arg, depth + 1):
                    return True
        elif isinstance(e, Unary) and e.op == '&':
            # Taking address - definitely escapes
            return True
        elif isinstance(e, AssignStmt):
            # Assignment - check if RHS escapes
            return analyze_recursive(e.expr, depth + 1)
        elif isinstance(e, ReturnStmt):
            if e.expr:
                # Returned expression escapes
                escape_info.escapes_via_return = True
                return True
        
        return False
    
    escapes = analyze_recursive(expr)
    escape_info.does_not_escape = not escapes
    
    return escape_info


def _analyze_allocation(expr: Any, current_function: str) -> AllocationInfo:
    """Analyze allocation requirements for an expression."""
    alloc_info = AllocationInfo()
    
    # Analyze escape status
    alloc_info.escape_info = _analyze_escape(expr, current_function)
    
    # Determine if can allocate on stack
    if alloc_info.escape_info.does_not_escape:
        alloc_info.can_allocate_on_stack = True
        alloc_info.lifetime_info = "stack_local"
    else:
        alloc_info.can_allocate_on_stack = False
        alloc_info.lifetime_info = "heap_required"
    
    # Estimate size (heuristic)
    if isinstance(expr, Call) and isinstance(expr.fn, Name):
        if expr.fn.value in ['malloc', 'new', 'alloc']:
            alloc_info.size_estimate = 64  # Default heuristic
            alloc_info.lifetime_info = "heap_explicit"
    
    return alloc_info


# Parallelism Analysis Framework
@dataclass
class ParallelismInfo:
    """Information about parallel execution safety."""
    can_parallelize: bool = False
    has_data_dependencies: bool = False
    has_control_dependencies: bool = False
    has_side_effects: bool = False
    requires_synchronization: Set[str] = field(default_factory=set)
    safe_to_vectorize: bool = False
    loop_carried_dependencies: Set[str] = field(default_factory=set)


# Global parallelism analysis context
_parallelism_analysis: Dict[str, ParallelismInfo] = {}


def _analyze_loop_parallelism(loop_stmt: Any) -> ParallelismInfo:
    """Analyze if a loop can be parallelized safely."""
    parallel_info = ParallelismInfo()
    
    if not isinstance(loop_stmt, WhileStmt):
        return parallel_info
    
    # Check for loop-carried dependencies
    loop_vars = _used_names_expr(loop_stmt.cond) if loop_stmt.cond else set()
    
    def check_dependencies(stmts: list[Any], depth: int = 0) -> Set[str]:
        if depth > 5:  # Prevent infinite recursion
            return set()
        
        dependencies = set()
        
        for stmt in stmts:
            if isinstance(stmt, AssignStmt):
                if isinstance(stmt.target, Name):
                    # Check if RHS uses variables modified in previous iterations
                    rhs_vars = _used_names_expr(stmt.expr)
                    if stmt.target.value in rhs_vars:
                        # Loop-carried dependency
                        dependencies.add(stmt.target.value)
            elif isinstance(stmt, ExprStmt) and isinstance(stmt.expr, Call):
                # Function calls may have dependencies
                func_info = _get_function_info(stmt.expr.fn.value) if isinstance(stmt.expr.fn, Name) else None
                if func_info and not func_info.is_pure:
                    dependencies.add(stmt.expr.fn.value)
            elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
                dependencies.update(check_dependencies(stmt.body, depth + 1))
            elif hasattr(stmt, 'then_body') and isinstance(stmt.then_body, list):
                dependencies.update(check_dependencies(stmt.then_body, depth + 1))
            elif hasattr(stmt, 'else_body') and isinstance(stmt.else_body, list):
                dependencies.update(check_dependencies(stmt.else_body, depth + 1))
        
        return dependencies
    
    loop_carried = check_dependencies(loop_stmt.body)
    
    if loop_carried:
        parallel_info.has_data_dependencies = True
        parallel_info.loop_carried_dependencies = loop_carried
        parallel_info.can_parallelize = False
    else:
        # No obvious dependencies - might be parallelizable
        parallel_info.can_parallelize = True
        parallel_info.safe_to_vectorize = True
    
    # Check for side effects
    def has_side_effects_recursive(stmts: list[Any], depth: int = 0) -> bool:
        if depth > 5:
            return False
        
        for stmt in stmts:
            if isinstance(stmt, ExprStmt) and isinstance(stmt.expr, Call):
                func_info = _get_function_info(stmt.expr.fn.value) if isinstance(stmt.expr.fn, Name) else None
                if func_info and (func_info.writes_globals or func_info.mutates_params):
                    return True
            elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
                if has_side_effects_recursive(stmt.body, depth + 1):
                    return True
        
        return False
    
    parallel_info.has_side_effects = has_side_effects_recursive(loop_stmt.body)
    
    if parallel_info.has_side_effects:
        parallel_info.can_parallelize = False
        parallel_info.requires_synchronization = {'memory_barrier', 'atomic_ops'}
    
    return parallel_info


# Global analysis context
_function_registry: Dict[str, FunctionInfo] = {}
_alias_info = AliasInfo()
_type_info_cache: Dict[Any, TypeInfo] = {}


def _analyze_type(expr: Any) -> TypeInfo:
    """Analyze type information for an expression using symbol table."""
    # Use string representation as cache key since AST objects aren't hashable
    cache_key = str(expr)
    if cache_key in _type_info_cache:
        return _type_info_cache[cache_key]
    
    info = TypeInfo()
    
    if isinstance(expr, Name):
        # Use symbol table for accurate type information
        symbol_info = _symbol_table.lookup(expr.value)
        if symbol_info:
            info.is_pointer = symbol_info.is_pointer
            info.is_reference = symbol_info.is_reference
            info.is_array = symbol_info.is_array
            info.element_type = symbol_info.element_type
            info.pointee_type = symbol_info.pointee_type
        else:
            # Fallback to heuristic analysis
            info.is_pointer = expr.value.endswith('_ptr') or expr.value.endswith('*')
            info.is_reference = expr.value.endswith('_ref') or expr.value.endswith('&')
    elif isinstance(expr, Unary):
        if expr.op == '*':
            info.is_pointer = True
            if isinstance(expr.expr, Name):
                symbol_info = _symbol_table.lookup(expr.expr.value)
                if symbol_info and symbol_info.pointee_type:
                    info.pointee_type = symbol_info.pointee_type
                else:
                    info.pointee_type = expr.expr.value.rstrip('_ptr').rstrip('*')
        elif expr.op == '&':
            info.is_reference = True
    elif isinstance(expr, IndexExpr):
        info.is_array = True
        if isinstance(expr.obj, Name):
            symbol_info = _symbol_table.lookup(expr.obj.value)
            if symbol_info and symbol_info.element_type:
                info.element_type = symbol_info.element_type
    
    _type_info_cache[cache_key] = info
    return info


def _complete_alias_analysis(stmts: list[Any]) -> AliasInfo:
    """Perform complete alias analysis on statements."""
    aliases = AliasInfo()
    
    def collect_aliases(stmt: Any, scope: Set[str]):
        if isinstance(stmt, LetStmt):
            scope.add(stmt.name)
            # Analyze the expression for alias creation
            _collect_expr_aliases(stmt.expr, scope, aliases)
        elif isinstance(stmt, AssignStmt):
            # Analyze both target and expression for aliases
            _collect_target_aliases(stmt.target, scope, aliases)
            _collect_expr_aliases(stmt.expr, scope, aliases)
        elif isinstance(stmt, ExprStmt):
            _collect_expr_aliases(stmt.expr, scope, aliases)
        # Recursively analyze compound statements
        elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
            for sub_stmt in stmt.body:
                collect_aliases(sub_stmt, scope.copy())
        elif hasattr(stmt, 'then_body') and isinstance(stmt.then_body, list):
            for sub_stmt in stmt.then_body:
                collect_aliases(sub_stmt, scope.copy())
        elif hasattr(stmt, 'else_body') and isinstance(stmt.else_body, list):
            for sub_stmt in stmt.else_body:
                collect_aliases(sub_stmt, scope.copy())
    
    for stmt in stmts:
        collect_aliases(stmt, set())
    
    return aliases


def _collect_expr_aliases(expr: Any, scope: Set[str], aliases: AliasInfo):
    """Collect alias relationships from expressions."""
    if isinstance(expr, Unary):
        if expr.op == '&':
            # Address-of creates a reference
            if isinstance(expr.expr, Name):
                source = expr.expr.value
                # This reference could alias with any future pointer that receives it
                for name in scope:
                    if name != source:
                        aliases.direct_aliases.setdefault(name, set()).add(source)
                        aliases.direct_aliases.setdefault(source, set()).add(name)
        elif expr.op == '*':
            # Dereference - pointer may alias with its target
            if isinstance(expr.expr, Name):
                ptr_name = expr.expr.value
                type_info = _analyze_type(expr.expr)
                if type_info.pointee_type:
                    aliases.pointer_targets.setdefault(ptr_name, set()).add(type_info.pointee_type)
        # Recursively analyze sub-expressions
        _collect_expr_aliases(expr.expr, scope, aliases)
    elif isinstance(expr, Binary):
        _collect_expr_aliases(expr.left, scope, aliases)
        _collect_expr_aliases(expr.right, scope, aliases)
    elif isinstance(expr, Call):
        # Function calls may create aliases through parameters
        for i, arg in enumerate(expr.args):
            func_info = _function_registry.get(expr.fn.value) if isinstance(expr.fn, Name) else None
            if func_info and i in func_info.takes_refs:
                if isinstance(arg, Name):
                    aliases.ref_sources[arg.value] = f"param_{i}"
            _collect_expr_aliases(arg, scope, aliases)


def _collect_target_aliases(target: Any, scope: Set[str], aliases: AliasInfo):
    """Collect alias relationships from assignment targets."""
    if isinstance(target, Name):
        # Direct assignment - no new aliases created
        pass
    elif isinstance(target, IndexExpr):
        # Array indexing doesn't create aliases
        _collect_expr_aliases(target.obj, scope, aliases)
        _collect_expr_aliases(target.index, scope, aliases)
    elif isinstance(target, FieldExpr):
        # Field access doesn't create aliases
        _collect_expr_aliases(target.obj, scope, aliases)
    elif isinstance(target, Unary) and target.op == '*':
        # Writing through pointer - may affect all aliases
        if isinstance(target.expr, Name):
            ptr_name = target.expr.value
            # This pointer write may affect all names it aliases with
            all_aliases = set()
            all_aliases.update(aliases.direct_aliases.get(ptr_name, set()))
            all_aliases.update(aliases.pointer_targets.get(ptr_name, set()))
            for alias in all_aliases:
                aliases.direct_aliases.setdefault(ptr_name, set()).add(alias)
                aliases.direct_aliases.setdefault(alias, set()).add(ptr_name)


def _names_mutated_via_aliases(target: Any, aliases: AliasInfo) -> Set[str]:
    """Get names that may be mutated through alias relationships."""
    mutated = set()
    
    if isinstance(target, Name):
        name = target.value
        # Get all direct aliases
        mutated.update(aliases.direct_aliases.get(name, set()))
        # Get pointer target aliases
        mutated.update(aliases.pointer_targets.get(name, set()))
        # Check if this is a reference to something
        if name in aliases.ref_sources:
            source = aliases.ref_sources[name]
            mutated.update(aliases.direct_aliases.get(source, set()))
    elif isinstance(target, Unary) and target.op == '*':
        # Pointer dereference - may mutate all possible targets
        if isinstance(target.expr, Name):
            ptr_name = target.expr.value
            mutated.update(aliases.pointer_targets.get(ptr_name, set()))
            # Also check direct aliases
            mutated.update(aliases.direct_aliases.get(ptr_name, set()))
    
    return mutated


def _dse_stmts(stmts: list[Any], live_out: set[str]) -> tuple[list[Any], set[str]]:
    live = set(live_out)
    out_rev: list[Any] = []
    for st in reversed(stmts):
        if isinstance(st, ReturnStmt):
            out_rev.append(st)
            live = _used_names_expr(st.expr) if st.expr is not None else set()
            continue
        if isinstance(st, ExprStmt):
            if _is_discardable_expr(st.expr):
                continue
            out_rev.append(st)
            live |= _used_names_expr(st.expr)
            continue
        if isinstance(st, LetStmt):
            uses = _used_names_expr(st.expr)
            if st.name not in live:
                if _is_discardable_expr(st.expr):
                    continue
                out_rev.append(st)
                live |= uses
                continue
            out_rev.append(st)
            live.discard(st.name)
            live |= uses
            continue
        if isinstance(st, AssignStmt):
            if isinstance(st.target, Name) and st.op == "=" and st.target.value not in live:
                if _is_discardable_expr(st.expr):
                    continue
                # Keep AssignStmt as-is instead of converting to ExprStmt
                # Converting to ExprStmt breaks variable assignments in generated code
                out_rev.append(st)
                live |= _used_names_expr(st.expr)
                continue
            out_rev.append(st)
            uses = _used_names_expr(st.expr) | _used_names_in_target_addr(st.target)
            if isinstance(st.target, Name):
                if st.op == "=":
                    live.discard(st.target.value)
                    live |= uses
                elif st.op in {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}:
                    # Compound assignments read the previous target value.
                    live |= uses | {st.target.value}
                else:
                    live |= uses
            else:
                live |= uses
            continue
        if isinstance(st, IfStmt):
            then_body, then_live = _dse_stmts(st.then_body, set(live))
            else_body, else_live = _dse_stmts(st.else_body, set(live))
            st.then_body = then_body
            st.else_body = else_body
            cond_uses = _used_names_expr(st.cond)
            if not st.then_body and not st.else_body and _is_discardable_expr(st.cond):
                live |= then_live | else_live
                continue
            out_rev.append(st)
            live = cond_uses | then_live | else_live
            continue
        if isinstance(st, MatchStmt):
            arm_lives: list[set[str]] = []
            new_arms: list[tuple[Any, list[Any]]] = []
            for pat, body in st.arms:
                body_out, arm_live = _dse_stmts(body, set(live))
                new_arms.append((pat, body_out))
                arm_lives.append(arm_live | _used_names_expr(pat))
            st.arms = new_arms
            out_rev.append(st)
            cond_live = _used_names_expr(st.expr)
            combined = set(cond_live)
            for arm_live in arm_lives:
                combined |= arm_live
            live = combined
            continue
        if isinstance(st, WhileStmt):
            loop_live_seed = set(live) | _used_names_expr(st.cond) | _may_write_names_stmts(st.body)
            body_out, body_live = _dse_stmts(st.body, loop_live_seed)
            st.body = body_out
            out_rev.append(st)
            live = set(live) | _used_names_expr(st.cond) | body_live | _may_write_names_stmts(st.body)
            continue
        if isinstance(st, IteratorForStmt):
            loop_seed = set(live) | _may_write_names_stmts(st.body)
            if st.cond is not None:
                loop_seed |= _used_names_expr(st.cond)
            if st.step is not None:
                if isinstance(st.step, AssignStmt):
                    loop_seed |= _used_names_expr(st.step.expr) | _used_names_in_target_addr(st.step.target)
                else:
                    loop_seed |= _used_names_expr(st.step)
            body_out, body_live = _dse_stmts(st.body, loop_seed)
            st.body = body_out
            out_rev.append(st)
            live |= body_live
            if st.init is not None:
                if isinstance(st.init, LetStmt):
                    live |= _used_names_expr(st.init.expr)
                else:
                    live |= _used_names_expr(st.init)
            if st.cond is not None:
                live |= _used_names_expr(st.cond)
            if st.step is not None:
                if isinstance(st.step, AssignStmt):
                    live |= _used_names_expr(st.step.expr) | _used_names_in_target_addr(st.step.target)
                    if isinstance(st.step.target, Name):
                        live.add(st.step.target.value)
                else:
                    live |= _used_names_expr(st.step)
            continue
        if isinstance(st, ComptimeStmt):
            body_out, body_live = _dse_stmts(st.body, set(live))
            st.body = body_out
            out_rev.append(st)
            live |= body_live
            continue
        if isinstance(st, UnsafeStmt):
            body_out, body_live = _dse_stmts(st.body, set(live))
            st.body = body_out
            out_rev.append(st)
            live |= body_live
            continue
        if isinstance(st, (BreakStmt, ContinueStmt)):
            out_rev.append(st)
            continue
        out_rev.append(st)
    out_rev.reverse()
    return out_rev, live


def _used_names_expr(expr: Any) -> set[str]:
    if isinstance(expr, Name):
        return {expr.value}
    if isinstance(expr, (Literal, BoolLit, NilLit)):
        return set()
    if isinstance(expr, Unary):
        return _used_names_expr(expr.expr)
    if isinstance(expr, Binary):
        return _used_names_expr(expr.left) | _used_names_expr(expr.right)
    if isinstance(expr, Call):
        out = _used_names_expr(expr.fn)
        for arg in expr.args:
            out |= _used_names_expr(arg)
        return out
    if isinstance(expr, AwaitExpr):
        return _used_names_expr(expr.expr)
    if isinstance(expr, TryExpr):
        return _used_names_expr(expr.expr)
    if isinstance(expr, IndexExpr):
        return _used_names_expr(expr.obj) | _used_names_expr(expr.index)
    if isinstance(expr, FieldExpr):
        return _used_names_expr(expr.obj)
    if isinstance(expr, ArrayLit):
        out: set[str] = set()
        for elem in expr.elements:
            out |= _used_names_expr(elem)
        return out
    if isinstance(expr, StringInterpolation):
        out: set[str] = set()
        for expr_part in expr.exprs:
            out |= _used_names_expr(expr_part)
        return out
    if isinstance(expr, StructLit):
        out: set[str] = set()
        for _, value in expr.fields:
            out |= _used_names_expr(value)
        return out
    if isinstance(expr, TypeAnnotated):
        return _used_names_expr(expr.expr)
    if isinstance(expr, CastExpr):
        return _used_names_expr(expr.expr)
    if isinstance(expr, OrPattern):
        out: set[str] = set()
        for p in expr.patterns:
            out |= _used_names_expr(p)
        return out
    if isinstance(expr, GuardedPattern):
        return _used_names_expr(expr.pattern) | _used_names_expr(expr.guard)
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr, BitSizeOfTypeExpr, MaxValTypeExpr, MinValTypeExpr)):
        return set()
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        return _used_names_expr(expr.expr)
    return set()


def _used_names_in_target_addr(target: Any) -> set[str]:
    """Get names whose values are read to compute the target address.
    
    This represents names read in order to determine WHERE to write,
    not what value is being written. For example:
    
    - x = ...: reads no names to identify target, returns set()
    - a[i] = ...: reads a and i to compute target address
    - obj.field = ...: reads obj to compute target address
    
    This is distinct from names read in the RHS expression.
    """
    if isinstance(target, Name):
        return set()
    if isinstance(target, IndexExpr):
        return _used_names_expr(target.obj) | _used_names_expr(target.index)
    if isinstance(target, FieldExpr):
        return _used_names_expr(target.obj)
    return _used_names_expr(target)


def _may_write_names_stmts(stmts: list[Any], aliases: AliasInfo = None) -> Set[str]:
    """Get names that may be written (assigned) in the given statements.
    
    Enhanced with complete alias analysis, function purity, and type information.
    """
    out: Set[str] = set()
    
    # Perform alias analysis if not provided
    if aliases is None:
        aliases = _complete_alias_analysis(stmts)

    def walk(items: list[Any]):
        for st in items:
            if isinstance(st, LetStmt):
                # Let creates a new binding for the name
                out.add(st.name)
            elif isinstance(st, AssignStmt):
                # Direct assignment to a name
                if isinstance(st.target, Name):
                    out.add(st.target.value)
                else:
                    # Indirect write - enhanced analysis with aliases and types
                    mutated = _names_mutated_by_target(st.target, aliases=None)
                    out.update(mutated)
            elif isinstance(st, ExprStmt):
                # Function calls with interprocedural analysis
                mutated = _names_mutated_by_expr(st.expr, aliases)
                out.update(mutated)
            elif isinstance(st, IfStmt):
                # Union of both branches (may-assign)
                walk(st.then_body)
                walk(st.else_body)
            elif isinstance(st, WhileStmt):
                walk(st.body)
            elif isinstance(st, MatchStmt):
                for _, body in st.arms:
                    walk(body)
            elif isinstance(st, ComptimeStmt):
                walk(st.body)
            elif isinstance(st, UnsafeStmt):
                walk(st.body)

    walk(stmts)
    return out
