# Language Overview

ASTRA is a modern, statically-typed programming language with explicit ownership-oriented semantics, deterministic compilation, and comprehensive tooling.

## Core Features

### Type System
- **Strong static typing** with automatic type inference
- **Advanced type system** with union types, nullable types, and automatic conversions
- **Memory safety** with ownership and borrowing semantics
- **Generic programming** with type parameters and constraints

### Syntax Highlights
- **Clean, modern syntax** with minimal punctuation
- **Function signatures**: `fn name(param_type) return_type` (no `->`)
- **Iterator-style loops**: `for item in collection`
- **Pattern matching** with guards and destructuring
- **Nullable types**: `Int?` = `Int | none`
- **Coalesce operator**: `value ?? default`

### Language Features
- **Compile-time execution** via `comptime {}`
- **Union-based error modeling** (`A | B`, `T?`, `none`, `??`)
- **Async/await** for concurrent programming
- **Unsafe code** for low-level operations
- **GPU computing** with `gpu fn` kernels
- **Package management** with dependency resolution

### Build Modes
- **Hosted mode**: Full runtime with standard library
- **Freestanding mode**: Bare-metal without runtime dependencies
- **Multiple backends**: Python, LLVM IR, native executables

## Current Language Status

### ✅ Implemented Features
- **Core language**: Functions, structs, enums, control flow
- **Type system**: Advanced types with automatic conversions
- **Memory management**: Ownership, borrowing, lifetimes
- **Error handling**: Union types, nullable types, coalesce operator
- **Modules**: Import system with package management
- **Async**: Native async/await syntax
- **GPU**: First-class GPU compute support
- **Tooling**: Formatter, linter, LSP, debugger, profiler

### 🔄 Recent Changes
- **Function syntax**: Updated to `fn name() Type` (no `->`)
- **For loops**: Iterator-style only (no C-style loops)
- **AST updates**: `IteratorForStmt` replaces `ForStmt`
- **Type conversions**: Automatic Int ↔ i64 conversion
- **Impl blocks**: Removed, use standalone functions
- **Editor tools**: Automatic synchronization with language changes

### 📋 Language Specification
- **Keywords**: 34 total keywords for language features
- **Operators**: Comprehensive operator set with precedence
- **Types**: Primitive, compound, and generic types
- **Expressions**: Full expression grammar with type checking
- **Statements**: Control flow, declarations, and side effects

## Main Reference Links

### Language Documentation
- **[Language Specification](specification.md)** - Complete language definition
- **[Syntax Guide](syntax.md)** - Current syntax and usage examples
- **[Type System](types.md)** - Type system and conversions
- **[Functions](functions.md)** - Function definitions and calls
- **[Control Flow](control_flow.md)** - Loops, branches, and pattern matching

### Advanced Topics
- **[Memory Model](memory_model.md)** - Ownership and borrowing
- **[Modules](modules.md)** - Import system and packages
- **[Unsafe Code](unsafe.md)** - Low-level operations
- **[Async Support](generics.md)** - Concurrent programming
- **[GPU Computing](../gpu/overview.md)** - GPU compute features

### Development Resources
- **[Getting Started](../development/getting-started.md)** - Setup and installation
- **[Contributing](../development/contributing.md)** - Development guidelines
- **[Testing](../development/testing.md)** - Test suite and verification
- **[Build System](../development/build_system.md)** - Build and compilation

## Design Philosophy

ASTRA follows these design principles:

1. **Safety First**: Memory safety and type safety by default
2. **Performance**: Zero-cost abstractions and efficient compilation
3. **Practicality**: Real-world features with comprehensive tooling
4. **Expressiveness**: Clean syntax that reads like natural language
5. **Interoperability**: Multiple backends and platform support
6. **Extensibility**: Package system and GPU computing support

## Getting Started

To start using ASTRA:

1. **Install**: Follow the [installation guide](../development/getting-started.md)
2. **Learn**: Read the [language tour](tour.md) for interactive examples
3. **Practice**: Try the [examples](../../examples/) directory
4. **Develop**: Set up [editor integration](../development/editor_setup.md)
5. **Contribute**: Follow the [contributing guide](../development/contributing.md)

## Community and Support

- **Documentation**: Comprehensive docs in `/docs` directory
- **Examples**: Real-world examples in `/examples` directory
- **Tests**: Extensive test suite in `/tests` directory
- **Tools**: Built-in CLI tools and VS Code extension
- **Standards**: Language specification and reference implementation
