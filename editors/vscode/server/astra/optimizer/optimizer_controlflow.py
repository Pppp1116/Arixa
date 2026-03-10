"""Control flow optimization passes."""

from __future__ import annotations

from typing import Any, Optional

from astra.ast import *
from .optimizer_enhanced import OptimizationContext


class BlockMerger:
    """DISABLED: Merge basic blocks to reduce control flow overhead.
    
    DISABLED because:
    - ASTRA/Arixa does not have a comma operator
    - Inventing syntax/semantics is unsafe
    - Can affect debugging, source mapping, and lifetime semantics
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def merge_blocks(self, prog: Any) -> tuple[Any, bool]:
        """Disabled - does nothing."""
        return prog, False


class NestedIfCombiner:
    """Combine nested if statements where safe.
    
    This is NOT real jump threading - it's a simple AST transformation
    that combines nested ifs when no else branches are present.
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def combine_nested_ifs(self, prog: Any) -> tuple[Any, bool]:
        """Combine nested if statements in the program.
        
        Returns (program, changed) for fixed-point iteration.
        """
        changed = False
        for item in prog.items:
            if isinstance(item, FnDecl):
                fn_changed = self._combine_function_nested_ifs(item)
                changed = changed or fn_changed
        return prog, changed
    
    def _combine_function_nested_ifs(self, fn: FnDecl) -> bool:
        """Combine nested ifs in a function.
        
        Returns True if any changes were made.
        """
        new_body = self._combine_stmt_nested_ifs(fn.body)
        if new_body != fn.body:
            fn.body = new_body
            return True
        return False
    
    def _combine_stmt_nested_ifs(self, stmts: list[Any]) -> list[Any]:
        """Combine nested ifs in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                optimized = self._combine_if_statement(stmt)
                new_stmts.append(optimized)
            else:
                new_stmts.append(stmt)
        
        return new_stmts
    
    def _combine_if_statement(self, if_stmt: IfStmt) -> Any:
        """Combine nested if statements."""
        # Simple combination: if (c) { if (d) { ... } }
        if (len(if_stmt.then_body) == 1 and 
            isinstance(if_stmt.then_body[0], IfStmt) and 
            not if_stmt.else_body):
            
            inner_if = if_stmt.then_body[0]
            if not inner_if.else_body:
                # Can combine conditions: if (c && d) { ... }
                combined_cond = Binary(
                    op="&&",
                    left=if_stmt.cond,
                    right=inner_if.cond,
                    pos=if_stmt.cond.pos,
                    line=if_stmt.cond.line,
                    col=if_stmt.cond.col
                )
                return IfStmt(
                    cond=combined_cond,
                    then_body=inner_if.then_body,
                    else_body=[],
                    pos=if_stmt.pos,
                    line=if_stmt.line,
                    col=if_stmt.col
                )
        
        return if_stmt


class SwitchOptimizer:
    """DISABLED: Optimize switch/match statements.
    
    DISABLED because:
    - Repeated evaluation of match expression (side effects)
    - Assumes all patterns are == (wildcards, ranges, destructuring unsupported)
    - No temporary variable introduction for expensive expressions
    - May break pattern priority and exhaustiveness semantics
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def optimize_switches(self, prog: Any) -> tuple[Any, bool]:
        """Disabled - does nothing."""
        return prog, False


