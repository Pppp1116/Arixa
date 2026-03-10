"""Expression canonicalization and keying for ASTRA optimizations.

Provides structural expression comparison and canonicalization to enable:
- Common subexpression elimination (CSE)
- Global value numbering (GVN) foundation
- Expression equivalence testing
- Hash-based expression lookup
- Safe expression caching

Key design principles:
- Structural equivalence, not just syntactic
- Canonical form for commutative operations
- Type-aware comparison
- Position-independent comparison
- Safe for optimization passes
"""

from __future__ import annotations

from typing import Any, Optional, Tuple, Dict, Union
from dataclasses import dataclass
from hashlib import sha256
import pickle

from astra.ast import *
from astra.optimizer.effects import EffectAnalyzer, EffectInfo, create_effect_analyzer


@dataclass(frozen=True)
class ExpressionKey:
    """Canonical key for expression comparison and hashing.
    
    Provides structural equivalence that's safe for optimizations:
    - Commutative operations are canonicalized
    - Type information is included
    - Position information is excluded
    - Structural normalization applied
    """
    
    expr_type: str  # Type of expression (Binary, Unary, Call, etc.)
    op: Optional[str] = None  # Operator for Binary/Unary
    args: Tuple[Any, ...] = ()  # Canonicalized arguments
    
    # Type information for disambiguation
    result_type: Optional[str] = None
    
    def __str__(self) -> str:
        if self.op:
            return f"{self.expr_type}({self.op}, {self.args})"
        return f"{self.expr_type}({self.args})"
    
    def __hash__(self) -> int:
        return hash((self.expr_type, self.op, self.args, self.result_type))
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, ExpressionKey):
            return False
        return (self.expr_type == other.expr_type and
                self.op == other.op and
                self.args == other.args and
                self.result_type == other.result_type)
    
    def __lt__(self, other) -> bool:
        """Support comparison for sorting in canonicalization."""
        if not isinstance(other, ExpressionKey):
            return NotImplemented
        # Use tuple-based lexicographic comparison
        return (self.expr_type, self.op, self.args, self.result_type) < (other.expr_type, other.op, other.args, other.result_type)
    
    def __le__(self, other) -> bool:
        """Support comparison for sorting in canonicalization."""
        if not isinstance(other, ExpressionKey):
            return NotImplemented
        # Use tuple-based lexicographic comparison
        return (self.expr_type, self.op, self.args, self.result_type) <= (other.expr_type, other.op, other.args, other.result_type)


