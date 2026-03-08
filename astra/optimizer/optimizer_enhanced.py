"""Enhanced optimizer with advanced passes for better performance."""

from __future__ import annotations

from typing import Any, Set, Dict, List, Tuple, Optional
from dataclasses import dataclass

from astra.ast import *
from astra.int_types import parse_int_type_name


@dataclass
class OptimizationContext:
    """Context for optimization passes."""
    overflow_mode: str = "trap"
    profile: str = "debug"
    mutable_names: Set[str] = None
    function_calls: Set[str] = None
    
    def __post_init__(self):
        if self.mutable_names is None:
            self.mutable_names = set()
        if self.function_calls is None:
            self.function_calls = set()


class LoopOptimizer:
    """Advanced loop optimization pass."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def optimize_loops(self, stmts: List[Any]) -> List[Any]:
        """Apply loop optimizations to statement list."""
        out = []
        for stmt in stmts:
            if isinstance(stmt, WhileStmt):
                optimized = self._optimize_while_loop(stmt)
                out.append(optimized)
            elif isinstance(stmt, IteratorForStmt):
                # Iterator for loops
                out.append(stmt)
            else:
                out.append(stmt)
        return out
    
    def _optimize_while_loop(self, loop: WhileStmt) -> WhileStmt:
        """Optimize a while loop with invariant code motion."""
        # Collect loop-carried variables
        loop_vars = self._collect_loop_vars(loop.body)
        
        # Identify invariant statements
        invariant_stmts = []
        varied_stmts = []
        
        for stmt in loop.body:
            if self._is_loop_invariant(stmt, loop_vars):
                invariant_stmts.append(stmt)
            else:
                varied_stmts.append(stmt)
        
        # Move invariant statements before the loop
        loop.body = varied_stmts
        
        # Return modified loop with invariants to be hoisted
        setattr(loop, "_invariant_stmts", invariant_stmts)
        return loop
    
    def _collect_loop_vars(self, stmts: List[Any]) -> Set[str]:
        """Collect variables that may be modified in the loop."""
        vars_modified = set()
        
        for stmt in stmts:
            if isinstance(stmt, LetStmt):
                vars_modified.add(stmt.name)
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                vars_modified.add(stmt.target.value)
            elif isinstance(stmt, IfStmt):
                vars_modified.update(self._collect_loop_vars(stmt.then_body))
                vars_modified.update(self._collect_loop_vars(stmt.else_body))
        
        return vars_modified
    
    def _is_loop_invariant(self, stmt: Any, loop_vars: Set[str]) -> bool:
        """Check if a statement is loop invariant."""
        if isinstance(stmt, ExprStmt):
            return self._expr_is_invariant(stmt.expr, loop_vars)
        elif isinstance(stmt, LetStmt):
            return self._expr_is_invariant(stmt.expr, loop_vars) and stmt.name not in loop_vars
        return False
    
    def _expr_is_invariant(self, expr: Any, loop_vars: Set[str]) -> bool:
        """Check if an expression is loop invariant."""
        if isinstance(expr, Name):
            return expr.value not in loop_vars
        elif isinstance(expr, (Literal, BoolLit, NilLit)):
            return True
        elif isinstance(expr, Unary):
            return self._expr_is_invariant(expr.expr, loop_vars)
        elif isinstance(expr, Binary):
            return (self._expr_is_invariant(expr.left, loop_vars) and 
                   self._expr_is_invariant(expr.right, loop_vars))
        elif isinstance(expr, Call):
            # Conservative: assume function calls are not invariant
            # unless they are known pure functions
            return False
        return False


class SSAPromoter:
    """Promote allocas to SSA form (mem2reg equivalent)."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def promote_to_ssa(self, fn: FnDecl) -> FnDecl:
        """Promote local variables to SSA form."""
        # Find variables that can be promoted
        promotable = self._find_promotable_vars(fn.body)
        
        # Replace stores/loads with direct SSA values
        new_body = self._replace_memory_ops(fn.body, promotable)
        
        fn.body = new_body
        return fn
    
    def _find_promotable_vars(self, stmts: List[Any]) -> Set[str]:
        """Find variables that can be promoted to SSA."""
        promotable = set()
        
        for stmt in stmts:
            if isinstance(stmt, LetStmt):
                # Only promote immutable locals
                if not stmt.mut and self._is_simple_type(stmt):
                    promotable.add(stmt.name)
        
        return promotable
    
    def _is_simple_type(self, stmt: LetStmt) -> bool:
        """Check if variable has a simple type suitable for SSA."""
        # For now, only promote scalar types
        typ = getattr(stmt, "inferred_type", None)
        if typ is None:
            return False
        
        simple_types = {"Int", "isize", "usize", "Bool", "Float", "f32", "f64"}
        if typ in simple_types:
            return True
        
        # Check for integer types like i32, u64, etc.
        if parse_int_type_name(typ) is not None:
            return True
        
        return False
    
    def _replace_memory_ops(self, stmts: List[Any], promotable: Set[str]) -> List[Any]:
        """Replace memory operations with SSA values."""
        # This is a simplified implementation
        # A full implementation would need proper SSA construction
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, LetStmt) and stmt.name in promotable:
                # Keep the let but mark for SSA promotion
                setattr(stmt, "_ssa_promoted", True)
                new_stmts.append(stmt)
            else:
                new_stmts.append(stmt)
        
        return new_stmts


