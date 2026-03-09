"""Effect classification and purity analysis for ASTRA optimizations.

Provides sound analysis of expression effects to enable safe optimizations:
- Pure vs impure classification
- Side effect detection
- Memory access analysis
- Exception/trap behavior analysis
- Control flow effect analysis

This is critical for real optimizations because:
- CSE requires purity to be sound
- Dead code elimination needs effect analysis
- Code motion requires effect guarantees
- Reordering requires effect safety
"""

from __future__ import annotations

from typing import Any, Optional, Set, Dict, List
from dataclasses import dataclass, field
from enum import Enum, auto

from astra.ast import *


class EffectType(Enum):
    """Types of effects an expression can have."""
    PURE = auto()              # No effects, always returns same result for same inputs
    READS_MEMORY = auto()      # Reads memory but doesn't write
    WRITES_MEMORY = auto()     # Writes to memory
    CALLS_FUNCTION = auto()    # May have unknown effects via function call
    CAN_TRAP = auto()          # Can trap/panic/exception
    HAS_IO = auto()            # I/O operations
    MODIFIES_GLOBAL = auto()   # Modifies global state
    READS_GLOBAL = auto()      # Reads global state
    ALLOCATES_MEMORY = auto()  # Memory allocation
    DEALLOCATES_MEMORY = auto() # Memory deallocation


@dataclass
class EffectInfo:
    """Detailed effect information for an expression."""
    
    # Primary effect classification
    is_pure: bool = True
    is_constexpr: bool = False  # Can be evaluated at compile time
    
    # Effect flags
    effects: Set[EffectType] = field(default_factory=set)
    
    # Memory access information
    reads_memory: bool = False
    writes_memory: bool = False
    allocated_memory: bool = False
    deallocated_memory: bool = False
    
    # Global state access
    reads_globals: Set[str] = field(default_factory=set)
    writes_globals: Set[str] = field(default_factory=set)
    
    # Function call effects
    calls_pure_functions: bool = False
    calls_impure_functions: bool = False
    may_recurse: bool = False
    
    # Control flow effects
    can_trap: bool = False
    can_throw: bool = False
    may_not_return: bool = False
    
    # Dependencies for invalidation
    depends_on: Set[str] = field(default_factory=set)  # Variables this depends on
    modifies: Set[str] = field(default_factory=set)   # Variables this may modify
    
    def __str__(self) -> str:
        if self.is_pure:
            return "PURE"
        
        effects = []
        if self.reads_memory: effects.append("READ")
        if self.writes_memory: effects.append("WRITE")
        if self.can_trap: effects.append("TRAP")
        if self.calls_impure_functions: effects.append("CALL")
        if self.reads_globals: effects.append(f"READ_GLOBAL({','.join(self.reads_globals)})")
        if self.writes_globals: effects.append(f"WRITE_GLOBAL({','.join(self.writes_globals)})")
        
        return f"IMPURE({','.join(effects)})" if effects else "IMPURE"
    
    def combine_with(self, other: EffectInfo) -> EffectInfo:
        """Combine effects of two expressions (e.g., function arguments)."""
        result = EffectInfo()
        
        # Pure only if both are pure
        result.is_pure = self.is_pure and other.is_pure
        
        # Combine all effects
        result.effects = self.effects | other.effects
        
        # Memory effects
        result.reads_memory = self.reads_memory or other.reads_memory
        result.writes_memory = self.writes_memory or other.writes_memory
        result.allocated_memory = self.allocated_memory or other.allocated_memory
        result.deallocated_memory = self.deallocated_memory or other.deallocated_memory
        
        # Global effects
        result.reads_globals = self.reads_globals | other.reads_globals
        result.writes_globals = self.writes_globals | other.writes_globals
        
        # Function effects
        result.calls_impure_functions = self.calls_impure_functions or other.calls_impure_functions
        
        # Control flow effects
        result.can_trap = self.can_trap or other.can_trap
        result.can_throw = self.can_throw or other.can_throw
        result.may_not_return = self.may_not_return or other.may_not_return
        
        # Dependencies
        result.depends_on = self.depends_on | other.depends_on
        result.modifies = self.modifies | other.modifies
        
        return result


