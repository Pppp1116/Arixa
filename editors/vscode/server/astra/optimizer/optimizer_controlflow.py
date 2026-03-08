"""Control flow optimization passes."""

from __future__ import annotations

from typing import Any, Set, Dict, List, Tuple, Optional
from dataclasses import dataclass

from astra.ast import *
from .optimizer_enhanced import OptimizationContext


class BlockMerger:
    """Merge basic blocks to reduce control flow overhead."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def merge_blocks(self, prog: Any) -> Any:
        """Merge basic blocks in the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._merge_function_blocks(item)
        return prog
    
    def _merge_function_blocks(self, fn: FnDecl) -> None:
        """Merge basic blocks in a function."""
        fn.body = self._merge_stmt_blocks(fn.body)
    
    def _merge_stmt_blocks(self, stmts: List[Any]) -> List[Any]:
        """Merge blocks in statement list."""
        new_stmts = []
        i = 0
        while i < len(stmts):
            stmt = stmts[i]
            
            # Check if we can merge with the next statement
            if i + 1 < len(stmts):
                next_stmt = stmts[i + 1]
                merged = self._try_merge(stmt, next_stmt)
                if merged is not None:
                    new_stmts.append(merged)
                    i += 2
                    continue
            
            new_stmts.append(stmt)
            i += 1
        
        return new_stmts
    
    def _try_merge(self, stmt1: Any, stmt2: Any) -> Optional[Any]:
        """Try to merge two statements."""
        # Simple case: merge consecutive expressions
        if isinstance(stmt1, ExprStmt) and isinstance(stmt2, ExprStmt):
            return ExprStmt(
                Binary(op=",", left=stmt1.expr, right=stmt2.expr, 
                       pos=stmt1.pos, line=stmt1.line, col=stmt1.col)
            )
        
        return None


class JumpThreading:
    """Jump threading optimization to reduce branch mispredictions."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def thread_jumps(self, prog: Any) -> Any:
        """Apply jump threading to the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._thread_function_jumps(item)
        return prog
    
    def _thread_function_jumps(self, fn: FnDecl) -> None:
        """Thread jumps in a function."""
        fn.body = self._thread_stmt_jumps(fn.body)
    
    def _thread_stmt_jumps(self, stmts: List[Any]) -> List[Any]:
        """Thread jumps in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                # Try to thread through nested ifs
                optimized = self._thread_if_statement(stmt)
                new_stmts.append(optimized)
            else:
                new_stmts.append(stmt)
        
        return new_stmts
    
    def _thread_if_statement(self, if_stmt: IfStmt) -> Any:
        """Thread through an if statement."""
        # Simple jump threading: if (c) { if (d) { ... } }
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
    """Optimize switch/match statements."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def optimize_switches(self, prog: Any) -> Any:
        """Optimize switch statements in the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._optimize_function_switches(item)
        return prog
    
    def _optimize_function_switches(self, fn: FnDecl) -> None:
        """Optimize switches in a function."""
        fn.body = self._optimize_stmt_switches(fn.body)
    
    def _optimize_stmt_switches(self, stmts: List[Any]) -> List[Any]:
        """Optimize switches in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, MatchStmt):
                optimized = self._optimize_match(stmt)
                new_stmts.append(optimized)
            else:
                new_stmts.append(stmt)
        
        return new_stmts
    
    def _optimize_match(self, match_stmt: MatchStmt) -> Any:
        """Optimize a match statement."""
        # Simple optimization: convert small matches to if-else chains
        if len(match_stmt.arms) <= 3:
            return self._match_to_if_else(match_stmt)
        
        return match_stmt
    
    def _match_to_if_else(self, match_stmt: MatchStmt) -> Any:
        """Convert match to if-else chain."""
        if not match_stmt.arms:
            return ExprStmt(expr=match_stmt.expr, pos=match_stmt.pos, line=match_stmt.line, col=match_stmt.col)
        
        # Build if-else chain
        result = None
        current_else = None
        
        for i, (pattern, body) in enumerate(match_stmt.arms):
            condition = Binary(
                op="==",
                left=match_stmt.expr,
                right=pattern,
                pos=match_stmt.pos,
                line=match_stmt.line,
                col=match_stmt.col
            )
            
            if current_else is None:
                # First if
                result = IfStmt(
                    cond=condition,
                    then_body=body,
                    else_body=[],
                    pos=match_stmt.pos,
                    line=match_stmt.line,
                    col=match_stmt.col
                )
                current_else = result.else_body
            else:
                # Add else if
                else_if = IfStmt(
                    cond=condition,
                    then_body=body,
                    else_body=[],
                    pos=match_stmt.pos,
                    line=match_stmt.line,
                    col=match_stmt.col
                )
                current_else.extend([else_if])
                current_else = else_if.else_body
        
        return result


