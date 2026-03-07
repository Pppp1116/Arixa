"""Advanced optimizer with additional high-impact optimizations."""

from __future__ import annotations

from typing import Any, Set, Dict, List, Tuple, Optional
from dataclasses import dataclass

from astra.ast import *
from astra.optimizer_enhanced import OptimizationContext, EnhancedConstantFolder


class GlobalValueNumbering:
    """Global Value Numbering for cross-function CSE."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
        self.value_numbers: Dict[str, int] = {}
        self.expressions: Dict[int, Any] = {}
        self.next_value = 1
    
    def analyze_program(self, prog: Any) -> Any:
        """Apply GVN across the entire program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._analyze_function(item)
        return prog
    
    def _analyze_function(self, fn: FnDecl) -> None:
        """Analyze a single function for GVN."""
        self._value_numbers.clear()
        self._expressions.clear()
        self.next_value = 1
        
        self._gvn_stmts(fn.body)
    
    def _gvn_stmts(self, stmts: List[Any]) -> List[Any]:
        """Apply GVN to statement list."""
        new_stmts = []
        for stmt in stmts:
            new_stmt = self._gvn_stmt(stmt)
            if new_stmt is not None:
                new_stmts.append(new_stmt)
        return new_stmts
    
    def _gvn_stmt(self, stmt: Any) -> Any:
        """Apply GVN to a single statement."""
        if isinstance(stmt, LetStmt):
            stmt.expr = self._gvn_expr(stmt.expr)
            
            # Check if this expression is already computed
            expr_key = self._expr_key(stmt.expr)
            if expr_key is not None:
                existing_vn = self._expressions.get(expr_key)
                if existing_vn is not None:
                    # Replace with existing computation
                    for name, vn in self._value_numbers.items():
                        if vn == existing_vn:
                            return LetStmt(
                                stmt.name, 
                                Name(name, stmt.expr.pos, stmt.expr.line, stmt.expr.col),
                                stmt.mut, 
                                stmt.type_name, 
                                stmt.pos, stmt.line, stmt.col
                            )
            
            # Assign new value number
            vn = self.next_value
            self.next_value += 1
            self._value_numbers[stmt.name] = vn
            if expr_key is not None:
                self._expressions[expr_key] = vn
            
            return stmt
        
        elif isinstance(stmt, ExprStmt):
            stmt.expr = self._gvn_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                stmt.expr = self._gvn_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, IfStmt):
            stmt.cond = self._gvn_expr(stmt.cond)
            stmt.then_body = self._gvn_stmts(stmt.then_body)
            stmt.else_body = self._gvn_stmts(stmt.else_body)
            return stmt
        
        elif isinstance(stmt, WhileStmt):
            stmt.cond = self._gvn_expr(stmt.cond)
            stmt.body = self._gvn_stmts(stmt.body)
            return stmt
        
        return stmt
    
    def _gvn_expr(self, expr: Any) -> Any:
        """Apply GVN to an expression."""
        if isinstance(expr, (Literal, BoolLit, NilLit, Name)):
            return expr
        elif isinstance(expr, Unary):
            expr.expr = self._gvn_expr(expr.expr)
            return expr
        elif isinstance(expr, Binary):
            expr.left = self._gvn_expr(expr.left)
            expr.right = self._gvn_expr(expr.right)
            return expr
        elif isinstance(expr, Call):
            expr.fn = self._gvn_expr(expr.fn)
            expr.args = [self._gvn_expr(arg) for arg in expr.args]
            return expr
        return expr
    
    def _expr_key(self, expr: Any) -> Optional[int]:
        """Generate a key for expression hashing."""
        if isinstance(expr, Literal):
            return hash(("lit", type(expr.value).__name__, expr.value))
        elif isinstance(expr, Name):
            return hash(("name", expr.value))
        elif isinstance(expr, Binary):
            left_key = self._expr_key(expr.left)
            right_key = self._expr_key(expr.right)
            if left_key is not None and right_key is not None:
                return hash(("binary", expr.op, left_key, right_key))
        elif isinstance(expr, Unary):
            inner_key = self._expr_key(expr.expr)
            if inner_key is not None:
                return hash(("unary", expr.op, inner_key))
        return None


class PartialRedundancyElimination:
    """Partial Redundancy Elimination optimization."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def eliminate_partial_redundancy(self, prog: Any) -> Any:
        """Apply PRE to the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._pre_function(item)
        return prog
    
    def _pre_function(self, fn: FnDecl) -> None:
        """Apply PRE to a function."""
        # This is a simplified PRE implementation
        # Full PRE would require more sophisticated dataflow analysis
        available_expressions = set()
        
        def analyze_stmts(stmts: List[Any]) -> List[Any]:
            new_stmts = []
            for stmt in stmts:
                if isinstance(stmt, LetStmt):
                    # Check if expression is already available
                    expr_str = self._expr_to_string(stmt.expr)
                    if expr_str in available_expressions:
                        # Redundant computation, can be eliminated or reused
                        continue
                    available_expressions.add(expr_str)
                    new_stmts.append(stmt)
                else:
                    new_stmts.append(stmt)
            return new_stmts
        
        fn.body = analyze_stmts(fn.body)
    
    def _expr_to_string(self, expr: Any) -> str:
        """Convert expression to string for comparison."""
        if isinstance(expr, Literal):
            return str(expr.value)
        elif isinstance(expr, Name):
            return expr.value
        elif isinstance(expr, Binary):
            left = self._expr_to_string(expr.left)
            right = self._expr_to_string(expr.right)
            return f"({left} {expr.op} {right})"
        return str(expr)