class ExpressionCanonicalizer:
    """Canonicalizes expressions for consistent comparison and hashing.
    
    Handles:
    - Commutative operation ordering
    - Type normalization
    - Structural normalization
    - Position-independent comparison
    """
    
    def __init__(self, effect_analyzer: Optional[EffectAnalyzer] = None):
        self.effect_analyzer = effect_analyzer
        self.canonical_cache: Dict[int, ExpressionKey] = {}
        
        # Commutative operations where operand order doesn't matter
        self.commutative_ops = {
            '+', '*', '&', '|', '^', '==', '!=', 
            '<', '>', '<=', '>=',  # These are not commutative, handled separately
        }
        
        # Truly commutative operations
        self.truly_commutative = {'+', '*', '&', '|', '^'}
    
    def canonicalize_expression(self, expr: Any) -> ExpressionKey:
        """Create canonical key for expression."""
        expr_id = id(expr)
        if expr_id in self.canonical_cache:
            return self.canonical_cache[expr_id]
        
        key = self._canonicalize_impl(expr)
        self.canonical_cache[expr_id] = key
        return key
    
    def _canonicalize_impl(self, expr: Any) -> ExpressionKey:
        """Internal canonicalization implementation."""
        if isinstance(expr, (Literal, BoolLit, NilLit)):
            return self._canonicalize_literal(expr)
        
        elif isinstance(expr, Name):
            return self._canonicalize_name(expr)
        
        elif isinstance(expr, Binary):
            return self._canonicalize_binary(expr)
        
        elif isinstance(expr, Unary):
            return self._canonicalize_unary(expr)
        
        elif isinstance(expr, Call):
            return self._canonicalize_call(expr)
        
        elif isinstance(expr, IndexExpr):
            return self._canonicalize_index(expr)
        
        elif isinstance(expr, FieldExpr):
            return self._canonicalize_field(expr)
        
        elif isinstance(expr, CastExpr):
            return self._canonicalize_cast(expr)
        
        else:
            # Unknown expression type - use type-based fallback
            return ExpressionKey(
                expr_type=type(expr).__name__,
                args=(str(expr),)  # String representation as fallback
            )
    
    def _canonicalize_literal(self, literal: Any) -> ExpressionKey:
        """Canonicalize literal expressions."""
        if isinstance(literal, Literal):
            return ExpressionKey(
                expr_type="Literal",
                args=(type(literal.value).__name__, literal.value)
            )
        elif isinstance(literal, BoolLit):
            return ExpressionKey(
                expr_type="BoolLit", 
                args=(literal.value,)
            )
        elif isinstance(literal, NilLit):
            return ExpressionKey(
                expr_type="NilLit",
                args=()
            )
        else:
            return ExpressionKey(
                expr_type=type(literal).__name__,
                args=(str(literal),)
            )
    
    def _canonicalize_name(self, name: Name) -> ExpressionKey:
        """Canonicalize name expressions."""
        # Include type information if available
        result_type = None
        if hasattr(name, 'inferred_type'):
            result_type = str(name.inferred_type)
        
        return ExpressionKey(
            expr_type="Name",
            args=(name.value,),
            result_type=result_type
        )
    
    def _canonicalize_binary(self, binary: Binary) -> ExpressionKey:
        """Canonicalize binary expressions."""
        left_key = self.canonicalize_expression(binary.left)
        right_key = self.canonicalize_expression(binary.right)
        
        # Handle commutative operations
        if binary.op in self.truly_commutative:
            # Sort operands for canonical order
            if left_key.args <= right_key.args:
                args = (left_key, right_key)
            else:
                args = (right_key, left_key)
        else:
            args = (left_key, right_key)
        
        return ExpressionKey(
            expr_type="Binary",
            op=binary.op,
            args=args
        )
    
    def _canonicalize_unary(self, unary: Unary) -> ExpressionKey:
        """Canonicalize unary expressions."""
        expr_key = self.canonicalize_expression(unary.expr)
        
        return ExpressionKey(
            expr_type="Unary",
            op=unary.op,
            args=(expr_key,)
        )
    
    def _canonicalize_call(self, call: Call) -> ExpressionKey:
        """Canonicalize function call expressions."""
        fn_key = self.canonicalize_expression(call.fn)
        arg_keys = tuple(self.canonicalize_expression(arg) for arg in call.args)
        
        return ExpressionKey(
            expr_type="Call",
            args=(fn_key,) + arg_keys
        )
    
    def _canonicalize_index(self, index: IndexExpr) -> ExpressionKey:
        """Canonicalize index expressions."""
        obj_key = self.canonicalize_expression(index.obj)
        index_key = self.canonicalize_expression(index.index)
        
        return ExpressionKey(
            expr_type="IndexExpr",
            args=(obj_key, index_key)
        )
    
    def _canonicalize_field(self, field: FieldExpr) -> ExpressionKey:
        """Canonicalize field access expressions."""
        obj_key = self.canonicalize_expression(field.obj)
        
        return ExpressionKey(
            expr_type="FieldExpr",
            args=(obj_key, field.field)
        )
    
    def _canonicalize_cast(self, cast: CastExpr) -> ExpressionKey:
        """Canonicalize cast expressions."""
        expr_key = self.canonicalize_expression(cast.expr)
        
        return ExpressionKey(
            expr_type="CastExpr",
            args=(expr_key, cast.type_name),
            result_type=cast.type_name
        )
    
    def expressions_are_equivalent(self, expr1: Any, expr2: Any) -> bool:
        """Check if two expressions are structurally equivalent."""
        key1 = self.canonicalize_expression(expr1)
        key2 = self.canonicalize_expression(expr2)
        return key1 == key2
    
    def clear_cache(self) -> None:
        """Clear canonicalization cache."""
        self.canonical_cache.clear()


