# Arixa Language Spec (Implementation-Facing)

This document defines the current language contract in a single place for parser/semantic/codegen behavior.

## 1. Lexical Grammar

Source is tokenized as:

```ebnf
whitespace      = { " " | "\t" | "\r" | "\n" } ;
line_comment    = "//" { any_char - "\n" } ;
doc_comment     = "///" { any_char - "\n" } ;
block_comment   = "/*" { any_char } "*/" ;

ident           = ( "_" | letter ) { "_" | letter | digit } ;
int_lit         = dec_int_lit | hex_int_lit | bin_int_lit ;
dec_int_lit     = digit { digit | "_" } ;
hex_int_lit     = ("0x" | "0X") hex_digit { hex_digit | "_" } ;
bin_int_lit     = ("0b" | "0B") ("0" | "1") { "0" | "1" | "_" } ;
int_type_tok    = ("i" | "u") nonzero_digit { digit } ;
float_lit       = (digit { digit | "_" } "." digit { digit | "_" })
                | ("." digit { digit | "_" }) ;
str_lit         = "\"" { char | escape } "\"" ;
str_multi_lit   = "\"\"\"" { any_char } "\"\"\"" ;
char_lit        = "'" { char | escape } "'" ;
bool_lit        = "true" | "false" ;

keyword         = "fn" | "return" | "if" | "else" | "while"
                | "for" | "break" | "continue" | "struct" | "enum" | "type"
                | "import" | "mut" | "pub" | "extern" | "async" | "await"
                | "unsafe" | "trait" | "match" | "defer" | "drop"
                | "comptime" | "none" | "in" | "as" | "sizeof" | "alignof" ;

multi_op        = "::" | "=>" | "->" | "==" | "!="
                | "<=" | ">=" | "&&" | "||" | "??"
                | "+=" | "-=" | "*=" | "/=" | "%="
                | "&=" | "|=" | "^=" | "<<=" | ">>="
                | "<<" | ">>" | ".." ;
single_op       = "{" | "}" | "(" | ")" | "<" | ">" | ";" | "," | "=" | "+"
                | "-" | "*" | "/" | "%" | "!" | "?" | "[" | "]" | ":"
                | "." | "&" | "|" | "^" | "~" | "@" ;
```

Notes:
- Unterminated block comments/strings/chars are lexer errors (`LEX file:line:col: ...`).
- `doc_comment` tokens are consumed by parser in declaration/block positions.
- `str_multi_lit` is tokenized as `STR_MULTI` and accepted by expression parsing; it produces the same literal expression shape as `str_lit` but may contain embedded newlines and indentation.
- `int_type_tok` is recognized as an integer-type token and validated to width range `1..128` (`i0`, `u0`, and widths above `128` are lexer errors).
- `@packed` is recognized as an attribute introducer and is only valid on `struct` declarations.

## 2. Expression Grammar

```ebnf
expr            = coalesce_expr ;
coalesce_expr   = logic_or_expr { "??" logic_or_expr } ;
logic_or_expr   = logic_and_expr { "||" logic_and_expr } ;
logic_and_expr  = bit_or_expr { "&&" bit_or_expr } ;
bit_or_expr     = bit_xor_expr { "|" bit_xor_expr } ;
bit_xor_expr    = bit_and_expr { "^" bit_and_expr } ;
bit_and_expr    = compare_expr { "&" compare_expr } ;
compare_expr    = shift_expr { ("==" | "!=" | "<" | "<=" | ">" | ">=") shift_expr } ;
shift_expr      = add_expr { ("<<" | ">>") add_expr } ;
add_expr        = mul_expr { ("+" | "-") mul_expr } ;
mul_expr        = unary_expr { ("*" | "/" | "%") unary_expr } ;
unary_expr      = [ "await" ] ( ( "-" | "!" | "~" | "*" | "&" [ "mut" ] ) unary_expr | cast_expr ) ;
cast_expr       = postfix_expr { "as" type } ;
postfix_expr    = atom { "." ident | "[" expr "]" | "(" [expr {"," expr}] ")" } ;
atom            = int_lit | float_lit | str_lit | char_lit | bool_lit
                | typed_int_lit | "none" | ident | array_lit | "(" expr ")" | layout_query | type_intrinsic_query ;
typed_int_lit   = int_lit int_type_tok ;
array_lit       = "[" [expr {"," expr}] "]" ;
layout_query    = "sizeof" "(" type ")" | "alignof" "(" type ")"
                | "size_of" "(" expr ")" | "align_of" "(" expr ")" ;
type_intrinsic_query = "bitSizeOf" "(" type ")" | "maxVal" "(" type ")" | "minVal" "(" type ")" ;
```