class EnhancedConstantFolder:
    """Enhanced constant folding with more operations."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def fold_program(self, prog: Program) -> Program:
        """Apply enhanced constant folding to entire program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._fold_function(item)
        return prog
    
    def _fold_function(self, fn: FnDecl) -> None:
        """Fold constants in a function."""
        env = {}
        mutable_names = self._collect_mutable_names(fn.body)
        
        for _ in range(10):  # More iterations for better convergence
            changed = False
            new_body = []
            
            for stmt in fn.body:
                new_stmt = self._fold_stmt(stmt, env, mutable_names)
                if new_stmt is not None:
                    new_body.append(new_stmt)
                    if new_stmt != stmt:
                        changed = True
            
            fn.body = new_body
            if not changed:
                break
    
    def _fold_stmt(self, stmt: Any, env: Dict[str, Any], mutable_names: Set[str]) -> Any:
        """Fold constants in a statement."""
        if isinstance(stmt, LetStmt):
            stmt.expr = self._fold_expr(stmt.expr, env, mutable_names)
            lit = self._literal_value(stmt.expr)
            if lit is not self._NO_LITERAL and stmt.name not in mutable_names:
                env[stmt.name] = self._literal_node(lit, stmt.expr)
            return stmt
        elif isinstance(stmt, ExprStmt):
            stmt.expr = self._fold_expr(stmt.expr, env, mutable_names)
            # Remove dead pure expressions
            if self._is_discardable_expr(stmt.expr):
                return None
            return stmt
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                stmt.expr = self._fold_expr(stmt.expr, env, mutable_names)
            return stmt
        elif isinstance(stmt, IfStmt):
            stmt.cond = self._fold_expr(stmt.cond, env, mutable_names)
            cond_val = self._literal_value(stmt.cond)
            if isinstance(cond_val, bool):
                # Dead branch elimination
                branch = stmt.then_body if cond_val else stmt.else_body
                branch_body = self._fold_stmts(branch, dict(env), mutable_names)
                # Return branch body directly
                return branch_body
            else:
                stmt.then_body = self._fold_stmts(stmt.then_body, dict(env), mutable_names)
                stmt.else_body = self._fold_stmts(stmt.else_body, dict(env), mutable_names)
                return stmt
        else:
            return stmt
    
    def _fold_stmts(self, stmts: List[Any], env: Dict[str, Any], mutable_names: Set[str]) -> List[Any]:
        """Fold constants in statement list."""
        new_stmts = []
        for stmt in stmts:
            folded = self._fold_stmt(stmt, env, mutable_names)
            if folded is not None:
                if isinstance(folded, list):
                    new_stmts.extend(folded)
                else:
                    new_stmts.append(folded)
        return new_stmts
    
    def _fold_expr(self, expr: Any, env: Dict[str, Any], mutable_names: Set[str]) -> Any:
        """Enhanced constant folding for expressions."""
        if isinstance(expr, Name):
            if expr.value in env and expr.value not in mutable_names:
                bound = env[expr.value]
                lit = self._literal_value(bound)
                if lit is not self._NO_LITERAL:
                    return self._literal_node(lit, expr)
            return expr
        elif isinstance(expr, (Literal, BoolLit, NilLit)):
            return expr
        elif isinstance(expr, Unary):
            expr.expr = self._fold_expr(expr.expr, env, mutable_names)
            value = self._literal_value(expr.expr)
            if value is self._NO_LITERAL:
                return expr
            
            if expr.op == "-":
                if isinstance(value, (int, float)):
                    return self._literal_node(-value, expr)
            elif expr.op == "!":
                return self._literal_node(not bool(value), expr)
            elif expr.op == "~":
                if isinstance(value, int):
                    return self._literal_node(~value, expr)
            return expr
        elif isinstance(expr, Binary):
            expr.left = self._fold_expr(expr.left, env, mutable_names)
            expr.right = self._fold_expr(expr.right, env, mutable_names)
            
            lval = self._literal_value(expr.left)
            rval = self._literal_value(expr.right)
            
            # Try constant evaluation
            result = self._eval_binary_const(expr.op, lval, rval)
            if result is not self._NO_LITERAL:
                return self._literal_node(result, expr)
            
            # Enhanced algebraic simplifications
            return self._simplify_binary(expr, lval, rval)
        elif isinstance(expr, Call):
            expr.fn = self._fold_expr(expr.fn, env, mutable_names)
            expr.args = [self._fold_expr(arg, env, mutable_names) for arg in expr.args]
            return expr
        else:
            return expr
    
    def _simplify_binary(self, expr: Binary, lval: Any, rval: Any) -> Binary:
        """Enhanced binary expression simplification."""
        # More aggressive strength reduction
        if expr.op == "*":
            # Multiplication by power of 2
            if rval is not None and isinstance(rval, int) and rval > 0 and (rval & (rval - 1)) == 0:
                shift = rval.bit_length() - 1
                if self._is_integer_expr(expr):
                    return Binary(op="<<", left=expr.left, right=self._literal_node(shift, expr.right),
                                pos=expr.pos, line=expr.line, col=expr.col)
            # Multiplication by -1
            if rval == -1:
                return Unary(op="-", expr=expr.left, pos=expr.pos, line=expr.line, col=expr.col)
        
        elif expr.op == "/":
            # Division by power of 2 (for unsigned)
            if rval is not None and isinstance(rval, int) and rval > 0 and (rval & (rval - 1)) == 0:
                shift = rval.bit_length() - 1
                if self._is_unsigned_integer_expr(expr):
                    return Binary(op=">>", left=expr.left, right=self._literal_node(shift, expr.right),
                                pos=expr.pos, line=expr.line, col=expr.col)
        
        elif expr.op == "%":
            # Modulo by power of 2 (for unsigned)
            if rval is not None and isinstance(rval, int) and rval > 0 and (rval & (rval - 1)) == 0:
                if self._is_unsigned_integer_expr(expr):
                    return Binary(op="&", left=expr.left, right=self._literal_node(rval - 1, expr.right),
                                pos=expr.pos, line=expr.line, col=expr.col)
        
        elif expr.op == "&":
            # Bitwise AND with all 1s is no-op
            if rval == -1:
                return expr.left
            # Bitwise AND with 0 is 0
            if rval == 0:
                return self._literal_node(0, expr)
        
        elif expr.op == "|":
            # Bitwise OR with 0 is no-op
            if rval == 0:
                return expr.left
            # Bitwise OR with all 1s is all 1s
            if rval == -1:
                return self._literal_node(-1, expr)
        
        return expr
    
    def _eval_binary_const(self, op: str, left: Any, right: Any) -> Any:
        """Enhanced constant evaluation."""
        if left is self._NO_LITERAL or right is self._NO_LITERAL:
            return self._NO_LITERAL
        
        try:
            if op == "+":
                return left + right
            elif op == "-":
                return left - right
            elif op == "*":
                return left * right
            elif op == "/":
                if right != 0:
                    if isinstance(left, int) and isinstance(right, int):
                        return left // right
                    return left / right
            elif op == "%":
                if right != 0:
                    return left % right
            elif op == "&":
                return int(left) & int(right)
            elif op == "|":
                return int(left) | int(right)
            elif op == "^":
                return int(left) ^ int(right)
            elif op == "<<":
                return int(left) << int(right)
            elif op == ">>":
                return int(left) >> int(right)
            elif op == "==":
                return left == right
            elif op == "!=":
                return left != right
            elif op == "<":
                return left < right
            elif op == "<=":
                return left <= right
            elif op == ">":
                return left > right
            elif op == ">=":
                return left >= right
            elif op == "&&":
                return bool(left) and bool(right)
            elif op == "||":
                return bool(left) or bool(right)
        except (ZeroDivisionError, OverflowError, ValueError):
            pass
        
        return self._NO_LITERAL
    
    def _collect_mutable_names(self, stmts: List[Any]) -> Set[str]:
        """Collect mutable variable names."""
        mutable = set()
        for stmt in stmts:
            if isinstance(stmt, LetStmt) and stmt.mut:
                mutable.add(stmt.name)
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                mutable.add(stmt.target.value)
        return mutable
    
    def _is_integer_expr(self, expr: Any) -> bool:
        """Check if expression has integer type."""
        typ = getattr(expr, "inferred_type", None)
        if isinstance(typ, str):
            if typ in {"Int", "isize", "usize"}:
                return True
            return parse_int_type_name(typ) is not None
        return False
    
    def _is_unsigned_integer_expr(self, expr: Any) -> bool:
        """Check if expression has unsigned integer type."""
        typ = getattr(expr, "inferred_type", None)
        if isinstance(typ, str):
            return typ in {"usize"} or (parse_int_type_name(typ) is not None and typ.startswith('u'))
        return False
    
    def _is_discardable_expr(self, expr: Any) -> bool:
        """Check if expression can be safely discarded."""
        return self._is_pure_expr(expr) and not self._may_trap_expr(expr)
    
    def _is_pure_expr(self, expr: Any) -> bool:
        """Check if expression is pure."""
        if isinstance(expr, (Name, Literal, BoolLit, NilLit)):
            return True
        elif isinstance(expr, (Unary, Binary)):
            return True
        elif isinstance(expr, Call):
            return False  # Conservative
        return False
    
    def _may_trap_expr(self, expr: Any) -> bool:
        """Check if expression may trap."""
        if isinstance(expr, (Literal, BoolLit, NilLit, Name)):
            return False
        elif isinstance(expr, Binary):
            if expr.op in {"/", "%"}:
                rval = self._literal_value(expr.right)
                return rval == 0 or rval == -1
            return False
        return True
    
    _NO_LITERAL = object()
    
    def _literal_value(self, expr: Any) -> Any:
        """Extract literal value from expression."""
        if isinstance(expr, BoolLit):
            return bool(expr.value)
        elif isinstance(expr, NilLit):
            return None
        elif isinstance(expr, Literal):
            return expr.value
        return self._NO_LITERAL
    
    def _literal_node(self, value: Any, src: Any) -> Any:
        """Create literal node with position from source."""
        pos = getattr(src, "pos", 0)
        line = getattr(src, "line", 0)
        col = getattr(src, "col", 0)
        
        if value is None:
            return NilLit(pos=pos, line=line, col=col)
        elif isinstance(value, bool):
            return BoolLit(value=value, pos=pos, line=line, col=col)
        else:
            return Literal(value=value, pos=pos, line=line, col=col)


