"""Profile-guided optimization using runtime feedback."""

from __future__ import annotations

from typing import Any, Set, Dict, List, Tuple, Optional
from dataclasses import dataclass
import json
from pathlib import Path

from astra.ast import *
from .optimizer_enhanced import OptimizationContext

# Threshold for identifying hot functions - used across the optimizer
HOT_FUNCTION_CALL_THRESHOLD = 1000


@dataclass
class ProfileData:
    """Profile data collected from runtime execution."""
    function_counts: Dict[str, int]
    branch_counts: Dict[str, Dict[str, int]]  # function -> branch -> count
    hot_loops: Set[str]
    cold_functions: Set[str]
    hot_paths: List[List[str]]  # Paths through functions


class ProfileCollector:
    """Collect runtime profile data."""
    
    def __init__(self, ctx: OptimizationContext):
        self.ctx = ctx
        self.profile_data = ProfileData({}, {}, set(), set(), [])
    
    def collect_profile(self, prog: Any, profile_file: str = None) -> ProfileData:
        """Collect profile data from runtime execution."""
        if profile_file and Path(profile_file).exists():
            return self._load_profile(profile_file)
        else:
            return self._generate_profile(prog)
    
    def _load_profile(self, profile_file: str) -> ProfileData:
        """Load profile data from file."""
        with open(profile_file, 'r') as f:
            data = json.load(f)
        
        return ProfileData(
            function_counts=data.get('function_counts', {}),
            branch_counts=data.get('branch_counts', {}),
            hot_loops=set(data.get('hot_loops', [])),
            cold_functions=set(data.get('cold_functions', [])),
            hot_paths=data.get('hot_paths', [])
        )
    
    def _generate_profile(self, prog: Any) -> ProfileData:
        """Generate synthetic profile data."""
        # This is a placeholder for actual profile collection
        # Full implementation would:
        # 1. Instrument the program
        # 2. Execute with representative inputs
        # 3. Collect execution statistics
        
        # Generate synthetic data for demonstration
        function_counts = {}
        hot_loops = set()
        
        for item in prog.items:
            if isinstance(item, FnDecl):
                # Assume main is hot
                if item.name == "main":
                    function_counts[item.name] = 1000
                    hot_loops.add(f"{item.name}_loop")
                else:
                    function_counts[item.name] = 100
        
        return ProfileData(
            function_counts=function_counts,
            branch_counts={},
            hot_loops=hot_loops,
            cold_functions=set(),
            hot_paths=[]
        )


