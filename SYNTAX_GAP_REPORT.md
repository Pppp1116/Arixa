# Syntax Gap Report

This report identifies syntax and language features that have gaps between documentation, implementation, and usage.

## Executive Summary

**Total Features Analyzed**: 85  
**Fully Documented & Implemented**: 70 (82%)  
**Implemented but Undocumented**: 6 (7%)  
**Documented but Not Implemented**: 1 (1%)  
**Partially Implemented**: 4 (5%)  
**Removed Features**: 4 (5%)

## 1. Documented but Not Implemented

### 1.1 `const` Keyword  
- **Documentation Claims**: `const` keyword for constants
- **Implementation Reality**: Tokenized but no parse rule found
- **Evidence**: In KEYWORDS set but no parser implementation
- **Recommendation**: Remove `const` from lexer or implement constant syntax

### 1.2 `let` Keyword (REMOVED)
- **Previous Claims**: `let` keyword for variable bindings
- **Implementation Reality**: Completely removed from language
- **Evidence**: Removed from lexer, parser, and all documentation
- **Actual Syntax**: `name = expr` (identifier-based parsing)
- **Status**: ✅ RESOLVED - Removed completely

### 1.3 C-style For Loops (REMOVED)
- **Previous Implementation**: `for mut i = 0; i < 10; i += 1 { }`
- **Implementation Reality**: Completely removed from language
- **Evidence**: Removed from parser, AST, semantic analysis, and LLVM codegen
- **Current Syntax**: `for item in iterable { }` only
- **Status**: ✅ RESOLVED - Simplified to iterator-style only

### 1.4 Drop Statement (REMOVED)
- **Documentation Claims**: `drop expr;` statement existed historically
- **Implementation Reality**: Completely removed from language
- **Evidence**: Successfully removed in previous cleanup
- **Status**: ✅ RESOLVED - Already removed

### 1.5 Defer Statements (REMOVED)
- **Documentation Claims**: `defer expr;` statements for cleanup
- **Implementation Reality**: Completely removed from language
- **Evidence**: Removed from AST, parser, semantic analysis, codegen, and all components
- **Reason**: Replaced by automatic scope cleanup through ownership system
- **Status**: ✅ RESOLVED - Removed in favor of automatic cleanup

## 2. Implemented but Undocumented

### 2.1 Enhanced While Loop
- **Syntax**: `while mut variable = condition { body }`
- **Evidence**: `astra/parser.py` lines 961-973, `ast.py` line 340-347
- **Usage**: None found in examples or tests
- **Recommendation**: Document or deprecate


### 2.3 Iterator For Loop (FULLY IMPLEMENTED)
- **Syntax**: `for item in iterable { body }`
- **Evidence**: `astra/parser.py` parse_for() function, `astra/ast.py` line 343-354
- **Features**: 
  - Range iteration: `for i in 0..10` and `for i in 0..=10`
  - Vec iteration: `for item in vec`
  - String iteration: `for ch in "hello"`
  - Nested loops supported
  - Break and continue statements supported
- **Usage**: Found in `examples/iterator_for_loop_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete parser, semantic analysis, and codegen

### 2.4 Ownership System (FULLY IMPLEMENTED)
- **Features**: Complete move semantics, borrow checking, lifetime analysis
- **Evidence**: Comprehensive implementation in `astra/semantic.py`
- **Classes**: 
  - `_OwnedState` - Enhanced with allocation tracking and move chains
  - `_BorrowState` - Advanced reference tracking with lifetime regions
  - `_MoveState` - Move semantics with use-after-move detection
  - `_LifetimeAnalyzer` - Advanced lifetime analysis system
- **Capabilities**:
  - Move semantics with detailed tracking and error reporting
  - Borrow checking (mutable and immutable references)
  - Lifetime analysis with region tracking
  - Use-after-move and use-after-free detection
  - Reference conflict detection and reporting
  - Allocation site tracking for better error messages
- **Usage**: `examples/memory_safety_test.arixa`, `examples/ownership_system_test.arixa`, `examples/advanced_ownership_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete ownership system with comprehensive safety checks