Precedence (high to low):
1. Postfix: `.`, `[]`, call `()`
2. Unary: `await`, unary `-`, `!`, `~`, deref `*`, borrow `&`/`&mut`
3. Multiplicative: `* / %`
4. Additive: `+ -`
5. Shift: `<< >>`
6. Comparison: `< <= > >=`
7. Equality: `== !=`
8. Bitwise AND: `&`
9. Bitwise XOR: `^`
10. Bitwise OR: `|`
11. Logical AND: `&&`
12. Logical OR: `||`
13. Coalesce: `??`

Associativity:
- Current parser behavior is left-associative for all binary operators, including `??`.
- `??` is short-circuiting: RHS is evaluated only when LHS is `none`.

## 3. Statement Grammar

```ebnf
block           = "{" { stmt } "}" ;
stmt            = binding_stmt
                | return_stmt | break_stmt | continue_stmt
                | defer_stmt | drop_stmt | comptime_stmt
                | if_stmt | while_stmt | for_stmt | match_stmt
                | assign_stmt | expr_stmt ;

binding_stmt     = [ "mut" ] ident [ ":" type ] "=" expr ";" ;
return_stmt     = "return" [ expr ] ";" ;
break_stmt      = "break" ";" ;
continue_stmt   = "continue" ";" ;
defer_stmt      = "defer" expr ";" ;
drop_stmt       = "drop" expr ";" ;
comptime_stmt   = "comptime" block ;

if_stmt         = "if" expr block [ "else" block ] ;
while_stmt      = "while" expr block ;
for_stmt        = "for" ident "in" for_iterable block ;
for_iterable    = range_iterable | expr ;
range_iterable  = expr ( ".." | "..=" ) expr ;
match_stmt      = "match" expr "{" { expr "=>" block [","] } "}" ;

assign_stmt     = expr ( "=" | "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=" ) expr ";" ;
assign_or_expr  = assign_stmt | expr ;
expr_stmt       = expr ";" ;
```

Constraints:
- Mutable bindings use `mut` keyword: `mut name[: Type] = expr;`.
- Immutable bindings omit `mut`: `name[: Type] = expr;`.
- Expression statements may discard values of any type.
- `return;` is only valid in `-> Void` functions.
- `for` uses only `for <ident> in <iterable-expr> { ... }` syntax; C-style `for init; cond; step { ... }` is invalid.
- Supported `for` iterables are:
  - ranges: `start..end`, `start..=end`
  - `Vec<T>`
  - slices (`[T]`) behind references (`&[T]`, `&mut [T]`)
  - `Bytes` (`Vec<u8>`)

## 4. Module Resolution

```ebnf
import_decl      = "import" ( module_path | str_lit ) [ "as" ident ] [ ";" ] ;
module_path      = ident { ("." | "::") ident } ;
```

Rules:
- `import std.io;` and `import stdlib::io;` both resolve through stdlib lookup.
- `import "path/to/mod";` resolves relative to the importing file (absolute paths resolve as-is).
- Non-stdlib module imports resolve from the nearest ancestor directory containing `Astra.toml`.
- If no package root is present, non-stdlib module imports resolve relative to the importing file directory.
- Stdlib lookup order is:
  - `ASTRA_STDLIB_PATH` (if set)
  - repository `stdlib/` (dev checkout)
  - bundled package path `astra/stdlib` (installed package)

## 5. Type System Rules

Core:
- Primitive roots include `Int`, dynamic-width ints (`iN`/`uN`, `N=1..128`) plus aliases (`isize`, `usize`), `Float` (`f32`, `f64`), `Bool`, `Any`, `Void`, `Never`.
- `T?` desugars to `Option<T>`.
- `none` is only valid in `Option<T>` context.
- `a ?? b` requires `a: Option<T>`, `b: T`, result `T`.
- `Never` is bottom-like and can coerce to any expected type.
- `i1` is rejected in semantic analysis with a hint (`i1 can only represent 0 and -1, did you mean u1?`).

References:
- Shared reference: `&T`.
- Mutable reference: `&mut T`.
- Shared references are copyable values; mutable references are not copyable.
- Returning a reference must be tied to at least one input reference origin.

Function types:
- First-class function type syntax: `fn(T1, T2, ...) R`.
- Calls require exact arity; parameter/return types are checked by semantic analysis.
- Function values may be direct names or indirect (fn-typed expressions).

Unsized:
- `str` and `[T]` are unsized and cannot be used by value in safe surface syntax.
- Use behind references/pointers (e.g. `&str`, `&[T]`, `&mut [T]`).

## 6. Move/Borrow Rules

Copy vs move:
- Copy types (current): scalar numerics, `Bool`, shared refs (`&T`).
- Non-copy values are move-by-default on assignment, argument passing, and return.
- Use-after-move is a semantic error.

Borrowing:
- `&name` creates shared borrow; many shared borrows may coexist.
- `&mut name` creates exclusive mutable borrow.
- While mutably borrowed, owner cannot be read/written directly.
- While shared-borrowed, owner cannot be mutated.
- `&mut` requires mutable source binding (`mut name = ...`), not immutable binding.

