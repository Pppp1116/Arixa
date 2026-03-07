"""Interprocedural optimization: cross-function analysis and optimization."""

from __future__ import annotations

from typing import Any, Set, Dict, List, Tuple, Optional
from dataclasses import dataclass

from astra.ast import *
from astra.optimizer_enhanced import OptimizationContext


@dataclass
class FunctionInfo:
    """Information about a function for interprocedural analysis."""
    name: str
    params: List[str]
    returns: str
    body: List[Any]
    calls: Set[str] = None
    called_by: Set[str] = None
    is_pure: bool = False
    is_constant: bool = False
    side_effects: Set[str] = None
    
    def __post_init__(self):
        if self.calls is None:
            self.calls = set()
        if self.called_by is None:
            self.called_by = set()
        if self.side_effects is None:
            self.side_effects = set()


class CallGraphBuilder:
    """Build call graph for interprocedural analysis."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
        self.functions: Dict[str, FunctionInfo] = {}
    
    def build_call_graph(self, prog: Any) -> Dict[str, FunctionInfo]:
        """Build call graph for the program."""
        # Collect all functions
        for item in prog.items:
            if isinstance(item, (FnDecl, ExternFnDecl)):
                self._collect_function(item)
        
        # Analyze call relationships
        for func_info in self.functions.values():
            self._analyze_function_calls(func_info)
        
        return self.functions
    
    def _collect_function(self, fn: Any) -> None:
        """Collect function information."""
        if isinstance(fn, FnDecl):
            func_info = FunctionInfo(
                name=fn.name,
                params=[param for param, _ in fn.params],
                returns=fn.ret,
                body=fn.body
            )
            self.functions[fn.name] = func_info
        elif isinstance(fn, ExternFnDecl):
            func_info = FunctionInfo(
                name=fn.name,
                params=[param for param, _ in fn.params],
                returns=fn.ret,
                body=[]
            )
            self.functions[fn.name] = func_info
    
    def _analyze_function_calls(self, func_info: FunctionInfo) -> None:
        """Analyze calls made by a function."""
        for stmt in func_info.body:
            calls = self._find_calls_in_stmt(stmt)
            func_info.calls.update(calls)
            
            # Update called_by relationships
            for called_func in calls:
                if called_func in self.functions:
                    self.functions[called_func].called_by.add(func_info.name)
    
    def _find_calls_in_stmt(self, stmt: Any) -> Set[str]:
        """Find function calls in a statement."""
        calls = set()
        
        if isinstance(stmt, ExprStmt):
            calls.update(self._find_calls_in_expr(stmt.expr))
        elif isinstance(stmt, LetStmt):
            calls.update(self._find_calls_in_expr(stmt.expr))
        elif isinstance(stmt, AssignStmt):
            calls.update(self._find_calls_in_expr(stmt.expr))
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                calls.update(self._find_calls_in_expr(stmt.expr))
        elif isinstance(stmt, IfStmt):
            calls.update(self._find_calls_in_expr(stmt.cond))
            for body_stmt in stmt.then_body:
                calls.update(self._find_calls_in_stmt(body_stmt))
            for body_stmt in stmt.else_body:
                calls.update(self._find_calls_in_stmt(body_stmt))
        elif isinstance(stmt, WhileStmt):
            calls.update(self._find_calls_in_expr(stmt.cond))
            for body_stmt in stmt.body:
                calls.update(self._find_calls_in_stmt(body_stmt))
        
        return calls
    
    def _find_calls_in_expr(self, expr: Any) -> Set[str]:
        """Find function calls in an expression."""
        calls = set()
        
        if isinstance(expr, Call):
            # Get the function name
            if isinstance(expr.fn, Name):
                calls.add(expr.fn.value)
            else:
                calls.update(self._find_calls_in_expr(expr.fn))
            
            # Check arguments
            for arg in expr.args:
                calls.update(self._find_calls_in_expr(arg))
        
        elif isinstance(expr, (Unary, Binary)):
            if hasattr(expr, 'expr'):
                calls.update(self._find_calls_in_expr(expr.expr))
            if hasattr(expr, 'left'):
                calls.update(self._find_calls_in_expr(expr.left))
            if hasattr(expr, 'right'):
                calls.update(self._find_calls_in_expr(expr.right))
        
        elif isinstance(expr, IndexExpr):
            calls.update(self._find_calls_in_expr(expr.obj))
            calls.update(self._find_calls_in_expr(expr.index))
        
        return calls


class FunctionAnalyzer:
    """Analyze functions for properties like purity and constness."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def analyze_functions(self, functions: Dict[str, FunctionInfo]) -> None:
        """Analyze all functions for optimization properties."""
        # Analyze purity and side effects
        for func_info in functions.values():
            self._analyze_function_purity(func_info)
            self._analyze_function_constness(func_info)
            self._analyze_side_effects(func_info)
    
    def _analyze_function_purity(self, func_info: FunctionInfo) -> None:
        """Analyze if a function is pure."""
        # A function is pure if it has no side effects and only depends on parameters
        func_info.is_pure = self._is_pure_function(func_info)
    
    def _is_pure_function(self, func_info: FunctionInfo) -> bool:
        """Check if a function is pure."""
        # Check for side effects
        has_side_effects = self._has_side_effects(func_info.body)
        if has_side_effects:
            return False
        
        # Check if it only uses parameters and constants
        external_deps = self._find_external_dependencies(func_info.body)
        return not external_deps
    
    def _analyze_function_constness(self, func_info: FunctionInfo) -> None:
        """Analyze if a function returns a constant value."""
        # A function is constant if it always returns the same value
        func_info.is_constant = self._is_constant_function(func_info)
    
    def _is_constant_function(self, func_info: FunctionInfo) -> bool:
        """Check if a function returns a constant value."""
        # Simple check: if function has no parameters and returns a literal
        if not func_info.params:
            return self._returns_constant(func_info.body)
        return False
    
    def _returns_constant(self, stmts: List[Any]) -> bool:
        """Check if function body returns a constant."""
        for stmt in stmts:
            if isinstance(stmt, ReturnStmt) and stmt.expr is not None:
                return isinstance(stmt.expr, (Literal, BoolLit))
        return False
    
    def _analyze_side_effects(self, func_info: FunctionInfo) -> None:
        """Analyze side effects of a function."""
        func_info.side_effects = self._find_side_effects(func_info.body)
    
    def _has_side_effects(self, stmts: List[Any]) -> bool:
        """Check if statements have side effects."""
        return bool(self._find_side_effects(stmts))
    
    def _find_side_effects(self, stmts: List[Any]) -> Set[str]:
        """Find side effects in statements."""
        effects = set()
        
        for stmt in stmts:
            if isinstance(stmt, ExprStmt):
                if isinstance(stmt.expr, Call):
                    effects.add("call")
            elif isinstance(stmt, AssignStmt):
                effects.add("assignment")
            elif isinstance(stmt, IfStmt):
                effects.update(self._find_side_effects(stmt.then_body))
                effects.update(self._find_side_effects(stmt.else_body))
            elif isinstance(stmt, WhileStmt):
                effects.update(self._find_side_effects(stmt.body))
        
        return effects
    
    def _find_external_dependencies(self, stmts: List[Any]) -> Set[str]:
        """Find external dependencies in statements."""
        deps = set()
        
        for stmt in stmts:
            if isinstance(stmt, LetStmt):
                if isinstance(stmt.expr, Name):
                    deps.add(stmt.expr.value)
            elif isinstance(stmt, ExprStmt):
                deps.update(self._find_external_deps_in_expr(stmt.expr))
            elif isinstance(stmt, AssignStmt):
                deps.update(self._find_external_deps_in_expr(stmt.expr))
            elif isinstance(stmt, ReturnStmt):
                if stmt.expr is not None:
                    deps.update(self._find_external_deps_in_expr(stmt.expr))
        
        return deps
    
    def _find_external_deps_in_expr(self, expr: Any) -> Set[str]:
        """Find external dependencies in expression."""
        deps = set()
        
        if isinstance(expr, Name):
            deps.add(expr.value)
        elif isinstance(expr, (Unary, Binary)):
            if hasattr(expr, 'expr'):
                deps.update(self._find_external_deps_in_expr(expr.expr))
            if hasattr(expr, 'left'):
                deps.update(self._find_external_deps_in_expr(expr.left))
            if hasattr(expr, 'right'):
                deps.update(self._find_external_deps_in_expr(expr.right))
        elif isinstance(expr, Call):
            for arg in expr.args:
                deps.update(self._find_external_deps_in_expr(arg))
        
        return deps


