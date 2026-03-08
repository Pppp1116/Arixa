# ASTRA Optimizer Implementation Plan

## Executive Summary

This document outlines the complete redesign of the ASTRA compiler optimizer from a collection of local AST rewrites into a genuinely correct optimization pipeline built on solid compiler infrastructure.

## Current State Analysis

### Existing Optimizer Problems

The current optimizer (`astra/optimizer/optimizer.py`) suffers from fundamental issues:

1. **Fake Advanced Optimizations**: 
   - "Global Value Numbering" without real CFG/SSA
   - "Partial Redundancy Elimination" without dataflow analysis  
   - "Induction Variable Optimization" without loop analysis
   - "Tail Call Optimization" without backend support

2. **No Real Infrastructure**:
   - No Control Flow Graph (CFG) construction
   - No basic block model
   - No dominance analysis
   - No proper effect analysis
   - No expression canonicalization
   - No sound change tracking

3. **Safety Issues**:
   - No guarantee of evaluation order preservation
   - No side-effect safety analysis
   - No overflow semantics awareness
   - No alias/mutation analysis

### Language Semantics Requirements

ASTRA has specific semantics that must be respected:

- **Evaluation Order**: Strict left-to-right evaluation
- **Side Effects**: Function calls and assignments have effects
- **Overflow Behavior**: Configurable trap vs wrap semantics
- **Memory Model**: Pointers, references, and arrays
- **Control Flow**: if, while, match with proper semantics
- **Type System**: Strong typing with inference

## Implementation Strategy

### Stage 1: Foundation Infrastructure

#### 1.1 Control Flow Graph (CFG)
**File**: `astra/optimizer/cfg.py`

**Purpose**: Real CFG construction for sound optimizations

**Key Features**:
- Basic block identification with terminator analysis
- Predecessor/successor relationship tracking
- Natural loop detection via back edges
- Dominance tree computation
- Reverse post-order traversal
- CFG validation and invariants

**Correctness Guarantees**:
- All control flow paths preserved
- Exact block boundaries
- Proper loop nesting
- Sound dominance relationships

#### 1.2 Effect Analysis
**File**: `astra/optimizer/effects.py`

**Purpose**: Sound side-effect and purity analysis

**Key Features**:
- Expression effect classification (pure/impure)
- Memory access analysis (read/write)
- Function call effect modeling
- Global variable dependency tracking
- Safe reordering analysis
- Effect combination for complex expressions

**Correctness Guarantees**:
- Conservative impurity assumptions
- No effect underestimation
- Safe expression reordering
- Proper dependency tracking

#### 1.3 Expression Canonicalization
**File**: `astra/optimizer/expressions.py`

**Purpose**: Structural expression comparison and caching

**Key Features**:
- Commutative operation canonicalization
- Type-aware expression keys
- Effect-safe expression caching
- Dependency-based invalidation
- Structural equivalence testing

**Correctness Guarantees**:
- Canonical forms for equivalent expressions
- Type-sensitive comparison
- Safe cache invalidation
- Position-independent comparison

#### 1.4 Pass Manager
**File**: `astra/optimizer/pass_manager.py`

**Purpose**: Robust optimization pipeline orchestration

**Key Features**:
- Fixed-point iteration with convergence detection
- Precise change tracking at multiple granularities
- Pass dependency management
- Comprehensive statistics collection
- Error handling and recovery

**Correctness Guarantees**:
- Termination (max iteration limits)
- Sound convergence detection
- Proper invalidation on changes
- Complete change tracking

### Stage 2: Safe Mid-Level Optimizations

#### 2.1 Enhanced Dead Code Elimination
**File**: `astra/optimizer/safe_optimizations.py`

**Approach**: CFG-aware DCE with effect safety

**Key Features**:
- Unreachable block elimination using CFG reachability
- Effect-aware dead statement removal
- Control flow preservation
- Variable usage analysis

**Safety Conditions**:
- Only eliminates pure statements
- Requires both `pure && non_trapping` (or equivalent speculatable predicate) for elimination/substitution
- Preserves all side effects
- Maintains control flow structure
- Respects evaluation order
- Expressions that are pure but may trap (divide-by-zero, overflow-checked ops, bounds-checked loads) are not removed or duplicated

#### 2.2 Local Value Numbering (LVN)
**File**: `astra/optimizer/safe_optimizations.py`

**Approach**: Block-local value numbering with real expression keys

**Key Features**:
- Structural expression equivalence
- Effect-based invalidation
- Block-local availability analysis
- Safe expression substitution with non_trapping checks

**Safety Conditions**:
- Only substitutes pure expressions that are also non_trapping/speculatable
- Uses distinct `non_trapping` predicate separate from `pure`
- Respects variable mutations
- Maintains block boundaries
- Preserves evaluation order
- LVN substitution check requires both purity and non-trapping properties

#### 2.3 Constant Propagation
**File**: `astra/optimizer/safe_optimizations.py`

**Approach**: Dataflow-based constant propagation with CFG

**Key Features**:
- Inter-block constant flow analysis
- Effect-aware constant invalidation
- Safe constant folding with non_trapping verification
- Control-flow-sensitive propagation

**Safety Conditions**:
- Only propagates pure constants that are non_trapping
- Respects memory effects
- Handles control flow correctly
- Preserves overflow semantics
- Constant folding/propagation guards check both pure && non_trapping before applying

#### 2.4 Dead Branch Elimination
**File**: `astra/optimizer/safe_optimizations.py`

**Approach**: CFG-based dead branch removal

**Key Features**:
- Constant condition evaluation
- Unreachable path elimination
- CFG structure simplification
- Control flow optimization

**Safety Conditions**:
- Only removes provably dead branches
- Preserves all possible executions
- Maintains loop structure
- Respects condition effects