class BranchLayoutHeuristic:
    """Simple branch layout heuristic.
    
    This is NOT real branch prediction optimization - it's a simple heuristic
    that swaps branches to put the smaller body first. May not affect final codegen.
    """
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def optimize_branch_layout(self, prog: Any) -> tuple[Any, bool]:
        """Apply branch layout heuristic to the program.
        
        Returns (program, changed) for fixed-point iteration.
        """
        changed = False
        for item in prog.items:
            if isinstance(item, FnDecl):
                fn_changed = self._optimize_function_branches(item)
                changed = changed or fn_changed
        return prog, changed
    
    def _optimize_function_branches(self, fn: FnDecl) -> bool:
        """Optimize branch layout in a function.
        
        Returns True if any changes were made.
        """
        new_body = self._optimize_stmt_branches(fn.body)
        if new_body != fn.body:
            fn.body = new_body
            return True
        return False
    
    def _optimize_stmt_branches(self, stmts: list[Any]) -> list[Any]:
        """Optimize branch layout in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                optimized = self._optimize_if_branch(stmt)
                new_stmts.append(optimized)
            else:
                new_stmts.append(stmt)
        
        return new_stmts
    
    def _optimize_if_branch(self, if_stmt: IfStmt) -> Any:
        """Optimize an if statement using simple heuristic."""
        # Simple heuristic: put smaller body first
        then_size = self._estimate_stmts_size(if_stmt.then_body)
        else_size = self._estimate_stmts_size(if_stmt.else_body)
        
        if else_size > 0 and else_size < then_size:
            # Swap branches
            negated_cond = Unary(
                op="!",
                expr=if_stmt.cond,
                pos=if_stmt.cond.pos,
                line=if_stmt.cond.line,
                col=if_stmt.cond.col
            )
            return IfStmt(
                cond=negated_cond,
                then_body=if_stmt.else_body,
                else_body=if_stmt.then_body,
                pos=if_stmt.pos,
                line=if_stmt.line,
                col=if_stmt.col
            )
        
        return if_stmt
    
    def _estimate_stmts_size(self, stmts: list[Any]) -> int:
        """Estimate the size of a statement list."""
        return len(stmts)


class DeadBranchEliminator:
    """Eliminate dead branches in control flow."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def eliminate_dead_branches(self, prog: Any) -> tuple[Any, bool]:
        """Eliminate dead branches in the program.
        
        Returns (program, changed) for fixed-point iteration.
        """
        changed = False
        for item in prog.items:
            if isinstance(item, FnDecl):
                fn_changed = self._eliminate_function_dead_branches(item)
                changed = changed or fn_changed
        return prog, changed
    
    def _eliminate_function_dead_branches(self, fn: FnDecl) -> bool:
        """Eliminate dead branches in a function.
        
        Returns True if any changes were made.
        """
        new_body = self._eliminate_stmt_dead_branches(fn.body)
        if new_body != fn.body:
            fn.body = new_body
            return True
        return False
    
    def _eliminate_stmt_dead_branches(self, stmts: list[Any]) -> list[Any]:
        """Eliminate dead branches in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                optimized = self._eliminate_if_dead_branch(stmt)
                if isinstance(optimized, list):
                    # Flatten list of statements
                    new_stmts.extend(optimized)
                elif optimized is not None:
                    new_stmts.append(optimized)
            elif isinstance(stmt, WhileStmt):
                optimized = self._eliminate_while_dead_branch(stmt)
                if optimized is not None:
                    new_stmts.append(optimized)
            else:
                new_stmts.append(stmt)
        
        return new_stmts
    
    def _eliminate_if_dead_branch(self, if_stmt: IfStmt) -> Any:
        """Eliminate dead branch in if statement."""
        # Check if condition is always true or false
        cond_value = self._evaluate_constant_condition(if_stmt.cond)
        
        if cond_value is True:
            # Always take then branch - return the body (list of statements)
            return if_stmt.then_body
        elif cond_value is False:
            # Always take else branch - return the body or None
            return if_stmt.else_body if if_stmt.else_body else None
        
        return if_stmt
    
    def _eliminate_while_dead_branch(self, while_stmt: WhileStmt) -> Any:
        """Eliminate dead branch in while statement."""
        # Check if condition is always false
        cond_value = self._evaluate_constant_condition(while_stmt.cond)
        
        if cond_value is False:
            # Loop never executes - remove it
            return None
        
        return while_stmt
    
    def _evaluate_constant_condition(self, cond: Any) -> Optional[bool]:
        """Evaluate if condition is constant."""
        # This is a simplified constant evaluation
        # Full implementation would use the constant folder
        
        if isinstance(cond, BoolLit):
            return cond.value
        elif isinstance(cond, Literal):
            return bool(cond.value)
        elif isinstance(cond, Binary) and cond.op == "&&":
            left = self._evaluate_constant_condition(cond.left)
            right = self._evaluate_constant_condition(cond.right)
            if left is False or right is False:
                return False
            if left is True and right is True:
                return True
        elif isinstance(cond, Binary) and cond.op == "||":
            left = self._evaluate_constant_condition(cond.left)
            right = self._evaluate_constant_condition(cond.right)
            if left is True or right is True:
                return True
            if left is False and right is False:
                return False
        
        return None


class ControlFlowOptimizer:
    """Combined control flow optimization passes with fixed-point iteration."""
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug"):
        self.ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
        self.release_mode = profile == "release"
        
        # Initialize control flow optimization passes
        self.block_merger = BlockMerger(self.ctx)  # DISABLED
        self.if_combiner = NestedIfCombiner(self.ctx)
        self.switch_optimizer = SwitchOptimizer(self.ctx)  # DISABLED
        self.branch_layout = BranchLayoutHeuristic(self.ctx)
        self.dead_branch_eliminator = DeadBranchEliminator(self.ctx)
    
    def optimize_control_flow(self, prog: Any) -> Any:
        """Apply all control flow optimizations to the program.
        
        Uses fixed-point iteration for better optimization.
        """
        if self.ctx.profile == "debug":
            print(f"OPTIMIZE: Running control flow optimization pipeline (profile={self.ctx.profile})")
        
        max_rounds = 4
        
        for round_num in range(max_rounds):
            changed = False
            
            if self.release_mode:
                # Pass 1: Dead branch elimination (always first)
                prog, dead_changed = self.dead_branch_eliminator.eliminate_dead_branches(prog)
                changed = changed or dead_changed
                
                # Pass 2: Nested if combination
                prog, if_changed = self.if_combiner.combine_nested_ifs(prog)
                changed = changed or if_changed
                
                # Pass 3: Branch layout heuristic (low value)
                prog, branch_changed = self.branch_layout.optimize_branch_layout(prog)
                changed = changed or branch_changed
                
                # Pass 4: Block merger (disabled)
                prog, block_changed = self.block_merger.merge_blocks(prog)
                changed = changed or block_changed
                
                # Pass 5: Switch optimizer (disabled)
                prog, switch_changed = self.switch_optimizer.optimize_switches(prog)
                changed = changed or switch_changed
            
            if self.ctx.profile == "debug":
                print(f"OPTIMIZE: Control flow round {round_num + 1}, changed={changed}")
            
            if not changed:
                break
        
        return prog


def optimize_controlflow_program(prog: Any, overflow_mode: str = "trap", profile: str = "debug") -> Any:
    """Apply control flow optimizations to a program."""
    optimizer = ControlFlowOptimizer(overflow_mode=overflow_mode, profile=profile)
    return optimizer.optimize_control_flow(prog)