class BranchPredictionOptimizer:
    """Optimize branches for better prediction."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def optimize_branch_prediction(self, prog: Any) -> Any:
        """Optimize branch prediction in the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._optimize_function_branches(item)
        return prog
    
    def _optimize_function_branches(self, fn: FnDecl) -> None:
        """Optimize branch prediction in a function."""
        fn.body = self._optimize_stmt_branches(fn.body)
    
    def _optimize_stmt_branches(self, stmts: List[Any]) -> List[Any]:
        """Optimize branch prediction in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                optimized = self._optimize_if_branch(stmt)
                new_stmts.append(optimized)
            else:
                new_stmts.append(stmt)
        
        return new_stmts
    
    def _optimize_if_branch(self, if_stmt: IfStmt) -> Any:
        """Optimize an if statement for better branch prediction."""
        # Reorder branches to put the more likely one first
        # This is a heuristic - full implementation would use profiling data
        
        # Simple heuristic: put smaller body first (better for instruction cache)
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
    
    def _estimate_stmts_size(self, stmts: List[Any]) -> int:
        """Estimate the size of a statement list."""
        return len(stmts)


class DeadBranchEliminator:
    """Eliminate dead branches in control flow."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
    
    def eliminate_dead_branches(self, prog: Any) -> Any:
        """Eliminate dead branches in the program."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._eliminate_function_dead_branches(item)
        return prog
    
    def _eliminate_function_dead_branches(self, fn: FnDecl) -> None:
        """Eliminate dead branches in a function."""
        fn.body = self._eliminate_stmt_dead_branches(fn.body)
    
    def _eliminate_stmt_dead_branches(self, stmts: List[Any]) -> List[Any]:
        """Eliminate dead branches in statement list."""
        new_stmts = []
        
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                optimized = self._eliminate_if_dead_branch(stmt)
                if optimized is not None:
                    new_stmts.append(optimized)
            elif isinstance(stmt, WhileStmt):
                optimized = self._eliminate_while_dead_branch(stmt)
                if optimized is not None:
                    new_stmts.append(optimized)
            else:
                new_stmts.append(stmt)
        
        return new_stmts
    
    def _eliminate_if_dead_branch(self, if_stmt: IfStmt) -> Optional[Any]:
        """Eliminate dead branch in if statement."""
        # Check if condition is always true or false
        cond_value = self._evaluate_constant_condition(if_stmt.cond)
        
        if cond_value is True:
            # Always take then branch
            return if_stmt.then_body
        elif cond_value is False:
            # Always take else branch
            return if_stmt.else_body if if_stmt.else_body else None
        
        return if_stmt
    
    def _eliminate_while_dead_branch(self, while_stmt: WhileStmt) -> Optional[Any]:
        """Eliminate dead branch in while statement."""
        # Check if condition is always false
        cond_value = self._evaluate_constant_condition(while_stmt.cond)
        
        if cond_value is False:
            # Loop never executes
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
    """Combined control flow optimization passes."""
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug"):
        self.ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
        self.release_mode = profile == "release"
        
        # Initialize control flow optimization passes
        self.block_merger = BlockMerger(self.ctx)
        self.jump_threader = JumpThreading(self.ctx)
        self.switch_optimizer = SwitchOptimizer(self.ctx)
        self.branch_optimizer = BranchPredictionOptimizer(self.ctx)
        self.dead_branch_eliminator = DeadBranchEliminator(self.ctx)
    
    def optimize_control_flow(self, prog: Any) -> Any:
        """Apply all control flow optimizations to the program."""
        if self.release_mode:
            # Dead branch elimination first
            self.dead_branch_eliminator.eliminate_dead_branches(prog)
            
            # Jump threading
            self.jump_threader.thread_jumps(prog)
            
            # Switch optimization
            self.switch_optimizer.optimize_switches(prog)
            
            # Branch prediction optimization
            self.branch_optimizer.optimize_branch_prediction(prog)
            
            # Block merging
            self.block_merger.merge_blocks(prog)
        
        return prog


def optimize_controlflow_program(prog: Any, overflow_mode: str = "trap", profile: str = "debug") -> Any:
    """Apply control flow optimizations to a program."""
    optimizer = ControlFlowOptimizer(overflow_mode=overflow_mode, profile=profile)
    return optimizer.optimize_control_flow(prog)
