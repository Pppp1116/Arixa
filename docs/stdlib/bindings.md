# FFI Bindings

The `std.bindings` directory contains Foreign Function Interface (FFI) bindings for external libraries, enabling Astra programs to interoperate with existing C libraries and system APIs.

## Available Bindings

### libc - Standard C Library

Location: `std/bindings/libc.arixa`

Provides bindings to the standard C library for system calls, memory management, file I/O, and string operations.

**Key Functions:**
- Memory management: `malloc`, `free`, `memcpy`, `memset`
- String operations: `strlen`, `strcmp`
- File I/O: `fopen`, `fclose`, `fread`, `fwrite`
- Process operations: `exit`, `getenv`
- Formatted I/O: `printf`

**Usage Example:**
```astra
import std.bindings.libc;

fn read_file_content(path String) String? {
    // Convert Astra string to C string
    c_path = path.as_c_string();
    
    // Open file
    file = fopen(c_path, "r");
    if file == null as *Void {
        return none;
    }
    
    // Get file size
    fseek(file, 0, SEEK_END);
    size = ftell(file);
    fseek(file, 0, SEEK_SET);
    
    // Allocate buffer
    buffer = malloc(size);
    if buffer == null as *Void {
        fclose(file);
        return none;
    }
    
    // Read file
    bytes_read = fread(buffer, 1, size, file);
    fclose(file);
    
    // Convert to Astra string
    result = String.from_c_string(buffer as *u8, bytes_read);
    free(buffer);
    
    return result;
}
```

### raylib - Game Development Library

Location: `std/bindings/raylib.arixa`

Bindings for Raylib, a simple and easy-to-use library for game development and multimedia programming.

**Key Functions:**
- Window management: `InitWindow`, `CloseWindow`, `WindowShouldClose`
- Drawing: `BeginDrawing`, `EndDrawing`, `ClearBackground`
- Shapes: `DrawRectangle`, `DrawCircle`, `DrawText`
- Input: `IsKeyDown`, `IsMouseButtonPressed`
- Audio: `PlaySound`, `DrawRectangleRec`

**Usage Example:**
```astra
import std.bindings.raylib;

fn game_loop() {
    InitWindow(800, 600, "My Game");
    
    while !WindowShouldClose() {
        BeginDrawing();
        ClearBackground(RAYWHITE);
        
        DrawText("Hello, Astra!", 190, 200, 20, BLACK);
        DrawRectangle(150, 150, 100, 50, RED);
        
        EndDrawing();
    }
    
    CloseWindow();
}
```

### SDL2 - Cross-platform Multimedia

Location: `std/bindings/sdl2.arixa`

Bindings for SDL2, a cross-platform development library for games, simulations, and other multimedia applications.

**Key Functions:**
- Initialization: `SDL_Init`, `SDL_Quit`
- Window/Display: `SDL_CreateWindow`, `SDL_CreateRenderer`
- Events: `SDL_PollEvent`, `SDL_WaitEvent`
- Graphics: `SDL_RenderClear`, `SDL_RenderPresent`
- Input: `SDL_GetKeyboardState`, `SDL_GetMouseState`

**Usage Example:**
```astra
import std.bindings.sdl2;

fn sdl_app() Int {
    if SDL_Init(SDL_INIT_VIDEO) < 0 {
        return -1;
    }
    
    window = SDL_CreateWindow("Astra SDL App", 100, 100, 640, 480, 0);
    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED);
    
    running = true;
    while running {
        mut event = SDL_Event();
        while SDL_PollEvent(event) != 0 {
            if event.type == SDL_QUIT {
                running = false;
            }
        }
        
        SDL_RenderClear(renderer);
        // Render...
        SDL_RenderPresent(renderer);
    }
    
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    
    return 0;
}
```

### sqlite3 - Database Engine

Location: `std/bindings/sqlite3.arixa`

Bindings for SQLite3, a self-contained SQL database engine.

