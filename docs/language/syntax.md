# ASTRA Language Syntax

This document describes the syntax features and enhancements of the ASTRA programming language.

## Overview

ASTRA is a modern, statically-typed programming language designed for safety, performance, and expressiveness. The syntax combines familiar patterns from systems programming languages with modern conveniences.

## Basic Syntax

### Declarations

- Functions: `fn name(args) Type { ... }` (note: space before brace, no `->`)
- Structs: `struct Name { field Type, ... }`
- Enums: `enum Name { Variant, Variant(T) }`
- Type aliases: `type Name = Existing;`
- Imports: `import std.io;` or `import "relative/path";`

### Functions
```astra
fn main() Int {
    print("Hello, ASTRA!");
    return 0;
}

fn add(a Int, b Int) Int {
    return a + b;
}

// Async function
async fn fetch_data(url String) String {
    // async implementation
}

// Unsafe function
unsafe fn raw_operation(ptr *mut Int) Int {
    *ptr
}
```

**Important Syntax Notes**:
- Function signatures: `fn name(param_type) return_type` (no `->`)
- Space required before opening brace: `fn main() Int {`
- Parameter syntax: `name Type` (no colon in parameters)
- `impl` blocks have been removed - use standalone functions

### Variables and Types
```astra
// Immutable variable
name = "ASTRA";

// Mutable variable
mut counter = 0;

// Type annotations
mut numbers: Vec<Int> = [1, 2, 3, 4, 5];

// Nullable types
optional_value: Int? = some_value ?? 42;

// References
data = &[1, 2, 3];
mut_data = &mut [1, 2, 3];
```

## Statements

- `name = expr`, `mut name = expr`, `set name = expr`
- `if` / `else`
- `while`
- `for item in iterable { ... }`
- `match`
- `return`, `break`, `continue`

## Control Flow

### For Loops

ASTRA supports iterator-style for loops:

#### Iterator For Loop
```astra
for item in iterable {
    print("Processing: " + str.to_string_int(item));
}
```

#### Enhanced While Loop with Inline Mutable
```astra
while mut i < 5 {
    print("Count: " + str.to_string_int(i));
    i += 1;
}
```

### Pattern Matching

#### Expression Arms (Concise)
```astra
match value {
    42 => "answer",
    _ => "other",
}
```

#### Block Arms (Traditional)
```astra
match value {
    42 => {
        print("answer");
        "answer"
    },
    _ => "other",
}
```

### If Expressions
```astra
result = if condition { true } else { false };
```

### Try-Catch Statements
```astra
try {
    risky_operation()
} catch error {
    handle_error(error)
}
```

## Expressions

### Collections and Literals

#### Vector Literal
```astra
v = [1, 2, 3, 4, 5];
```

#### Map Literal
```astra
m = { "key": "value", "count": 42 };
```

#### Set Literal
```astra
s = {1, 2, 3, 4, 5};
```

### Structs and Literals

#### Struct Definition
```astra
struct Point {
    x: Float,
    y: Float
}
```

#### Struct Literal
```astra
point = Point(3.0, 4.0);
```

### Method Calls

ASTRA supports method call syntax for improved readability:

```astra
length = v.len();
result = data.filter().map().collect();
```

## Syntax Enhancements

The language includes several syntax enhancements that improve code readability and reduce boilerplate:

### Inline Mutable Variables
Mutable variables can be declared inline in loops and conditionals:

```astra
// Before
mut i = 0;
while i < 10 {
    // body
    i += 1;
}

// After
while mut i < 10 {
    // body
    i += 1;
}
```

### Concise Pattern Matching
Single-expression arms in pattern matching eliminate unnecessary braces:

```astra
// Before
match value {
    42 => {
        return "answer";
    },
    _ => {
        return "other";
    }
}

// After
match value {
    42 => "answer",
    _ => "other",
}
```

## Type System

ASTRA features a strong static type system with:
- Type inference
- Generic types
- Union types
- Pattern matching on types

## Memory Safety

The language includes built-in memory safety features:
- Automatic memory management
- Borrow checking concepts
- Safe pointer operations

## GPU Computing

ASTRA has first-class GPU compute support:

```astra
gpu fn vector_add(a: [Float], b: [Float]) -> [Float] {
    // GPU kernel implementation
}

// Launch GPU computation
gpu.launch(vector_add, input_a, input_b);
```

## Conclusion

The ASTRA syntax combines the safety and performance of systems programming with the expressiveness of modern languages. The enhancements focus on reducing boilerplate while maintaining clarity and explicitness.

## Additional Expressions

- arithmetic, logical, and bitwise operators
- casts: `expr as Type`
- coalescing: `option_value ?? fallback`
- calls/indexing/field access
- layout/type queries (`sizeof`, `alignof`, `bitSizeOf`, `maxVal`, `minVal`)
