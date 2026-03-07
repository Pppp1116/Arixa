# Logging Module

The `std.logging` module provides structured logging utilities with leveled output, formatted messages, and file logging capabilities for hosted environments.

## Usage

```astra
import std.logging;
```

## Log Levels

Log levels are ordered by severity, with higher numbers indicating higher severity:

| Level | Value | Description |
|-------|-------|-------------|
| `LOG_LEVEL_TRACE` | 0 | Very detailed information, typically only of interest when diagnosing problems |
| `LOG_LEVEL_DEBUG` | 1 | Detailed information on the flow through the system |
| `LOG_LEVEL_INFO` | 2 | Interesting runtime events (startup/shutdown) |
| `LOG_LEVEL_WARN` | 3 | Use of deprecated APIs, poor use of API, 'almost' errors, other runtime situations |
| `LOG_LEVEL_ERROR` | 4 | Runtime errors or unexpected conditions |
| `LOG_LEVEL_FATAL` | 5 | Very severe error events that will presumably lead the application to abort |

## Logger Configuration

### Creating Loggers

#### `new() -> Logger`

Create a new logger with default configuration.

**Default Configuration:**
- Level: INFO
- Output: Console
- Format: Simple
- Timestamp: Enabled
- Level: Enabled
- Module: Enabled

#### `with_config(config: LoggerConfig) -> Logger`

Create a logger with custom configuration.

**LoggerConfig Structure:**
```astra
struct LoggerConfig {
    level LogLevel,           // Minimum log level
    output LogOutput,         // Output destination
    format LogFormat,         // Log format
    include_timestamp Bool,   // Include timestamp
    include_level Bool,       // Include log level
    include_module Bool,      // Include module name
}
```

**Example:**
```astra
config = LoggerConfig{
    level: LOG_LEVEL_DEBUG,
    output: LOG_OUTPUT_BOTH,
    format: LOG_FORMAT_DETAILED,
    include_timestamp: true,
    include_level: true,
    include_module: true,
};

logger = with_config(config);
```

### Configuration Methods

#### `set_level(logger: &mut Logger, level: LogLevel)`

Set minimum log level.

**Example:**
```astra
mut logger = new();
set_level(logger, LOG_LEVEL_WARN);  // Only log WARN and above
```

#### `set_output(logger: &mut Logger, output: LogOutput)`

Set log output destination.

**Output Options:**
- `LOG_OUTPUT_CONSOLE` - Print to console
- `LOG_OUTPUT_FILE` - Write to log file
- `LOG_OUTPUT_BOTH` - Both console and file

**Example:**
```astra
set_output(logger, LOG_OUTPUT_FILE);
```

#### `set_format(logger: &mut Logger, format: LogFormat)`

Set log message format.

**Format Options:**
- `LOG_FORMAT_SIMPLE` - `[LEVEL] module: message`
- `LOG_FORMAT_DETAILED` - `[TIMESTAMP] [LEVEL] [module] message`
- `LOG_FORMAT_JSON` - JSON structured format

## Basic Logging

### Level-based Logging

#### `log(logger: Logger, level: LogLevel, module: String, message: String)`

Log a message with specified level.

**Example:**
```astra
logger = new();
log(logger, LOG_LEVEL_INFO, "my_app", "Application started");
log(logger, LOG_LEVEL_ERROR, "my_app", "An error occurred");
```

### Convenience Functions

#### `trace(logger: Logger, module: String, message: String)`
#### `debug(logger: Logger, module: String, message: String)`
#### `info(logger: Logger, module: String, message: String)`
#### `warn(logger: Logger, module: String, message: String)`
#### `error(logger: Logger, module: String, message: String)`
#### `fatal(logger: Logger, module: String, message: String)`

**Example:**
```astra
logger = new();

trace(logger, "database", "Connecting to database");
debug(logger, "database", "Connection string: " + conn_str);
info(logger, "database", "Connected successfully");
warn(logger, "database", "Connection pool nearly full");
error(logger, "database", "Connection failed");
fatal(logger, "database", "Database server unavailable");
```

## Structured Logging

### Field-based Logging

#### `log_with_fields(logger: Logger, level: LogLevel, module: String, message: String, fields: Vec<(String, String)>)`

Log a message with additional structured fields.

**Example:**
```astra
fields = vec_from([
    ("user_id", "12345"),
    ("action", "login"),
    ("ip_address", "192.168.1.100")
]);

log_with_fields(logger, LOG_LEVEL_INFO, "auth", "User login attempt", fields);
```