class FunctionInliner:
    """Function inlining optimization."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
        self.max_inline_size = 10  # Maximum function size for inlining
    
    def inline_functions(self, prog: Any, functions: Dict[str, FunctionInfo]) -> Any:
        """Inline functions in the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._inline_function(item, functions)
        return prog
    
    def _inline_function(self, fn: FnDecl, functions: Dict[str, FunctionInfo]) -> None:
        """Inline functions in a single function."""
        fn.body = self._inline_stmts(fn.body, functions)
    
    def _inline_stmts(self, stmts: List[Any], functions: Dict[str, FunctionInfo]) -> List[Any]:
        """Inline functions in statement list."""
        new_stmts = []
        for stmt in stmts:
            inlined = self._inline_stmt(stmt, functions)
            if inlined is not None:
                if isinstance(inlined, list):
                    new_stmts.extend(inlined)
                else:
                    new_stmts.append(inlined)
        return new_stmts
    
    def _inline_stmt(self, stmt: Any, functions: Dict[str, FunctionInfo]) -> Any:
        """Inline functions in a single statement."""
        if isinstance(stmt, ExprStmt):
            if isinstance(stmt.expr, Call):
                inlined_call = self._inline_call(stmt.expr, functions)
                if inlined_call is not None:
                    return inlined_call
            return stmt
        
        elif isinstance(stmt, LetStmt):
            if isinstance(stmt.expr, Call):
                inlined_call = self._inline_call(stmt.expr, functions)
                if inlined_call is not None:
                    # Create let statement with inlined result
                    stmt.expr = inlined_call[-1] if inlined_call else stmt.expr
                    return stmt
            else:
                stmt.expr = self._inline_expr(stmt.expr, functions)
            return stmt
        
        elif isinstance(stmt, AssignStmt):
            if isinstance(stmt.expr, Call):
                inlined_call = self._inline_call(stmt.expr, functions)
                if inlined_call is not None:
                    stmt.expr = inlined_call[-1] if inlined_call else stmt.expr
                    return stmt
            else:
                stmt.expr = self._inline_expr(stmt.expr, functions)
            return stmt
        
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr is not None and isinstance(stmt.expr, Call):
                inlined_call = self._inline_call(stmt.expr, functions)
                if inlined_call is not None:
                    stmt.expr = inlined_call[-1] if inlined_call else stmt.expr
                    return stmt
            elif stmt.expr is not None:
                stmt.expr = self._inline_expr(stmt.expr, functions)
            return stmt
        
        elif isinstance(stmt, IfStmt):
            stmt.cond = self._inline_expr(stmt.cond, functions)
            stmt.then_body = self._inline_stmts(stmt.then_body, functions)
            stmt.else_body = self._inline_stmts(stmt.else_body, functions)
            return stmt
        
        elif isinstance(stmt, WhileStmt):
            stmt.cond = self._inline_expr(stmt.cond, functions)
            stmt.body = self._inline_stmts(stmt.body, functions)
            return stmt
        
        return stmt
    
    def _inline_expr(self, expr: Any, functions: Dict[str, FunctionInfo]) -> Any:
        """Inline functions in expression."""
        if isinstance(expr, Call):
            inlined_call = self._inline_call(expr, functions)
            return inlined_call[-1] if inlined_call else expr
        elif isinstance(expr, (Unary, Binary)):
            if hasattr(expr, 'expr'):
                expr.expr = self._inline_expr(expr.expr, functions)
            if hasattr(expr, 'left'):
                expr.left = self._inline_expr(expr.left, functions)
            if hasattr(expr, 'right'):
                expr.right = self._inline_expr(expr.right, functions)
        elif isinstance(expr, IndexExpr):
            expr.obj = self._inline_expr(expr.obj, functions)
            expr.index = self._inline_expr(expr.index, functions)
        
        return expr
    
    def _inline_call(self, call_expr: Call, functions: Dict[str, FunctionInfo]) -> Optional[List[Any]]:
        """Inline a function call."""
        if not isinstance(call_expr.fn, Name):
            return None
        
        func_name = call_expr.fn.value
        if func_name not in functions:
            return None
        
        func_info = functions[func_name]
        
        # Check if function is inlineable
        if not self._is_inlineable(func_info):
            return None
        
        # Create inlined body
        return self._create_inlined_body(func_info, call_expr.args)
    
    def _is_inlineable(self, func_info: FunctionInfo) -> bool:
        """Check if a function is suitable for inlining."""
        # Don't inline recursive functions
        if func_info.name in func_info.calls:
            return False
        
        # Don't inline functions that are too large
        if len(func_info.body) > self.max_inline_size:
            return False
        
        # Prefer inlining pure functions
        if func_info.is_pure:
            return True
        
        # Don't inline functions with side effects (simplified)
        if func_info.side_effects:
            return False
        
        return True
    
    def _create_inlined_body(self, func_info: FunctionInfo, args: List[Any]) -> List[Any]:
        """Create inlined function body."""
        # This is a simplified inlining implementation
        # Full implementation would:
        # 1. Map parameters to arguments
        # 2. Rename variables to avoid conflicts
        # 3. Handle return statements
        # 4. Handle control flow
        
        inlined_body = []
        
        # Create parameter assignments
        for i, (param, _) in enumerate(func_info.params):
            if i < len(args):
                param_assign = LetStmt(
                    name=param,
                    expr=args[i],
                    mut=False,
                    type_name=None,
                    pos=0, line=0, col=0
                )
                inlined_body.append(param_assign)
        
        # Clone function body
        for stmt in func_info.body:
            cloned_stmt = self._clone_stmt(stmt)
            inlined_body.append(cloned_stmt)
        
        return inlined_body
    
    def _clone_stmt(self, stmt: Any) -> Any:
        """Clone a statement for inlining."""
        # Simplified cloning - full implementation would deep clone
        return stmt


