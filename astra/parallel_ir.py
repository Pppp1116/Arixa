"""
Parallel IR generation and optimization for ASTRA compiler.

Generates and optimizes IR for functions in parallel using
shared immutable context.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from astra.ast import Program, FnDecl
from astra.parallel import ParallelExecutor, WorkItem
from astra.profiler import profiler
from astra.optimizer import optimize_program


@dataclass
class IROptimizationWorkItem:
    """A function to optimize in parallel"""
    fn_decl: FnDecl
    context: Dict[str, Any]  # Shared optimization context


class ThreadLocalIROptimizer:
    """Thread-local IR optimizer with isolated state"""
    
    def __init__(self):
        self.local_context: Dict[str, Any] = {}
        self.optimized_functions: List[FnDecl] = []
    
    def optimize_function(self, work_item: IROptimizationWorkItem) -> FnDecl:
        """Optimize a single function with thread-local state"""
        try:
            # Create a temporary program with just this function
            temp_program = Program(items=[work_item.fn_decl])
            
            # Apply optimizations to the program
            optimized_program = optimize_program(temp_program)
            
            # Return the optimized function
            if optimized_program.items:
                return optimized_program.items[0]
            else:
                return work_item.fn_decl
        except Exception as e:
            # Return original function if optimization fails
            return work_item.fn_decl
    
    def _copy_function(self, fn: FnDecl) -> FnDecl:
        """Create a deep copy of function for thread-safe optimization"""
        import copy
        return copy.deepcopy(fn)


def prepare_ir_optimization_work_items(
    program: Program,
    optimization_context: Dict[str, Any]
) -> List[IROptimizationWorkItem]:
    """Prepare work items for parallel IR optimization"""
    work_items = []
    
    for item in program.items:
        if isinstance(item, FnDecl):
            work_item = IROptimizationWorkItem(
                fn_decl=item,
                context=optimization_context
            )
            work_items.append(work_item)
    
    return work_items


def optimize_program_parallel(
    program: Program,
    optimization_context: Optional[Dict[str, Any]] = None
) -> Program:
    """
    Optimize a program's functions in parallel.
    
    Returns a new program with optimized functions.
    """
    if optimization_context is None:
        optimization_context = {}
    
    # Prepare work items
    work_items = prepare_ir_optimization_work_items(program, optimization_context)
    
    if not work_items:
        return program  # No functions to optimize
    
    # Optimize functions in parallel
    optimized_functions = []
    
    if len(work_items) == 1:
        # Sequential optimization for single function
        with profiler.section("ir_optimize_sequential"):
            optimizer = ThreadLocalIROptimizer()
            optimized_fn = optimizer.optimize_function(work_items[0])
            optimized_functions.append(optimized_fn)
    else:
        # Parallel optimization for multiple functions
        with profiler.section("ir_optimize_parallel"):
            with ParallelExecutor() as executor:
                # Submit all work
                futures = []
                for i, work_item in enumerate(work_items):
                    work = WorkItem(
                        id=f"optimize_fn_{i}",
                        fn=lambda wi=work_item: _optimize_function_worker(wi)
                    )
                    future = executor.submit_work(work)
                    futures.append((work.id, future))
                
                # Collect results
                for work_id, future in futures:
                    try:
                        optimized_fn = executor.wait_for(work_id)
                        optimized_functions.append(optimized_fn)
                    except Exception as e:
                        # Fall back to original function
                        work_idx = int(work_id.split("_")[-1])
                        original_fn = work_items[work_idx].fn_decl
                        optimized_functions.append(original_fn)
    
    # Build new program with optimized functions
    new_items = []
    fn_map = {id(work_items[i].fn_decl): optimized_functions[i] for i in range(len(work_items))}
    
    for item in program.items:
        if isinstance(item, FnDecl):
            new_items.append(fn_map.get(id(item), item))
        else:
            new_items.append(item)
    
    return Program(items=new_items)


def _optimize_function_worker(work_item: IROptimizationWorkItem) -> FnDecl:
    """Worker function for parallel optimization"""
    optimizer = ThreadLocalIROptimizer()
    return optimizer.optimize_function(work_item)


def generate_ir_parallel(
    program: Program,
    ir_generator: Any,  # IR generator function/class
    generation_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generate IR for functions in parallel.
    
    Returns a mapping from function names to their IR.
    """
    if generation_context is None:
        generation_context = {}
    
    # Collect functions to generate IR for
    functions = []
    for item in program.items:
        if isinstance(item, FnDecl):
            functions.append(item)
    
    if not functions:
        return {}
    
    # Generate IR in parallel
    ir_results = {}
    
    if len(functions) == 1:
        # Sequential IR generation for single function
        with profiler.section("ir_gen_sequential"):
            fn = functions[0]
            try:
                ir = ir_generator(fn, generation_context)
                ir_results[fn.name] = ir
            except Exception as e:
                # Create error placeholder
                ir_results[fn.name] = f"ERROR: {e}"
    else:
        # Parallel IR generation for multiple functions
        with profiler.section("ir_gen_parallel"):
            with ParallelExecutor() as executor:
                # Submit all work
                futures = []
                for i, fn in enumerate(functions):
                    work = WorkItem(
                        id=f"gen_ir_{i}",
                        fn=lambda f=fn: _generate_ir_worker(f, ir_generator, generation_context)
                    )
                    future = executor.submit_work(work)
                    futures.append((work.id, future, fn.name))
                
                # Collect results
                for work_id, future, fn_name in futures:
                    try:
                        ir = executor.wait_for(work_id)
                        ir_results[fn_name] = ir
                    except Exception as e:
                        # Create error placeholder
                        ir_results[fn_name] = f"ERROR: {e}"
    
    return ir_results


def _generate_ir_worker(fn: FnDecl, ir_generator: Any, context: Dict[str, Any]) -> Any:
    """Worker function for parallel IR generation"""
    try:
        return ir_generator(fn, context)
    except Exception as e:
        return f"ERROR: {e}"


class ParallelIROptimizer:
    """High-level interface for parallel IR operations"""
    
    def __init__(self):
        self.optimization_context: Dict[str, Any] = {}
        self.generation_context: Dict[str, Any] = {}
    
    def set_optimization_context(self, context: Dict[str, Any]) -> None:
        """Set shared optimization context"""
        self.optimization_context = context
    
    def set_generation_context(self, context: Dict[str, Any]) -> None:
        """Set shared IR generation context"""
        self.generation_context = context
    
    def optimize_program(self, program: Program) -> Program:
        """Optimize a program in parallel"""
        return optimize_program_parallel(program, self.optimization_context)
    
    def generate_ir(self, program: Program, ir_generator: Any) -> Dict[str, Any]:
        """Generate IR for a program in parallel"""
        return generate_ir_parallel(program, ir_generator, self.generation_context)
