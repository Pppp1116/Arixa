# Environment Module

The `std.env` module provides environment variable utilities and current working directory access for hosted environments.

## Usage

```astra
import std.env;
```

## Environment Variables

### Basic Operations

#### `get_var(name: String) -> String?`

Get an environment variable value.

**Returns:** Environment variable value, or `none` if not found

**Example:**
```astra
path = get_var("PATH");
if path != none {
    print("PATH: " + (path as String?));
}

home = get_var("HOME");
if home == none {
    print("HOME not set");
}
```

#### `set_var(name: String, value: String) -> Bool`

Set an environment variable.

**Returns:** `true` if successful, `false` otherwise

**Example:**
```astra
success = set_var("MY_VAR", "my_value");
if success {
    print("Environment variable set");
}
```

#### `remove_var(name: String) -> Bool`

Remove an environment variable.

**Returns:** `true` if variable was removed, `false` if it didn't exist

**Example:**
```astra
removed = remove_var("TEMP_VAR");
if removed {
    print("Variable removed");
}
```

#### `var_exists(name: String) -> Bool`

Check if an environment variable exists.

**Returns:** `true` if variable exists, `false` otherwise

**Example:**
```astra
if var_exists("DEBUG") {
    print("Debug mode enabled");
}
```

### Bulk Operations

#### `vars() -> Vec<(String, String)>?`

Get all environment variables as name-value pairs.

**Returns:** Vector of `(name, value)` tuples, or `none` on error

**Example:**
```astra
all_vars = vars();
if all_vars != none {
    var_list = all_vars as Vec<(String, String)>;
    mut i = 0;
    while i < vec_len(var_list) {
        pair_opt = vec_get(var_list, i);
        if pair_opt != none {
            pair = (pair_opt as (String, String)?) ?? ("", "");
            print(pair.0 + "=" + pair.1);
        }
        i += 1;
    }
}
```

#### `for_each_env(callback: fn(String, String)) -> Bool`

Iterate over all environment variables with a callback.

**Returns:** `true` if iteration completed, `false` on error

**Example:**
```astra
fn print_env_var(name String, value String) {
    print(name + "=" + value);
}

success = for_each_env(print_env_var);
```

#### `vars_with_prefix(prefix: String) -> Vec<(String, String)>?`

Get environment variables matching a prefix.

**Returns:** Vector of matching variables, or `none` on error

**Example:**
```astra
path_vars = vars_with_prefix("PATH_");
if path_vars != none {
    // Process PATH-related variables
}
```

### Common Variables

#### `get_path() -> Vec<String>`

Get PATH environment variable as individual path components.

**Returns:** Vector of path strings

**Example:**
```astra
path_components = get_path();
mut i = 0;
while i < vec_len(path_components) {
    comp_opt = vec_get(path_components, i);
    if comp_opt != none {
        comp = (comp_opt as String?) ?? "";
        print("Path component: " + comp);
    }
    i += 1;
}
```

#### `set_path(components: Vec<String>) -> Bool`

Set PATH environment variable from components.

**Returns:** `true` if successful, `false` otherwise

**Example:**
```astra
new_paths = vec_from(["/usr/bin", "/usr/local/bin", "/home/user/bin"]);
success = set_path(new_paths);
```

#### `home_dir() -> String?`

Get user's home directory.

**Returns:** Home directory path, or `none` if not set

**Example:**
```astra
home = home_dir();
if home != none {
    config_path = (home as String?) + "/.config";
    print("Config directory: " + config_path);
}
```

#### `user_name() -> String?`

Get current user name.

**Returns:** User name, or `none` if not available

#### `shell() -> String?`

Get current shell path.

**Returns:** Shell path, or `none` if not set

#### `term() -> String?`

Get terminal type.

**Returns:** Terminal type, or `none` if not set

#### `locale() -> String?`

Get system locale.

**Returns:** Locale string, or `none` if not set

## PATH Utilities

### `parse_path_var(path_var: String) -> Vec<String>`

Parse PATH-like environment variable into components.

**Returns:** Vector of path components

**Example:**
```astra
path_string = "/usr/bin:/usr/local/bin:/home/bin";
components = parse_path_var(path_string);
// Returns: ["/usr/bin", "/usr/local/bin", "/home/bin"]
```

### `join_path_var(components: Vec<String>) -> String`

Join path components into PATH-like string.

**Returns:** Colon-separated path string

**Example:**
```astra
components = vec_from(["/usr/bin", "/usr/local/bin"]);
path_string = join_path_var(components);
// Returns: "/usr/bin:/usr/local/bin"
```

## Current Working Directory

### `current_dir() -> String?`

Get current working directory.

**Returns:** Current directory path, or `none` on error

**Example:**
```astra
cwd = current_dir();
if cwd != none {
    print("Current directory: " + (cwd as String?));
}
```

### `set_current_dir(path: String) -> Bool`

Set current working directory.

**Returns:** `true` if successful, `false` otherwise

**Example:**
```astra
success = set_current_dir("/tmp");
if success {
    print("Changed to /tmp");
}
```

## Validation

### `is_valid_var_name(name: String) -> Bool`

Validate environment variable name.

**Returns:** `true` if name is valid, `false` otherwise

**Rules:**
- Must start with letter or underscore
- Can contain letters, digits, and underscores
- Cannot be empty