class ConstantPropagation:
    """Interprocedural constant propagation."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def propagate_constants(self, prog: Any, functions: Dict[str, FunctionInfo]) -> Any:
        """Propagate constants across function boundaries."""
        # Find constant-returning functions
        constant_functions = {
            name: self._get_constant_value(func_info)
            for name, func_info in functions.items()
            if func_info.is_constant
        }
        
        # Replace calls to constant functions with their values
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._replace_constant_calls(item.body, constant_functions)
        
        return prog
    
    def _get_constant_value(self, func_info: FunctionInfo) -> Any:
        """Get the constant value returned by a function."""
        for stmt in func_info.body:
            if isinstance(stmt, ReturnStmt) and stmt.expr is not None:
                if isinstance(stmt.expr, Literal):
                    return stmt.expr.value
                elif isinstance(stmt.expr, BoolLit):
                    return stmt.expr.value
        return None
    
    def _replace_constant_calls(self, stmts: List[Any], constant_functions: Dict[str, Any]) -> None:
        """Replace calls to constant functions with their values."""
        for stmt in stmts:
            self._replace_constant_calls_in_stmt(stmt, constant_functions)
    
    def _replace_constant_calls_in_stmt(self, stmt: Any, constant_functions: Dict[str, Any]) -> None:
        """Replace constant calls in a statement."""
        if isinstance(stmt, ExprStmt):
            stmt.expr = self._replace_constant_calls_in_expr(stmt.expr, constant_functions)
        elif isinstance(stmt, LetStmt):
            stmt.expr = self._replace_constant_calls_in_expr(stmt.expr, constant_functions)
        elif isinstance(stmt, AssignStmt):
            stmt.expr = self._replace_constant_calls_in_expr(stmt.expr, constant_functions)
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                stmt.expr = self._replace_constant_calls_in_expr(stmt.expr, constant_functions)
        elif isinstance(stmt, IfStmt):
            stmt.cond = self._replace_constant_calls_in_expr(stmt.cond, constant_functions)
            self._replace_constant_calls(stmt.then_body, constant_functions)
            self._replace_constant_calls(stmt.else_body, constant_functions)
        elif isinstance(stmt, WhileStmt):
            stmt.cond = self._replace_constant_calls_in_expr(stmt.cond, constant_functions)
            self._replace_constant_calls(stmt.body, constant_functions)
    
    def _replace_constant_calls_in_expr(self, expr: Any, constant_functions: Dict[str, Any]) -> Any:
        """Replace constant calls in an expression."""
        if isinstance(expr, Call) and isinstance(expr.fn, Name):
            func_name = expr.fn.value
            if func_name in constant_functions:
                # Replace with literal
                value = constant_functions[func_name]
                if isinstance(value, bool):
                    return BoolLit(value, expr.pos, expr.line, expr.col)
                else:
                    return Literal(value, expr.pos, expr.line, expr.col)
        
        # Recursively process sub-expressions
        elif isinstance(expr, (Unary, Binary)):
            if hasattr(expr, 'expr'):
                expr.expr = self._replace_constant_calls_in_expr(expr.expr, constant_functions)
            if hasattr(expr, 'left'):
                expr.left = self._replace_constant_calls_in_expr(expr.left, constant_functions)
            if hasattr(expr, 'right'):
                expr.right = self._replace_constant_calls_in_expr(expr.right, constant_functions)
        elif isinstance(expr, Call):
            expr.fn = self._replace_constant_calls_in_expr(expr.fn, constant_functions)
            expr.args = [self._replace_constant_calls_in_expr(arg, constant_functions) for arg in expr.args]
        
        return expr


class InterproceduralOptimizer:
    """Combined interprocedural optimizations."""
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug"):
        self.ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
        self.release_mode = profile == "release"
        
        # Initialize interprocedural optimization passes
        self.call_graph_builder = CallGraphBuilder(self.ctx)
        self.function_analyzer = FunctionAnalyzer(self.ctx)
        self.inliner = FunctionInliner(self.ctx)
        self.constant_propagator = ConstantPropagation(self.ctx)
    
    def optimize_interprocedural(self, prog: Any) -> Any:
        """Apply all interprocedural optimizations to the program."""
        if self.release_mode:
            # Build call graph
            functions = self.call_graph_builder.build_call_graph(prog)
            
            # Analyze functions
            self.function_analyzer.analyze_functions(functions)
            
            # Apply interprocedural optimizations
            self.constant_propagator.propagate_constants(prog, functions)
            self.inliner.inline_functions(prog, functions)
        
        return prog


def optimize_interprocedural_program(prog: Any, overflow_mode: str = "trap", profile: str = "debug") -> Any:
    """Apply interprocedural optimizations to a program."""
    optimizer = InterproceduralOptimizer(overflow_mode=overflow_mode, profile=profile)
    return optimizer.optimize_interprocedural(prog)
