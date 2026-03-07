# Path Module

The `std.path` module provides cross-platform path manipulation utilities. All functions are pure string operations that work in both hosted and freestanding modes.

## Usage

```astra
import std.path;
```

## Path Creation

### `from_string(path_str: String) -> Path`

Create a new path from a string, automatically normalizing components.

**Returns:** Normalized `Path` object

**Example:**
```astra
path = from_string("dir/../file.txt");  // Normalized to "file.txt"
abs_path = from_string("/usr/local/bin");  // Absolute path
```

### `from_components(components: Vec<String>, absolute: Bool) -> Path`

Create a path from individual components.

**Parameters:**
- `components` - Vector of path components
- `absolute` - Whether path should be absolute

**Example:**
```astra
comps = vec_from(["home", "user", "documents"]);
path = from_components(comps, false);  // "home/user/documents"
```

### `join(components: Vec<String>) -> String`

Join multiple path components with appropriate separators.

**Returns:** Joined path string

**Example:**
```astra
comps = vec_from(["home", "user", "file.txt"]);
path = join(comps);  // "home/user/file.txt"
```

## Path Analysis

### `parent_path(path: String) -> String`

Get the parent directory of a path.

**Returns:** Parent path, or empty/root if no parent

**Example:**
```astra
parent = parent_path("dir/subdir/file.txt");  // "dir/subdir"
parent = parent_path("file.txt");              // ""
parent = parent_path("/usr/local/bin");        // "/usr/local"
```

### `file_name(path: String) -> String`

Get the file name (last component) of a path.

**Returns:** File name without directory

**Example:**
```astra
name = file_name("dir/subdir/file.txt");  // "file.txt"
name = file_name("/usr/local/bin");       // "bin"
name = file_name("file.txt");             // "file.txt"
```

### `extension(path: String) -> String`

Get the file extension (including the dot).

**Returns:** Extension string, or empty if no extension

**Example:**
```astra
ext = extension("file.txt");     // ".txt"
ext = extension("archive.tar.gz"); // ".gz"
ext = extension("README");        // ""
```

### `file_stem(path: String) -> String`

Get the file name without extension.

**Returns:** File name without extension

**Example:**
```astra
stem = file_stem("file.txt");     // "file"
stem = file_stem("archive.tar.gz"); // "archive.tar"
stem = file_stem("README");        // "README"
```

### `is_absolute(path: String) -> Bool`

Check if a path is absolute.

**Returns:** `true` if path is absolute, `false` otherwise

**Example:**
```astra
abs = is_absolute("/usr/local/bin");  // true
abs = is_absolute("file.txt");        // false
abs = is_absolute("C:\\Windows");     // false (Unix-style paths only)
```

### `is_relative(path: String) -> Bool`

Check if a path is relative.

**Returns:** `true` if path is relative, `false` otherwise

**Example:**
```astra
rel = is_relative("dir/file.txt");  // true
rel = is_relative("/usr/bin");       // false
```

## Path Normalization

### `normalize(path: String) -> String`

Normalize a path by removing redundant components.

**Returns:** Normalized path string

**Example:**
```astra
norm = normalize("dir/../file.txt");     // "file.txt"
norm = normalize("./current/./file.txt"); // "current/file.txt"
norm = normalize("dir/subdir/../../file"); // "file.txt"
```

### `absolute(path: String) -> String`

Convert a path to absolute form.

**Note:** In freestanding mode, this just returns normalized path. In hosted mode, it would resolve against current working directory.

**Returns:** Absolute path string

**Example:**
```astra
abs = absolute("file.txt");  // "file.txt" (freestanding)
abs = absolute("../file");   // "../file" (freestanding)
```

### `relative(path: String, base: String) -> String`

Convert a path to be relative to another path.

**Returns:** Relative path from `base` to `path`

**Example:**
```astra
rel = relative("/home/user/docs/file.txt", "/home/user"); // "docs/file.txt"
rel = relative("/home/user/docs", "/home/user/docs");    // ""
rel = relative("/home/user/../other/file", "/home/user"); // "../other/file"
```

## Path Comparison

### `starts_with(path: String, prefix: String) -> Bool`

Check if a path starts with a given prefix.

**Returns:** `true` if path starts with prefix, `false` otherwise

