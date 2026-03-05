# Astra Language Syntax Book (Current)

This book describes the current user-facing Astra syntax in this repository.

## 1. Top-level declarations

```astra
import std.io as io;

type UserId = Int;

pub struct Point {
  x: Int,
  y: Int,
}

enum State {
  Idle,
  Busy(Int),
}

enum Option<T> {
  None,
  Some(T),
}

enum Result<T, E> {
  Ok(T),
  Err(E),
}

type Bytes = Vec<u8>;

unsafe extern "libc.so.6" fn c_abs(x: Int) -> Int;

impl fn id<T>(x: T) -> T { return x; }
pub async fn worker(n: Int) -> Int { return n; }
fn main() -> Int { return 0; }
```

Notes:
- Canonical typed form is `name: Type`.
- Params/fields still accept legacy `name Type`.
- `@packed` is currently supported only on `struct` declarations.
- `Vec<T>` is a built-in owned growable buffer type used by `Bytes = Vec<u8>`.
- Legacy module separator `::` is still accepted (`import stdlib::io as io;`).

## 2. Functions and types

```astra
fn add(a: Int, b: Int) -> Int { return a + b; }
fn wrap(f: fn(Int) -> Int, v: Int) -> Int { return f(v); }
fn takes_ref(x: &Int, y: &mut Int) -> Int { return 0; }
fn vec_sum(xs: &[Int]) -> Int { return 0; }
fn vec_sum_mut(xs: &mut [Int]) -> Int { return 0; }
fn text_len(s: &str) -> Int { return len(s); }
```

Type forms:
- Primitive scalars/control: `Int`, `Float`, `Bool`, `Any`, `Void`, `Never`
- Integer families: `iN`/`uN` where `N` is `1..128`, plus `isize`/`usize` aliases
- Function types: `fn(T1, T2) -> R`
- Generic types: `Option<User>`, `Result<Int, String>`, `Vec<u8>`
- Borrow types: `&T`, `&mut T`
- Slice type: `[T]` (unsized; legal as `&[T]`, `&mut [T]`, or behind pointers/DST positions)
- Plain by-value slice parameters/locals like `[Int]` are rejected in safe surface syntax.
- Owned bytes alias: `Bytes` (canonical alias of `Vec<u8>`)
- Core stdlib owned types: `String`, `Vec<T>` (`Bytes = Vec<u8>`)
- Builtin unsized text type: `str` (legal as `&str` or behind pointers/DST positions)
- Sugar: `T?` desugars to `Option<T>`
- Integer literal suffixes are supported (for example `15u4`, `3i7`)
- Signed `i1` is rejected with a diagnostic hint recommending `u1`

## 3. Statements

```astra
fn main() -> Int {
  fixed base: i16 = 12;
  let mut acc = 0;
  let note: &str = "ok";

  if acc == 0 {
    acc = base;
  } else {
    acc += 1;
  }

  while acc < 20 {
    acc += 1;
  }

  for let mut i = 0; i < 3; i += 1 {
    acc += i;
  }

  for item in [1, 2, 3] {
    acc += item;
  }

  defer print("leaving");

  match acc {
    0 => { return 0; }
    1 => { return 1; }
  }

  return acc;
}
```

Binding rules:
- `fixed` is immutable.
- `let mut` is mutable.
- Assignment operators: `=`, `+=`, `-=`, `*=`, `/=`, `%=`.
- Bare expression statements must have type `Void` or `Never`.
- `drop expr;` consumes `expr` and runs its destructor at that point.
- Use `let _ = expr;` (or `_ = expr;`) to explicitly ignore/discard a produced value.
- `return;` is valid only in `-> Void` functions.

## 4. Expressions

```astra
let a = 1 + 2 * 3;
let b = -a;
let c = !false;
let d = arr[0].field;
let e = call(a, b, c);
let f = await e;
let maybe: Option<Int> = none;
let g = maybe ?? 42;
let h: Option<Int> = none;
let bs: Bytes = get_payload();
let first = bs[0];
```

Supported operators:
- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Bitwise/shift: `&`, `|`, `^`, `<<`, `>>`
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Logical: `&&`, `||`
- Null-coalescing: `??`