class HotPathOptimizer:
    """Optimize hot paths identified by profiling."""
    
    def __init__(self, ctx: OptimizationContext, profile_data: ProfileData):
        self.ctx = ctx
        self.profile_data = profile_data
    
    def optimize_hot_paths(self, prog: Any) -> Any:
        """Optimize hot paths based on profile data."""
        # Identify hot functions
        hot_functions = self._get_hot_functions()
        print(f"DEBUG: Hot functions identified: {hot_functions}")
        
        # Apply aggressive optimizations to hot functions
        for item in prog.items:
            if isinstance(item, FnDecl) and item.name in hot_functions:
                print(f"DEBUG: Optimizing hot function: {item.name}")
                self._optimize_hot_function(item)
        
        return prog
    
    def _get_hot_functions(self) -> Set[str]:
        """Get hot functions from profile data."""
        # Consider functions with >= HOT_FUNCTION_CALL_THRESHOLD calls as hot
        return {name for name, count in self.profile_data.function_counts.items() if count >= HOT_FUNCTION_CALL_THRESHOLD}
    
    def _optimize_hot_function(self, fn: FnDecl) -> None:
        """Apply aggressive optimizations to a hot function."""
        # Mark function for aggressive optimization
        print(f"DEBUG: Marking function {fn.name} as hot")
        setattr(fn, "_hot_function", True)
        setattr(fn, "_call_count", self.profile_data.function_counts.get(fn.name, 0))
        
        # Optimize loops in hot functions
        print(f"DEBUG: Optimizing loops in {fn.name}")
        fn.body = self._optimize_hot_loops(fn.body)
        
        # Optimize branches in hot functions
        print(f"DEBUG: Optimizing branches in {fn.name}")
        fn.body = self._optimize_hot_branches(fn.body)
        
        print(f"DEBUG: Final optimized body for {fn.name}: {len(fn.body) if hasattr(fn.body, '__len__') else 'N/A'}")
        return fn
    
    def _optimize_hot_loops(self, stmts: List[Any]) -> List[Any]:
        """Optimize loops in hot functions."""
        new_stmts = []
        for stmt in stmts:
            if isinstance(stmt, WhileStmt):
                # Check if this is a hot loop
                loop_id = self._get_loop_id(stmt)
                if loop_id in self.profile_data.hot_loops:
                    # Apply aggressive loop optimizations
                    optimized_loop = self._optimize_hot_loop(stmt)
                    new_stmts.append(optimized_loop)
                else:
                    new_stmts.append(stmt)
            else:
                new_stmts.append(stmt)
        return new_stmts
    
    def _get_loop_id(self, while_stmt: WhileStmt) -> str:
        """Generate an ID for a loop."""
        # This is a simplified ID generation
        return f"loop_{while_stmt.line}_{while_stmt.col}"
    
    def _optimize_hot_loop(self, while_stmt: WhileStmt) -> Any:
        """Optimize a hot loop."""
        # Mark for aggressive optimization
        setattr(while_stmt, "_hot_loop", True)
        
        # Apply loop unrolling
        setattr(while_stmt, "_unroll_factor", 8)  # Higher unroll factor for hot loops
        
        return while_stmt
    
    def _optimize_hot_branches(self, stmts: List[Any]) -> List[Any]:
        """Optimize branches in hot functions."""
        new_stmts = []
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                # Optimize branch ordering based on profile data
                optimized_if = self._optimize_hot_if(stmt)
                new_stmts.append(optimized_if)
            else:
                new_stmts.append(stmt)
        return new_stmts
    
    def _optimize_hot_if(self, if_stmt: IfStmt) -> Any:
        """Optimize an if statement based on profile data."""
        # This would use branch prediction data from profile
        # For now, just mark as hot
        setattr(if_stmt, "_hot_branch", True)
        return if_stmt


class ColdFunctionOptimizer:
    """Optimize cold functions to reduce code size."""
    
    def __init__(self, ctx: OptimizationContext, profile_data: ProfileData):
        self.ctx = ctx
        self.profile_data = profile_data
    
    def optimize_cold_functions(self, prog: Any) -> Any:
        """Optimize cold functions to reduce code size."""
        # Identify cold functions
        cold_functions = self._get_cold_functions()
        
        # Apply size optimizations to cold functions
        for item in prog.items:
            if isinstance(item, FnDecl) and item.name in cold_functions:
                self._optimize_cold_function(item)
        
        return prog
    
    def _get_cold_functions(self) -> Set[str]:
        """Get cold functions from profile data."""
        # Consider functions with < 10 calls as cold
        return {name for name, count in self.profile_data.function_counts.items() if count < 10}
    
    def _optimize_cold_function(self, fn: FnDecl) -> None:
        """Apply size optimizations to a cold function."""
        # Mark as cold for size optimization
        setattr(fn, "_cold_function", True)
        setattr(fn, "_call_count", self.profile_data.function_counts.get(fn.name, 0))
        
        # Disable expensive optimizations
        setattr(fn, "_disable_inlining", True)
        setattr(fn, "_optimize_for_size", True)


