# File System Module

The `std.fs` module provides file system utilities for hosted environments. This module enables file and directory operations, metadata queries, and path manipulation.

## Usage

```astra
import std.fs;
```

## File Operations

### Existence Checks

#### `exists(path: String) -> Bool`

Check if a file or directory exists at the given path.

**Returns:** `true` if the path exists, `false` otherwise

**Example:**
```astra
if exists("config.txt") {
    print("Config file found");
}
```

#### `is_file(path: String) -> Bool`

Check if a path points to a regular file.

**Returns:** `true` if path is a file, `false` otherwise

#### `is_dir(path: String) -> Bool`

Check if a path points to a directory.

**Returns:** `true` if path is a directory, `false` otherwise

#### `is_symlink(path: String) -> Bool`

Check if a path points to a symbolic link.

**Returns:** `true` if path is a symlink, `false` otherwise

### File Information

#### `file_info(path: String) -> FileInfo?`

Get comprehensive file information.

**Returns:** `FileInfo` structure if path exists, `none` otherwise

**FileInfo Structure:**
```astra
struct FileInfo {
    path String,        // Full path
    size Int,           // Size in bytes
    is_file Bool,       // True if regular file
    is_dir Bool,        // True if directory
    is_symlink Bool,    // True if symbolic link
    created Int,         // Creation timestamp (ms)
    modified Int,        // Modification timestamp (ms)
    accessed Int,        // Access timestamp (ms)
}
```

**Example:**
```astra
info = file_info("data.txt");
if info != none {
    file_data = info as FileInfo?;
    print("Size: " + file_data.size + " bytes");
    print("Modified: " + file_data.modified);
}
```

#### `file_size(path: String) -> Int?`

Get file size in bytes.

**Returns:** File size if file exists, `none` otherwise

**Example:**
```astra
size = file_size("large_file.bin");
if size != none {
    print("File size: " + (size as Int?) + " bytes");
}
```

### File Permissions

#### `file_permissions(path: String) -> FilePermissions?`

Get file permissions.

**Returns:** `FilePermissions` structure if successful, `none` otherwise

**FilePermissions Structure:**
```astra
struct FilePermissions {
    readable Bool,
    writable Bool,
    executable Bool,
}
```

#### `set_permissions(path: String, perms: FilePermissions) -> Bool`

Set file permissions.

**Returns:** `true` if successful, `false` otherwise

**Example:**
```astra
perms = FilePermissions{true, false, false};  // Read-only
success = set_permissions("script.sh", perms);
```

### File Operations

#### `remove_file(path: String) -> Bool`

Remove a file.

**Returns:** `true` if file was removed, `false` otherwise

#### `copy_file(src: String, dst: String) -> Bool`

Copy a file from source to destination.

**Returns:** `true` if copy succeeded, `false` otherwise

**Example:**
```astra
success = copy_file("source.txt", "backup.txt");
if success {
    print("File copied successfully");
}
```

#### `rename(old_path: String, new_path: String) -> Bool`

Move/rename a file or directory.

**Returns:** `true` if rename succeeded, `false` otherwise

**Example:**
```astra
success = rename("old_name.txt", "new_name.txt");
```

## Directory Operations

### Directory Creation

#### `create_dir(path: String) -> Bool`

Create a new directory. Parent directories must exist.

**Returns:** `true` if directory was created, `false` otherwise

#### `create_dir_all(path: String) -> Bool`

Create directories recursively (like `mkdir -p`).

**Returns:** `true` if all directories were created, `false` otherwise

**Example:**
```astra
success = create_dir_all("data/logs/2023");
if success {
    print("Directory structure created");
}
```

### Directory Removal

#### `remove_dir(path: String) -> Bool`

Remove an empty directory.

**Returns:** `true` if directory was removed, `false` otherwise

#### `remove_dir_all(path: String) -> Bool`

Remove a directory and all its contents recursively.

**Returns:** `true` if directory and contents were removed, `false` otherwise

**⚠️ Warning:** This operation is irreversible and will delete all contents.

### Directory Reading

#### `read_dir(path: String) -> Vec<DirEntry>?`

Read directory contents.

**Returns:** Vector of `DirEntry` structures if successful, `none` otherwise

**DirEntry Structure:**
```astra
struct DirEntry {
    name String,        // Entry name (without path)
    path String,        // Full path to entry
    file_info FileInfo,  // File information
}
```

**Example:**
```astra
entries = read_dir(".");
if entries != none {
    entry_list = entries as Vec<DirEntry>?;
    mut i = 0;
    while i < vec_len(entry_list) {
        entry_opt = vec_get(entry_list, i);
        if entry_opt != none {
            entry = (entry_opt as DirEntry?) ?? DirEntry{"", "", FileInfo{"", 0, false, false, false, 0, 0, 0}};
            if entry.file_info.is_file {
                print("File: " + entry.name);
            } else {
                print("Dir:  " + entry.name);
            }
        }
        i += 1;
    }
}
```