**Example:**
```astra
valid = is_valid_var_name("MY_VAR_123");  // true
invalid = is_valid_var_name("123_INVALID"); // false
invalid = is_valid_var_name("MY-VAR");     // false
```

## Utilities

### `create_temp_var(prefix: String) -> String?`

Create a temporary environment variable with unique name.

**Returns:** Unique variable name, or `none` if failed

**Example:**
```astra
temp_name = create_temp_var("TEMP_");
if temp_name != none {
    set_var(temp_name as String?, "temporary_value");
}
```

### `backup_vars(pattern: String) -> Vec<(String, String)>?`

Backup environment variables matching a pattern.

**Returns:** Vector of matching variables, or `none` on error

**Example:**
```astra
backup = backup_vars("APP_");
// Later restore with restore_vars(backup)
```

### `restore_vars(backup: Vec<(String, String)>) -> Bool`

Restore environment variables from backup.

**Returns:** `true` if all variables restored, `false` otherwise

**Example:**
```astra
backup = backup_vars("MY_APP_");
// ... do work that modifies environment ...
restored = restore_vars(backup);
```

## Usage Examples

### Environment Configuration

```astra
import std.env;

fn setup_development_environment() Bool {
    // Set development variables
    if !set_var("APP_ENV", "development") {
        return false;
    }
    
    if !set_var("DEBUG", "true") {
        return false;
    }
    
    if !set_var("LOG_LEVEL", "debug") {
        return false;
    }
    
    // Add current directory to PATH
    current = current_dir();
    if current == none {
        return false;
    }
    
    path_components = get_path();
    vec_push(path_components, current as String?);
    
    return set_path(path_components);
}
```

### Environment-Aware Configuration

```astra
import std.env;

fn get_database_config() (String, String) {
    host = get_var("DB_HOST");
    port = get_var("DB_PORT");
    
    // Use defaults if not set
    if host == none {
        host = "localhost";
    }
    
    if port == none {
        port = "5432";
    }
    
    return (host as String?, port as String?);
}

fn print_environment_info() {
    print("=== Environment Information ===");
    
    user = user_name();
    if user != none {
        print("User: " + (user as String?));
    }
    
    home = home_dir();
    if home != none {
        print("Home: " + (home as String?));
    }
    
    shell = shell();
    if shell != none {
        print("Shell: " + (shell as String?));
    }
    
    cwd = current_dir();
    if cwd != none {
        print("Current Directory: " + (cwd as String?));
    }
    
    print("PATH components:");
    path_components = get_path();
    mut i = 0;
    while i < vec_len(path_components) {
        comp_opt = vec_get(path_components, i);
        if comp_opt != none {
            comp = (comp_opt as String?) ?? "";
            print("  " + comp);
        }
        i += 1;
    }
}
```

### Temporary Environment Changes

```astra
import std.env;

fn with_temp_env(changes Vec<(String, String)>, callback fn()) {
    // Backup current values
    mut backup = vec_new() as Vec<(String, String)>;
    
    mut i = 0;
    while i < vec_len(changes) {
        change_opt = vec_get(changes, i);
        if change_opt != none {
            change = (change_opt as (String, String)?) ?? ("", "");
            name = change.0;
            
            current_value = get_var(name);
            if current_value != none {
                vec_push(backup, (name, current_value as String?));
            }
            
            // Set new value
            set_var(name, change.1);
        }
        i += 1;
    }
    
    // Execute callback
    callback();
    
    // Restore original values
    i = 0;
    while i < vec_len(backup) {
        backup_opt = vec_get(backup, i);
        if backup_opt != none {
            backup_pair = (backup_opt as (String, String)?) ?? ("", "");
            set_var(backup_pair.0, backup_pair.1);
        }
        i += 1;
    }
    
    // Remove variables that didn't exist before
    i = 0;
    while i < vec_len(changes) {
        change_opt = vec_get(changes, i);
        if change_opt != none {
            change = (change_opt as (String, String)?) ?? ("", "");
            name = change.0;
            
            // Check if this was a new variable
            was_new = true;
            mut j = 0;
            while j < vec_len(backup) {
                backup_opt = vec_get(backup, j);
                if backup_opt != none {
                    backup_pair = (backup_opt as (String, String)?) ?? ("", "");
                    if backup_pair.0 == name {
                        was_new = false;
                        break;
                    }
                }
                j += 1;
            }
            
            if was_new {
                remove_var(name);
            }
        }
        i += 1;
    }
}

// Usage
env_changes = vec_from([
    ("APP_ENV", "test"),
    ("DEBUG", "true")
]);

with_temp_env(env_changes, fn() {
    // Run tests with test environment
    run_test_suite();
});
```

## Security Considerations

- **Path injection:** Be careful with PATH manipulation to avoid security issues
- **Sensitive data:** Don't log sensitive environment variables (passwords, tokens)
- **Validation:** Always validate environment variable values before use
- **Privilege escalation:** Be aware of security implications of environment changes

## Performance Considerations

- **System calls:** Environment variable access requires system calls
- **String operations:** Parsing and joining can be expensive for large PATH variables
- **Caching:** Consider caching frequently accessed variables
- **Bulk operations:** Use bulk operations for multiple variable changes

## Hosted Compatibility

❌ **Hosted-only** - Requires OS environment variable support.

## See Also

- [File System Module](fs.md) - File system operations
- [Process Module](process.md) - Process and system utilities
- [Path Module](path.md) - Path manipulation utilities
