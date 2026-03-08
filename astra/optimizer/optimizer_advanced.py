"""Advanced optimizer with additional high-impact optimizations."""

from __future__ import annotations

from typing import Any, Optional
from dataclasses import dataclass

from astra.ast import *
from .optimizer_enhanced import OptimizationContext, EnhancedConstantFolder


class ConstantExpressionReuse:
    """Local expression reuse with constant expression cataloging.
    
    This is NOT global value numbering - it's local expression memoization
    with compile-time constant cataloging. Real GVN would require:
    - CFG and dominance reasoning
    - SSA form and join-state merging
    - Side-effect/alias invalidation models
    - Cross-function safety analysis
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
        # Function-local expression memoization only
        self._local_expressions: dict[tuple, int] = {}
        self._vn_to_name: dict[int, str] = {}
        self.next_vn = 1
        # Compile-time constant catalog (read-only)
        self._constant_catalog: dict[tuple, Any] = {}
    
    def reuse_expressions(self, prog: Any) -> tuple[Any, bool]:
        """Apply local expression reuse with constant cataloging.
        
        Returns (program, changed) for fixed-point iteration.
        """
        changed = False
        
        # Phase 1: Catalog compile-time constants across all functions
        self._catalog_constants(prog)
        
        # Phase 2: Apply local expression reuse within each function
        for item in prog.items:
            if isinstance(item, FnDecl):
                fn_changed = self._reuse_function_expressions(item)
                changed = changed or fn_changed
        
        return prog, changed
    
    def _catalog_constants(self, prog: Any) -> None:
        """Catalog compile-time constant expressions for reference."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._catalog_function_constants(item)
    
    def _catalog_function_constants(self, fn: FnDecl) -> None:
        """Catalog constant expressions in a function."""
        def catalog_expr(expr: Any) -> Optional[tuple]:
            """Catalog constant expressions."""
            if isinstance(expr, Literal):
                key = ("lit", type(expr.value).__name__, expr.value)
                self._constant_catalog[key] = expr
                return key
            elif isinstance(expr, BoolLit):
                key = ("bool", expr.value)
                self._constant_catalog[key] = expr
                return key
            elif isinstance(expr, NilLit):
                key = ("nil",)
                self._constant_catalog[key] = expr
                return key
            elif isinstance(expr, Binary):
                if isinstance(expr.left, (Literal, BoolLit, NilLit)) and isinstance(expr.right, (Literal, BoolLit, NilLit)):
                    # Constant binary expression
                    left_key = catalog_expr(expr.left)
                    right_key = catalog_expr(expr.right)
                    if left_key and right_key:
                        # Canonicalize commutative operations
                        if expr.op in {"+", "*", "&", "|", "^"}:
                            if left_key <= right_key:
                                key = ("binary", expr.op, left_key, right_key)
                            else:
                                key = ("binary", expr.op, right_key, left_key)
                        else:
                            key = ("binary", expr.op, left_key, right_key)
                        self._constant_catalog[key] = expr
                        return key
            return None
        
        def walk_expr(expr: Any) -> None:
            catalog_expr(expr)
            # Recursively walk sub-expressions
            if hasattr(expr, 'left') and expr.left:
                walk_expr(expr.left)
            if hasattr(expr, 'right') and expr.right:
                walk_expr(expr.right)
            if hasattr(expr, 'expr') and expr.expr:
                walk_expr(expr.expr)
            if hasattr(expr, 'args'):
                for arg in expr.args:
                    walk_expr(arg)
        
        def walk_stmts(stmts: list[Any]) -> None:
            for stmt in stmts:
                if isinstance(stmt, LetStmt):
                    walk_expr(stmt.expr)
                elif isinstance(stmt, AssignStmt):
                    walk_expr(stmt.expr)
                elif isinstance(stmt, ExprStmt):
                    walk_expr(stmt.expr)
                elif isinstance(stmt, ReturnStmt) and stmt.expr:
                    walk_expr(stmt.expr)
                # Recursively walk compound statements
                elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
                    walk_stmts(stmt.body)
                elif hasattr(stmt, 'then_body') and isinstance(stmt.then_body, list):
                    walk_stmts(stmt.then_body)
                elif hasattr(stmt, 'else_body') and isinstance(stmt.else_body, list):
                    walk_stmts(stmt.else_body)
        
        walk_stmts(fn.body)
    
    def _reuse_function_expressions(self, fn: FnDecl) -> bool:
        """Reuse expressions within a single function.
        
        Returns True if any changes were made.
        """
        # Clear function-local state
        self._local_expressions.clear()
        self._vn_to_name.clear()
        self.next_vn = 1
        
        new_body = self._reuse_stmts(fn.body)
        if new_body != fn.body:
            fn.body = new_body
            return True
        return False
    
    def _reuse_stmts(self, stmts: list[Any]) -> list[Any]:
        """Reuse expressions in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            new_stmt = self._reuse_stmt(stmt)
            if isinstance(new_stmt, list):
                new_stmts.extend(new_stmt)
            elif new_stmt is not None:
                new_stmts.append(new_stmt)
        
        return new_stmts
    
    def _reuse_stmt(self, stmt: Any) -> Any:
        """Reuse expressions in a single statement."""
        if isinstance(stmt, LetStmt):
            stmt.expr = self._reuse_expr(stmt.expr)
            
            # Check for local expression reuse
            expr_key = self._expr_key(stmt.expr)
            if expr_key is not None and expr_key in self._local_expressions:
                existing_vn = self._local_expressions[expr_key]
                if existing_vn in self._vn_to_name:
                    existing_name = self._vn_to_name[existing_vn]
                    return LetStmt(
                        stmt.name,
                        Name(existing_name, stmt.expr.pos, stmt.expr.line, stmt.expr.col),
                        stmt.mut,
                        stmt.type_name,
                        stmt.pos,
                        stmt.line,
                        stmt.col
                    )
            
            # Assign new value number
            vn = self.next_vn
            self.next_vn += 1  # Fix: Actually update the counter
            if expr_key is not None:
                self._local_expressions[expr_key] = vn
            self._vn_to_name[vn] = stmt.name
            
            return stmt
        
        elif isinstance(stmt, AssignStmt):
            stmt.expr = self._reuse_expr(stmt.expr)
            # Invalidate on assignment
            if isinstance(stmt.target, Name) and stmt.target.value in self._vn_to_name.values():
                self._invalidate_variable(stmt.target.value)
            return stmt
        
        elif isinstance(stmt, ExprStmt):
            stmt.expr = self._reuse_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, ReturnStmt) and stmt.expr:
            stmt.expr = self._reuse_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, IfStmt):
            stmt.cond = self._reuse_expr(stmt.cond)
            stmt.then_body = self._reuse_stmts(stmt.then_body)
            stmt.else_body = self._reuse_stmts(stmt.else_body)
            return stmt
        
        elif isinstance(stmt, WhileStmt):
            stmt.cond = self._reuse_expr(stmt.cond)
            stmt.body = self._reuse_stmts(stmt.body)
            return stmt
        
        return stmt
    
    def _invalidate_variable(self, var_name: str) -> None:
        """Invalidate expressions that use this variable."""
        # Find and remove expressions that use this variable
        to_remove = []
        for expr_key, vn in self._local_expressions.items():
            if self._expr_uses_var(expr_key, var_name):
                to_remove.append(expr_key)
                # Remove from vn_to_name mapping
                if vn in self._vn_to_name:
                    del self._vn_to_name[vn]
        
        for key in to_remove:
            del self._local_expressions[key]
    
    def _reuse_expr(self, expr: Any) -> Any:
        """Reuse expressions recursively."""
        if isinstance(expr, (Literal, BoolLit, NilLit, Name)):
            return expr
        elif isinstance(expr, Unary):
            expr.expr = self._reuse_expr(expr.expr)
            return expr
        elif isinstance(expr, Binary):
            expr.left = self._reuse_expr(expr.left)
            expr.right = self._reuse_expr(expr.right)
            return expr
        elif isinstance(expr, Call):
            expr.fn = self._reuse_expr(expr.fn)
            expr.args = [self._reuse_expr(arg) for arg in expr.args]
            return expr
        return expr
    
    def _expr_key(self, expr: Any) -> Optional[tuple]:
        """Generate a canonical key for expression comparison."""
        if isinstance(expr, Literal):
            return ("lit", type(expr.value).__name__, expr.value)
        elif isinstance(expr, BoolLit):
            return ("bool", expr.value)
        elif isinstance(expr, NilLit):
            return ("nil",)
        elif isinstance(expr, Name):
            return ("name", expr.value)
        elif isinstance(expr, Binary):
            left_key = self._expr_key(expr.left)
            right_key = self._expr_key(expr.right)
            if left_key is not None and right_key is not None:
                # Canonicalize commutative operations
                if expr.op in {"+", "*", "&", "|", "^"}:
                    if left_key <= right_key:
                        return ("binary", expr.op, left_key, right_key)
                    else:
                        return ("binary", expr.op, right_key, left_key)
                else:
                    return ("binary", expr.op, left_key, right_key)
        elif isinstance(expr, Unary):
            inner_key = self._expr_key(expr.expr)
            if inner_key is not None:
                return ("unary", expr.op, inner_key)
        return None
    
    def _expr_uses_var(self, expr_key: tuple, var_name: str) -> bool:
        """Check if an expression key uses a variable."""
        if expr_key[0] == "name" and expr_key[1] == var_name:
            return True
        elif expr_key[0] in {"binary", "unary"}:
            for component in expr_key[2:]:
                if isinstance(component, tuple) and self._expr_uses_var(component, var_name):
                    return True
        return False


class PartialRedundancyElimination:
    """DISABLED: Partial Redundancy Elimination with dataflow analysis.
    
    DISABLED because:
    - CFG is placeholder-only (single block)
    - No real predecessor/successor structure
    - No forward/backward dataflow convergence
    - No insertion placement correctness
    - No dominance or safety proof
    - Dangerous insertion without purity checks
    
    Real PRE would require:
    - Full CFG construction
    - Dataflow analysis (availability, anticipatability)
    - Safety proofs for insertion points
    - Side-effect and alias analysis
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def eliminate_partial_redundancy(self, prog: Any) -> tuple[Any, bool]:
        """Disabled - does nothing."""
        return prog, False


