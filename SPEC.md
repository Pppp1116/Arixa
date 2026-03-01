# Astra Language Spec (Implementation-Facing)

This document defines the current language contract in a single place for parser/semantic/codegen behavior.

## 1. Lexical Grammar

Source is tokenized as:

```ebnf
whitespace      = { " " | "\t" | "\r" | "\n" } ;
line_comment    = "//" { any_char - "\n" } ;
doc_comment     = "///" { any_char - "\n" } ;
block_comment   = "/*" { any_char } "*/" ;

ident           = ( "_" | letter ) { "_" | letter | digit } ;
int_lit         = digit { digit } ;
float_lit       = digit { digit } "." digit { digit } ;
str_lit         = "\"" { char | escape } "\"" ;
str_multi_lit   = "\"\"\"" { any_char } "\"\"\"" ;
char_lit        = "'" { char | escape } "'" ;
bool_lit        = "true" | "false" ;

keyword         = "fn" | "let" | "fixed" | "return" | "if" | "else" | "while"
                | "for" | "break" | "continue" | "struct" | "enum" | "type"
                | "import" | "mut" | "pub" | "extern" | "async" | "await"
                | "unsafe" | "impl" | "match" | "defer" | "drop"
                | "comptime" | "none" | "in" | "as" ;

multi_op        = "&&=" | "||=" | "..." | "::" | "=>" | "->" | "==" | "!="
                | "<=" | ">=" | "&&" | "||" | "??"
                | "+=" | "-=" | "*=" | "/=" | "%="
                | "<<" | ">>" | ".." ;
single_op       = "{" | "}" | "(" | ")" | "<" | ">" | ";" | "," | "=" | "+"
                | "-" | "*" | "/" | "%" | "!" | "?" | "[" | "]" | ":"
                | "." | "&" | "|" | "^" | "~" | "@" ;
```

Notes:
- Unterminated block comments/strings/chars are lexer errors (`LEX file:line:col: ...`).
- `doc_comment` tokens are consumed by parser in declaration/block positions.
- `str_multi_lit` is tokenized but not currently accepted by expression parsing.

## 2. Expression Grammar

```ebnf
expr            = binary_expr ;
binary_expr     = unary_expr { bin_op unary_expr } ;
unary_expr      = [ "await" ] ( ( "-" | "!" | "~" | "*" | "&" [ "mut" ] ) unary_expr
                  | postfix_expr ) ;
postfix_expr    = atom { "." ident | "[" expr "]" | "(" [expr {"," expr}] ")" } ;
atom            = int_lit | float_lit | str_lit | char_lit
                | bool_lit | "none" | ident | array_lit | "(" expr ")" ;
array_lit       = "[" [expr {"," expr}] "]" ;

bin_op          = "??" | "||" | "&&" | "==" | "!=" | "<" | "<=" | ">" | ">="
                | "+" | "-" | "*" | "/" | "%" ;
```

Precedence (high to low):
1. Postfix: `.`, `[]`, call `()`
2. Unary: `await`, unary `-`, `!`, `~`, deref `*`, borrow `&`/`&mut`
3. Multiplicative: `* / %`
4. Additive: `+ -`
5. Comparison: `< <= > >=`
6. Equality: `== !=`
7. Logical AND: `&&`
8. Logical OR: `||`
9. Coalesce: `??`

Associativity:
- Current parser behavior is left-associative for all binary operators, including `??`.
- `??` is short-circuiting: RHS is evaluated only when LHS is `none`.

## 3. Statement Grammar

```ebnf
block           = "{" { stmt } "}" ;
stmt            = let_stmt | fixed_stmt
                | return_stmt | break_stmt | continue_stmt
                | defer_stmt | drop_stmt | comptime_stmt
                | if_stmt | while_stmt | for_stmt | match_stmt
                | assign_stmt | expr_stmt ;

let_stmt        = "let" [ "mut" ] ident [ ":" type ] "=" expr ";" ;
fixed_stmt      = "fixed" ident [ ":" type ] "=" expr ";" ;
return_stmt     = "return" [ expr ] ";" ;
break_stmt      = "break" ";" ;
continue_stmt   = "continue" ";" ;
defer_stmt      = "defer" expr ";" ;
drop_stmt       = "drop" expr ";" ;
comptime_stmt   = "comptime" block ;

if_stmt         = "if" expr block [ "else" block ] ;
while_stmt      = "while" expr block ;
for_stmt        = "for" ( ident "in" expr
                | [ (let_stmt | fixed_stmt | expr ";") ] [expr] ";" [assign_or_expr] ) block ;
match_stmt      = "match" expr "{" { expr "=>" block [","] } "}" ;

assign_stmt     = expr ( "=" | "+=" | "-=" | "*=" | "/=" | "%=" ) expr ";" ;
assign_or_expr  = assign_stmt | expr ;
expr_stmt       = expr ";" ;
```

