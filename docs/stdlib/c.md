# C Language Bindings

The `std.c` module provides C language bindings and FFI utilities for interoperating with C libraries and system functions.

## Usage

```astra
import std.c;
```

## Available Functions

The module provides commonly used C library functions via `@link("c")` extern declarations:

### Memory Management

#### `malloc(size: u64) -> *Void`

Allocate memory from the C heap.

**Parameters:**
- `size` - Number of bytes to allocate

**Returns:** Pointer to allocated memory, or null if allocation fails

**Example:**
```astra
// Allocate 100 bytes
ptr = malloc(100);
if ptr == null as *Void {
    // Handle allocation failure
}
// Use memory...
free(ptr);  // Don't forget to free!
```

#### `free(ptr: *Void) -> Void`

Free previously allocated memory.

**Parameters:**
- `ptr` - Pointer to memory to free

**Example:**
```astra
ptr = malloc(64);
// Use ptr...
free(ptr);  // Always free allocated memory
```

#### `memcpy(dst: *Void, src: *Void, n: u64) -> *Void`

Copy `n` bytes from `src` to `dst`.

**Returns:** Pointer to `dst`

**Example:**
```astra
src = "Hello, world!";
dst = malloc(13);
memcpy(dst, src, 13);
```

#### `memset(dst: *Void, val: i32, n: u64) -> *Void`

Fill `n` bytes at `dst` with `val`.

**Returns:** Pointer to `dst`

**Example:**
```astra
buffer = malloc(1024);
memset(buffer, 0, 1024);  // Zero-initialize buffer
```

### String Operations

#### `strlen(s: *u8) -> u64`

Get length of null-terminated C string.

**Returns:** Length of string in bytes

**Example:**
```astra
c_str = "Hello, world!";
length = strlen(c_str);  // Returns: 13
```

#### `strcmp(a: *u8, b: *u8) -> i32`

Compare two C strings.

**Returns:** 
- `< 0` if `a` < `b`
- `0` if `a` == `b`
- `> 0` if `a` > `b`

**Example:**
```astra
result = strcmp("apple", "banana");  // Returns: negative
result = strcmp("hello", "hello");    // Returns: 0
```

### File Operations

#### `fopen(path: *u8, mode: *u8) -> *Void`

Open a file with specified mode.

**Parameters:**
- `path` - File path (null-terminated)
- `mode` - File mode ("r", "w", "a", etc.)

**Returns:** File pointer, or null on error

**Example:**
```astra
file = fopen("test.txt", "w");
if file == null as *Void {
    // Handle error
}
// Use file...
fclose(file);
```

#### `fclose(f: *Void) -> i32`

Close an open file.

**Returns:** 0 on success, EOF on error

#### `fread(buf: *Void, size: u64, count: u64, f: *Void) -> u64`

Read data from file.

**Returns:** Number of items successfully read

#### `fwrite(buf: *Void, size: u64, count: u64, f: *Void) -> u64`

Write data to file.

**Returns:** Number of items successfully written

### Process Operations

#### `exit(code: i32) -> Void`

Exit the current process.

**Parameters:**
- `code` - Exit code (0 for success, non-zero for error)

#### `getenv(name: *u8) -> *u8`

Get environment variable value.

**Returns:** Pointer to environment variable value, or null if not found

**Example:**
```astra
path = getenv("PATH");
if path == null as *u8 {
    // Environment variable not found
}
```

### Formatted Output

#### `printf(fmt: *u8, ...) -> i32`

Print formatted output to stdout.

**Parameters:**
- `fmt` - Format string (printf-style)
- `...` - Variable arguments

**Returns:** Number of characters printed

**Example:**
```astra
printf("Hello, %s! Number: %d\n", "world", 42);
```

## Safety Considerations

- **Memory Safety:** C functions don't perform bounds checking. Always validate pointers and buffer sizes.
- **String Safety:** C strings are null-terminated. Ensure strings are properly terminated.
- **Resource Management:** Always free allocated memory and close file handles.
- **Error Handling:** Check return values for null pointers and error codes.

## Best Practices

1. **Always check return values:**
```astra
ptr = malloc(size);
if ptr == null as *Void {
    // Handle allocation failure
    return;
}
```

2. **Use RAII-style patterns when possible:**
```astra
fn process_data() {
    ptr = malloc(1024);
    if ptr == null as *Void {
        return;
    }
    
    // Use ptr...
    
    free(ptr);  // Clean up
}
```

3. **Prefer Astra's built-in types when possible:**
- Use `String` instead of `*u8` for text
- Use `Vec<T>` instead of manual memory management
- Use Astra's I/O functions when available

## Hosted Compatibility

❌ **Hosted-only** - Requires C library and runtime support.

## See Also

- [IO Module](io.md) - Astra-native I/O operations
- [String Module](str.md) - Astra string utilities
- [Memory Module](mem.md) - Memory management utilities