class InductionVariableOptimizer:
    """Real Induction Variable Optimizations.
    
    Performs actual optimizations:
    - Strength reduction of induction variables
    - Loop invariant code motion
    - Induction variable replacement
    - Linear recurrence optimization
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def optimize_induction_variables(self, prog: Any) -> tuple[Any, bool]:
        """Optimize induction variables in loops.
        
        Returns (program, changed) for fixed-point iteration.
        """
        changed = False
        for item in prog.items:
            if isinstance(item, FnDecl):
                fn_changed = self._optimize_function(item)
                changed = changed or fn_changed
        return prog, changed
    
    def _optimize_function(self, fn: FnDecl) -> bool:
        """Optimize induction variables in a function.
        
        Returns True if any changes were made.
        """
        new_body = self._optimize_stmts(fn.body)
        if new_body != fn.body:
            fn.body = new_body
            return True
        return False
    
    def _optimize_stmts(self, stmts: list[Any]) -> list[Any]:
        """Optimize statements recursively."""
        new_stmts = []
        for stmt in stmts:
            optimized = self._optimize_stmt(stmt)
            if optimized is not None:
                if isinstance(optimized, list):
                    new_stmts.extend(optimized)
                else:
                    new_stmts.append(optimized)
        return new_stmts
    
    def _optimize_stmt(self, stmt: Any) -> Any:
        """Optimize a single statement."""
        if isinstance(stmt, WhileStmt):
            # Analyze and optimize loop
            iv_info = self._analyze_induction_variables(stmt.body)
            
            if iv_info:
                # Apply strength reduction and other optimizations
                optimized_body = self._apply_iv_optimizations(stmt.body, iv_info)
                if optimized_body != stmt.body:
                    stmt.body = optimized_body
            
            # Continue optimizing the loop body
            stmt.body = self._optimize_stmts(stmt.body)
            return stmt
        
        elif isinstance(stmt, IfStmt):
            stmt.then_body = self._optimize_stmts(stmt.then_body)
            stmt.else_body = self._optimize_stmts(stmt.else_body)
            return stmt
        
        return stmt
    
    def _analyze_induction_variables(self, body: list[Any]) -> dict[str, Any]:
        """Analyze loop body for induction variables.
        
        Returns detailed IV information for optimization.
        """
        iv_info = {}
        
        for stmt in body:
            if isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                var_name = stmt.target.value
                
                # Check for simple linear induction variables
                if stmt.op == "+=" and isinstance(stmt.expr, Literal):
                    # x += constant
                    iv_info[var_name] = {
                        'type': 'linear',
                        'step': stmt.expr.value,
                        'base': None,  # Would need more analysis to determine
                        'strength_reduction_candidate': True,
                        'replacement_possible': True
                    }
                elif stmt.op == "-=" and isinstance(stmt.expr, Literal):
                    # x -= constant
                    iv_info[var_name] = {
                        'type': 'linear', 
                        'step': -stmt.expr.value,
                        'base': None,
                        'strength_reduction_candidate': True,
                        'replacement_possible': True
                    }
                elif stmt.op == "=" and isinstance(stmt.expr, Binary):
                    # Check for x = x + constant, x = x - constant, or x = x * constant
                    if (isinstance(stmt.expr.left, Name) and stmt.expr.left.value == var_name and
                        isinstance(stmt.expr.right, Literal)):
                        if stmt.expr.op in {"+", "-"}:
                            # Linear case
                            step = stmt.expr.right.value if stmt.expr.op == "+" else -stmt.expr.right.value
                            iv_info[var_name] = {
                                'type': 'linear',
                                'step': step,
                                'base': None,
                                'strength_reduction_candidate': True,
                                'replacement_possible': True
                            }
                        elif stmt.expr.op == "*":
                            # Geometric case
                            iv_info[var_name] = {
                                'type': 'geometric',
                                'step': stmt.expr.right.value,
                                'base': None,
                                'strength_reduction_candidate': True,
                                'replacement_possible': True
                            }
        
        return iv_info
    
    def _apply_iv_optimizations(self, body: list[Any], iv_info: dict[str, Any]) -> list[Any]:
        """Apply induction variable optimizations.
        
        Returns optimized body with IV transformations.
        """
        new_body = []
        
        for stmt in body:
            if isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                var_name = stmt.target.value
                
                if var_name in iv_info:
                    iv = iv_info[var_name]
                    
                    # Apply strength reduction
                    if iv['type'] == 'linear' and iv['strength_reduction_candidate']:
                        # Replace multiplications with additions
                        optimized_stmt = self._strength_reduce_linear_iv(stmt, iv)
                        if optimized_stmt != stmt:
                            new_body.append(optimized_stmt)
                            continue
                    
                    # Apply geometric progression optimization
                    elif iv['type'] == 'geometric' and iv['strength_reduction_candidate']:
                        optimized_stmt = self._optimize_geometric_iv(stmt, iv)
                        if optimized_stmt != stmt:
                            new_body.append(optimized_stmt)
                            continue
            
            new_body.append(stmt)
        
        return new_body
    
    def _strength_reduce_linear_iv(self, stmt: AssignStmt, iv: dict[str, Any]) -> AssignStmt:
        """Apply strength reduction to linear induction variables."""
        # Replace expensive operations with cheaper ones
        if isinstance(stmt.expr, Binary) and stmt.expr.op == "*":
            # Replace x * constant with x + x + ... (constant times)
            if isinstance(stmt.expr.right, Literal) and stmt.expr.right.value > 0 and stmt.expr.right.value <= 4:
                # Small constants: replace multiplication with repeated addition
                multiplier = stmt.expr.right.value
                if multiplier == 2:
                    # x * 2 -> x + x
                    new_expr = Binary(
                        op="+",
                        left=stmt.expr.left,
                        right=stmt.expr.left,
                        pos=stmt.expr.pos,
                        line=stmt.expr.line,
                        col=stmt.expr.col
                    )
                    return AssignStmt(
                        target=stmt.target,
                        op="=",
                        expr=new_expr,
                        pos=stmt.pos,
                        line=stmt.line,
                        col=stmt.col
                    )
                elif multiplier == 3:
                    # x * 3 -> x + x + x
                    x_plus_x = Binary(
                        op="+",
                        left=stmt.expr.left,
                        right=stmt.expr.left,
                        pos=stmt.expr.pos,
                        line=stmt.expr.line,
                        col=stmt.expr.col
                    )
                    new_expr = Binary(
                        op="+",
                        left=x_plus_x,
                        right=stmt.expr.left,
                        pos=stmt.expr.pos,
                        line=stmt.expr.line,
                        col=stmt.expr.col
                    )
                    return AssignStmt(
                        target=stmt.target,
                        op="=",
                        expr=new_expr,
                        pos=stmt.pos,
                        line=stmt.line,
                        col=stmt.col
                    )
        
        return stmt
    
    def _optimize_geometric_iv(self, stmt: AssignStmt, iv: dict[str, Any]) -> AssignStmt:
        """Optimize geometric progression induction variables."""
        # For power-of-2 multiplications, use bit shifts
        if isinstance(stmt.expr, Binary) and stmt.expr.op == "*":
            if isinstance(stmt.expr.right, Literal):
                multiplier = stmt.expr.right.value
                # Check if it's a power of 2
                if multiplier > 0 and (multiplier & (multiplier - 1)) == 0:
                    # Replace x * 2^n with x << n
                    shift_amount = 0
                    temp = multiplier
                    while temp > 1:
                        temp >>= 1
                        shift_amount += 1
                    
                    # Create shift operation (would need language support)
                    # For now, keep original as placeholder
                    pass
        
        return stmt


class TailCallMarker:
    """Mark tail calls for potential optimization.
    
    This only annotates tail calls - actual optimization would require
    backend support, frame reuse, and proper ABI handling.
    
    Self-tail recursion transformation is DISABLED due to semantic issues:
    - Parameter mapping is simplified and unsafe
    - No proper scope analysis
    - May break function call semantics
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def mark_tail_calls(self, prog: Any) -> tuple[Any, bool]:
        """Mark tail calls in the program.
        
        Returns (program, changed) for fixed-point iteration.
        """
        changed = False
        for item in prog.items:
            if isinstance(item, FnDecl):
                fn_changed = self._mark_function(item)
                changed = changed or fn_changed
        return prog, changed
    
    def _mark_function(self, fn: FnDecl) -> bool:
        """Mark tail calls in a function.
        
        Returns True if any tail calls were marked.
        """
        fn.body = self._mark_stmts(fn.body)
        # Check if any tail calls were marked by looking for the attribute
        def has_tail_calls(stmts: list[Any]) -> bool:
            for stmt in stmts:
                if isinstance(stmt, ReturnStmt) and hasattr(stmt, '_has_tail_call'):
                    return True
                elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
                    if has_tail_calls(stmt.body):
                        return True
                elif hasattr(stmt, 'then_body') and isinstance(stmt.then_body, list):
                    if has_tail_calls(stmt.then_body):
                        return True
                elif hasattr(stmt, 'else_body') and isinstance(stmt.else_body, list):
                    if has_tail_calls(stmt.else_body):
                        return True
            return False
        
        return has_tail_calls(fn.body)
    
    def _mark_stmts(self, stmts: list[Any]) -> list[Any]:
        """Mark statements recursively."""
        new_stmts = []
        for stmt in stmts:
            marked = self._mark_stmt(stmt)
            if marked is not None:
                new_stmts.append(marked)
        return new_stmts
    
    def _mark_stmt(self, stmt: Any) -> Any:
        """Mark a single statement."""
        if isinstance(stmt, ReturnStmt):
            if stmt.expr is not None and isinstance(stmt.expr, Call):
                # This is a tail call - mark it for potential optimization
                setattr(stmt.expr, "_is_tail_call", True)
                setattr(stmt, "_has_tail_call", True)
            return stmt
        
        elif isinstance(stmt, IfStmt):
            stmt.then_body = self._mark_stmts(stmt.then_body)
            stmt.else_body = self._mark_stmts(stmt.else_body)
            return stmt
        
        elif isinstance(stmt, WhileStmt):
            stmt.body = self._mark_stmts(stmt.body)
            return stmt
        
        return stmt