### Stage 3: Advanced Optimizations

#### 3.1 Loop-Invariant Code Motion (LICM)
**File**: `astra/optimizer/advanced_optimizations.py`

**Approach**: Real loop analysis with pre-header insertion

**Key Features**:
- Natural loop detection from CFG
- Pre-header block creation
- Invariant expression analysis
- Safe code motion to pre-headers with execution guards

**Safety Conditions**:
- Only moves pure expressions
- Preserves loop semantics
- Handles nested loops correctly
- Maintains evaluation order
- Requires execution guard or proof of safe speculation when hoisting into pre-header
- Each invariant must either (a) be proven to execute on every original path or (b) be proven side-effect-free and safe to speculate
- Guards composed for nested/nondeterministic control-flow
- Uses dominance/predecessor checks for safe hoisting

#### 3.2 Global Value Numbering (GVN)
**File**: `astra/optimizer/advanced_optimizations.py`

**Approach**: Real dataflow-based GVN with proper availability

**Key Features**:
- Cross-block value numbering
- Dataflow convergence analysis
- Redundancy elimination
- Proper availability handling

**Safety Conditions**:
- Sound availability analysis
- Respects control flow
- Handles block merging correctly
- Preserves expression effects

#### 3.3 Strength Reduction
**File**: `astra/optimizer/advanced_optimizations.py`

**Approach**: Overflow-aware strength reduction

**Key Features**:
- Power-of-2 multiplication → bit shifts
- Small constant multiplication → repeated addition
- Overflow semantics awareness
- Overflow-mode gating (only when overflow mode is wrap/defined-as-non-trapping)

**Safety Conditions**:
- Respects overflow mode configuration
- Only enabled when overflow mode is set to wrap/defined-as-non-trapping
- Preserves exact semantics
- Handles edge cases correctly

## Disabled Optimizations

The following optimizations remain **DISABLED** because they cannot be implemented safely with the current infrastructure:

### Partial Redundancy Elimination (PRE)
**Status**: DISABLED
**Reason**: Requires full anticipatability/availability analysis and safe insertion point computation
**Missing Infrastructure**: Complete dataflow framework, insertion safety analysis

### Tail Call Optimization
**Status**: DISABLED  
**Reason**: Backend doesn't support proper frame reuse and ABI handling
**Missing Infrastructure**: Backend cooperation, frame layout analysis

### Vectorization
**Status**: DISABLED
**Reason**: No SIMD backend support and no proper vector type analysis
**Missing Infrastructure**: Target-specific codegen, vector type system

### SSA Construction
**Status**: NOT IMPLEMENTED
**Reason**: Complex and not needed for current optimization goals
**Alternative**: CFG + dataflow analysis provides sufficient foundation

### Loop Unrolling
**Status**: DISABLED
**Reason**: Requires trip count analysis and safe code duplication
**Missing Infrastructure**: Precise loop analysis, safe cloning

## Integration Strategy

### Backward Compatibility
- Existing optimizer interface preserved
- Gradual migration path
- Feature flags for new optimizations
- Fallback to old optimizer for compatibility

### Configuration
- Profile-based optimization levels (debug/release)
- Overflow mode configuration (trap/wrap)
- Individual pass enable/disable
- Statistics and debugging support

### Testing Strategy
- Unit tests for each infrastructure component
- Integration tests for optimization pipelines
- Correctness tests for language semantics
- Performance benchmarks for optimization impact

## Implementation Timeline

### Phase 1: Foundation (Weeks 1-2)
- CFG construction and validation
- Effect analysis implementation
- Expression canonicalization
- Pass manager framework
- Comprehensive test suite

### Phase 2: Safe Optimizations (Weeks 3-4)
- Enhanced DCE implementation
- Local value numbering
- Constant propagation
- Dead branch elimination
- Integration testing

### Phase 3: Advanced Optimizations (Weeks 5-6)
- Loop-invariant code motion
- Global value numbering
- Strength reduction
- Performance testing
- Documentation

### Phase 4: Integration (Weeks 7-8)
- Pipeline integration
- Backward compatibility
- Performance benchmarking
- Final testing and validation

## Success Criteria

### Correctness
- All optimizations preserve program semantics
- No regressions in existing functionality
- All tests pass with new optimizer
- Sound overflow and effect handling

### Performance
- Measurable improvement in generated code quality
- Reasonable compilation time overhead
- Effective optimization at different levels
- Scalable to large programs

### Maintainability
- Clear separation of concerns
- Well-documented infrastructure
- Extensible optimization framework
- Comprehensive test coverage

## Risks and Mitigations

### Risk: CFG Construction Complexity
**Mitigation**: Incremental implementation with extensive testing
**Fallback**: Simplified CFG for initial implementation

### Risk: Effect Analysis Conservatism
**Mitigation**: Calibrated impurity assumptions with real-world testing
**Fallback**: More conservative analysis if optimization impact is low

### Risk: Performance Overhead
**Mitigation**: Efficient data structures and caching strategies
**Fallback**: Profile-guided optimization pass selection

### Risk: Integration Complexity
**Mitigation**: Gradual migration with compatibility layers
**Fallback**: Parallel optimizer implementation during transition

## Conclusion

This implementation plan transforms the ASTRA optimizer from a collection of unsafe local rewrites into a genuinely correct optimization pipeline built on solid compiler infrastructure. The phased approach ensures correctness at each stage while providing measurable improvements in code quality and maintainability.

The key insight is that **sound infrastructure enables sound optimizations**. By investing in proper CFG construction, effect analysis, and expression canonicalization, we create a foundation where advanced optimizations can be implemented safely and effectively.

This approach prioritizes correctness over aggression, ensuring that the optimizer never breaks program semantics while still providing significant optimization benefits.
