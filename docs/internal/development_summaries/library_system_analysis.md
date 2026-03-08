# ASTRA Library System Analysis

## Overview
The ASTRA language has a well-structured library system that supports both standard library modules and user-defined modules with flexible import mechanisms.

## Library System Architecture

### 1. Standard Library (Stdlib)

**Location**: `/stdlib/` (development) and `/astra/stdlib/` (bundled)

**Core Modules**:
- **`core.arixa`** - Fundamental types and checked arithmetic helpers
  - `Bytes` type alias (`Vec<u8>`)
  - Overflow-checked arithmetic: `add_checked`, `sub_checked`, `mul_checked`
  - Freestanding-safe

- **`math.arixa`** - Pure numeric helpers
  - `min_int`, `max_int`, `clamp_int`, `abs_int`
  - Freestanding-safe

- **`vec.arixa`** - Typed vector wrappers
  - `Vec<T>` type definitions around builtin vectors
  - Freestanding-safe

- **`mem.arixa`** - Memory utilities
  - Byte buffer operations using freestanding vector API
  - Freestanding-safe

- **`atomic.arixa`** - Atomic operations
  - `AtomicInt` type with load/store/fetch_add/cas operations
  - Freestanding-safe

**Hosted Modules** (require runtime):
- **`io.arixa`** - File I/O and printing
- **`collections.arixa`** - List/map helpers (`List<T>`, `Map<K,V>`)
- **`net.arixa`** - TCP networking helpers
- **`thread.arixa`** - Task spawning and management
- **`sync.arixa`** - Mutex wrappers
- **`channel.arixa`** - FIFO channels
- **`process.arixa`** - Process/environment helpers
- **`crypto.arixa`** - Cryptographic functions
- **`serde.arixa`** - JSON serialization
- **`time.arixa`** - Time utilities
- **`str.arixa`** - String utilities

### 2. External Bindings

**Location**: `/stdlib/bindings/`

Available bindings:
- **`libc.arixa`** - C standard library functions
- **`raylib.arixa`** - Game programming library
- **`sdl2.arixa`** - SDL2 multimedia library
- **`sqlite3.arixa`** - SQLite database

### 3. Package Registry

**Location**: `/registry/modules.json`

Registered modules:
- `c` - C standard library bindings
- `curl` - libcurl bindings
- `opengl` - OpenGL bindings
- `raylib` - raylib game programming library
- `sdl2` - SDL2 bindings
- `sqlite3` - SQLite3 bindings

## Import System

### Import Syntax

```astra
// Module imports (stdlib)
import std.core;
import std.math;
import std.io;

// Relative file imports
import "local_module.arixa";
import "../shared/utils.arixa";

// Package imports (future feature)
import some_module;
```

### Import Resolution

**Module Resolution Logic**:
1. **String imports** (`"path/file.arixa"`) - Relative to current file
2. **Module imports** (`std.module`) - Resolved through module resolver
3. **Stdlib imports** (`std.core`) - Mapped to stdlib root directory
4. **Package imports** - Resolved through module cache

**Resolution Priority**:
1. Check if path starts with `std` or `stdlib` → use stdlib root
2. Check for relative file path from current directory
3. Check for module root (`Astra.toml`)
4. Default to current working directory

### Import Behavior

**Function/Variable Access**:
- Imported functions are available directly (no module qualification)
- All top-level declarations are imported
- No explicit `pub` keyword needed (all declarations are public by default)

**Example**:
```astra
import std.core;
import "helper.arixa";

fn main() Int {
    // Direct access to imported functions
    result = add_checked(5, 10);  // from std.core
    helper_result = helper_func(20); // from helper.arixa
    return result + helper_result;
}
```

## Module System Features

### 1. Freestanding vs Hosted

**Freestanding Modules**:
- Can be used with `--freestanding` flag
- No runtime dependencies
- Suitable for kernel/bootloader development

**Hosted Modules**:
- Require runtime support
- OS integration (file I/O, networking, etc.)
- Full application development

### 2. Type System Integration

**Strong Typing**:
- All imported functions maintain type signatures
- No implicit conversions between modules
- Explicit casting required when needed

**Example**:
```astra
import std.core;

fn main() Int {
    result = add_checked(5, 10);  // Returns Int?
    return result as Int;          // Explicit cast required
}
```

### 3. Error Handling

**Import Errors**:
- Module not found: `cannot resolve import "module"`
- File not found: `cannot resolve import "file.arixa"`
- Enhanced error messages with suggestions

**Enhanced Error Messages**:
```
error[E0202]: cannot resolve import std.nonexistent
  = help: imports are path-validated; ensure the module file exists and matches the import path
```

## Package Management

### Package Cache

**Location**: `~/.arixa/modules/` (configurable via `ARIXA_PKG_HOME`)

**Package Structure**:
- Each module in separate directory
- Version management through lock files
- Dependency resolution via `Astra.toml`

### Registry Integration

**Central Registry**: `/registry/modules.json`

**Package Information**:
- Repository URL
- Description
- Version
- Dependencies

## Build System Integration

### Compilation Pipeline

1. **Import Resolution** - Parse and resolve all imports
2. **Semantic Analysis** - Type checking across module boundaries
3. **Code Generation** - LLVM IR generation with linked modules
4. **Linking** - Runtime and external library linking

### Dependency Tracking

**Automatic Detection**:
- Compiler tracks import dependencies
- Incremental compilation support
- Build system integration for external tools

## Current Status and Limitations

### ✅ Working Features
- Stdlib module imports (`std.core`, `std.math`, etc.)
- Relative file imports (`"module.arixa"`)
- Type-safe cross-module function calls
- Enhanced error messages for import failures
- Freestanding vs hosted module separation

### 🚧 Known Limitations
- No module-qualified function calls (e.g., `module.function()`)
- No circular dependency detection
- Package management still in development
- No version conflict resolution
- Limited external module ecosystem

### 🔄 Future Enhancements
- Package manager with version resolution
- Module qualification support
- Circular dependency detection
- Private/public visibility controls
- Conditional compilation features

## Usage Examples

### Basic Stdlib Usage
```astra
import std.core;
import std.math;

fn main() Int {
    x = 5;
    y = 10;
    result = add_checked(x, y);
    if result == none {
        return -1;
    }
    return result as Int;
}
```

### Multi-Module Project
```astra
// main.arixa
import "utils.arixa";
import std.core;

fn main() Int {
    return helper_function(42);
}

// utils.arixa
fn helper_function(x Int) Int {
    return x * 2;
}
```

### External Library Integration
```astra
import std.bindings.libc;

fn main() Int {
    // Use C library functions
    return 0;
}
```

## Conclusion

The ASTRA library system provides a solid foundation for modular development with:
- **Clear separation** between freestanding and hosted modules
- **Flexible import mechanisms** supporting both stdlib and local modules
- **Type-safe cross-module compilation**
- **Enhanced error reporting** for import issues
- **Growing ecosystem** of external libraries and bindings

While some advanced features are still in development, the current system supports most common use cases and provides a good foundation for future enhancements.
