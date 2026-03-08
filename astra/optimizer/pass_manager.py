"""Robust pass manager and change tracking for ASTRA optimizations.

Provides the foundation for sound optimization pipelines with:
- Fixed-point iteration with proper convergence detection
- Precise change tracking at multiple granularities
- Pass dependency management and ordering
- Optimization statistics and profiling
- Safe invalidation and cache management
- Pipeline composition and orchestration

This replaces the ad-hoc optimization loops with a proper framework
that can support real optimizations safely.
"""

from __future__ import annotations

from typing import Any, Optional, Dict, List, Set, Callable, Union
from dataclasses import dataclass, field
from enum import Enum, auto
from time import perf_counter
import logging

from astra.ast import *
from astra.optimizer.cfg import ControlFlowGraph, build_cfg_for_function
from astra.optimizer.effects import EffectAnalyzer, create_effect_analyzer
from astra.optimizer.expressions import ExpressionKeyManager, create_expression_key_manager


class ChangeType(Enum):
    """Types of changes that can occur during optimization."""
    NONE = auto()
    STATEMENT_ADDED = auto()
    STATEMENT_REMOVED = auto()
    STATEMENT_MODIFIED = auto()
    EXPRESSION_MODIFIED = auto()
    BLOCK_STRUCTURE_CHANGED = auto()
    CFG_STRUCTURE_CHANGED = auto()
    TYPE_INFORMATION_CHANGED = auto()


@dataclass
class ChangeInfo:
    """Detailed information about changes made during optimization."""
    
    change_type: ChangeType = ChangeType.NONE
    location: Optional[str] = None  # Description of where change occurred
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    description: Optional[str] = None
    
    def __str__(self) -> str:
        if self.change_type == ChangeType.NONE:
            return "No changes"
        
        parts = [self.change_type.name.replace('_', ' ').title()]
        if self.location:
            parts.append(f"at {self.location}")
        if self.description:
            parts.append(f"({self.description})")
        
        return " ".join(parts)


@dataclass
class PassResult:
    """Result of running an optimization pass."""
    
    success: bool
    changed: bool
    changes: List[ChangeInfo] = field(default_factory=list)
    execution_time_ms: float = 0.0
    statistics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        change_str = "CHANGED" if self.changed else "UNCHANGED"
        time_str = f"{self.execution_time_ms:.1f}ms"
        
        return f"PassResult({status}, {change_str}, {time_str})"
    
    def add_change(self, change_type: ChangeType, location: str = None, 
                   old_value: Any = None, new_value: Any = None, 
                   description: str = None) -> None:
        """Add a change record."""
        change = ChangeInfo(
            change_type=change_type,
            location=location,
            old_value=old_value,
            new_value=new_value,
            description=description
        )
        self.changes.append(change)
        if change_type != ChangeType.NONE:
            self.changed = True
    
    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)
    
    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)
        self.success = False


class PassContext:
    """Context provided to optimization passes.
    
    Contains all the analysis results and utilities that passes
    might need for sound optimization.
    """
    
    def __init__(self, function_name: str, overflow_mode: str = "trap", profile: str = "debug"):
        self.function_name = function_name
        self.overflow_mode = overflow_mode
        self.profile = profile
        self.release_mode = profile == "release"
        
        # Analysis results (filled by pass manager or passes)
        self.cfg: Optional[ControlFlowGraph] = None
        self.effect_analyzer: EffectAnalyzer = create_effect_analyzer()
        self.expression_manager: ExpressionKeyManager = create_expression_key_manager()
        
        # Mutable state for passes
        self.mutable_names: Set[str] = set()
        self.global_variables: Set[str] = set()
        self.pure_functions: Set[str] = set()
        self.impure_functions: Set[str] = set()
        
        # Pass-specific data storage
        self.pass_data: Dict[str, Any] = {}
    
    def get_pass_data(self, key: str, default: Any = None) -> Any:
        """Get pass-specific data."""
        return self.pass_data.get(key, default)
    
    def set_pass_data(self, key: str, value: Any) -> None:
        """Set pass-specific data."""
        self.pass_data[key] = value
    
    def invalidate_caches_for_variable(self, var_name: str) -> None:
        """Invalidate expression caches when variable is modified."""
        self.expression_manager.invalidate_variable(var_name)
    
    def invalidate_caches_for_global(self, global_name: str) -> None:
        """Invalidate expression caches when global is modified."""
        self.expression_manager.invalidate_global(global_name)
    
    def clear_all_caches(self) -> None:
        """Clear all optimization caches."""
        self.expression_manager.clear_all_caches()
        self.effect_analyzer.clear_cache()