**Key Functions:**
- Database operations: `sqlite3_open`, `sqlite3_close`
- Query execution: `sqlite3_exec`, `sqlite3_prepare_v2`
- Result processing: `sqlite3_step`, `sqlite3_column_text`
- Error handling: `sqlite3_errmsg`, `sqlite3_errcode`

**Usage Example:**
```astra
import std.bindings.sqlite3;

fn query_users() Bool {
    mut db = sqlite3_open("database.db");
    if sqlite3_errcode(db) != SQLITE_OK {
        print("Cannot open database: " + sqlite3_errmsg(db));
        sqlite3_close(db);
        return false;
    }
    
    sql = "SELECT name, email FROM users";
    mut stmt = sqlite3_prepare_v2(db, sql, -1);
    
    while sqlite3_step(stmt) == SQLITE_ROW {
        name = sqlite3_column_text(stmt, 0);
        email = sqlite3_column_text(stmt, 1);
        
        print("User: " + name + ", Email: " + email);
    }
    
    sqlite3_finalize(stmt);
    sqlite3_close(db);
    
    return true;
}
```

## Using FFI Bindings

### Basic Pattern

1. **Import the binding module**
2. **Convert Astra types to C types** (strings to `*u8`, etc.)
3. **Call the C function**
4. **Handle errors and return values**
5. **Convert C types back to Astra types**
6. **Manage memory** (free allocated C memory)

### Type Conversions

| Astra Type | C Type | Conversion |
|------------|--------|------------|
| `String` | `*u8` | `string.as_c_string()` |
| `Vec<T>` | `*T` | `vec.data` pointer |
| `Int` | `i32`/`i64` | Cast as needed |
| `Bool` | `i32` | `1` for true, `0` for false |

### Memory Management

```astra
// Good: Always free C-allocated memory
c_string = to_c_string(astra_string);
result = some_c_function(c_string);
free(c_string as *Void);

// Bad: Memory leak
c_string = to_c_string(astra_string);
result = some_c_function(c_string);
// Forgot to free!
```

### Error Handling

```astra
// Check return values
ptr = malloc(size);
if ptr == null as *Void {
    // Handle allocation failure
    return error;
}

// Check error codes
result = sqlite3_open(db_path, db);
if result != SQLITE_OK {
    error_msg = sqlite3_errmsg(db);
    print("Database error: " + error_msg);
    return error;
}
```

## Creating New Bindings

To add new FFI bindings:

1. **Create the binding file** in `stdlib/bindings/`
2. **Use `@link("library")` attribute** for each extern function
3. **Follow C calling conventions** and type mappings
4. **Add documentation** with usage examples
5. **Test with actual library** on target platforms

### Example Binding Template

```astra
/// std.bindings.mylib - My Library bindings
///
/// Provides bindings to MyLibrary for X functionality.

@link("mylib") extern fn mylib_init() i32;
@link("mylib") extern fn mylib_cleanup() Void;
@link("mylib") extern fn mylib_do_work(input *u8, size u64) *u8;

/// Initialize MyLibrary
fn init() Bool {
    result = mylib_init();
    return result == 0;
}

/// Cleanup MyLibrary
fn cleanup() {
    mylib_cleanup();
}

/// Do work with MyLibrary
fn do_work(data String) String? {
    c_data = data.as_c_string();
    c_size = strlen(c_data);
    
    result = mylib_do_work(c_data, c_size);
    if result == null as *u8 {
        return none;
    }
    
    // Convert result back to Astra string
    astra_result = String.from_c_string(result);
    
    // Free C-allocated memory if needed
    mylib_free_result(result);
    
    return astra_result;
}
```

## Safety Considerations

- **Pointer Safety:** Always validate pointers before dereferencing
- **Memory Safety:** Free all C-allocated memory
- **Thread Safety:** Be aware of C library thread safety guarantees
- **Platform Compatibility:** Some bindings may be platform-specific
- **Error Handling:** Always check C function return values

## Hosted Compatibility

❌ **Hosted-only** - FFI bindings require external libraries and runtime support.

## See Also

- [C Module](c.md) - Standard C library bindings
- [IO Module](io.md) - Astra-native I/O operations
- [Process Module](process.md) - Process and environment utilities