Constraints:
- `fixed` bindings are immutable and cannot be `mut`.
- Bare expression statements must type-check to `Void` or `Never`.
- `return;` is only valid in `-> Void` functions.

## 4. Type System Rules

Core:
- Primitive roots include `Int`, fixed-width ints (`i8...u128`, `isize`, `usize`), `Float` (`f32`, `f64`), `Bool`, `Any`, `Void`, `Never`.
- `T?` desugars to `Option<T>`.
- `none` is only valid in `Option<T>` context.
- `a ?? b` requires `a: Option<T>`, `b: T`, result `T`.
- `Never` is bottom-like and can coerce to any expected type.

References:
- Shared reference: `&T`.
- Mutable reference: `&mut T`.
- Shared references are copyable values; mutable references are not copyable.
- Returning a reference must be tied to at least one input reference origin.

Function types:
- First-class function type syntax: `fn(T1, T2, ...) -> R`.
- Calls require exact arity; parameter/return types are checked by semantic analysis.
- Function values may be direct names or indirect (fn-typed expressions).

Unsized:
- `str` and `[T]` are unsized and cannot be used by value in safe surface syntax.
- Use behind references/pointers (e.g. `&str`, `&[T]`, `&mut [T]`).

## 5. Move/Borrow Rules

Copy vs move:
- Copy types (current): scalar numerics, `Bool`, shared refs (`&T`).
- Non-copy values are move-by-default on assignment, argument passing, and return.
- Use-after-move is a semantic error.

Borrowing:
- `&name` creates shared borrow; many shared borrows may coexist.
- `&mut name` creates exclusive mutable borrow.
- While mutably borrowed, owner cannot be read/written directly.
- While shared-borrowed, owner cannot be mutated.
- `&mut` requires mutable source binding (`let mut ...`), not `fixed`.

Owned-state checks:
- Tracked owned allocations must not be used after `free`/move.
- Reassignment of still-live tracked ownership without drop/move is rejected.
- Function-level live owned leaks are rejected.

## 6. Evaluation Order Guarantees

- Expression evaluation order is strict left-to-right.
- Binary operators evaluate LHS before RHS.
- Function call arguments are evaluated left-to-right.
- Postfix chains evaluate base before field/index/call operand effects.
- `&&`, `||`, and `??` are short-circuiting.
- `defer` executes in LIFO order at function exit.

## 7. Backend-Defined Behavior Boundaries (`py` vs `x86_64`)

Frontend (lex/parse/semantic) is shared; backend differences begin at lowering/codegen.

Common contract:
- Diagnostics keep phase prefixes: `LEX`, `PARSE`, `SEM`, `CODEGEN`.
- Type/ownership/borrow checks occur before backend lowering.

`py` backend:
- Emits Python source and executes with Python runtime semantics.
- Broader dynamic runtime support and host interop through emitted Python.
- Numeric behavior and runtime effects follow Python execution model.

`x86_64` backend:
- System V ABI-oriented lowering with explicit int/SSE classes.
- `Int` lowers to 64-bit integer ABI representation.
- Runtime ABI symbols are required for lowered builtins (`astra_*` shims).
- Backend has explicit unsupported-case errors for some constructs/types; these are `CODEGEN` errors.
- `native` target additionally requires external toolchain (`nasm`, `ld`).

Normative boundary rule:
- If a program passes semantic analysis but fails only due to backend lowering limits, failure must be reported as backend-defined (`CODEGEN`) rather than semantic invalidity.

## 8. Diagnostics and Source Span Requirements

Current issue:
- Some semantic internal checks emit hardcoded `SEM <input>:1:1` (e.g. internal owned-state checks), which hides real source locations.
- Optimizer/IR transforms may lose clean origin mapping.

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
- All diagnostics (`LEX/PARSE/SEM/CODEGEN`) must use node-associated spans.
- Internal semantic errors (including ownership/borrow state helpers) must receive and report the current node span.
- Optimizer/IR passes must preserve origin spans or maintain a stable source-map from transformed nodes back to original spans.
- Synthetic/compiler-generated nodes must carry either:
  - parent/trigger span, or
  - explicit synthetic span metadata that points to the nearest user-authored source location.