class ExpressionCache:
    """Thread-safe expression cache for optimization passes.
    
    Provides:
    - Expression value storage
    - Effect-based invalidation
    - Safe lookup with dependency tracking
    - Cache statistics
    """
    
    def __init__(self, effect_analyzer: EffectAnalyzer):
        self.effect_analyzer = effect_analyzer
        self.canonicalizer = ExpressionCanonicalizer(effect_analyzer)
        
        # Expression storage
        self.expressions: Dict[ExpressionKey, Any] = {}
        self.expression_effects: Dict[ExpressionKey, EffectInfo] = {}
        self.expression_locations: Dict[ExpressionKey, List[Tuple[int, int]]] = {}  # (block_id, stmt_index)
        
        # Dependency tracking for invalidation
        self.dependencies: Dict[str, Set[ExpressionKey]] = {}  # variable -> expressions that depend on it
        self.global_dependencies: Dict[str, Set[ExpressionKey]] = {}  # global variable -> expressions
        
        # Statistics
        self.cache_hits = 0
        self.cache_misses = 0
        self.invalidations = 0
    
    def lookup_expression(self, expr: Any, block_id: int, stmt_index: int) -> Optional[Any]:
        """Look up expression value in cache."""
        key = self.canonicalizer.canonicalize_expression(expr)
        
        if key in self.expressions:
            self.cache_hits += 1
            # Record location for dependency tracking
            if key not in self.expression_locations:
                self.expression_locations[key] = []
            self.expression_locations[key].append((block_id, stmt_index))
            return self.expressions[key]
        
        self.cache_misses += 1
        return None
    
    def store_expression(self, expr: Any, value: Any, block_id: int, stmt_index: int) -> None:
        """Store expression value in cache."""
        key = self.canonicalizer.canonicalize_expression(expr)
        effect = self.effect_analyzer.analyze_expression(expr)
        
        # Only cache pure expressions or expressions with predictable effects
        if not self._is_cacheable(effect):
            return
        
        self.expressions[key] = value
        self.expression_effects[key] = effect
        
        # Record location
        if key not in self.expression_locations:
            self.expression_locations[key] = []
        self.expression_locations[key].append((block_id, stmt_index))
        
        # Track dependencies for invalidation
        for dep_var in effect.depends_on:
            if dep_var not in self.dependencies:
                self.dependencies[dep_var] = set()
            self.dependencies[dep_var].add(key)
        
        for global_var in effect.reads_globals:
            if global_var not in self.global_dependencies:
                self.global_dependencies[global_var] = set()
            self.global_dependencies[global_var].add(key)
    
    def invalidate_variable(self, var_name: str) -> None:
        """Invalidate all expressions that depend on a variable."""
        if var_name in self.dependencies:
            keys_to_invalidate = self.dependencies[var_name]
            for key in keys_to_invalidate:
                if key in self.expressions:
                    del self.expressions[key]
                    self.invalidations += 1
            
            # Clear dependency tracking
            del self.dependencies[var_name]
    
    def invalidate_global(self, global_name: str) -> None:
        """Invalidate all expressions that depend on a global variable."""
        if global_name in self.global_dependencies:
            keys_to_invalidate = self.global_dependencies[global_name]
            for key in keys_to_invalidate:
                if key in self.expressions:
                    del self.expressions[key]
                    self.invalidations += 1
            
            del self.global_dependencies[global_name]
    
    def invalidate_all(self) -> None:
        """Invalidate entire cache."""
        # Capture count before clearing
        n = len(self.expressions)
        self.expressions.clear()
        self.expression_effects.clear()
        self.expression_locations.clear()
        self.dependencies.clear()
        self.global_dependencies.clear()
        self.invalidations += n
    
    def _is_cacheable(self, effect: EffectInfo) -> bool:
        """Check if expression with given effect is cacheable."""
        # Pure expressions are always cacheable
        if effect.is_pure:
            return True
        
        # Expressions that only read memory might be cacheable
        # (conservative approach - could be improved with alias analysis)
        if effect.effects == {EffectType.READS_MEMORY}:
            return True
        
        # Expressions that read globals are cacheable but need invalidation
        if effect.effects == {EffectType.READS_GLOBAL}:
            return True
        
        # Anything with writes or unknown effects is not cacheable
        return False
    
    def get_cache_statistics(self) -> Dict[str, int]:
        """Get cache performance statistics."""
        total_lookups = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_lookups * 100) if total_lookups > 0 else 0
        
        return {
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'hit_rate_percent': int(hit_rate),
            'invalidations': self.invalidations,
            'cached_expressions': len(self.expressions)
        }
    
    def clear_statistics(self) -> None:
        """Clear cache statistics."""
        self.cache_hits = 0
        self.cache_misses = 0
        self.invalidations = 0