Option rules:
- `none` does not have a standalone type.
- `none` is only valid where `Option<T>` is expected.
- `??` requires left operand `Option<T>` and right operand `T`.
- `??` is short-circuiting; rhs is evaluated only when lhs is `none`.
- Use `Option<T>` for presence/absence; use `Result<T, E>` for recoverable failures with error detail.

Integer utility rules:
- Type queries: `bitSizeOf(T)`, `maxVal(T)`, `minVal(T)`.
- Width-aware bit intrinsics: `countOnes(x)`, `leadingZeros(x)`, `trailingZeros(x)`.
- Implicit conversion across integer widths/signedness is rejected; use `as` explicitly.

Borrow checker rules:
- `&expr` creates a shared borrow.
- `&mut expr` creates an exclusive mutable borrow.
- Multiple shared borrows are allowed.
- Mutable borrows are exclusive (no other shared or mutable borrow of the same binding).
- A binding cannot be mutated while any shared borrow exists.
- A binding cannot be used directly while a mutable borrow exists (use the reference instead).
- Mutable borrows require a mutable source binding (`let mut`), not `fixed`.
- References carry lifetimes; lifetimes are currently elided in surface syntax.
- Elision baseline: input reference parameters receive distinct inferred lifetimes unless constrained by return type.
- Returning a reference requires that the returned lifetime be tied to at least one input reference; otherwise it is rejected.
- Example (ok): `fn first(xs: &[Int]) -> &Int`
- Example (error): `fn bad() -> &Int`

Text/buffer rules:
- `String` is an owned stdlib UTF-8 text type (not a primitive scalar).
- `str` is an unsized UTF-8 text DST; use as `&str` (or other pointer-backed DST position).
- String literals conceptually have type `&'static str` (lifetime syntax is currently elided in user code).
- `Vec<T>` is an owned stdlib growable, heap-backed buffer (conceptually ptr/len/cap; moves copy that handle, not elements).
- Borrowing `Vec<T>` produces slices (`&[T]`, `&mut [T]`) for view-based APIs.
- Element indexing is via `[]`; iteration over slices/vectors is in index order.
- `[T]` is an unsized slice DST.
- `Bytes` aliases `Vec<u8>`.
- Indexing (`v[i]`, `s[i]`) is bounds-checked and traps/panics on out-of-bounds in safe code.
- `get(i)`-style APIs return `Option<T>` (`T?`) for non-trapping access.
- Direct indexing of `String`/`str` is rejected; index bytes/slices (`Vec<u8>`, `Bytes`, `[u8]`) instead.

Move/copy rules:
- Default for assignment, argument passing, and return is move semantics.
- Copy-by-default set is currently: scalar numerics (`Int` and `iN`/`uN` ints), `Float`, `Bool`, and shared references (`&T`).
- Other values are move-only unless constrained through impl selection (`where T: Copy` etc.).

Generic constraints:
- `impl fn` specializations may include `where` constraints over type variables.
- Supported constraint names are currently `Copy`, `Send`, and `Sync`.

Pattern matching:
- `match` arms support literal patterns, wildcard `_`, bind patterns (`name`), enum variant patterns (`Enum.Variant`, `Enum.Variant(x, ...)`), and optional guards (`if cond`).

Never rule:
- `Never` is coercible to any type `T`, including `Void`.
- For joins, `Never` behaves as bottom (`join(Never, T) = T`).

## 5. Compile-time blocks

```astra
fn fib(n: Int) -> Int {
  if n <= 1 { return n; }
  return fib(n - 1) + fib(n - 2);
}

fn main() -> Int {
  comptime {
    let k = fib(8);
  }
  return 0;
}
```

`comptime { ... }` runs deterministic/pure code at compile time.

## 6. Backend contract (x86-64)

Current x86-64 backend contract (System V ABI oriented):

- Scalar lowering:
  - `Bool` -> logical `i1`, materialized as `0/1` in integer registers (`al`/`rax` path).
  - `Int`, `iN`/`uN`, `isize`, `usize` -> integer register class.
  - `&T`, `&mut T`, and `fn(...) -> ...` values -> pointer-sized integers (`u64` on x86-64).
  - `Float`/`f32`/`f64` -> SSE class (`xmm*` registers).