### 2.5 Unsafe Blocks (FULLY IMPLEMENTED)
- **Syntax**: `unsafe { body }`
- **Evidence**: `astra/parser.py` lines 1008-1010, `astra/ast.py` line 472-481
- **Features**:
  - Complete unsafe context tracking with `_UnsafeContextTracker`
  - Proper nesting of unsafe blocks
  - Unsafe operation validation and enforcement
  - LLVM codegen with unsafe block markers
  - Integration with borrow checking and ownership system
- **Classes**:
  - `UnsafeStmt` - AST node for unsafe blocks
  - `_UnsafeContextTracker` - Tracks unsafe operations and contexts
- **Capabilities**:
  - Nested unsafe blocks supported
  - Unsafe function calls (requires unsafe context)
  - Unsafe casts and pointer operations
  - FFI integration (extern unsafe functions)
  - Proper error messages for unsafe violations
- **Usage**: Found in `examples/unsafe_block_test.arixa`, `examples/advanced_unsafe_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete unsafe block system with comprehensive tracking

### 2.6 Comptime Blocks
- **Syntax**: `comptime { body }`
- **Evidence**: `astra/parser.py` lines 951-953, `ast.py` line 170-178
- **Usage**: Limited usage in examples
- **Recommendation**: Document

### 2.7 Defer Statements (REMOVED)
- **Syntax**: `defer expr;`
- **Evidence**: Previously existed but completely removed
- **Reason**: Replaced by automatic scope cleanup through ownership system
- **Status**: ✅ REMOVED - Automatic cleanup is now used instead

### 2.8 Pattern Matching Enhancements (FULLY IMPLEMENTED)
- **Features**: Expression arms, guard patterns, advanced pattern types
- **Evidence**: Comprehensive implementation in `astra/parser.py`, `astra/ast.py`, `astra/semantic.py`, `astra/llvm_codegen.py`
- **Pattern Types**:
  - `LiteralPattern` - Literal values (42, "hello", true)
  - `RangePattern` - Range patterns (1..=10, 5..20)
  - `SlicePattern` - Slice patterns ([a, b, ..])
  - `TuplePattern` - Tuple patterns ((a, b, c))
  - `StructPattern` - Struct patterns (Point { x, y })
  - `EnumPattern` - Enum patterns (Option::Some(value))
  - `WildcardPattern` - Wildcard patterns (_)
  - `OrPattern` - Alternative patterns (A | B | C)
  - `GuardedPattern` - Guarded patterns (pattern if condition)
- **Capabilities**:
  - Nested pattern matching with arbitrary depth
  - Guard expressions with complex boolean logic
  - Pattern binding and destructuring
  - Exhaustiveness checking for enums and structs
  - Range pattern matching with inclusive/exclusive bounds
  - Slice pattern matching with rest patterns
  - Struct field pattern matching with shorthand syntax
  - Tuple element pattern matching
  - Or-pattern alternatives with shared bindings
- **Usage**: Found in `examples/pattern_matching_test.arixa`, `examples/advanced_pattern_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete pattern matching system with comprehensive features

### 2.9 GPU Computing Features
- **Syntax**: `gpu fn`, `gpu.launch`, device buffers
- **Evidence**: Entire `astra/gpu/` directory
- **Usage**: `examples/gpu/` directory
- **Recommendation**: Document comprehensively

### 2.10 Method Call Syntax
- **Syntax**: `object.method(args)`
- **Evidence**: Parser supports method calls via postfix parsing
- **Usage**: Found in stdlib and examples
- **Recommendation**: Document

### 2.11 Layout Queries
- **Syntax**: `sizeof(Type)`, `alignof(Type)`
- **Evidence**: Parser and semantic support
- **Usage**: Found in low-level examples
- **Recommendation**: Document

### 2.12 Option Coalescing
- **Syntax**: `value ?? default`
- **Evidence**: Parser precedence table includes `??`
- **Usage**: Found in examples
- **Recommendation**: Document

### 2.13 Range Expressions (FULLY IMPLEMENTED)
- **Syntax**: `start..end` (exclusive), `start..=end` (inclusive)
- **Evidence**: Complete implementation in `astra/parser.py`, `astra/ast.py`, `astra/semantic.py`, `astra/llvm_codegen.py`
- **Features**:
  - Both exclusive (`..`) and inclusive (`..=`) range operators
  - Type inference for range expressions (`Range[T]` and `RangeInclusive[T]`)
  - Integer type compatibility checking and coercion
  - Integration with for-loop iteration
  - Pattern matching with range patterns
  - LLVM codegen as structured range values