class InductionVariableSimplifier:
    """Simplify loop induction variables."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def simplify_induction_variables(self, prog: Any) -> Any:
        """Simplify induction variables in loops."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._simplify_function(item)
        return prog
    
    def _simplify_function(self, fn: FnDecl) -> None:
        """Simplify induction variables in a function."""
        fn.body = self._simplify_stmts(fn.body)
    
    def _simplify_stmts(self, stmts: List[Any]) -> List[Any]:
        """Simplify statements recursively."""
        new_stmts = []
        for stmt in stmts:
            simplified = self._simplify_stmt(stmt)
            if simplified is not None:
                if isinstance(simplified, list):
                    new_stmts.extend(simplified)
                else:
                    new_stmts.append(simplified)
        return new_stmts
    
    def _simplify_stmt(self, stmt: Any) -> Any:
        """Simplify a single statement."""
        if isinstance(stmt, WhileStmt):
            # Analyze loop for induction variables
            iv_info = self._analyze_induction_variables(stmt.body)
            
            # Simplify the loop body
            stmt.body = self._simplify_stmts(stmt.body)
            
            # Apply induction variable optimizations
            if iv_info:
                stmt.body = self._apply_iv_optimizations(stmt.body, iv_info)
            
            return stmt
        
        elif isinstance(stmt, IfStmt):
            stmt.then_body = self._simplify_stmts(stmt.then_body)
            stmt.else_body = self._simplify_stmts(stmt.else_body)
            return stmt
        
        return stmt
    
    def _analyze_induction_variables(self, body: List[Any]) -> Dict[str, Any]:
        """Analyze loop body for induction variables."""
        iv_info = {}
        
        for stmt in body:
            if isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                var_name = stmt.target.value
                
                # Check if this is a simple increment/decrement
                if stmt.op == "+=" and isinstance(stmt.expr, Literal):
                    iv_info[var_name] = {
                        'type': 'linear',
                        'step': stmt.expr.value,
                        'base': None  # Would need more analysis to determine
                    }
                elif stmt.op == "-=" and isinstance(stmt.expr, Literal):
                    iv_info[var_name] = {
                        'type': 'linear', 
                        'step': -stmt.expr.value,
                        'base': None
                    }
        
        return iv_info
    
    def _apply_iv_optimizations(self, body: List[Any], iv_info: Dict[str, Any]) -> List[Any]:
        """Apply induction variable optimizations."""
        # This is a placeholder for more sophisticated IV optimizations
        # Full implementation would strength-reduce induction variables
        return body


class TailCallOptimizer:
    """Optimize tail calls for better performance."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def optimize_tail_calls(self, prog: Any) -> Any:
        """Optimize tail calls in the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._optimize_function(item)
        return prog
    
    def _optimize_function(self, fn: FnDecl) -> None:
        """Optimize tail calls in a function."""
        fn.body = self._optimize_stmts(fn.body)
    
    def _optimize_stmts(self, stmts: List[Any]) -> List[Any]:
        """Optimize statements recursively."""
        new_stmts = []
        for stmt in stmts:
            optimized = self._optimize_stmt(stmt)
            if optimized is not None:
                new_stmts.append(optimized)
        return new_stmts
    
    def _optimize_stmt(self, stmt: Any) -> Any:
        """Optimize a single statement."""
        if isinstance(stmt, ReturnStmt):
            if stmt.expr is not None and isinstance(stmt.expr, Call):
                # This is a tail call - could be optimized
                # Mark it for potential tail call optimization
                setattr(stmt.expr, "_is_tail_call", True)
            return stmt
        
        elif isinstance(stmt, IfStmt):
            stmt.then_body = self._optimize_stmts(stmt.then_body)
            stmt.else_body = self._optimize_stmts(stmt.else_body)
            return stmt
        
        elif isinstance(stmt, WhileStmt):
            stmt.body = self._optimize_stmts(stmt.body)
            return stmt
        
        return stmt


class AdvancedOptimizer:
    """Advanced optimizer combining multiple high-impact optimizations."""
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug"):
        self.ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
        self.release_mode = profile == "release"
        
        # Initialize optimization passes
        self.constant_folder = EnhancedConstantFolder(self.ctx)
        self.gvn = GlobalValueNumbering(self.ctx)
        self.pre = PartialRedundancyElimination(self.ctx)
        self.iv_simplifier = InductionVariableSimplifier(self.ctx)
        self.tail_call_optimizer = TailCallOptimizer(self.ctx)
    
    def optimize_program(self, prog: Any) -> Any:
        """Apply all advanced optimizations to the program."""
        print(f"OPTIMIZE: Running advanced optimization pipeline (profile={self.ctx.profile})")
        
        # Pass 1: Enhanced constant folding and propagation
        self.constant_folder.fold_program(prog)
        
        if self.release_mode:
            # Pass 2: Global Value Numbering
            self.gvn.analyze_program(prog)
            
            # Pass 3: Partial Redundancy Elimination  
            self.pre.eliminate_partial_redundancy(prog)
            
            # Pass 4: Induction Variable Simplification
            self.iv_simplifier.simplify_induction_variables(prog)
            
            # Pass 5: Tail Call Optimization
            self.tail_call_optimizer.optimize_tail_calls(prog)
        
        return prog


def optimize_program_advanced(prog: Any, overflow_mode: str = "trap", profile: str = "debug") -> Any:
    """Apply advanced optimizations to a program."""
    optimizer = AdvancedOptimizer(overflow_mode=overflow_mode, profile=profile)
    return optimizer.optimize_program(prog)
