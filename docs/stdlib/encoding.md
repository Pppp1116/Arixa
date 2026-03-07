# Encoding Module

The `std.encoding` module provides text encoding utilities including UTF-8 validation, Base64 encoding/decoding, hex encoding/decoding, and URL encoding. Basic operations are freestanding-safe.

## Usage

```astra
import std.encoding;
```

## UTF-8 Utilities

### Validation

#### `is_valid_utf8(bytes: Vec<UInt8>) -> Bool`

Validate UTF-8 byte sequence.

**Returns:** `true` if bytes form valid UTF-8, `false` otherwise

**Example:**
```astra
// Valid UTF-8
valid_bytes = vec_from([0x48, 0x65, 0x6C, 0x6C, 0x6F]);  // "Hello"
print(is_valid_utf8(valid_bytes));  // true

// Invalid UTF-8
invalid_bytes = vec_from([0x80, 0x81]);  // Invalid continuation
print(is_valid_utf8(invalid_bytes));  // false
```

#### `utf8_to_string(bytes: Vec<UInt8>) -> String?`

Convert UTF-8 bytes to string with validation.

**Returns:** String if bytes are valid UTF-8, `none` otherwise

**Example:**
```astra
utf8_bytes = vec_from([0x48, 0x65, 0x6C, 0x6C, 0x6F]);  // "Hello"
text = utf8_to_string(utf8_bytes);
if text != none {
    print("Decoded: " + (text as String?));
}
```

#### `string_to_utf8(s: String) -> Vec<UInt8>`

Convert string to UTF-8 bytes.

**Returns:** UTF-8 byte representation

**Example:**
```astra
text = "Hello, 世界";
bytes = string_to_utf8(text);
print("UTF-8 bytes: " + vec_len(bytes));  // Length in bytes
```

#### `utf8_char_count(bytes: Vec<UInt8>) -> Int`

Count Unicode code points in UTF-8 bytes.

**Returns:** Number of characters, 0 if invalid UTF-8

**Example:**
```astra
emoji_bytes = string_to_utf8("🌟🚀");
char_count = utf8_char_count(emoji_bytes);  // Returns: 2
```

### UTF-8 Analysis

#### `is_utf8_continuation(byte: UInt8) -> Bool`

Check if a byte is a valid UTF-8 continuation byte.

**Returns:** `true` if byte is continuation (10xxxxxx), `false` otherwise

#### `is_utf8_start(byte: UInt8) -> Bool`

Check if a byte is a valid UTF-8 start byte.

**Returns:** `true` if byte can start UTF-8 sequence, `false` otherwise

#### `utf8_sequence_length(first_byte: UInt8) -> Int`

Get expected length of UTF-8 sequence from first byte.

**Returns:** Sequence length (1-4), 0 if invalid

| First Byte Pattern | Sequence Length | Description |
|-------------------|-----------------|-------------|
| 0xxxxxxx          | 1               | ASCII |
| 110xxxxx          | 2               | 2-byte sequence |
| 1110xxxx          | 3               | 3-byte sequence |
| 11110xxx          | 4               | 4-byte sequence |

## Base64 Encoding/Decoding

### Encoding

#### `base64_encode(data: Vec<UInt8>) -> String`

Encode byte array as Base64 string.

**Returns:** Base64 encoded string

**Example:**
```astra
data = vec_from([0x48, 0x65, 0x6C, 0x6C, 0x6F]);  // "Hello"
encoded = base64_encode(data);
print("Base64: " + encoded);  // "SGVsbG8="
```

### Decoding

#### `base64_decode(encoded: String) -> Vec<UInt8>?`

Decode Base64 string to byte array.

**Returns:** Decoded bytes, or `none` if invalid Base64

**Example:**
```astra
encoded = "SGVsbG8=";
decoded = base64_decode(encoded);
if decoded != none {
    print("Decoded successfully");
}
```

### Usage Examples

```astra
import std.encoding;

fn encode_file_data(data Vec<UInt8>) String {
    return base64_encode(data);
}

fn decode_file_data(encoded String) Vec<UInt8>? {
    return base64_decode(encoded);
}

// Binary data transmission
binary_data = vec_from([0x01, 0x02, 0x03, 0xFF]);
transmission_ready = encode_file_data(binary_data);

// On receiving end
received_data = decode_file_data(transmission_ready);
if received_data != none {
    print("Data received intact");
}
```

## Hex Encoding/Decoding

### Encoding

#### `hex_encode(data: Vec<UInt8>) -> String`

Encode byte array as lowercase hex string.

**Returns:** Hexadecimal string (lowercase)

#### `hex_encode_upper(data: Vec<UInt8>) -> String`

Encode byte array as uppercase hex string.

**Returns:** Hexadecimal string (uppercase)

**Example:**
```astra
data = vec_from([0xDE, 0xAD, 0xBE, 0xEF]);
lower_hex = hex_encode(data);      // "deadbeef"
upper_hex = hex_encode_upper(data); // "DEADBEEF"
```

### Decoding

#### `hex_decode(encoded: String) -> Vec<UInt8>?`

Decode hex string to byte array.

**Returns:** Decoded bytes, or `none` if invalid hex

**Example:**
```astra
hex_string = "deadbeef";
bytes = hex_decode(hex_string);
if bytes != none {
    print("Hex decoded successfully");
}
```

### Usage Examples

```astra
import std.encoding;

fn format_bytes_as_hex(data Vec<UInt8>) String {
    return hex_encode(data);
}

fn parse_hex_string(hex_str String) Vec<UInt8>? {
    return hex_decode(hex_str);
}

// Color representation
red = vec_from([0xFF, 0x00, 0x00]);
color_hex = hex_encode(red);  // "ff0000"

// Parsing hex values
color_bytes = hex_decode("ff0000");
if color_bytes != none {
    print("Color parsed: " + hex_encode(color_bytes as Vec<UInt8>?));
}
```

