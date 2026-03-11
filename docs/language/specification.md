# ASTRA Language Specification (Low-Level Reference)

This document is the canonical, implementation-aligned reference for ASTRA.
It is intentionally low-level and tracks current compiler behavior.

Implementation anchors:
- Lexer: `astra/lexer.py`
- Parser: `astra/parser.py`
- Semantic/type system: `astra/semantic.py`
- Python backend: `astra/codegen.py`
- LLVM backend: `astra/llvm_codegen.py`
- Build/link pipeline: `astra/build.py`

## 1. Scope and Stability

- ASTRA supports hosted and freestanding compilation modes.
- Source file extension is `.arixa` (some tests still use `.astra` paths as legacy aliases).
- This spec describes the behavior currently implemented in the repository, not historical syntax.
- If behavior differs from older docs/examples, current compiler behavior wins.

## 2. Lexical Structure

## 2.1 Comments

- Line comments: `// ...`
- Hash comments: `# ...`
- Block comments: `/* ... */` (non-nested)
- Doc comments: `/// ...` (module/item docs)

## 2.2 Keywords

Current keywords (from lexer):
- `fn`, `mut`, `if`, `else`, `while`, `for`, `match`
- `return`, `break`, `continue`
- `unreachable`
- `unsafe`, `struct`, `enum`, `trait`, `type`
- `import`, `extern`, `comptime`
- `none`, `set`, `in`, `as`
- `sizeof`, `alignof`
- `f16`, `f80`, `f128`
- `pub`, `const`, `true`, `false`, `where`
- `async`, `await`

## 2.3 Operators and Delimiters

Multi-token operators:
- `...`, `::`, `=>`, `->`
- `==`, `!=`, `<=`, `>=`
- `&&`, `||`, `??`
- `+=`, `-=`, `*=`, `/=`, `%=`
- `<<=`, `>>=`, `&=`, `|=`, `^=`
- `<<`, `>>`, `..`, `..=`

Single-char tokens include:
- `{ } ( ) < > [ ]`
- `; , . : @`
- `= + - * / % ! ?`
- `& | ^ ~`

## 2.4 Literals

Integer literals:
- Decimal: `42`
- Binary: `0b1010`
- Octal: `0o755`
- Hex: `0xFF`
- `_` separators allowed between digits.
- Typed integer literals: `123i64`, `255u8`, etc.

Float literals:
- Decimal with fraction: `3.14`
- Scientific notation: `1e9`, `2.5E-3`
- `_` separators accepted in digit spans.

String literals:
- Standard string: `"hello"`
- Multiline string: `"""..."""` (raw body preserved)
- Interpolated string tokenized separately when unescaped `{...}` appears.
- Escaped braces in interpolation strings: `{{` and `}}` mean literal braces.

Char literals:
- `'a'`, escaped forms supported by lexer.

Other literals:
- `true`, `false`
- `none`

## 3. Top-Level Grammar

`Program` is a list of top-level items.

Supported top-level items:
- `import`
- `fn` declarations
- `extern fn` declarations
- `struct`, `enum`, `trait`, `type` alias
- `const`
- top-level bindings (`name = expr;`, `mut name = expr;`) with safety rules

## 3.1 Modifiers and Attributes

Supported declaration modifiers:
- `pub`
- `unsafe` (functions/extern functions; also required for top-level mutable bindings)
- `async`
- `gpu` (only valid as `gpu fn ...`)

Supported attributes:
- `@packed` (struct only)
- `@derive(...)` (struct/enum only)
- `@link("lib")` (extern fn only)

Invalid modifier/attribute combinations are parser errors.

## 3.2 Imports

Two import forms:
- Symbolic path: `import std.io;`
- String path: `import "deps/module";`

Optional alias:
- `import std.io as io;`

## 3.3 Functions

Syntax:
- `fn name(params) ReturnType { ... }`
- `fn name(params) { ... }` (defaults to `Void`)

Important:
- `->` return syntax is rejected; return type appears after `)`.
- Generic params supported: `fn f<T>(x T) T { ... }`
- Trait bounds accepted inline and in `where`:
  - `<T: Trait>`
  - `<T Trait>` (parser accepts and normalizes)
  - `where T: Trait + Other`

GPU kernel form:
- `gpu fn kernel(...) Void { ... }`

Async form:
- `async fn ...`

Unsafe form:
- `unsafe fn ...`

## 3.4 Extern Functions / FFI

Syntax:
- `extern fn name(params) Ret;`
- Legacy library tag accepted: `extern c fn name(...) Ret;`
- Library attributes also supported via `@link("...")`.
- Variadic externs supported with trailing `...`.

## 3.5 Structs, Enums, Traits, Type Aliases

Struct:
- `struct Name { field Type, ... }`

Enum:
- `enum E { A, B(Int), C(String, Int) }`

Trait:
- method signatures only (no bodies) in declaration:
  - `trait T { fn m(x Int) Int; }`

Type alias:
- `type Bytes = Vec<u8>;`

