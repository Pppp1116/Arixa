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

type Bytes = Vec<u8>;

unsafe extern "libc.so.6" fn c_abs(x Int) Int;

fn id<T>(x T) T{
    return x;
}
pub async fn worker(n Int) Int{
    return n;
}
fn main() Int{
    return 0;
}
```

Notes:
- Parameter typed form is `name Type` (no `:`).
- Field/local typed form is `name: Type`.
- `@packed` is currently supported only on `struct` declarations.
- `Vec<T>` is a built-in owned growable buffer type used by `Bytes = Vec<u8>`.
- Legacy module separator `::` is still accepted (`import stdlib::io as io;`).
- Any function may omit return type; omitted means `Void`.

## 2. Functions and types

```astra
fn add(a Int, b Int) Int{
    return a + b;
}
fn wrap(f fn(Int) Int, v Int) Int{
    return f(v);
}
fn takes_ref(x &Int, y &mut Int) Int{
    return 0;
}
fn vec_sum(xs &[Int]) Int{
    return 0;
}
fn vec_sum_mut(xs &mut [Int]) Int{
    return 0;
}
fn text_len(s &str) Int{
    return len(s);
}
```

Type forms:
- Primitive scalars/control: `Int`, `Float`, `Bool`, `Any`, `Void`, `Never`
- Integer families: `iN`/`uN` where `N` is `1..128`, plus `isize`/`usize` aliases
- Function types: `fn(T1, T2) R`
- Generic/union types: `Vec<u8>`, `User | NotFoundError`, `String?`
- Borrow types: `&T`, `&mut T`
- Slice type: `[T]` (unsized; legal as `&[T]`, `&mut [T]`, or behind pointers/DST positions)
- Plain by-value slice parameters/locals like `[Int]` are rejected in safe surface syntax.
- Owned bytes alias: `Bytes` (canonical alias of `Vec<u8>`)
- Core stdlib owned types: `String`, `Vec<T>` (`Bytes = Vec<u8>`)
- Builtin unsized text type: `str` (legal as `&str` or behind pointers/DST positions)
- Sugar: `T?` desugars to `T | none`
- Integer literal suffixes are supported (for example `15u4`, `3i7`)
- Signed `i1` is rejected with a diagnostic hint recommending `u1`

## 3. Statements

```astra
fn main() Int{
  base: i16 = 12;
  mut acc = 0;
  note: &str = "ok";

  if acc == 0 {
    acc = base;
  } else {
    acc += 1;
  }

  while acc < 20 {
    acc += 1;
  }

  for i in 0..3 {
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
- `name = ...` creates an immutable binding.
- `mut name = ...` creates a mutable binding.
- `set name = ...` reassigns an existing mutable binding.
- Assignment operators: `=`, `+=`, `-=`, `*=`, `/=`, `%=`.
- Bare expression statements must have type `Void` or `Never`.
- `drop expr;` consumes `expr` and runs its destructor at that point.
- Use `_ = expr;` to explicitly ignore/discard a produced value.
- `return;` is valid only in `Void` functions.
- `return` is for early exit; trailing expression returns implicitly in non-`Void` functions.

## 4. Expressions

```astra
a = 1 + 2 * 3;
b = -a;
c = !false;
d = arr[0].field;
e = call(a, b, c);
f = await e;
maybe: Int | none = none;
g = maybe ?? 42;
h: Int? = none;
bs: Bytes = get_payload();
first = bs[0];
```

Supported operators:
- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Bitwise/shift: `&`, `|`, `^`, `<<`, `>>`
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Logical: `&&`, `||`
- Null-coalescing: `??`

Nullable/union rules:
- `none` does not have a standalone type.
- `none` is only valid where a nullable union is expected.
- `??` requires left operand `T | none` and right operand `T`.
- `??` is short-circuiting; rhs is evaluated only when lhs is `none`.
- `a!` propagates non-success union branches to the caller.
- Use unions (`A | B | ...`) for absence/error modeling.

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
- Mutable borrows require a mutable source binding (`mut name = ...`).
- References carry lifetimes; lifetimes are currently elided in surface syntax.
- Elision baseline: input reference parameters receive distinct inferred lifetimes unless constrained by return type.
- Returning a reference requires that the returned lifetime be tied to at least one input reference; otherwise it is rejected.
- Example (ok): `fn first(xs &[Int]) &Int`
- Example (error): `fn bad() &Int`

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
- `get(i)`-style APIs return `T | none` (`T?`) for non-trapping access.
- Direct indexing of `String`/`str` is rejected; index bytes/slices (`Vec<u8>`, `Bytes`, `[u8]`) instead.

Move/copy rules:
- Default for assignment, argument passing, and return is move semantics.
- Copy-by-default set is currently: scalar numerics (`Int` and `iN`/`uN` ints), `Float`, `Bool`, and shared references (`&T`).
- Other values are move-only unless explicitly designated copyable by future trait/type rules.

Never rule:
- `Never` is coercible to any type `T`, including `Void`.
- For joins, `Never` behaves as bottom (`join(Never, T) = T`).

## 5. Compile-time blocks

```astra
fn fib(n Int) Int{
  if n <= 1 { return n; }
  return fib(n - 1) + fib(n - 2);
}

fn main() Int{
  comptime {
    k = fib(8);
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
  - `&T`, `&mut T`, and `fn(...) ...` values -> pointer-sized integers (`u64` on x86-64).
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
  - First-class function pointers are supported (`fn(T...) R` values).
  - Calls through function pointers lower to indirect machine calls.
- Additional native-lowered constructs:
  - `async`/`await` lower through direct native control flow/runtime helper paths; no full scheduler contract is guaranteed yet.
  - Aggregate and dynamic values lower as opaque pointer-sized handles at the ABI boundary.
  - `match`, struct field access/assignment, and array/slice indexing/get are lowered directly.
  - `@packed struct` field accesses/updates lower through shift/mask read-modify-write paths (packed integer fields are supported up to language maximum width `128`).

## 7. EBNF snapshot

```ebnf
program      = { import_decl | type_decl | struct_decl | enum_decl | extern_fn | fn_decl } ;
fn_decl      = ["pub"] ["async"] ["unsafe"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" [type] ["where" where_bound {"," where_bound}] block ;
extern_fn    = ["unsafe"] "extern" string "fn" ident "(" [param {"," param}] ")" [type] ";" ;
param        = ["mut"] ident type ;
where_bound  = ident ":" ident {"+" ident} ;
type         = postfix_type ;
postfix_type = primary_type ["?"] ;
primary_type = ident ["<" type {"," type} ">"]
             | "&" ["mut"] type
             | "[" type "]"
             | "fn" "(" [type {"," type}] ")" type
             | "(" type ")" ;
stmt         = bind_stmt | set_stmt | comptime_stmt | defer_stmt | drop_stmt | return_stmt | if_stmt | while_stmt | for_stmt | match_stmt | assign_stmt | expr ";" ;
bind_stmt    = ["mut"] ident [":" type] "=" expr ";" ;
set_stmt     = "set" expr ("=" | "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=") expr ";" ;
drop_stmt    = "drop" expr ";" ;
for_stmt     = "for" ident "in" for_iterable block ;
for_iterable = range_iterable | expr ;
range_iterable = expr (".." | "..=") expr ;
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
postfix_expr = atom { "." ident | "[" expr "]" | "(" [expr {"," expr}] ")" | "!" } ;
atom         = int | float | string | typed_int | "none" | ident | "(" expr ")" | layout_query | type_query ;
typed_int    = int int_type_tok ;
int_type_tok = ("i" | "u") nonzero_digit {digit} ;
layout_query = "sizeof" "(" type ")" | "alignof" "(" type ")" | "size_of" "(" expr ")" | "align_of" "(" expr ")" ;
type_query   = "bitSizeOf" "(" type ")" | "maxVal" "(" type ")" | "minVal" "(" type ")" ;
```