### Convenience Field Functions

#### `info_fields(logger: Logger, module: String, message: String, fields: Vec<(String, String)>)`
#### `error_fields(logger: Logger, module: String, message: String, fields: Vec<(String, String)>)`

And similar functions for all log levels.

**Example:**
```astra
error_fields(logger, "payment", "Payment failed", vec_from([
    ("amount", "99.99"),
    ("currency", "USD"),
    ("error_code", "CARD_DECLINED"),
    ("transaction_id", "txn_123456")
]));
```

## Global Logger

For simple applications, use the global logger instance:

### Global Configuration

#### `set_global_level(level: LogLevel)`
#### `set_global_output(output: LogOutput)`
#### `set_global_format(format: LogFormat)`

### Global Logging Functions

#### `log_trace(module: String, message: String)`
#### `log_debug(module: String, message: String)`
#### `log_info(module: String, message: String)`
#### `log_warn(module: String, message: String)`
#### `log_error(module: String, message: String)`
#### `log_fatal(module: String, message: String)`

**Example:**
```astra
set_global_level(LOG_LEVEL_DEBUG);
set_global_output(LOG_OUTPUT_FILE);

log_info("main", "Application starting");
log_debug("database", "Initializing connection");
log_error("network", "Connection timeout");
```

## Log Formats

### Simple Format

```
[INFO] main: Application started
[ERROR] database: Connection failed
```

### Detailed Format

```
[2023-12-07T10:30:45.123Z] [INFO] [main] Application started
[2023-12-07T10:30:45.456Z] [ERROR] [database] Connection failed
```

### JSON Format

```json
{"timestamp": "2023-12-07T10:30:45.123Z", "level": "INFO", "module": "main", "message": "Application started"}
{"timestamp": "2023-12-07T10:30:45.456Z", "level": "ERROR", "module": "database", "message": "Connection failed", "fields": {"error_code": "TIMEOUT", "retry_count": "3"}}
```

## Usage Examples

### Application Logging Setup

```astra
import std.logging;

fn setup_logging() Logger {
    // Get log level from environment
    log_level_str = env.get_var("LOG_LEVEL");
    mut log_level = LOG_LEVEL_INFO;
    
    if log_level_str != none {
        level_str = log_level_str as String?;
        if level_str == "TRACE" { log_level = LOG_LEVEL_TRACE; }
        else if level_str == "DEBUG" { log_level = LOG_LEVEL_DEBUG; }
        else if level_str == "WARN" { log_level = LOG_LEVEL_WARN; }
        else if level_str == "ERROR" { log_level = LOG_LEVEL_ERROR; }
        else if level_str == "FATAL" { log_level = LOG_LEVEL_FATAL; }
    }
    
    // Configure logger
    config = LoggerConfig{
        level: log_level,
        output: LOG_OUTPUT_BOTH,
        format: LOG_FORMAT_DETAILED,
        include_timestamp: true,
        include_level: true,
        include_module: true,
    };
    
    return with_config(config);
}

fn main() {
    logger = setup_logging();
    
    log_info(logger, "main", "Application starting");
    
    // Application logic...
    
    log_info(logger, "main", "Application finished");
}
```

### Request Logging

```astra
import std.logging;

fn log_request(logger Logger, method String, path String, status_code Int, duration Int, user_id String?) {
    mut fields = vec_from([
        ("method", method),
        ("path", path),
        ("status_code", str_from_int(status_code)),
        ("duration_ms", str_from_int(duration))
    ]);
    
    if user_id != none {
        vec_push(fields, ("user_id", user_id as String?));
    }
    
    if status_code >= 400 {
        log_with_fields(logger, LOG_LEVEL_WARN, "http", "HTTP request completed with error", fields);
    } else {
        log_with_fields(logger, LOG_LEVEL_INFO, "http", "HTTP request completed", fields);
    }
}

// Usage
log_request(logger, "GET", "/api/users", 200, 45, "user123");
log_request(logger, "POST", "/api/orders", 500, 234, none);
```

### Error Logging with Context

