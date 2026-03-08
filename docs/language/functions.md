# Functions

## Declaration Forms

- **Regular**: `fn add(a Int, b Int) Int { ... }`
- **Public**: `pub fn add(a Int, b Int) Int { ... }`
- **Async**: `async fn fetch(url String) String { ... }`
- **Unsafe**: `unsafe fn raw_ptr_op(ptr *Int) Int { ... }`
- **Overloads**: Multiple `fn` with same name and different parameter types
- **External**: `extern fn printf(fmt *Char, ...) Int;`

**Important Syntax Changes**:
- Function signatures use `fn name(param_type) return_type` (no `->`)
- Space required before opening brace: `fn main() Int {`
- `impl` blocks have been removed - use standalone functions with explicit `self` parameter

## Returns

- **Explicit**: `return expr;`
- **Void functions**: `return;` or omit return statement
- **Implicit return**: Last expression in function body (for non-Void functions)
- **Main function**: Must return `Int` type

## Parameters

Function parameters use `name Type` syntax:
```astra
fn greet(name String) Void {
    print("Hello, " + name);
}

fn calculate(a Int, b Int, op String) Int {
    // implementation
}
```

## Self Parameters (Standalone Functions)

Since `impl` blocks are removed, methods are implemented as standalone functions:

```astra
// Before (impl blocks - removed)
impl Calculator {
    fn add(self: Calculator, value Int) Int {
        self.value + value
    }
}

// After (standalone functions)
fn add(calculator: Calculator, value Int) Calculator {
    calculator.value = calculator.value + value;
    return calculator;
}
```

## Calls

- **Direct calls**: `add(1, 2)`
- **Method calls**: `obj.method(arg)` (uses UFCS desugaring)
- **UFCS**: `x.f(a, b)` desugars to `f(x, a, b)`
- **Evaluation**: Left-to-right argument evaluation

## Function Overloading

Multiple functions with the same name but different parameter types:

```astra
fn process(value Int) String {
    value.to_string()
}

fn process(value Float) String {
    value.to_string()
}

fn process(value String) String {
    value
}
```

## Type Conversion

- **Int to i64**: Automatic conversion supported
- **Slice types**: `&Vec<T>` can be passed to `&[T]` parameters
- **Nullable types**: `Int` values work with `Int | none` parameters

## Async Functions

```astra
async fn fetch_data(url String) String {
    // async implementation
    response.await
}
```

## Unsafe Functions

```astra
unsafe fn raw_memory_operation(ptr *mut Int) Int {
    // unsafe operations
    *ptr
}
```