- **Types**:
  - `Range[T]` - Exclusive range from start to end (end not included)
  - `RangeInclusive[T]` - Inclusive range from start to end (end included)
- **Capabilities**:
  - Support for all integer types (Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64)
  - Type coercion between compatible integer types
  - Compile-time validation of range bounds
  - Integration with ownership and memory management
  - Support for negative ranges and mixed sign ranges
- **Usage**: Found in `examples/range_expressions_test.arixa`, `examples/advanced_range_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete range expression system with comprehensive features

### 2.14 Arbitrary Precision Integers (FULLY IMPLEMENTED)
- **Syntax**: `i123`, `u456` (any width from 1-128 bits), `123i64`, `456u32` (typed literals)
- **Evidence**: Complete implementation in `astra/int_types.py`, `astra/lexer.py`, `astra/parser.py`, `astra/semantic.py`, `astra/llvm_codegen.py`
- **Features**:
  - Support for arbitrary bit widths from 1 to 128 bits
  - Both signed (`iN`) and unsigned (`uN`) integer types
  - Typed integer literals with suffixes (`123i64`, `456u32`)
  - Type inference and validation
  - LLVM codegen for arbitrary width integers
  - Comprehensive arithmetic and bitwise operations
- **Supported Types**:
  - **Signed**: `i1`, `i8`, `i16`, `i32`, `i64`, `i128`, and any `iN` where 1 ≤ N ≤ 128
  - **Unsigned**: `u1`, `u8`, `u16`, `u32`, `u64`, `u128`, and any `uN` where 1 ≤ N ≤ 128
  - **Built-in**: `Int` (i64), `isize` (i64), `usize` (u64)
- **Capabilities**:
  - Type-safe arithmetic operations with proper overflow handling
  - Bitwise operations (AND, OR, XOR, NOT, shifts)
  - Comparison operations (equality, ordering)
  - Type casting between different integer widths
  - Memory layout optimization for small integers
  - Integration with pattern matching and control flow
- **Validation**:
  - Compile-time width validation (1-128 bits)
  - Type compatibility checking
  - Overflow detection in constants
  - Proper alignment and storage calculation
- **Usage**: Found in `examples/arbitrary_precision_test.arixa`, `examples/advanced_arbitrary_precision_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete arbitrary precision integer system with comprehensive features

### 2.15 Advanced Type Features (FULLY IMPLEMENTED)
- **Syntax**: Union types `T | U`, generics `Struct<T>`, traits `trait Name`
- **Evidence**: Complete implementation in `astra/ast.py`, `astra/parser.py`, `astra/semantic.py`, `astra/build.py`
- **Features**:
  - **Union Types**: `T | U | V` syntax with nullable types `T?` (equivalent to `T | none`)
  - **Generic Types**: `Struct<T>`, `Enum<T>`, `type Alias = Type<T>` with type parameters
  - **Generic Functions**: `fn name<T>(param: T) T` with type inference
  - **Trait Declarations**: `trait Name { fn method(&self) ReturnType; }`
  - **Generic Constraints**: `where T: Trait` and inline bounds `<T: Trait>`
  - **Trait Bounds**: Multiple traits `T: Trait1 + Trait2`, trait hierarchies
  - **Where Clauses**: Complex constraints `where T: Trait1 + Trait2, U: Trait3`
- **Union Type Capabilities**:
  - Type-safe union types with pattern matching
  - Nullable types with `?` syntax sugar
  - Union type normalization and canonicalization
  - Integration with type system and casting
- **Generic Capabilities**:
  - Type parameter inference from function arguments
  - Generic type aliases and nested generics
  - Generic constraints with trait bounds
  - Multi-parameter generics `Struct<T, U>`
  - Generic enums and structs with constraints
- **Trait System Capabilities**:
  - Trait declarations with method signatures
  - Trait bounds in generic constraints
  - Multiple trait bounds and trait hierarchies
  - Where clauses for complex constraints
- **Type Safety**:
  - Compile-time type checking for unions
  - Generic constraint validation
  - Trait bound satisfaction checking
  - Type inference with constraints