```astra
import std.logging;

fn log_error_with_context(logger Logger, error Error, context Vec<(String, String)>) {
    mut fields = context;
    
    // Add error information
    vec_push(fields, ("error_type", error.type));
    vec_push(fields, ("error_message", error.message));
    vec_push(fields, ("error_code", str_from_int(error.code)));
    
    // Add stack trace if available
    if error.stack_trace != "" {
        vec_push(fields, ("stack_trace", error.stack_trace));
    }
    
    log_with_fields(logger, LOG_LEVEL_ERROR, "error_handler", "Error occurred", fields);
}

// Usage
error_context = vec_from([
    ("function", "process_payment"),
    ("user_id", "12345"),
    ("amount", "99.99")
]);

log_error_with_context(logger, payment_error, error_context);
```

### Performance Logging

```astra
import std.logging;
import std.time;

fn log_performance(logger Logger, operation String, duration Int, additional_fields Vec<(String, String)>) {
    mut fields = additional_fields;
    vec_push(fields, ("operation", operation));
    vec_push(fields, ("duration_ms", str_from_int(duration)));
    
    if duration > 1000 {
        log_with_fields(logger, LOG_LEVEL_WARN, "performance", "Slow operation detected", fields);
    } else {
        log_with_fields(logger, LOG_LEVEL_DEBUG, "performance", "Operation completed", fields);
    }
}

fn measure_operation[T](logger Logger, operation_name String, operation fn() T, fields Vec<(String, String)>) T {
    start_time = time.now_ms();
    
    result = operation();
    
    end_time = time.now_ms();
    duration = end_time - start_time;
    
    log_performance(logger, operation_name, duration, fields);
    
    return result;
}

// Usage
result = measure_operation(logger, "database_query", fn() {
    return execute_query("SELECT * FROM users");
}, vec_from([("query_type", "select"), ("table", "users")]));
```

## Environment Configuration

The logger can be configured via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `LOG_LEVEL` | Minimum log level (TRACE, DEBUG, INFO, WARN, ERROR, FATAL) | INFO |
| `LOG_OUTPUT` | Output destination (console, file, both) | console |
| `LOG_FORMAT` | Log format (simple, detailed, json) | simple |
| `LOG_DIR` | Directory for log files | System temp directory |

```astra
fn configure_from_environment() Logger {
    // Get log level
    level_str = env.get_var("LOG_LEVEL");
    mut level = LOG_LEVEL_INFO;
    if level_str != none {
        level = parse_log_level(level_str as String?);
    }
    
    // Get output
    output_str = env.get_var("LOG_OUTPUT");
    mut output = LOG_OUTPUT_CONSOLE;
    if output_str != none {
        output = parse_log_output(output_str as String?);
    }
    
    // Get format
    format_str = env.get_var("LOG_FORMAT");
    mut format = LOG_FORMAT_SIMPLE;
    if format_str != none {
        format = parse_log_format(format_str as String?);
    }
    
    config = LoggerConfig{
        level: level,
        output: output,
        format: format,
        include_timestamp: true,
        include_level: true,
        include_module: true,
    };
    
    return with_config(config);
}
```

## Performance Considerations

### Level Filtering

- **Early filtering:** Messages below configured level are discarded before formatting
- **Zero allocation:** Disabled levels don't allocate memory for log entries
- **Conditional compilation:** Consider compile-time log level for production

### Formatting Overhead

| Format | Performance | Features |
|--------|-------------|----------|
| Simple | Fast | Basic information |
| Detailed | Medium | Timestamps, structured |
| JSON | Slow | Machine-readable |

### File I/O

- **Buffered writes:** File logging uses buffered I/O
- **Async writes:** Consider async logging for high-performance applications
- **Rotation:** Implement log rotation for long-running applications

## Best Practices

1. **Use appropriate levels:**
   - TRACE: Detailed debugging information
   - DEBUG: Development and troubleshooting
   - INFO: General application flow
   - WARN: Recoverable issues
   - ERROR: Unrecoverable errors
   - FATAL: Critical failures

2. **Include context:**
   - Use structured fields for machine-readable data
   - Include relevant identifiers (user_id, request_id, etc.)
   - Add timing information for performance analysis

3. **Avoid sensitive data:**
   - Don't log passwords, tokens, or private keys
   - Sanitize user input before logging
   - Use data masking for PII

4. **Configure appropriately:**
   - Use DEBUG in development
   - Use INFO or WARN in production
   - Consider file logging for production applications

## Hosted Compatibility

❌ **Hosted-only** - Requires filesystem access and runtime support.

## See Also

- [IO Module](io.md) - Basic I/O operations
- [Time Module](time.md) - Timestamp utilities
- [Environment Module](env.md) - Environment variable access