class BranchPredictor:
    """Branch prediction optimization using profile data."""
    
    def __init__(self, ctx: OptimizationContext, profile_data: ProfileData):
        self.ctx = ctx
        self.profile_data = profile_data
    
    def optimize_branch_prediction(self, prog: Any) -> Any:
        """Optimize branch prediction based on profile data."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._optimize_function_branches(item)
        return prog
    
    def _optimize_function_branches(self, fn: FnDecl) -> None:
        """Optimize branches in a function."""
        fn.body = self._optimize_stmt_branches(fn.body)
    
    def _optimize_stmt_branches(self, stmts: List[Any]) -> List[Any]:
        """Optimize branches in statement list."""
        new_stmts = []
        for stmt in stmts:
            if isinstance(stmt, IfStmt):
                optimized_if = self._optimize_branch_prediction(stmt)
                new_stmts.append(optimized_if)
            else:
                new_stmts.append(stmt)
        return new_stmts
    
    def _optimize_branch_prediction(self, if_stmt: IfStmt) -> Any:
        """Optimize branch prediction for an if statement."""
        # This would use branch prediction data from profile
        # For now, just mark the branch
        branch_id = self._get_branch_id(if_stmt)
        
        # Check if we have profile data for this branch
        if branch_id in self.profile_data.branch_counts:
            branch_counts = self.profile_data.branch_counts[branch_id]
            then_count = branch_counts.get('then', 0)
            else_count = branch_counts.get('else', 0)
            
            # Reorder branches based on frequency
            if else_count > then_count:
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
    
    def _get_branch_id(self, if_stmt: IfStmt) -> str:
        """Generate an ID for a branch."""
        return f"branch_{if_stmt.line}_{if_stmt.col}"


class InlineDecisionMaker:
    """Make inlining decisions based on profile data."""
    
    def __init__(self, ctx: OptimizationContext, profile_data: ProfileData):
        self.ctx = ctx
        self.profile_data = profile_data
    
    def make_inline_decisions(self, prog: Any) -> Any:
        """Make inlining decisions based on profile data."""
        for item in prog.items:
            if isinstance(item, FnDecl):
                self._decide_inlining(item)
        return prog
    
    def _decide_inlining(self, fn: FnDecl) -> None:
        """Decide whether to inline a function."""
        call_count = self.profile_data.function_counts.get(fn.name, 0)
        
        # Inline small hot functions aggressively
        if call_count >= HOT_FUNCTION_CALL_THRESHOLD and len(fn.body) <= 5:
            setattr(fn, "_force_inline", True)
        
        # Don't inline large cold functions
        elif call_count < 10 and len(fn.body) > 10:
            setattr(fn, "_no_inline", True)


class ProfileGuidedOptimizer:
    """Combined profile-guided optimizations."""
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug", profile_file: str = None):
        self.ctx = OptimizationContext(overflow_mode=overflow_mode, profile=profile)
        self.release_mode = profile == "release"
        self.profile_file = profile_file
        
        # Initialize profile collector
        self.profile_collector = ProfileCollector(self.ctx)
    
    def optimize_with_profile(self, prog: Any) -> Any:
        """Apply profile-guided optimizations to the program."""
        if self.release_mode:
            # Collect or load profile data
            profile_data = self.profile_collector.collect_profile(prog, self.profile_file)
            
            # Apply profile-guided optimizations
            self._apply_pgo_optimizations(prog, profile_data)
        
        return prog
    
    def _apply_pgo_optimizations(self, prog: Any, profile_data: ProfileData) -> None:
        """Apply all profile-guided optimizations."""
        # Optimize hot paths
        hot_optimizer = HotPathOptimizer(self.ctx, profile_data)
        hot_optimizer.optimize_hot_paths(prog)
        
        # Optimize cold functions
        cold_optimizer = ColdFunctionOptimizer(self.ctx, profile_data)
        cold_optimizer.optimize_cold_functions(prog)
        
        # Optimize branch prediction
        branch_optimizer = BranchPredictor(self.ctx, profile_data)
        branch_optimizer.optimize_branch_prediction(prog)
        
        # Make inlining decisions
        inline_optimizer = InlineDecisionMaker(self.ctx, profile_data)
        inline_optimizer.make_inline_decisions(prog)


def optimize_pgo_program(prog: Any, overflow_mode: str = "trap", profile: str = "debug", profile_file: str = None) -> Any:
    """Apply profile-guided optimizations to a program."""
    optimizer = ProfileGuidedOptimizer(overflow_mode=overflow_mode, profile=profile, profile_file=profile_file)
    return optimizer.optimize_with_profile(prog)