**Example:**
```astra
starts = starts_with("/usr/local/bin", "/usr/local"); // true
starts = starts_with("/usr/local/bin", "/usr/bin");     // false
```

### `ends_with(path: String, suffix: String) -> Bool`

Check if a path ends with a given suffix.

**Returns:** `true` if path ends with suffix, `false` otherwise

**Example:**
```astra
ends = ends_with("/usr/local/bin", "/bin");    // true
ends = ends_with("/usr/local/bin", "/sbin");   // false
```

## Constants

```astra
const PATH_SEPARATOR = "/";
const PATH_SEPARATOR_STR = "/";
const CURRENT_DIR = ".";
const PARENT_DIR = "..";
const ROOT_PATH = "/";
```

## Usage Examples

### File Path Processing

```astra
import std.path;

fn process_file_path(full_path String) {
    print("Processing: " + full_path);
    
    // Extract components
    directory = parent_path(full_path);
    filename = file_name(full_path);
    extension = extension(full_path);
    stem = file_stem(full_path);
    
    print("Directory: " + directory);
    print("Filename: " + filename);
    print("Extension: " + extension);
    print("Stem: " + stem);
    
    // Build related paths
    backup_dir = join(vec_from([directory, "backups"]));
    backup_path = join(vec_from([backup_dir, stem + "_backup" + extension]));
    
    print("Backup path: " + backup_path);
}

// Usage
process_file_path("/home/user/documents/report.pdf");
```

### Path Normalization

```astra
import std.path;

fn normalize_user_paths(paths Vec<String>) Vec<String> {
    mut result = vec_new() as Vec<String>;
    
    mut i = 0;
    while i < vec_len(paths) {
        path_opt = vec_get(paths, i);
        if path_opt != none {
            path = (path_opt as String?) ?? "";
            normalized = normalize(path);
            vec_push(result, normalized);
        }
        i += 1;
    }
    
    return result;
}

// Usage
messy_paths = vec_from([
    "dir/../file.txt",
    "./current/./file.txt", 
    "dir/subdir/../../file",
    "dir//double//slash.txt"
]);

clean_paths = normalize_user_paths(messy_paths);
```

### Relative Path Calculation

```astra
import std.path;

fn get_relative_path(from_path String, to_path String) String {
    if is_absolute(from_path) && is_absolute(to_path) {
        return relative(to_path, from_path);
    } else {
        // For relative paths, just return the target
        return normalize(to_path);
    }
}

// Usage
rel = get_relative_path("/home/user/docs", "/home/user/images/photo.jpg");
print("Relative path: " + rel);  // "../images/photo.jpg"
```

### File Extension Handling

```astra
import std.path;

fn change_extension(path String, new_ext String) String {
    stem = file_stem(path);
    return stem + new_ext;
}

fn has_extension(path String, ext String) Bool {
    return extension(path) == ext;
}

// Usage
new_path = change_extension("document.pdf", ".txt");  // "document.txt"
is_pdf = has_extension("file.pdf", ".pdf");          // true
```

## Data Structure

### Path Structure

```astra
struct Path {
    components Vec<String>,  // Path components
    absolute Bool,          // Whether path is absolute
}
```

## Normalization Rules

The path normalization follows these rules:

1. **Remove redundant separators:** `dir//file` → `dir/file`
2. **Resolve `.` components:** `dir/./file` → `dir/file`
3. **Resolve `..` components:** `dir/../file` → `file`
4. **Handle root paths:** `/../file` → `/file` (absolute paths can't go above root)
5. **Preserve trailing `..`** in relative paths when needed

## Platform Considerations

- **Unix-style paths only:** Uses `/` as separator consistently
- **Case-sensitive:** Path comparison is case-sensitive
- **No drive letters:** Windows drive letters not supported
- **Unicode support:** Handles Unicode characters in paths

## Performance Considerations

- **String operations:** All operations are pure string manipulations
- **Memory usage:** Creates new strings for most operations
- **Complexity:** Most operations are O(n) where n is path length
- **Vector operations:** Component operations use vector operations

## Freestanding Compatibility

✅ **Freestanding-safe** - All operations are pure string manipulations that don't require filesystem access.

## See Also

- [File System Module](fs.md) - Actual filesystem operations
- [String Module](str.md) - String manipulation utilities
- [IO Module](io.md) - File content operations