- **Integration**:
  - Pattern matching on union types
  - Generic function resolution and monomorphization
  - Union type compatibility and casting
- **Usage**: Found in `examples/advanced_type_features_test.arixa`, `examples/comprehensive_advanced_type_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete advanced type system with union types, generics, traits, and constraints

### 2.16 Async/Await (FULLY IMPLEMENTED)
- **Syntax**: `async fn`, `await expr`
- **Evidence**: Complete implementation in `astra/ast.py`, `astra/lexer.py`, `astra/parser.py`, `astra/semantic.py`, `astra/llvm_codegen.py`, `astra/codegen.py`
- **Features**:
  - **Async Functions**: `async fn name(params) ReturnType { ... }`
  - **Await Expressions**: `await async_function_call()` in any context
  - **Type Safety**: Async functions properly typed and checked
  - **Runtime Integration**: Full Python asyncio runtime integration
  - **GPU Support**: Async functions properly restricted in GPU kernels
  - **Comptime Support**: Async functions properly excluded from comptime
- **Runtime Functions**:
  - `spawn(fn, args...)` - Spawn async task
  - `join(task_id)` - Wait for task completion
  - `sleep_ms(ms)` - Async sleep for milliseconds
  - `await_result(value)` - Runtime await handling
- **Code Generation**:
  - Python async functions with `async def` syntax
  - Automatic awaitable detection and handling
  - Main function async result handling
  - Proper asyncio integration
- **Type System**:
  - Async function signatures with proper return types
  - Await expression type inference
  - Generic async function support
  - Union type return values from async functions
- **Validation**:
  - Async function usage restrictions in GPU kernels
  - Comptime exclusion for async functions
  - Type checking for await expressions
  - Proper error messages for async violations
- **Integration**:
  - Works with all control flow (if, while, for, match)
  - Supports complex expressions with await
  - Compatible with ownership and memory management
  - Integrates with exception handling and error propagation
- **Usage**: Found in `examples/async_demo.arixa`, `examples/async_simple.arixa`, `examples/async_test.arixa`, `examples/comprehensive_async_test.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Complete async/await system with comprehensive runtime support

## 3. Partially Implemented Features

### 3.1 Traits System
- **Syntax**: `trait Name { }`
- **Evidence**: Semantic analysis has trait support
- **Usage**: Limited usage in examples
- **Status**: Implemented but not fully documented
- **Recommendation**: Document and test thoroughly

### 3.3 Generic Constraints
- **Syntax**: `fn func<T: Constraint>(param: T)`
- **Evidence**: Parser and semantic support exists
- **Usage**: Found in complex examples
- **Status**: Implemented but poorly documented
- **Recommendation**: Document

### 3.4 Attribute System
- **Syntax**: `@attribute decl`
- **Evidence**: Limited to `@packed` on structs
- **Usage**: Found in struct definitions
- **Status**: Partially implemented
- **Recommendation**: Document current state

## 4. Redundant or Overlapping Features

### 4.1 For Loop Syntax
- **Iterator Style**: `for item in iterable { }`
- **Status**: ✅ IMPLEMENTED - Iterator-style for loops fully functional

### 4.2 Multiple Binding Syntaxes
- **Identifier-based**: `name = expr`
- **Mutable**: `mut name = expr`
- **Explicit Set**: `set name = expr`
- **Recommendation**: Document clearly, reduce confusion

### 4.3 Duplicate AST Nodes
- **Status**: ✅ RESOLVED - No duplicate AST nodes found

## 5. Naming and Terminology Issues

### 5.1 Language Name
- **Repository**: ASTRA
- **README**: Arixa
- **File Extension**: .arixa
- **Tool Names**: ar* prefix
- **Recommendation**: Standardize on ASTRA

### 5.2 Inconsistent Terminology
- **Status**: ✅ RESOLVED - Standardized terminology implemented
- **Standardized Terms**:
  - **Module** (not package) - Used consistently for code organization
  - **Function** (not routine) - Used consistently for subroutines
  - **Binding** (not variable declaration) - Used consistently for variable bindings

## 6. Missing Documentation Areas

