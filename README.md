# ASTRA

ASTRA is a modern, statically-typed programming language with a full compiler pipeline, CLI tooling, language server support, and a comprehensive standard library.

## Main Features

- **Modern Syntax**: Clean, expressive syntax with automatic type inference
- **Type Safety**: Strong static typing with advanced type system features
- **Memory Safety**: Safe memory management with optional unsafe code
- **Performance**: Multiple backends (Python, LLVM IR, native executables)
- **Tooling**: Built-in formatter, linter, LSP server, debugger, and profiler
- **GPU Computing**: First-class GPU compute support with `gpu fn` kernels
- **Package Management**: Built-in package system with dependency resolution
- **Standard Library**: Comprehensive stdlib with I/O, networking, crypto, and more
- **Async Support**: Native async/await syntax for concurrent programming
- **Platform Support**: Hosted and freestanding compilation modes

## Language Highlights

### Current Syntax Features
- Function signatures: `fn name(param_type) return_type` (no `->`)
- Iterator-style loops: `for item in collection`
- Pattern matching with guards
- Nullable types: `Int?` = `Int | none`
- Coalesce operator: `value ?? default`
- Automatic type conversions (Int ↔ i64)
- Standalone functions (impl blocks removed)
- **Optimized Any Type**: Zero-overhead dynamic typing when not used

### Type System
- **Integers**: `Int` (default), `i8/i16/i32/i64/i128`, `u8/u16/u32/u64/u128`
- **Floats**: `Float` (default), `f16/f32/f64/f80/f128`
- **Collections**: `Vec<T>`, `[T; N]`, `&[T]`, `&mut [T]`
- **Union Types**: `A | B | C`, nullable `T?`
- **References**: `&T`, `&mut T`
- **Dynamic**: `Any` - opt-in runtime feature with zero overhead for typed code

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Requirements:
- Python 3.11+
- `clang` for native compilation
- `llvmlite` (installed automatically)

## Quick Example

`examples/hello_world.astra`:

```astra
fn main() Int {
    print("Hello, ASTRA!");
    return 0;
}
```

Build and run:

```bash
arixa check examples/hello_world.astra
arixa build examples/hello_world.astra -o build/hello.py
python build/hello.py
```

## More Examples

### Functions and Types
```astra
fn add(a Int, b Int) Int {
    return a + b;
}

fn greet(name String) Void {
    print("Hello, " + name);
}
```

### Control Flow
```astra
fn process_numbers(numbers: &[Int]) Int {
    mut sum = 0;
    
    for num in numbers {
        if num > 0 {
            sum = sum + num;
        } else {
            break;
        }
    }
    
    return sum;
}
```

### Nullable Types
```astra
fn find_item(items: &[Int], target: Int) Int? {
    for item in items {
        if item == target {
            return item;
        }
    }
    return none;
}

// Usage
result = find_item([1, 2, 3], 2) ?? 0;
```

### Async Functions
```astra
async fn fetch_data(url String) String {
    // async implementation
    response.await
}
```

## 🛠️ Error Reporting

ASTRA features an enhanced error reporting system that provides:

- **Clear, structured error messages** with severity indicators
- **Contextual code highlighting** showing problem areas
- **Actionable suggestions** for fixing common issues
- **Consistent formatting** across all error types
- **Educational error codes** with documentation links

### Example Error Output

```
❌ ERROR: type_mismatch
   📍 example.arixa:3:12

📄 Context:
   1 | fn main() -> Int {
   2 |     let x = "hello"
   3 |     return x
   4 | }
     |            ^

💬 Expected return type 'Int' but found 'String'

💡 Suggestions:
   1. Check types
      Verify the types match the expected signature
   2. Add type conversion
      Use explicit type conversion if needed
      Example: `return x as Int`

🔍 Error code: SEM102
   Learn more: https://astra-lang.dev/errors/SEM102
```

For more information, see the [Error Reporting Guide](docs/error_reporting.md).

## 📚 Documentation

- **Getting Started**: `docs/development/getting-started.md`
- **Error Reporting**: `docs/error_reporting.md`
- **Language Specification**: `docs/language/specification.md`
- **Language Reference**: `docs/language/`
  - **Any Type Optimization**: `docs/language/any_type_optimization.md`
- **Standard Library**: `docs/stdlib/`
- **Compiler Internals**: `docs/compiler/`
- **GPU Development**: `docs/gpu/`
- **Performance Analysis**: `docs/performance-analysis.md`
- **Tooling & VS Code**: `docs/tools/`
- **Development Guide**: `docs/development/`
- **Reference Materials**: `docs/reference/`

Current compiler behavior note:

- import paths are resolved and validated by semantic analysis.
- most callable stdlib-facing functions are currently surfaced through builtin names.