class OptimizationPass:
    """Base class for all optimization passes.
    
    Provides the interface and common functionality for passes
    in the new optimization pipeline.
    """
    
    def __init__(self, name: str, required_analyses: List[str] = None):
        self.name = name
        self.required_analyses = required_analyses or []
        self.enabled = True
        self.pass_number = -1  # Set by pass manager
        
        # Statistics
        self.total_runs = 0
        self.total_changes = 0
        self.total_time_ms = 0.0
        self.total_failures = 0
    
    def run(self, fn_decl: FnDecl, context: PassContext) -> PassResult:
        """Run the optimization pass on a function.
        
        Args:
            fn_decl: Function declaration to optimize
            context: Pass context with analysis results
            
        Returns:
            PassResult with changes and statistics
        """
        start_time = perf_counter()
        
        try:
            result = self._run_impl(fn_decl, context)
            result.execution_time_ms = (perf_counter() - start_time) * 1000.0
            
            # Update statistics
            self.total_runs += 1
            if result.success:
                self.total_changes += 1 if result.changed else 0
            else:
                self.total_failures += 1
            self.total_time_ms += result.execution_time_ms
            
            return result
            
        except Exception as e:
            # Handle unexpected errors gracefully
            execution_time = (perf_counter() - start_time) * 1000.0
            result = PassResult(success=False, changed=False, execution_time_ms=execution_time)
            result.add_error(f"Pass failed with exception: {e}")
            self.total_failures += 1
            self.total_time_ms += execution_time
            return result
    
    def _run_impl(self, fn_decl: FnDecl, context: PassContext) -> PassResult:
        """Implementation of the optimization pass.
        
        Subclasses should override this method.
        """
        raise NotImplementedError("Subclasses must implement _run_impl")
    
    def is_enabled(self) -> bool:
        """Check if pass is enabled."""
        return self.enabled
    
    def enable(self) -> None:
        """Enable the pass."""
        self.enabled = True
    
    def disable(self) -> None:
        """Disable the pass."""
        self.enabled = False
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pass statistics."""
        avg_time = self.total_time_ms / self.total_runs if self.total_runs > 0 else 0.0
        change_rate = self.total_changes / self.total_runs if self.total_runs > 0 else 0.0
        
        return {
            'name': self.name,
            'total_runs': self.total_runs,
            'total_changes': self.total_changes,
            'change_rate_percent': int(change_rate * 100),
            'total_failures': self.total_failures,
            'failure_rate_percent': int((self.total_failures / self.total_runs * 100) if self.total_runs > 0 else 0),
            'total_time_ms': self.total_time_ms,
            'avg_time_ms': avg_time,
            'enabled': self.enabled
        }
    
    def reset_statistics(self) -> None:
        """Reset pass statistics."""
        self.total_runs = 0
        self.total_changes = 0
        self.total_time_ms = 0.0
        self.total_failures = 0


class PassManager:
    """Manages optimization pass execution and fixed-point iteration.
    
    Provides:
    - Proper pass ordering based on dependencies
    - Fixed-point iteration with convergence detection
    - Change tracking and invalidation
    - Statistics collection and reporting
    - Error handling and recovery
    """
    
    def __init__(self, overflow_mode: str = "trap", profile: str = "debug"):
        self.overflow_mode = overflow_mode
        self.profile = profile
        self.release_mode = profile == "release"
        self.passes: List[OptimizationPass] = []
        
        # Global statistics
        self.total_functions_optimized = 0
        self.total_passes_run = 0
        self.total_time_ms = 0.0
        
        # Configuration
        self.max_iterations = 10  # Maximum fixed-point iterations
        self.enable_statistics = True
        self.enable_logging = False
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        if self.enable_logging:
            self.logger.setLevel(logging.DEBUG)
            # Only add handler if logger doesn't have one
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter('%(name)s - %(levelname)s - %(message)s'))
                self.logger.addHandler(handler)
        else:
            self.logger.setLevel(logging.WARNING)  # Set to warning level when disabled
    
    def add_pass(self, pass_obj: OptimizationPass) -> None:
        """Add an optimization pass to the pipeline."""
        self.passes.append(pass_obj)
    
    def remove_pass(self, pass_name: str) -> bool:
        """Remove a pass by name."""
        for i, pass_obj in enumerate(self.passes):
            if pass_obj.name == pass_name:
                del self.passes[i]
                return True
        return False
    
    def get_pass(self, pass_name: str) -> Optional[OptimizationPass]:
        """Get a pass by name."""
        for pass_obj in self.passes:
            if pass_obj.name == pass_name:
                return pass_obj
        return None
    
    def optimize_function(self, fn_decl: FnDecl) -> PassResult:
        """Optimize a single function using all enabled passes.
        
        Uses fixed-point iteration to ensure passes reach a stable state.
        """
        start_time = perf_counter()
        
        # Create context for this function
        context = PassContext(fn_decl.name, self.overflow_mode, self.profile)
        
        # Collect mutable names and other initial analysis
        self._collect_initial_analysis(fn_decl, context)
        
        # Build CFG if any passes require it
        if any('cfg' in pass_obj.required_analyses for pass_obj in self.passes if pass_obj.is_enabled()):
            context.cfg = build_cfg_for_function(fn_decl.name, fn_decl.body)
        
        # Run fixed-point iteration
        overall_result = self._run_fixed_point_iteration(fn_decl, context)
        
        execution_time = (perf_counter() - start_time) * 1000.0
        overall_result.execution_time_ms = execution_time
        
        # Update global statistics
        self.total_functions_optimized += 1
        self.total_passes_run += len([p for p in self.passes if p.is_enabled()])
        self.total_time_ms += execution_time
        
        if self.logger:
            self.logger.info(f"Optimized {fn_decl.name}: {overall_result}")
        
        return overall_result
    
    def optimize_program(self, program: Program) -> PassResult:
        """Optimize all functions in a program."""
        start_time = perf_counter()
        
        program_result = PassResult(success=True, changed=False)
        
        for item in program.items:
            if isinstance(item, FnDecl):
                fn_result = self.optimize_function(item)
                
                # Combine results
                program_result.changed = program_result.changed or fn_result.changed
                program_result.changes.extend(fn_result.changes)
                program_result.warnings.extend(fn_result.warnings)
                program_result.errors.extend(fn_result.errors)
                
                if not fn_result.success:
                    program_result.success = False
                    program_result.add_error(f"Failed to optimize function {item.name}")
        
        execution_time = (perf_counter() - start_time) * 1000.0
        program_result.execution_time_ms = execution_time
        
        if self.logger:
            self.logger.info(f"Program optimization completed in {execution_time:.1f}ms")
        
        return program_result
    
    def _run_fixed_point_iteration(self, fn_decl: FnDecl, context: PassContext) -> PassResult:
        """Run passes to fixed point."""
        overall_result = PassResult(success=True, changed=False)
        
        for iteration in range(self.max_iterations):
            iteration_changed = False
            
            # Run all enabled passes
            for pass_obj in self.passes:
                if not pass_obj.is_enabled():
                    continue
                
                pass_obj.pass_number = iteration
                pass_result = pass_obj.run(fn_decl, context)
                
                # Combine results
                overall_result.changed = overall_result.changed or pass_result.changed
                overall_result.changes.extend(pass_result.changes)
                overall_result.warnings.extend(pass_result.warnings)
                overall_result.errors.extend(pass_result.errors)
                
                if not pass_result.success:
                    overall_result.success = False
                    overall_result.add_error(f"Pass {pass_obj.name} failed in iteration {iteration}")
                    return overall_result
                
                if pass_result.changed:
                    iteration_changed = True
                    
                    # Invalidate caches if needed
                    if any(change.change_type in {ChangeType.STATEMENT_MODIFIED, 
                                                ChangeType.STATEMENT_REMOVED,
                                                ChangeType.BLOCK_STRUCTURE_CHANGED} 
                           for change in pass_result.changes):
                        context.clear_all_caches()
            
            # Check for convergence
            if not iteration_changed:
                if self.logger:
                    self.logger.debug(f"Converged after {iteration + 1} iterations")
                break
        else:
            # Max iterations reached
            overall_result.add_warning(f"Reached maximum iterations ({self.max_iterations}) without convergence")
            if self.logger:
                self.logger.warning(f"Fixed-point iteration failed to converge for {context.function_name}")
        
        return overall_result
    
    def _collect_initial_analysis(self, fn_decl: FnDecl, context: PassContext) -> None:
        """Collect initial analysis information."""
        # Collect mutable names
        context.mutable_names = self._collect_mutable_names(fn_decl.body)
        
        # Collect global variables (simplified - would need proper scope analysis)
        context.global_variables = self._collect_global_variables(fn_decl.body)
        
        # Configure effect analyzer
        for global_var in context.global_variables:
            context.effect_analyzer.add_global_variable(global_var)
    
    def _collect_mutable_names(self, stmts: List[Any]) -> Set[str]:
        """Collect all mutable variable names in statements."""
        mutable = set()
        
        for stmt in stmts:
            if isinstance(stmt, LetStmt) and stmt.mut:
                mutable.add(stmt.name)
            elif isinstance(stmt, AssignStmt) and isinstance(stmt.target, Name):
                mutable.add(stmt.target.value)
            # Recursively check nested statements
            elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
                mutable.update(self._collect_mutable_names(stmt.body))
            elif hasattr(stmt, 'then_body') and isinstance(stmt.then_body, list):
                mutable.update(self._collect_mutable_names(stmt.then_body))
            elif hasattr(stmt, 'else_body') and isinstance(stmt.else_body, list):
                mutable.update(self._collect_mutable_names(stmt.else_body))
        
        return mutable
    
    def _collect_global_variables(self, stmts: List[Any]) -> Set[str]:
        """Collect global variable references (simplified)."""
        # This is a simplified implementation
        # A real implementation would need proper scope analysis
        globals_set = set()
        
        # For now, assume variables with certain patterns are global
        # This would be replaced with proper symbol table analysis
        global_patterns = {'_', '_global', '_extern'}
        
        def collect_from_expr(expr: Any) -> None:
            if isinstance(expr, Name):
                if any(pattern in expr.value for pattern in global_patterns):
                    globals_set.add(expr.value)
            # Use separate ifs to visit all branches, not elif chains
            if hasattr(expr, 'left'):
                collect_from_expr(expr.left)
            if hasattr(expr, 'right'):
                collect_from_expr(expr.right)
            if hasattr(expr, 'expr'):
                collect_from_expr(expr.expr)
            if hasattr(expr, 'args'):
                for arg in expr.args:
                    collect_from_expr(arg)
        
        for stmt in stmts:
            if isinstance(stmt, ExprStmt):
                collect_from_expr(stmt.expr)
            elif isinstance(stmt, (LetStmt, AssignStmt)):
                collect_from_expr(stmt.expr)
            # Recursively check nested statements
            elif hasattr(stmt, 'body') and isinstance(stmt.body, list):
                globals_set.update(self._collect_global_variables(stmt.body))
            elif hasattr(stmt, 'then_body') and isinstance(stmt.then_body, list):
                globals_set.update(self._collect_global_variables(stmt.then_body))
            elif hasattr(stmt, 'else_body') and isinstance(stmt.else_body, list):
                globals_set.update(self._collect_global_variables(stmt.else_body))
        
        return globals_set
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics for all passes."""
        pass_stats = [pass_obj.get_statistics() for pass_obj in self.passes]
        
        avg_time_per_function = self.total_time_ms / self.total_functions_optimized if self.total_functions_optimized > 0 else 0.0
        avg_passes_per_function = self.total_passes_run / self.total_functions_optimized if self.total_functions_optimized > 0 else 0.0
        
        return {
            'functions_optimized': self.total_functions_optimized,
            'total_passes_run': self.total_passes_run,
            'avg_passes_per_function': avg_passes_per_function,
            'total_time_ms': self.total_time_ms,
            'avg_time_per_function_ms': avg_time_per_function,
            'max_iterations': self.max_iterations,
            'enabled_passes': len([p for p in self.passes if p.is_enabled()]),
            'total_passes': len(self.passes),
            'pass_statistics': pass_stats
        }
    
    def reset_statistics(self) -> None:
        """Reset all statistics."""
        self.total_functions_optimized = 0
        self.total_passes_run = 0
        self.total_time_ms = 0.0
        
        for pass_obj in self.passes:
            pass_obj.reset_statistics()
    
    def print_statistics(self) -> None:
        """Print detailed statistics."""
        stats = self.get_statistics()
        
        print(f"=== Pass Manager Statistics ===")
        print(f"Functions optimized: {stats['functions_optimized']}")
        print(f"Total passes run: {stats['total_passes_run']}")
        print(f"Average passes per function: {stats['avg_passes_per_function']:.1f}")
        print(f"Total time: {stats['total_time_ms']:.1f}ms")
        print(f"Average time per function: {stats['avg_time_per_function_ms']:.1f}ms")
        print(f"Enabled passes: {stats['enabled_passes']}/{stats['total_passes']}")
        
        print(f"\n=== Individual Pass Statistics ===")
        for pass_stat in stats['pass_statistics']:
            status = "ENABLED" if pass_stat['enabled'] else "DISABLED"
            print(f"{pass_stat['name']:20s} {status:8s} runs:{pass_stat['total_runs']:3d} "
                  f"changes:{pass_stat['total_changes']:3d} ({pass_stat['change_rate_percent']:2d}%) "
                  f"time:{pass_stat['total_time_ms']:6.1f}ms avg:{pass_stat['avg_time_ms']:4.1f}ms")


def create_pass_manager(overflow_mode: str = "trap", profile: str = "debug") -> PassManager:
    """Create a configured pass manager."""
    return PassManager(overflow_mode=overflow_mode, profile=profile)