class EffectAnalyzer:
    """Analyzes effects of ASTRA expressions and statements."""
    
    def __init__(self):
        # Known pure functions (can be extended)
        self.pure_functions = {
            # Math functions
            'abs', 'min', 'max', 'sqrt', 'sin', 'cos', 'tan',
            # Type operations
            'sizeof', 'alignof', 'bitsof',
            # Utility functions
            'len', 'capacity', 'is_empty', 'is_some', 'is_none',
        }
        
        # Known impure functions
        self.impure_functions = {
            # I/O
            'print', 'println', 'read', 'write', 'open', 'close',
            # Memory
            'malloc', 'free', 'realloc', 'calloc',
            # System
            'exit', 'abort', 'panic',
            # Threading
            'spawn', 'join', 'lock', 'unlock',
        }
        
        # Global variables (can be extended via analysis)
        self.global_variables = set()
        
        # Cache for effect analysis
        self.effect_cache: Dict[int, EffectInfo] = {}
    
    def analyze_expression(self, expr: Any) -> EffectInfo:
        """Analyze effects of an expression."""
        expr_id = id(expr)
        if expr_id in self.effect_cache:
            return self.effect_cache[expr_id]
        
        effect = self._analyze_expression_impl(expr)
        self.effect_cache[expr_id] = effect
        return effect
    
    def analyze_statement(self, stmt: Any) -> EffectInfo:
        """Analyze effects of a statement."""
        if isinstance(stmt, LetStmt):
            return self._analyze_let_stmt(stmt)
        elif isinstance(stmt, AssignStmt):
            return self._analyze_assign_stmt(stmt)
        elif isinstance(stmt, ExprStmt):
            return self.analyze_expression(stmt.expr)
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr:
                return self.analyze_expression(stmt.expr)
            return EffectInfo()  # Empty return is pure
        elif isinstance(stmt, IfStmt):
            return self._analyze_if_stmt(stmt)
        elif isinstance(stmt, WhileStmt):
            return self._analyze_while_stmt(stmt)
        elif isinstance(stmt, MatchStmt):
            return self._analyze_match_stmt(stmt)
        elif isinstance(stmt, UnsafeStmt):
            # Unsafe statements are conservatively treated as impure
            effect = EffectInfo()
            effect.is_pure = False
            effect.effects.add(EffectType.WRITES_MEMORY)
            return effect
        else:
            # Unknown statement type - conservatively impure
            effect = EffectInfo()
            effect.is_pure = False
            effect.effects.add(EffectType.CALLS_FUNCTION)
            return effect
    
    def _analyze_expression_impl(self, expr: Any) -> EffectInfo:
        """Internal expression analysis implementation."""
        if isinstance(expr, (Literal, BoolLit, NilLit)):
            return EffectInfo()  # Literals are pure
        
        elif isinstance(expr, Name):
            effect = EffectInfo()
            effect.depends_on.add(expr.value)
            if expr.value in self.global_variables:
                effect.reads_globals.add(expr.value)
                effect.reads_memory = True
            return effect
        
        elif isinstance(expr, Binary):
            left_effect = self.analyze_expression(expr.left)
            right_effect = self.analyze_expression(expr.right)
            result = left_effect.combine_with(right_effect)
            
            # Check for operations that can trap
            if expr.op in {'/', '%'}:
                result.can_trap = True
                result.effects.add(EffectType.CAN_TRAP)
            
            # Check for overflow/trap based on operation
            if expr.op in {'+', '-', '*', '/', '%'}:
                # In trap mode, arithmetic can trap on overflow
                result.can_trap = True
                result.effects.add(EffectType.CAN_TRAP)
            
            return result
        
        elif isinstance(expr, Unary):
            inner_effect = self.analyze_expression(expr.expr)
            result = EffectInfo()
            result.is_pure = inner_effect.is_pure
            result.depends_on = inner_effect.depends_on.copy()
            result.reads_globals = inner_effect.reads_globals.copy()
            result.reads_memory = inner_effect.reads_memory
            result.can_trap = inner_effect.can_trap
            
            # Dereference operator reads memory
            if expr.op == '*':
                result.reads_memory = True
                result.effects.add(EffectType.READS_MEMORY)
            
            return result
        
        elif isinstance(expr, Call):
            return self._analyze_call_expr(expr)
        
        elif isinstance(expr, IndexExpr):
            obj_effect = self.analyze_expression(expr.obj)
            index_effect = self.analyze_expression(expr.index)
            result = obj_effect.combine_with(index_effect)
            
            # Array access reads memory
            result.reads_memory = True
            result.effects.add(EffectType.READS_MEMORY)
            result.can_trap = True  # Bounds checking
            result.effects.add(EffectType.CAN_TRAP)
            
            return result
        
        elif isinstance(expr, FieldExpr):
            obj_effect = self.analyze_expression(expr.obj)
            result = EffectInfo()
            result.is_pure = obj_effect.is_pure
            result.depends_on = obj_effect.depends_on.copy()
            result.reads_globals = obj_effect.reads_globals.copy()
            result.reads_memory = True  # Field access reads memory
            result.effects.add(EffectType.READS_MEMORY)
            return result
        
        elif isinstance(expr, CastExpr):
            inner_effect = self.analyze_expression(expr.expr)
            result = EffectInfo()
            result.is_pure = inner_effect.is_pure
            result.depends_on = inner_effect.depends_on.copy()
            result.reads_globals = inner_effect.reads_globals.copy()
            result.can_trap = inner_effect.can_trap
            
            # Some casts can trap (e.g., float to int with NaN)
            result.can_trap = True
            result.effects.add(EffectType.CAN_TRAP)
            
            return result
        
        else:
            # Unknown expression type - conservatively impure
            effect = EffectInfo()
            effect.is_pure = False
            effect.effects.add(EffectType.CALLS_FUNCTION)
            return effect
    
    def _analyze_call_expr(self, call: Call) -> EffectInfo:
        """Analyze function call effects."""
        # Analyze arguments first
        arg_effects = []
        for arg in call.args:
            arg_effects.append(self.analyze_expression(arg))
        
        result = EffectInfo()
        if arg_effects:
            result = arg_effects[0]
            for arg_effect in arg_effects[1:]:
                result = result.combine_with(arg_effect)
        
        # Determine function purity
        fn_name = None
        if isinstance(call.fn, Name):
            fn_name = call.fn.value
        elif hasattr(call, 'resolved_name') and call.resolved_name:
            fn_name = call.resolved_name
        
        if fn_name:
            if fn_name in self.pure_functions:
                # Known pure function
                result.is_pure = True
                result.calls_pure_functions = True
            elif fn_name in self.impure_functions:
                # Known impure function
                result.is_pure = False
                result.calls_impure_functions = True
                result.effects.add(EffectType.CALLS_FUNCTION)
                
                # Specific effects for known impure functions
                if fn_name in {'malloc', 'calloc', 'realloc'}:
                    result.allocated_memory = True
                    result.effects.add(EffectType.ALLOCATES_MEMORY)
                elif fn_name == 'free':
                    result.deallocated_memory = True
                    result.effects.add(EffectType.DEALLOCATES_MEMORY)
                elif fn_name in {'print', 'println', 'write'}:
                    result.effects.add(EffectType.HAS_IO)
            else:
                # Unknown function - conservatively impure
                result.is_pure = False
                result.calls_impure_functions = True
                result.effects.add(EffectType.CALLS_FUNCTION)
        else:
            # Complex function expression - conservatively impure
            result.is_pure = False
            result.calls_impure_functions = True
            result.effects.add(EffectType.CALLS_FUNCTION)
        
        return result
    
    def _analyze_let_stmt(self, stmt: LetStmt) -> EffectInfo:
        """Analyze let statement effects."""
        effect = self.analyze_expression(stmt.expr)
        
        # Let statement introduces a new binding
        # This doesn't modify existing state, so it's pure if expr is pure
        return effect
    
    def _analyze_assign_stmt(self, stmt: AssignStmt) -> EffectInfo:
        """Analyze assignment statement effects."""
        expr_effect = self.analyze_expression(stmt.expr)
        target_effect = self._analyze_target_expression(stmt.target)
        
        result = expr_effect.combine_with(target_effect)
        
        # Assignment always writes memory
        result.is_pure = False
        result.writes_memory = True
        result.effects.add(EffectType.WRITES_MEMORY)
        
        # Track what gets modified
        if isinstance(stmt.target, Name):
            result.modifies.add(stmt.target.value)
            if stmt.target.value in self.global_variables:
                result.writes_globals.add(stmt.target.value)
        
        return result
    
    def _analyze_target_expression(self, target: Any) -> EffectInfo:
        """Analyze target expression (LHS of assignment)."""
        if isinstance(target, Name):
            effect = EffectInfo()
            effect.modifies.add(target.value)
            if target.value in self.global_variables:
                effect.writes_globals.add(target.value)
            return effect
        elif isinstance(target, IndexExpr):
            obj_effect = self.analyze_expression(target.obj)
            index_effect = self.analyze_expression(target.index)
            result = obj_effect.combine_with(index_effect)
            result.writes_memory = True
            result.effects.add(EffectType.WRITES_MEMORY)
            result.can_trap = True
            result.effects.add(EffectType.CAN_TRAP)
            return result
        elif isinstance(target, FieldExpr):
            obj_effect = self.analyze_expression(target.obj)
            # Create a new EffectInfo copy instead of mutating the cached obj_effect
            result = EffectInfo()
            result.is_pure = obj_effect.is_pure
            result.writes_memory = True
            result.can_trap = obj_effect.can_trap
            result.effects = obj_effect.effects.copy()
            result.effects.add(EffectType.WRITES_MEMORY)
            result.variables = obj_effect.variables.copy()
            return result
        else:
            # Unknown target type
            effect = EffectInfo()
            effect.is_pure = False
            effect.writes_memory = True
            effect.effects.add(EffectType.WRITES_MEMORY)
            return effect
    
    def _analyze_if_stmt(self, stmt: IfStmt) -> EffectInfo:
        """Analyze if statement effects."""
        cond_effect = self.analyze_expression(stmt.cond)
        
        # Analyze both branches
        then_effect = self._analyze_statement_list(stmt.then_body)
        else_effect = self._analyze_statement_list(stmt.else_body)
        
        # Combine all effects
        result = cond_effect.combine_with(then_effect)
        result = result.combine_with(else_effect)
        
        return result
    
    def _analyze_while_stmt(self, stmt: WhileStmt) -> EffectInfo:
        """Analyze while statement effects."""
        cond_effect = self.analyze_expression(stmt.cond)
        body_effect = self._analyze_statement_list(stmt.body)
        
        # Loop may execute multiple times, but that doesn't change effects
        result = cond_effect.combine_with(body_effect)
        
        return result
    
    def _analyze_match_stmt(self, stmt: MatchStmt) -> EffectInfo:
        """Analyze match statement effects."""
        expr_effect = self.analyze_expression(stmt.expr)
        
        # Analyze all arms
        arm_effects = []
        for pattern, arm_body in stmt.arms:
            arm_effect = self._analyze_statement_list(arm_body)
            arm_effects.append(arm_effect)
        
        result = expr_effect
        for arm_effect in arm_effects:
            result = result.combine_with(arm_effect)
        
        return result
    
    def _analyze_statement_list(self, stmts: List[Any]) -> EffectInfo:
        """Analyze effects of a statement list."""
        if not stmts:
            return EffectInfo()
        
        result = self.analyze_statement(stmts[0])
        for stmt in stmts[1:]:
            result = result.combine_with(self.analyze_statement(stmt))
        
        return result
    
    def is_expression_pure(self, expr: Any) -> bool:
        """Quick check if expression is pure."""
        return self.analyze_expression(expr).is_pure
    
    def is_statement_pure(self, stmt: Any) -> bool:
        """Quick check if statement is pure."""
        return self.analyze_statement(stmt).is_pure
    
    def can_safely_reorder(self, expr1: Any, expr2: Any) -> bool:
        """Check if two expressions can be safely reordered."""
        effect1 = self.analyze_expression(expr1)
        effect2 = self.analyze_expression(expr2)
        
        # Can always reorder pure expressions.
        if effect1.is_pure and effect2.is_pure:
            return True
        
        # Reordering becomes unsafe as soon as one side can perform observable
        # effects beyond reads.
        if effect1.calls_impure_functions or effect2.calls_impure_functions:
            return False
        if effect1.can_trap or effect2.can_trap:
            return False
        if EffectType.HAS_IO in effect1.effects or EffectType.HAS_IO in effect2.effects:
            return False
        if effect1.writes_globals or effect2.writes_globals:
            return False
        if effect1.writes_memory or effect2.writes_memory:
            return False
        
        # Read-only, non-trapping expressions can be reordered.
        return True
    
    def can_eliminate_expression(self, expr: Any) -> bool:
        """Check if expression can be safely eliminated (dead code)."""
        effect = self.analyze_expression(expr)
        
        # Can eliminate pure expressions
        if effect.is_pure:
            return True
        
        # Only eliminate expressions with truly no effects (not just CAN_TRAP)
        if not effect.effects:
            return True
        
        # Do NOT treat {EffectType.CAN_TRAP} as removable
        return False
    
    def add_global_variable(self, var_name: str) -> None:
        """Add a global variable to track."""
        self.global_variables.add(var_name)
    
    def add_pure_function(self, fn_name: str) -> None:
        """Add a pure function to the known set."""
        self.pure_functions.add(fn_name)
    
    def add_impure_function(self, fn_name: str) -> None:
        """Add an impure function to the known set."""
        self.impure_functions.add(fn_name)
    
    def clear_cache(self) -> None:
        """Clear the effect analysis cache."""
        self.effect_cache.clear()


def create_effect_analyzer() -> EffectAnalyzer:
    """Create a configured effect analyzer."""
    analyzer = EffectAnalyzer()
    
    # Add ASTRA-specific pure functions
    analyzer.add_pure_function('len')
    analyzer.add_pure_function('capacity')
    analyzer.add_pure_function('size')
    analyzer.add_pure_function('empty')
    analyzer.add_pure_function('some')
    analyzer.add_pure_function('none')
    analyzer.add_pure_function('ok')
    analyzer.add_pure_function('err')
    
    # Add ASTRA-specific impure functions
    analyzer.add_impure_function('print')
    analyzer.add_impure_function('println')
    analyzer.add_impure_function('panic')
    analyzer.add_impure_function('exit')
    analyzer.add_impure_function('abort')
    
    return analyzer