def optimize_program_enhanced(prog: Program, overflow_mode: str = "trap", profile: str = "debug") -> Program:
    """Enhanced optimization pipeline with multiple passes."""
    ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
    print(f"DEBUG: Enhanced optimizer called with profile={profile}")
    
    # Apply base optimizer for constant folding and basic optimizations
    from .optimizer import optimize_program
    prog = optimize_program(prog)
    
    # Apply profile-guided optimizations if profile is provided
    if profile != "debug":
        from .optimizer_pgo import optimize_pgo_program
        print(f"DEBUG: About to call optimize_pgo_program")
        prog = optimize_pgo_program(prog, overflow_mode=overflow_mode, profile=profile)
        print(f"DEBUG: PGO optimization completed, hot functions: {[f.name for f in prog.items if isinstance(f, FnDecl) and hasattr(f, '_hot_function')]}")
    
    # Apply other enhanced optimizations
    loop_optimizer = LoopOptimizer(ctx)
    for item in prog.items:
        if isinstance(item, FnDecl):
            item.body = loop_optimizer.optimize_loops(item.body)
    
    # Pass 3: SSA promotion
    ssa_promoter = SSAPromoter(ctx)
    for item in prog.items:
        if isinstance(item, FnDecl):
            ssa_promoter.promote_to_ssa(item)
    
    return prog