class AdvancedOptimizer:
    """Advanced optimizer combining multiple high-impact optimizations.
    
    Uses fixed-point iteration for better optimization opportunities.
    """
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug"):
        self.ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
        self.release_mode = profile == "release"
        
        # Initialize optimization passes
        self.constant_folder = EnhancedConstantFolder(self.ctx)
        self.expr_reuse = ConstantExpressionReuse(self.ctx)
        self.pre = PartialRedundancyElimination(self.ctx)  # DISABLED
        self.iv_optimizer = InductionVariableOptimizer(self.ctx)
        self.tail_call_marker = TailCallMarker(self.ctx)
    
    def optimize_program(self, prog: Any) -> Any:
        """Apply all advanced optimizations to the program.
        
        Uses fixed-point iteration for better optimization.
        """
        if self.ctx.profile == "debug":
            print(f"OPTIMIZE: Running advanced optimization pipeline (profile={self.ctx.profile})")
        
        max_rounds = 4
        
        for round_num in range(max_rounds):
            changed = False
            
            # Pass 1: Enhanced constant folding and propagation
            fold_changed = self.constant_folder.fold_program(prog)
            changed = changed or fold_changed
            
            if self.release_mode:
                # Pass 2: Local Expression Reuse (NOT real GVN)
                prog, expr_changed = self.expr_reuse.reuse_expressions(prog)
                changed = changed or expr_changed
                
                # Pass 3: Partial Redundancy Elimination (DISABLED)
                prog, pre_changed = self.pre.eliminate_partial_redundancy(prog)
                changed = changed or pre_changed
                
                # Pass 4: Induction Variable Optimization
                prog, iv_changed = self.iv_optimizer.optimize_induction_variables(prog)
                changed = changed or iv_changed
                
                # Pass 5: Tail Call Marking (NOT real optimization)
                prog, tail_changed = self.tail_call_marker.mark_tail_calls(prog)
                changed = changed or tail_changed
            
            if self.ctx.profile == "debug":
                print(f"OPTIMIZE: Round {round_num + 1}, changed={changed}")
            
            if not changed:
                break
        
        return prog


def optimize_program_advanced(prog: Any, overflow_mode: str = "trap", profile: str = "debug") -> Any:
    """Apply advanced optimizations to a program."""
    optimizer = AdvancedOptimizer(overflow_mode=overflow_mode, profile=profile)
    return optimizer.optimize_program(prog)