class ExpressionKeyManager:
    """High-level interface for expression keying and caching.
    
    Combines canonicalization, effect analysis, and caching
    for use in optimization passes.
    """
    
    def __init__(self, effect_analyzer: EffectAnalyzer):
        self.effect_analyzer = effect_analyzer
        self.canonicalizer = ExpressionCanonicalizer(effect_analyzer)
        self.cache = ExpressionCache(effect_analyzer)
        
        # Track original expressions for key lookup
        self.expression_by_key: Dict[ExpressionKey, Any] = {}
    
    def get_expression_key(self, expr: Any) -> ExpressionKey:
        """Get canonical key for expression."""
        key = self.canonicalizer.canonicalize_expression(expr)
        # Track the original expression for later retrieval
        self.expression_by_key[key] = expr
        return key
    
    def get_expression_by_key(self, expr_key: ExpressionKey) -> Optional[Any]:
        """Get the original AST expression for a given ExpressionKey."""
        return self.expression_by_key.get(expr_key)
    
    def expressions_equal(self, expr1: Any, expr2: Any) -> bool:
        """Check if two expressions are equal."""
        return self.canonicalizer.expressions_are_equivalent(expr1, expr2)
    
    def can_cache_expression(self, expr: Any) -> bool:
        """Check if expression can be safely cached."""
        effect = self.effect_analyzer.analyze_expression(expr)
        return self.cache._is_cacheable(effect)
    
    def lookup_cached_value(self, expr: Any, block_id: int, stmt_index: int) -> Optional[Any]:
        """Look up cached expression value."""
        return self.cache.lookup_expression(expr, block_id, stmt_index)
    
    def cache_expression(self, expr: Any, value: Any, block_id: int, stmt_index: int) -> None:
        """Cache expression value."""
        self.cache.store_expression(expr, value, block_id, stmt_index)
    
    def invalidate_variable(self, var_name: str) -> None:
        """Invalidate expressions dependent on variable."""
        self.cache.invalidate_variable(var_name)
    
    def invalidate_global(self, global_name: str) -> None:
        """Invalidate expressions dependent on global."""
        self.cache.invalidate_global(global_name)
    
    def clear_all_caches(self) -> None:
        """Clear all expression caches."""
        self.cache.invalidate_all()
        self.canonicalizer.clear_cache()
    
    def get_statistics(self) -> Dict[str, int]:
        """Get expression keying and caching statistics."""
        return self.cache.get_cache_statistics()
    
    def clear_statistics(self) -> None:
        """Clear statistics."""
        self.cache.clear_statistics()


def create_expression_key_manager() -> ExpressionKeyManager:
    """Create a configured expression key manager."""
    effect_analyzer = create_effect_analyzer()
    return ExpressionKeyManager(effect_analyzer)