## URL Encoding/Decoding

### Encoding

#### `url_encode(s: String) -> String`

URL encode string using percent encoding.

**Returns:** URL-safe encoded string

**Example:**
```astra
text = "Hello World!";
url_safe = url_encode(text);
print("URL encoded: " + url_safe);  // "Hello%20World%21"
```

### Decoding

#### `url_decode(encoded: String) -> String?`

Decode URL-encoded string.

**Returns:** Decoded string, or `none` if invalid encoding

**Example:**
```astra
encoded = "Hello%20World%21";
decoded = url_decode(encoded);
if decoded != none {
    print("URL decoded: " + (decoded as String?));
}
```

### URL-Safe Characters

The following characters are considered URL-safe and don't require encoding:

- **Letters:** A-Z, a-z
- **Digits:** 0-9  
- **Special:** -, _, ., ~

All other characters are percent-encoded.

### Usage Examples

```astra
import std.encoding;

fn prepare_url_params(params Vec<(String, String)>) String {
    mut result = "";
    mut i = 0;
    
    while i < vec_len(params) {
        param_opt = vec_get(params, i);
        if param_opt != none {
            param = (param_opt as (String, String)?) ?? ("", "");
            key = url_encode(param.0);
            value = url_encode(param.1);
            
            if result != "" {
                result += "&";
            }
            result += key + "=" + value;
        }
        i += 1;
    }
    
    return result;
}

// Usage
url_params = vec_from([
    ("name", "John Doe"),
    ("city", "New York"),
    ("query", "a+b=c")
]);

query_string = prepare_url_params(url_params);
// "name=John%20Doe&city=New%20York&query=a%2Bb%3Dc"
```

## Advanced Usage Examples

### UTF-8 File Processing

```astra
import std.encoding;
import std.fs;

fn read_text_file_safe(path String) String? {
    if !fs.exists(path) {
        return none;
    }
    
    // Read file as bytes
    file_content = fs.read_file_bytes(path);  // Assuming this exists
    if file_content == none {
        return none;
    }
    
    // Validate and convert UTF-8
    text = utf8_to_string(file_content as Vec<UInt8>?);
    return text;
}

fn write_text_file_safe(path String, content String) Bool {
    // Convert to UTF-8 bytes
    utf8_bytes = string_to_utf8(content);
    
    // Write bytes to file
    return fs.write_file_bytes(path, utf8_bytes);  // Assuming this exists
}
```

### Data Serialization

```astra
import std.encoding;

fn serialize_to_base64(data Vec<UInt8>) String {
    return base64_encode(data);
}

fn deserialize_from_base64(encoded String) Vec<UInt8>? {
    return base64_decode(encoded);
}

fn create_data_checksum(data Vec<UInt8>) String {
    // Create hex representation for easy comparison
    return hex_encode(data);
}

// Usage
original_data = vec_from([0x01, 0x02, 0x03, 0x04]);
serialized = serialize_to_base64(original_data);
checksum = create_data_checksum(original_data);

print("Serialized: " + serialized);
print("Checksum: " + checksum);
```

### Multi-encoding Pipeline

```astra
import std.encoding;

fn complex_encoding_pipeline(data Vec<UInt8>) String {
    // Step 1: Base64 encode
    base64_result = base64_encode(data);
    
    // Step 2: URL encode the Base64 string
    final_result = url_encode(base64_result);
    
    return final_result;
}

fn complex_decoding_pipeline(encoded String) Vec<UInt8>? {
    // Step 1: URL decode
    url_decoded = url_decode(encoded);
    if url_decoded == none {
        return none;
    }
    
    // Step 2: Base64 decode
    base64_decoded = base64_decode(url_decoded as String?);
    return base64_decoded;
}

// Usage
sensitive_data = vec_from([0x48, 0x65, 0x6C, 0x6C, 0x6F]);
transmission_ready = complex_encoding_pipeline(sensitive_data);

// On receiving end
received_data = complex_decoding_pipeline(transmission_ready);
```

## Performance Considerations

### UTF-8 Operations

- **Validation:** O(n) where n is byte length
- **Conversion:** O(n) with validation overhead
- **Character counting:** O(n) for UTF-8 sequences

### Base64 Operations

- **Encoding:** ~33% size increase
- **Decoding:** Requires validation of input
- **Memory:** Allocates new strings for results

### Hex Operations

- **Encoding:** 2x size increase (each byte = 2 hex chars)
- **Decoding:** Requires even-length input
- **Performance:** Simple byte manipulation

### URL Encoding

- **Encoding:** Variable size increase based on content
- **Decoding:** Requires validation of % sequences
- **Safety:** Handles special characters properly

## Error Handling

Always check return values for encoding/decoding operations:

```astra
// Good: Check for errors
decoded = base64_decode(encoded_string);
if decoded == none {
    print("Invalid Base64 input");
    return;
}

// Bad: Assume success
data = base64_decode(encoded_string) ?? vec_new();  // May hide errors
```

## Security Considerations

- **Base64:** Not encryption, just encoding
- **URL encoding:** Prevents injection in URLs
- **UTF-8:** Validate before processing to prevent issues
- **Hex:** Safe for binary data representation

## Freestanding Compatibility

✅ **Freestanding-safe** - Basic encoding operations work without runtime support.

❌ **Hosted-only** - Some advanced operations may require runtime support.

## See Also

- [String Module](str.md) - String manipulation utilities
- [Vector Module](vec.md) - Byte array operations
- [Crypto Module](crypto.md) - Cryptographic encoding