## 3.6 Const and Global Bindings

Const:
- `const NAME = expr;`

Top-level binding:
- `x = expr;`
- `unsafe mut x = expr;` for mutable global values

## 4. Type System

## 4.1 Primitive and Core Types

Built-in primitive/canonical core names include:
- Integers: `Int`, `isize`, `usize`, `iN`, `uN` where `N` in `[1, 128]`
- Floats: `Float`, `f16`, `f32`, `f64`, `f80`, `f128`
- `Bool`, `String`, `str`, `Any`, `Void`, `Never`

Alias normalization:
- `Bytes` canonicalizes to `Vec<u8>`.

## 4.2 Composite Types

- Vector/generic: `Vec<T>`
- Slice-like form in type syntax: `[T]`
- References: `&T`, `&mut T`
- Pointer types: `*T`
- Function type: `fn(T1, T2) Ret`
- Union type: `A | B | C`
- Nullable sugar: `T?` => `T | none`

Union normalization:
- Duplicate members collapse.
- Nested unions flatten.

## 4.3 Casts

Cast syntax:
- `expr as Type`

Casting rules are semantic-checked (`_cast_supported`):
- Numeric conversions supported with explicit casts.
- Ref/int and int/ref casts are supported under backend constraints.
- `Any` dynamic casts exist with restrictions.
- Some casts require `unsafe` context.

## 5. Statements

Supported statement forms:
- Binding declaration: `mut x = expr;`, `x = expr;`
- Assignment: `x = y;`, `x += y;`, etc.
- Explicit assignment marker: `set x = y;`
- `return [expr];`
- `break;`, `continue;`
- `unreachable;`
- `if cond { ... } else { ... }`
- `while cond { ... }`
- Enhanced while with inline mutable binding form exists in parser (`EnhancedWhileStmt`)
- Iterator-style `for`: `for item in iterable { ... }`
- `match` with pattern arms
- `comptime { ... }`
- `unsafe { ... }`
- Expression statement

Semicolons:
- Required for most statement forms except block terminators.

## 6. Expressions

## 6.1 Operator Precedence (high-level)

From low to high (approx):
- `??`
- `||`
- `&&`
- `|`
- `^`
- `&`
- equality / relational
- shifts
- `+ -`
- `* / %`
- range `..`, `..=`

Unary:
- `-`, `!`, `~`, `&`, `&mut`, `*`, `await`

Postfix:
- call `f(...)`
- indexing `x[i]`
- field access `x.f`
- try propagation `expr!`
- type args on call targets `f<T>(...)`

## 6.2 Control Expressions

If-expression:
- `if cond { expr } else { expr }`

Match-expression behavior is represented via `match` statement forms; lowering and typing handle arm consistency.

Range expression:
- `a..b`
- `a..=b`

## 6.3 Intrinsic Type Query Expressions

Type query forms:
- `sizeof(Type)`
- `alignof(Type)`
- `bitSizeOf(Type)`
- `maxVal(Type)`
- `minVal(Type)`

Value query forms:
- `size_of(expr)`
- `align_of(expr)`

## 6.4 String Interpolation

Interpolation syntax in strings:
- `"value={x}"`

Rules:
- Parsed into `StringInterpolation(parts, exprs)`.
- `{{` and `}}` produce literal braces.
- Expressions inside braces are full expressions.

## 7. Pattern Matching

Supported pattern forms:
- wildcard: `_`
- literal/expression patterns
- or-patterns: `p1 | p2 | ...`
- guarded patterns: `pat if cond`
- range patterns: `1..10`, `1..=10`
- slice patterns: `[a, b, ..]`
- tuple patterns: `(a, b)`
- struct patterns: `Point { x, y }`, `Point { x: px }`

Match arm syntax:
- `pattern => { ... }`
- short form without block is accepted for simple arm statements.

## 8. Ownership, Borrowing, and Moves

Semantic analysis tracks:
- borrow validity
- mutable-vs-immutable borrow conflicts
- move/use-after-move errors
- return/reference safety in function signatures

Borrow syntax:
- immutable: `&x`
- mutable: `&mut x`
- dereference: `*ptr`

## 9. Builtins

Builtins are defined in `semantic.BUILTIN_SIGS`.

Core examples:
- I/O and formatting: `print(...)`, `format(...)`
- Length: `len(x)`
- Assertions/hints: `assert(cond)`, `debug_assert(cond)`, `assume(cond)`, `likely(cond)`, `unlikely(cond)`, `static_assert(cond[, msg])`
- Files/args/process/time/network/crypto/json APIs
- Atomics and concurrency primitives
- Vector and dynamic container primitives
- Bit operations: `countOnes`, `clz`, `ctz`, `rotl`, `rotr`, etc.

Builtin aliasing:
- Most builtins also expose `__name` alias variants.
- Exceptions are intentionally excluded for some hosted-only/runtime entry operations.

### 9.1 Assertion and Hint Semantics

