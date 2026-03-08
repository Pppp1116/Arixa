# Error Reporting Guide

This guide covers ASTRA's enhanced error reporting system, which provides detailed, actionable error messages to help you debug and fix issues in your ASTRA code.

## Overview

ASTRA's error reporting system is designed to be:
- **Clear and concise**: Easy to understand error messages
- **Contextual**: Shows relevant code context and highlights problem areas
- **Actionable**: Provides specific suggestions for fixing errors
- **Consistent**: Uniform formatting across all error types
- **Educational**: Helps you learn the language through error messages

## Error Message Format

### Basic Structure

```
❌ ERROR: error_type
   📍 filename:line:column

📄 Context:
   1 | fn main() -> Int {
   2 |     let x = 42
   3 | }
     | ^

💬 Error description message

💡 Suggestions:
   1. Action title
      Detailed description of what to do
      Example: `code_example`

🔍 Error code: ERROR001
   Learn more: https://astra-lang.dev/errors/ERROR001
```

### Components

- **Severity Indicator**: ❌ (error), ⚠️ (warning), ℹ️ (info)
- **Error Type**: Category of error (syntax_error, type_mismatch, etc.)
- **Location**: File path, line number, and column
- **Context**: Surrounding code with visual highlight
- **Message**: Clear description of what went wrong
- **Suggestions**: Actionable steps to fix the error
- **Error Code**: Unique identifier for documentation lookup

## Error Categories

### 1. Syntax Errors (PARSE001-PARSE099)

These errors occur when the code doesn't follow ASTRA's grammar rules.

#### Common Examples

**Missing Semicolon (PARSE001)**
```astra
fn main() -> Int {
    let x = 42  // Missing semicolon
    return x
}
```

**Error Output:**
```
❌ ERROR: syntax_error
   📍 example.arixa:2:14

📄 Context:
   1 | fn main() -> Int {
   2 |     let x = 42
   3 |     return x
   4 | }
     | ^^^^^^^^

💬 Expected ';' at end of statement

💡 Suggestions:
   1. Add missing semicolon
      Add a semicolon at the end of the statement
      Example: `let x = 42;`

🔍 Error code: PARSE001
   Learn more: https://astra-lang.dev/errors/PARSE001
```

**Mismatched Brackets (PARSE002)**
```astra
fn main() -> Int {
    let x = [1, 2, 3  // Missing closing bracket
    return x[0]
}
```

**Error Output:**
```
❌ ERROR: syntax_error
   📍 example.arixa:2:20

📄 Context:
   1 | fn main() -> Int {
   2 |     let x = [1, 2, 3
   3 |     return x[0]
   4 | }
     | ^^^^^^^^^^^^^^^^^

💬 Expected ']' to close array literal

💡 Suggestions:
   1. Add closing bracket
      Add the missing ']' to close the array literal
      Example: `let x = [1, 2, 3];`

🔍 Error code: PARSE002
   Learn more: https://astra-lang.dev/errors/PARSE002
```

### 2. Semantic Errors (SEM100-SEM499)

These errors occur when code is syntactically correct but doesn't make sense semantically.

#### Common Examples

**Undefined Variable (SEM101)**
```astra
fn main() -> Int {
    return undefined_var  // Variable not defined
}
```

**Error Output:**
```
❌ ERROR: undefined_name
   📍 example.arixa:2:12

📄 Context:
   1 | fn main() -> Int {
   2 |     return undefined_var
   3 | }
     | ^^^^^^^^^^^^^^^^

💬 Name 'undefined_var' is not defined in this scope

💡 Suggestions:
   1. Check spelling
      Verify the name is spelled correctly
   2. Declare variable
      Declare the variable before using it
      Example: `let undefined_var = 42;`

🔍 Error code: SEM101
   Learn more: https://astra-lang.dev/errors/SEM101
```

**Type Mismatch (SEM102)**
```astra
fn main() -> Int {
    let x = "hello"  // String, but function expects Int
    return x
}
```

**Error Output:**
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

**Borrow Checker Error (SEM200)**
```astra
fn main() -> Int {
    let x = 42;
    let r1 = &x;
    let r2 = &mut x;  // Cannot borrow mutably while already borrowed
    return *r2;
}
```

**Error Output:**
```
❌ ERROR: borrow_checker
   📍 example.arixa:4:14

📄 Context:
   1 | fn main() -> Int {
   2 |     let x = 42;
   3 |     let r1 = &x;
   4 |     let r2 = &mut x;
   5 |     return *r2;
   6 | }
     |              ^^^

💬 Cannot create mutable reference to `x` because it is already borrowed

💡 Suggestions:
   1. Check ownership
      Review ownership and borrowing rules
   2. Use reference
      Use an immutable reference instead
      Example: `let r2 = &x;`

🔍 Error code: SEM200
   Learn more: https://astra-lang.dev/errors/SEM200
```

### 3. Code Generation Errors (CODEGEN500-CODEGEN599)

These errors occur during the code generation phase.

#### Common Examples

**Unsupported Operation (CODEGEN501)**
```astra
fn main() -> Int {
    // Operation not supported in target backend
    return unsupported_operation()
}
```