## Working Directory

#### `current_dir() -> String?`

Get current working directory.

**Returns:** Current directory path, or `none` on error

#### `set_current_dir(path: String) -> Bool`

Set current working directory.

**Returns:** `true` if successful, `false` otherwise

**Example:**
```astra
old_dir = current_dir();
if old_dir != none {
    print("Current directory: " + (old_dir as String?));
    
    if set_current_dir("/tmp") {
        print("Changed to /tmp");
    }
}
```

## Special Directories

#### `temp_dir() -> String`

Get system temporary directory.

**Returns:** Path to temporary directory

**Example:**
```astra
temp_path = temp_dir();
temp_file = temp_path + "/my_temp_file.txt";
```

## Path Operations

#### `canonicalize(path: String) -> String?`

Resolve symlinks and relative components to get absolute path.

**Returns:** Canonical path, or `none` if path doesn't exist

**Example:**
```astra
abs_path = canonicalize("../data/file.txt");
if abs_path != none {
    print("Absolute path: " + (abs_path as String?));
}
```

## File System Information

#### `available_space(path: String) -> Int?`

Get available space on the filesystem containing the given path.

**Returns:** Available space in bytes, or `none` on error

#### `total_space(path: String) -> Int?`

Get total space on the filesystem containing the given path.

**Returns:** Total space in bytes, or `none` on error

**Example:**
```astra
free = available_space(".");
total = total_space(".");
if free != none && total != none {
    used = (total as Int?) - (free as Int?);
    print("Used: " + used + " bytes");
    print("Free: " + (free as Int?) + " bytes");
}
```

## File Watching

#### `watch_directory(path: String, callback: fn(DirEntry)) -> Bool`

Watch a directory for changes (basic implementation).

**Returns:** `true` if watching started, `false` otherwise

**Example:**
```astra
fn on_file_change(entry DirEntry) {
    print("Changed: " + entry.name);
}

success = watch_directory(".", on_file_change);
```

## Usage Examples

### File Processing Pipeline

```astra
import std.fs;

fn process_input_files() {
    input_dir = "input";
    output_dir = "output";
    
    // Ensure directories exist
    if !exists(input_dir) {
        print("Input directory not found");
        return;
    }
    
    create_dir_all(output_dir);
    
    // Process all files
    entries = read_dir(input_dir);
    if entries != none {
        entry_list = entries as Vec<DirEntry>?;
        mut i = 0;
        while i < vec_len(entry_list) {
            entry_opt = vec_get(entry_list, i);
            if entry_opt != none {
                entry = (entry_opt as DirEntry?) ?? DirEntry{"", "", FileInfo{"", 0, false, false, false, 0, 0, 0}};
                if entry.file_info.is_file {
                    input_path = entry.path;
                    output_path = output_dir + "/" + entry.name;
                    
                    // Process file...
                    if copy_file(input_path, output_path) {
                        print("Processed: " + entry.name);
                    }
                }
            }
            i += 1;
        }
    }
}
```

### Disk Space Monitor

```astra
import std.fs;

fn check_disk_space(path String) {
    free = available_space(path);
    total = total_space(path);
    
    if free != none && total != none {
        free_gb = (free as Int?) / (1024 * 1024 * 1024);
        total_gb = (total as Int?) / (1024 * 1024 * 1024);
        used_gb = total_gb - free_gb;
        
        print("Disk space for: " + path);
        print("Total: " + total_gb + " GB");
        print("Used:  " + used_gb + " GB");
        print("Free:  " + free_gb + " GB");
        
        if free_gb < 10 {
            print("⚠️  Low disk space warning!");
        }
    }
}
```

## Error Handling

Most functions return `none` or `false` on error. Always check return values:

```astra
// Good: Check return values
size = file_size("data.txt");
if size == none {
    print("Cannot get file size");
    return;
}

// Bad: Assume success
size = file_size("data.txt") ?? 0;  // May hide errors
```

## Performance Considerations

- **Directory reading** can be expensive for large directories
- **File copying** involves full data transfer
- **Metadata queries** may require system calls
- **Recursive operations** can be slow on deep directory trees

## Security Notes

- **Path validation:** Be careful with user-provided paths to prevent directory traversal
- **Permissions:** Check file permissions before operations
- **Symlinks:** Be aware of symlink behavior in security contexts
- **Resource limits:** Large file operations may hit system limits

## Hosted Compatibility

❌ **Hosted-only** - Requires filesystem access and OS support.

## See Also

- [Path Module](path.md) - Path manipulation utilities
- [IO Module](io.md) - File content operations
- [Process Module](process.md) - Process and environment utilities