- `assert(cond)`:
  - `cond` must type-check as `Bool`.
  - Active in debug and release builds.
  - Lowered as a runtime check; false condition traps/fails.
- `debug_assert(cond)`:
  - `cond` must type-check as `Bool`.
  - Active in debug builds.
  - Lowered away in release builds.
- `assume(cond)`:
  - `cond` must type-check as `Bool`.
  - Debug builds: checked and traps/fails on false.
  - Release builds: lowered to optimizer assumption (`llvm.assume` on LLVM backend).
- `likely(cond)` / `unlikely(cond)`:
  - `cond` must type-check as `Bool`.
  - Returns `Bool` (same logical value as `cond`).
  - Treated as branch prediction hints only; they do not imply impossibility and are not `assume`.
- `unreachable`:
  - Statement form (not a library call).
  - Debug builds trap then terminate.
  - Release builds lower to backend unreachable termination.

## 10. Hosted vs Freestanding

Freestanding mode:
- selected hosted/runtime builtins are forbidden by semantic checks.
- runtime-dependent symbols (`astra_*`) are disallowed in freestanding LLVM output.
- external host symbols are disallowed, except platform hook namespace (`__*`).

Entrypoint rules:
- Hosted executable: requires `main()`.
- Freestanding executable: requires `_start()`.
- `--kind lib` may omit executable entrypoint.

## 11. Freestanding Platform Hook ABI

ASTRA reserves `__fs_*` hook names for low-level platform integration.

Current hooks used by stdlib low-level modules:
- Volatile MMIO:
  - `__fs_volatile_read8_impl`, `__fs_volatile_read16_impl`,
    `__fs_volatile_read32_impl`, `__fs_volatile_read64_impl`
  - `__fs_volatile_write8_impl`, `__fs_volatile_write16_impl`,
    `__fs_volatile_write32_impl`, `__fs_volatile_write64_impl`
- Tick:
  - `__fs_tick_now_impl`
- Panic handler:
  - `__fs_panic_set_handler_impl`
  - `__fs_panic_get_handler_impl`
  - `__fs_panic_with_code_impl`

Important implementation status:
- `volatile` is currently provided through runtime hooks/stdlib wrappers (`std.hardware` and `__fs_volatile_*` symbols).
- There is no dedicated language-level `volatile` type qualifier in parser/semantic/codegen at this time.

Build defaults:
- Native freestanding builds now compile default hook implementations (`_freestanding_hooks_source` in `astra/build.py`).
- You can still override by providing your own symbol definitions at link time.

## 12. Code Generation and Backends

## 12.1 Python backend

- Emits executable Python with runtime shims.
- Builtin mapping includes print/format wrappers and host runtime helpers.

## 12.2 LLVM backend

- Emits LLVM IR via `llvmlite`.
- Hosted mode links runtime C (`runtime/llvm_runtime.c` or override).
- Freestanding mode uses internal freestanding allocator paths and runtime-free checks.

## 12.3 Native linking

`build --target native`:
- Uses `clang`.
- Hosted: links runtime C and system libs.
- Freestanding: links generated freestanding entry + hook source with `-nostdlib -nostartfiles`.
- Freestanding entry supports:
  - x86_64 syscall exit
  - aarch64 syscall exit
  - riscv64 syscall exit

## 13. CLI Surface (Current)

Primary command:
- `arixa build <input> -o <output>`

Key flags:
- `--target py|llvm|native`
- `--kind exe|lib`
- `--freestanding`
- `--strict`
- `--profile debug|release|experimental|beta`
- `--overflow trap|wrap|debug`
- `--sanitize address|undefined|thread` (native only, hosted only)
- `--triple <llvm-triple>`
- `--link <lib>` (repeatable)

Other commands:
- `arixa check`
- `arixa run`
- `arixa test`
- `arixa fmt`
- `arixa doc`
- `arixa pkg`

## 14. Standard Library Notes

Low-level and freestanding-relevant modules:
- `std.core`, `std.atomic`, `std.mem`, `std.memory`
- `std.data`, `std.vec`, `std.algorithm`
- `std.hardware` (MMIO, register helpers, barriers, polling)
- `std.boot` (interrupt and boot primitives)
- `std.embedded` (peripheral wrappers)
- `std.os` (errno/device ids, IRQ helpers, tick helpers, SPSC ring, panic hooks)

Hosted-centric modules (forbidden in freestanding mode):
- `std.io`, `std.net`, `std.process`, `std.crypto`, `std.serde`, `std.thread`, `std.sync`, `std.channel`, and similar runtime-bound APIs.

## 15. Compatibility / Migration Notes

- Return type arrow `->` is obsolete in function declarations.
- Iterator-style `for item in iterable` is canonical.
- Builtin and stdlib surfaces continue to evolve; prefer this document + compiler diagnostics over stale external references.

---

For compiler-internal architecture and backend notes, see:
- `docs/compiler/overview.md`
- `docs/compiler/architecture.md`
- `docs/compiler/llvm_backend.md`