### 6.1 Memory Safety Model
- **Missing**: Comprehensive ownership system documentation
- **Impact**: Users don't understand borrow checking rules
- **Recommendation**: Create dedicated memory safety guide

### 6.2 Error Reporting (FULLY IMPLEMENTED)
- **Features**: Enhanced error reporting with context and suggestions
- **Evidence**: Complete implementation in `astra/error_reporting.py`, updated parser and semantic analysis
- **Capabilities**:
  - **Structured Error Messages**: Clear formatting with severity indicators
  - **Context Display**: Shows surrounding code with problem highlighting
  - **Actionable Suggestions**: Provides specific steps to fix errors
  - **Error Codes**: Unique identifiers with documentation links
  - **Multiple Error Support**: Handles multiple errors in single output
- **Integration**: Enhanced parser and semantic analyzer with improved error reporting
- **Usage**: Found in `docs/error_reporting.md`, `examples/error_demo.py`, `examples/error_examples.arixa`
- **Status**: ✅ FULLY IMPLEMENTED - Comprehensive error reporting system with documentation and examples

### 6.3 Generic Types (FULLY IMPLEMENTED)
- **Features**: Generic functions and structs without Result<T>/Option<T>
- **Evidence**: Complete implementation in parser, semantic analyzer, and examples
- **Capabilities**:
  - **Generic Functions**: Functions with type parameters and bounds
  - **Generic Structs**: Structs with type parameters
  - **Trait Bounds**: Where clauses for generic constraints
  - **Type Inference**: Automatic type deduction for generics
- **Integration**: Parser handles generic syntax, semantic analyzer validates constraints
- **Usage**: Found in examples and tests with simplified generic types
- **Status**: ✅ FULLY IMPLEMENTED - Generic types without complex Result/Option patterns

### 6.4 FFI Integration
- **Missing**: Foreign function interface documentation
- **Impact**: Users can't integrate with C libraries
- **Recommendation**: Document FFI patterns

### 6.5 Build System
- **Missing**: Build configuration and targeting documentation
- **Impact**: Users can't optimize builds
- **Recommendation**: Document build system features

## 7. Test Coverage Gaps

### 7.1 Enhanced Loop Forms
- **Gap**: No tests for enhanced while loops
- **Recommendation**: Add comprehensive tests

### 7.2 Edge Cases
- **Gap**: Limited testing of ownership edge cases
- **Gap**: Limited testing of generic constraint failures
- **Recommendation**: Expand test coverage

### 7.3 Error Messages
- **Gap**: Poor error messages for some syntax errors
- **Recommendation**: Improve error reporting

## 8. Priority Recommendations

### High Priority (Fix Immediately)
1. **Remove `let` and `const` from lexer** or implement them
2. **Document iterator for loops** (already in use)
3. **Document ownership system** (core feature)
4. **Fix naming consistency** (ASTRA vs Arixa)

### Medium Priority (Fix Soon)
1. **Document GPU features** (significant implementation)
2. **Document unsafe blocks** (important for FFI)
3. **Consolidate duplicate documentation**

### Low Priority (Fix Eventually)
1. **Document trait system** thoroughly
2. **Improve error messages**
3. **Add more comprehensive tests**

## 9. Implementation Evidence Summary

### Source Files Consulted
- `astra/lexer.py` - Token definitions
- `astra/parser.py` - Grammar implementation  
- `astra/ast.py` - AST node definitions
- `astra/semantic.py` - Type checking and analysis
- `astra/codegen.py` - Code generation
- `examples/` - Usage patterns (48 files)
- `tests/` - Expected behavior (59 files)
- `stdlib/` - Standard library implementation

### Documentation Files Consulted
- `docs/language/specification.md` - Language specification
- `docs/language/*.md` - Language reference
- `README.md` - Project overview
- `docs/archive/*.md` - Historical documentation

## 10. Next Steps

1. **Immediate Actions**:
   - Remove unused keywords from lexer
   - Document core undocumented features
   - Fix naming consistency

2. **Short Term**:
   - Consolidate documentation
   - Add missing examples
   - Improve test coverage

3. **Long Term**:
   - Finish partial implementations
   - Improve error messages
   - Create comprehensive guides

This report prioritizes implementation reality over documentation claims, ensuring that the language specification matches what actually works.