- Calls/returns:
  - Integer/pointer args use `rdi, rsi, rdx, rcx, r8, r9`, overflow args spill to stack.
  - Floating args use `xmm0..xmm7`, overflow args spill to stack.
  - Integer/pointer returns use `rax`; float returns use `xmm0`.
  - Call sites maintain 16-byte stack alignment before `call`.
- Runtime ABI symbols used by lowered builtins:
  - `astra_print_i64(Int) -> Void`
  - `astra_print_str(usize ptr, usize len) -> Void`
  - `astra_alloc(usize size, usize align) -> usize`
  - `astra_free(usize ptr, usize size, usize align) -> Void`
  - `astra_panic(usize ptr, usize len) -> Never`
- Deferred calls:
  - `defer <expr>;` is lowered to function-exit execution in reverse order (LIFO).
  - Defer sites are counted, so loop-contained defer expressions execute once per hit.
- Function values:
  - First-class function pointers are supported (`fn(T...) -> R` values).
  - Calls through function pointers lower to indirect machine calls.
- Additional native-lowered constructs:
  - `async` declarations and `await` expressions lower to direct native control flow.
  - Aggregate and dynamic values lower as opaque pointer-sized handles at the ABI boundary.
  - `match`, struct field access/assignment, and array/slice indexing/get are lowered directly.
  - `@packed struct` field accesses/updates lower through shift/mask read-modify-write paths (packed integer fields are supported up to language maximum width `128`).

## 7. EBNF snapshot

```ebnf
program      = { import_decl | type_decl | struct_decl | enum_decl | extern_fn | fn_decl | impl_fn } ;
fn_decl      = ["pub"] ["async"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" "->" type block ;
impl_fn      = ["pub"] "impl" ["async"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" "->" type block ;
extern_fn    = ["unsafe"] "extern" string "fn" ident "(" [param {"," param}] ")" "->" type ";" ;
param        = ident ":" type ;
type         = postfix_type ;
postfix_type = primary_type ["?"] ;
primary_type = ident ["<" type {"," type} ">"]
             | "&" ["mut"] type
             | "[" type "]"
             | "fn" "(" [type {"," type}] ")" "->" type
             | "(" type ")" ;
stmt         = let_stmt | fixed_stmt | comptime_stmt | defer_stmt | drop_stmt | return_stmt | if_stmt | while_stmt | for_stmt | match_stmt | assign_stmt | expr ";" ;
let_stmt     = "let" ["mut"] ident [":" type] "=" expr ";" ;
fixed_stmt   = "fixed" ident [":" type] "=" expr ";" ;
drop_stmt    = "drop" expr ";" ;
assign_stmt  = expr ("=" | "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=") expr ";" ;
expr         = coalesce_expr ;
coalesce_expr = logic_or_expr { "??" logic_or_expr } ;
logic_or_expr = logic_and_expr { "||" logic_and_expr } ;
logic_and_expr = bit_or_expr { "&&" bit_or_expr } ;
bit_or_expr  = bit_xor_expr { "|" bit_xor_expr } ;
bit_xor_expr = bit_and_expr { "^" bit_and_expr } ;
bit_and_expr = compare_expr { "&" compare_expr } ;
compare_expr = shift_expr { ("==" | "!=" | "<" | "<=" | ">" | ">=") shift_expr } ;
shift_expr   = add_expr { ("<<" | ">>") add_expr } ;
add_expr     = mul_expr { ("+" | "-") mul_expr } ;
mul_expr     = unary_expr { ("*" | "/" | "%") unary_expr } ;
unary_expr   = ["await"] ( ("-" | "!" | "~" | "*" | "&" ["mut"]) unary_expr | cast_expr ) ;
cast_expr    = postfix_expr { "as" type } ;
postfix_expr = atom { "." ident | "[" expr "]" | "(" [expr {"," expr}] ")" } ;
atom         = int | float | string | typed_int | "none" | ident | "(" expr ")" | layout_query | type_query ;
typed_int    = int int_type_tok ;
int_type_tok = ("i" | "u") nonzero_digit {digit} ;
layout_query = "sizeof" "(" type ")" | "alignof" "(" type ")" | "size_of" "(" expr ")" | "align_of" "(" expr ")" ;
type_query   = "bitSizeOf" "(" type ")" | "maxVal" "(" type ")" | "minVal" "(" type ")" ;
```
