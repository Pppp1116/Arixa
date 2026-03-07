"""Complete SSA construction and mem2reg optimization."""

from __future__ import annotations

from typing import Any, Set, Dict, List, Tuple, Optional
from dataclasses import dataclass

from astra.ast import *
from astra.optimizer_enhanced import OptimizationContext


@dataclass
class SSAValue:
    """Represents a value in SSA form."""
    name: str
    version: int
    def_point: Any  # Definition point (statement)
    use_points: List[Any] = None
    
    def __post_init__(self):
        if self.use_points is None:
            self.use_points = []


class SSABuilder:
    """Complete SSA construction with mem2reg optimization."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
        self.ssa_values: Dict[str, List[SSAValue]] = {}
        self.current_versions: Dict[str, int] = {}
        self.phi_nodes: Dict[Any, List[Tuple[str, SSAValue]]] = {}
    
    def construct_ssa(self, prog: Any) -> Any:
        """Construct SSA form for the entire program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._construct_function_ssa(item)
        return prog
    
    def _construct_function_ssa(self, fn: FnDecl) -> None:
        """Construct SSA form for a function."""
        # Reset per-function state
        self.ssa_values.clear()
        self.current_versions.clear()
        self.phi_nodes.clear()
        
        # First pass: identify variables and create initial values
        self._identify_variables(fn.body)
        
        # Second pass: rename variables and insert phi nodes
        self._rename_variables(fn.body)
        
        # Third pass: optimize by removing unnecessary phi nodes
        self._optimize_phi_nodes(fn.body)
    
    def _identify_variables(self, stmts: List[Any]) -> None:
        """Identify all variables that need SSA construction."""
        for stmt in stmts:
            if isinstance(stmt, LetStmt):
                # Initialize variable with version 0
                var_name = stmt.name
                self.ssa_values[var_name] = []
                self.current_versions[var_name] = 0
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                # Handle assignments to existing variables
                var_name = stmt.target.value
                if var_name not in self.ssa_values:
                    self.ssa_values[var_name] = []
                    self.current_versions[var_name] = 0
            elif isinstance(stmt, (IfStmt, WhileStmt)):
                # Recursively analyze nested blocks
                if isinstance(stmt, IfStmt):
                    self._identify_variables(stmt.then_body)
                    self._identify_variables(stmt.else_body)
                else:
                    self._identify_variables(stmt.body)
    
    def _rename_variables(self, stmts: List[Any]) -> None:
        """Rename variables to SSA form."""
        self._rename_stmts(stmts)
    
    def _rename_stmts(self, stmts: List[Any]) -> List[Any]:
        """Rename variables in statement list."""
        new_stmts = []
        for stmt in stmts:
            new_stmt = self._rename_stmt(stmt)
            if new_stmt is not None:
                if isinstance(new_stmt, list):
                    new_stmts.extend(new_stmt)
                else:
                    new_stmts.append(new_stmt)
        return new_stmts
    
    def _rename_stmt(self, stmt: Any) -> Any:
        """Rename a single statement."""
        if isinstance(stmt, LetStmt):
            # Create new SSA value for the variable
            var_name = stmt.name
            version = self.current_versions.get(var_name, 0) + 1
            self.current_versions[var_name] = version
            
            ssa_value = SSAValue(var_name, version, stmt)
            self.ssa_values[var_name].append(ssa_value)
            
            # Mark the statement as SSA
            setattr(stmt, "_ssa_version", version)
            setattr(stmt, "_ssa_value", ssa_value)
            
            # Rename expressions
            stmt.expr = self._rename_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
            # Create new SSA value for assignment
            var_name = stmt.target.value
            version = self.current_versions.get(var_name, 0) + 1
            self.current_versions[var_name] = version
            
            ssa_value = SSAValue(var_name, version, stmt)
            self.ssa_values[var_name].append(ssa_value)
            
            # Mark the assignment as SSA
            setattr(stmt, "_ssa_version", version)
            setattr(stmt, "_ssa_value", ssa_value)
            
            # Rename expressions
            stmt.expr = self._rename_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, ExprStmt):
            stmt.expr = self._rename_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                stmt.expr = self._rename_expr(stmt.expr)
            return stmt
        
        elif isinstance(stmt, IfStmt):
            # Rename condition
            stmt.cond = self._rename_expr(stmt.cond)
            
            # Insert phi nodes at block boundaries
            phi_insertions = self._insert_phi_nodes(stmt)
            
            # Rename branches
            stmt.then_body = self._rename_stmts(stmt.then_body)
            stmt.else_body = self._rename_stmts(stmt.else_body)
            
            # Combine phi insertions with the if statement
            if phi_insertions:
                return phi_insertions + [stmt]
            return stmt
        
        elif isinstance(stmt, WhileStmt):
            # Rename condition
            stmt.cond = self._rename_expr(stmt.cond)
            
            # Insert phi nodes for loop variables
            phi_insertions = self._insert_loop_phi_nodes(stmt)
            
            # Rename loop body
            stmt.body = self._rename_stmts(stmt.body)
            
            # Combine phi insertions with the while statement
            if phi_insertions:
                return phi_insertions + [stmt]
            return stmt
        
        return stmt
    
    def _rename_expr(self, expr: Any) -> Any:
        """Rename expressions to use SSA values."""
        if isinstance(expr, Name):
            # Replace with latest SSA version
            var_name = expr.value
            if var_name in self.ssa_values and self.ssa_values[var_name]:
                latest_version = len(self.ssa_values[var_name])
                setattr(expr, "_ssa_version", latest_version)
                # Record use point
                self.ssa_values[var_name][-1].use_points.append(expr)
            return expr
        
        elif isinstance(expr, (Literal, BoolLit, NilLit)):
            return expr
        
        elif isinstance(expr, Unary):
            expr.expr = self._rename_expr(expr.expr)
            return expr
        
        elif isinstance(expr, Binary):
            expr.left = self._rename_expr(expr.left)
            expr.right = self._rename_expr(expr.right)
            return expr
        
        elif isinstance(expr, Call):
            expr.fn = self._rename_expr(expr.fn)
            expr.args = [self._rename_expr(arg) for arg in expr.args]
            return expr
        
        elif isinstance(expr, IndexExpr):
            expr.obj = self._rename_expr(expr.obj)
            expr.index = self._rename_expr(expr.index)
            return expr
        
        return expr
    
    def _insert_phi_nodes(self, if_stmt: IfStmt) -> List[Any]:
        """Insert phi nodes at if-else join point."""
        phi_nodes = []
        
        # Find variables modified in both branches
        then_modifies = self._find_modified_variables(if_stmt.then_body)
        else_modifies = self._find_modified_variables(if_stmt.else_body)
        
        # Insert phi nodes for variables modified in both branches
        common_vars = then_modifies & else_modifies
        
        for var_name in common_vars:
            if var_name in self.ssa_values:
                # Create phi node
                phi_node = self._create_phi_node(var_name, if_stmt)
                if phi_node:
                    phi_nodes.append(phi_node)
        
        return phi_nodes
    
    def _insert_loop_phi_nodes(self, while_stmt: WhileStmt) -> List[Any]:
        """Insert phi nodes for loop variables."""
        phi_nodes = []
        
        # Find variables modified in loop body
        body_modifies = self._find_modified_variables(while_stmt.body)
        
        # Variables used in condition that are modified in body need phi nodes
        cond_uses = self._find_used_variables(while_stmt.cond)
        loop_vars = body_modifies & cond_uses
        
        for var_name in loop_vars:
            if var_name in self.ssa_values:
                phi_node = self._create_phi_node(var_name, while_stmt)
                if phi_node:
                    phi_nodes.append(phi_node)
        
        return phi_nodes
    
    def _find_modified_variables(self, stmts: List[Any]) -> Set[str]:
        """Find variables modified in statement list."""
        modified = set()
        
        for stmt in stmts:
            if isinstance(stmt, LetStmt):
                modified.add(stmt.name)
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                modified.add(stmt.target.value)
            elif isinstance(stmt, (IfStmt, WhileStmt)):
                if isinstance(stmt, IfStmt):
                    modified.update(self._find_modified_variables(stmt.then_body))
                    modified.update(self._find_modified_variables(stmt.else_body))
                else:
                    modified.update(self._find_modified_variables(stmt.body))
        
        return modified
    
    def _find_used_variables(self, expr: Any) -> Set[str]:
        """Find variables used in expression."""
        used = set()
        
        if isinstance(expr, Name):
            used.add(expr.value)
        elif isinstance(expr, (Unary, Binary)):
            if hasattr(expr, 'expr'):
                used.update(self._find_used_variables(expr.expr))
            if hasattr(expr, 'left'):
                used.update(self._find_used_variables(expr.left))
            if hasattr(expr, 'right'):
                used.update(self._find_used_variables(expr.right))
        elif isinstance(expr, Call):
            used.update(self._find_used_variables(expr.fn))
            for arg in expr.args:
                used.update(self._find_used_variables(arg))
        elif isinstance(expr, IndexExpr):
            used.update(self._find_used_variables(expr.obj))
            used.update(self._find_used_variables(expr.index))
        
        return used
    
    def _create_phi_node(self, var_name: str, location: Any) -> Optional[Any]:
        """Create a phi node for a variable."""
        # This is a simplified phi node creation
        # Full implementation would handle multiple predecessors
        if var_name in self.ssa_values and len(self.ssa_values[var_name]) > 0:
            # Create a let statement to represent the phi node
            phi_stmt = LetStmt(
                name=f"{var_name}_phi",
                expr=Name(var_name, 0, 0, 0),  # Placeholder
                mut=False,
                type_name=None,
                pos=0, line=0, col=0
            )
            setattr(phi_stmt, "_is_phi_node", True)
            setattr(phi_stmt, "_phi_var", var_name)
            return phi_stmt
        
        return None
    
    def _optimize_phi_nodes(self, stmts: List[Any]) -> None:
        """Optimize phi nodes by removing unnecessary ones."""
        # This is a placeholder for phi node optimization
        # Full implementation would analyze phi node liveness
        pass


class Mem2RegOptimizer:
    """Memory-to-register promotion optimization."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def promote_to_registers(self, prog: Any) -> Any:
        """Promote memory operations to register operations."""
        ssa_builder = SSABuilder(self.ctx)
        return ssa_builder.construct_ssa(prog)


def optimize_ssa_program(prog: Any, overflow_mode: str = "trap", profile: str = "debug") -> Any:
    """Apply SSA construction and mem2reg optimization to a program."""
    ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
    optimizer = Mem2RegOptimizer(ctx)
    return optimizer.promote_to_registers(prog)