**Error Output:**
```
❌ ERROR: codegen_error
   📍 example.arixa:3:12

📄 Context:
   1 | fn main() -> Int {
   2 |     // Operation not supported in target backend
   3 |     return unsupported_operation()
   4 | }
     |            ^^^^^^^^^^^^^^^^^^^^^^^

💬 Operation 'unsupported_operation' is not supported in LLVM backend

💡 Suggestions:
   1. Check backend support
      Verify the operation is supported in your target backend
   2. Use alternative approach
      Consider using a different approach to achieve the same result

🔍 Error code: CODEGEN501
   Learn more: https://astra-lang.dev/errors/CODEGEN501
```

## Error Severity Levels

### Errors (❌)
- **Impact**: Compilation fails
- **Required Action**: Must be fixed before code can run
- **Examples**: Syntax errors, type mismatches, undefined names

### Warnings (⚠️)
- **Impact**: Compilation succeeds but may have issues
- **Recommended Action**: Should be reviewed and potentially fixed
- **Examples**: Unused variables, dead code, potential issues

### Info (ℹ️)
- **Impact**: Compilation succeeds, informational only
- **Optional Action**: May be ignored or used for optimization
- **Examples**: Performance suggestions, style recommendations

## Error Codes Reference

### Syntax Errors (PARSE001-PARSE099)
- **PARSE001**: Missing semicolon
- **PARSE002**: Mismatched brackets
- **PARSE003**: Invalid token
- **PARSE004**: Expected identifier
- **PARSE005**: Invalid function signature

### Semantic Errors (SEM100-SEM499)
- **SEM101**: Undefined name
- **SEM102**: Type mismatch
- **SEM103**: Duplicate definition
- **SEM104**: Invalid operation
- **SEM200**: Borrow checker error
- **SEM201**: Ownership error
- **SEM202**: Mutability conflict

### Code Generation Errors (CODEGEN500-CODEGEN599)
- **CODEGEN501**: Unsupported operation
- **CODEGEN502**: Backend limitation
- **CODEGEN503**: Optimization error

## Best Practices

### 1. Reading Error Messages

1. **Start with the error type** - Understand the category of problem
2. **Check the location** - Look at the highlighted code
3. **Read the message** - Understand what went wrong
4. **Review suggestions** - Follow the actionable steps provided
5. **Look up the error code** - Get more detailed information

### 2. Debugging Workflow

1. **Fix syntax errors first** - These block all other analysis
2. **Address semantic errors** - These affect program correctness
3. **Review warnings** - These may indicate potential issues
4. **Test your fixes** - Ensure the error is resolved
5. **Run full tests** - Check for new errors introduced

### 3. Preventing Common Errors

1. **Use proper formatting** - Follow ASTRA style guidelines
2. **Declare variables before use** - Ensure proper scope
3. **Check types** - Understand ASTRA's type system
4. **Follow ownership rules** - Respect borrowing and mutability
5. **Test incrementally** - Add code in small, testable chunks

## IDE Integration

### Error Highlighting

Most IDEs that support ASTRA will:
- **Highlight errors** with red underlines
- **Show warnings** with yellow underlines
- **Display info** with blue underlines
- **Provide hover information** with error details
- **Offer quick fixes** based on suggestions

### Navigation

- **Go to error**: Ctrl/Cmd + Click on error location
- **Next error**: F8 or IDE-specific shortcut
- **Previous error**: Shift + F8 or IDE-specific shortcut
- **Error panel**: View all errors in a dedicated panel

## Configuration

### Error Reporting Level

You can configure the error reporting level in your project:

```toml
# astra.toml
[compiler]
error_level = "all"  # all, warnings, errors
show_suggestions = true
max_context_lines = 3
```

### Custom Error Handling

For advanced use cases, you can implement custom error handlers:

```python
from astra.error_reporting import ErrorReporter, EnhancedError

class CustomErrorHandler:
    def handle_error(self, error: EnhancedError) -> None:
        # Custom error handling logic
        if error.error_code == "SEM101":
            # Special handling for undefined names
            self.suggest_variable_name(error)
```

## Troubleshooting

### Common Issues

1. **Errors not showing**: Check error reporting configuration
2. **Missing context**: Ensure source files are accessible
3. **Incorrect suggestions**: Report to ASTRA team for improvement
4. **Performance issues**: Limit context lines for large files

### Getting Help

- **Documentation**: https://astra-lang.dev/errors
- **Community**: https://github.com/astra-lang/astra/discussions
- **Issues**: https://github.com/astra-lang/astra/issues
- **Discord**: https://discord.gg/astra-lang

## Contributing

Help improve ASTRA's error reporting:

1. **Report unclear errors**: File issues with error examples
2. **Suggest improvements**: Propose better error messages
3. **Add error codes**: Contribute to error code documentation
4. **Test edge cases**: Help identify missing error scenarios

---

For more information about specific errors, visit the [Error Code Reference](https://astra-lang.dev/errors) or check the [ASTRA Language Specification](https://astra-lang.dev/spec).