Owned-state checks:
- Tracked owned allocations must not be used after `free`/move.
- Reassignment of still-live tracked ownership without drop/move is rejected.
- Function-level live owned leaks are rejected.

## 7. Evaluation Order Guarantees

- Expression evaluation order is strict left-to-right.
- Binary operators evaluate LHS before RHS.
- Function call arguments are evaluated left-to-right.
- Postfix chains evaluate base before field/index/call operand effects.
- `&&`, `||`, and `??` are short-circuiting.
- `defer` executes in LIFO order at function exit.

Numeric semantics:
- Integer arithmetic/bitwise/shift operators require matching integer types.
- Mixed int/float arithmetic and comparison are rejected unless explicit cast (`expr as Type`) is used.
- Implicit conversion between different integer widths/signedness is rejected; explicit cast is required (for example `u4` -> `u8`).
- Cast extension behavior follows source signedness: signed sources use sign extension, unsigned sources use zero extension.
- Right shift is arithmetic for signed integer types and logical for unsigned integer types.
- Width-aware integer builtins are available: `countOnes`, `leadingZeros`, `trailingZeros`.
- Aliases are available: `popcnt`, `clz`, `ctz`.
- Rotate helpers are available: `rotl`, `rotr` (rotation count is modulo bit width).
- Type-level integer queries are available: `bitSizeOf(T)`, `maxVal(T)`, `minVal(T)`.
- JSON conversion for `Any` is shape-stable for arrays/lists and objects/maps.
- Extern function ABIs use proper LLVM attributes: `signext` for signed small integers, `zeroext` for unsigned small integers.
- Overflow mode is controlled by build/check configuration:
  - `check`: default effective overflow `trap` (`--overflow debug` also resolves to `trap`)
  - `build --profile debug` => effective default `trap`
  - `build --profile release` => effective default `wrap`
  - `--overflow trap|wrap|debug` overrides defaults (`debug` resolves by profile for `build`)

## 8. Backend-Defined Behavior Boundaries (`py` vs `llvm/native`)

Frontend (lex/parse/semantic) is shared; backend differences begin at lowering/codegen.

Common contract:
- Diagnostics keep phase prefixes: `LEX`, `PARSE`, `SEM`, `CODEGEN`.
- Type/ownership/borrow checks occur before backend lowering.

`py` backend:
- Emits Python source and executes with Python runtime semantics.
- Broader dynamic runtime support and host interop through emitted Python.
- Numeric behavior and runtime effects follow Python execution model.

`llvm` backend:
- Emits textual LLVM IR through `llvmlite`.
- `Int` lowers to 64-bit integer representation.
- Runtime ABI symbols are declared for lowered builtins (`astra_*` shims).
- Packed integer fields in `@packed struct` are supported up to language maximum width (`128`) and lower through byte-window shift/mask operations.

`native` target:
- Compiles/links emitted LLVM IR with `clang` plus bundled portable runtime source (override path with `ASTRA_RUNTIME_C_PATH`).
- In `--freestanding` mode:
  - hosted/runtime builtins are semantic errors
  - emitted LLVM IR must not reference `astra_*` runtime symbols or non-LLVM external host symbols
  - `native --freestanding` requires `fn _start()`
  - vector operations are provided by runtime-free builtins: `vec_new`, `vec_from`, `vec_len`, `vec_get`, `vec_set`, `vec_push`

Normative boundary rule:
- If a program passes semantic analysis but fails only due to backend lowering limits, failure must be reported as backend-defined (`CODEGEN`) rather than semantic invalidity.

## 9. Diagnostics and Source Span Requirements

Required model:

```text
Span {
  filename: str
  start: int      # byte offset inclusive
  end: int        # byte offset exclusive
  line: int       # 1-based
  col: int        # 1-based
}
```

Rules:
- Every AST node must carry a `Span` (not only line/col).
- All diagnostics (`LEX/PARSE/SEM/CODEGEN`) must use node-associated spans; hardcoded `SEM <input>:1:1` locations are not allowed.
- Internal semantic errors (including ownership/borrow state helpers) must receive and report the current node span.
- Optimizer/IR passes must preserve origin spans or maintain a stable source-map from transformed nodes back to original spans.
- Synthetic/compiler-generated nodes must carry either:
  - parent/trigger span, or
  - explicit synthetic span metadata that points to the nearest user-authored source location.
- Compiler check mode (`astra check`) must expose deterministic structured diagnostics:
  - stable `code` identifiers (`ASTRA-*`)
  - primary span (`filename`, `line`, `col`, `end_line`, `end_col`)
  - optional note spans for related type/context information
- LSP diagnostics must be produced from the same check pipeline used by CLI check mode.
- Check mode should prefer collecting multiple diagnostics in a single run rather than halting at first semantic error.
