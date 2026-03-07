# Random Module

The `std.random` module provides random number generation utilities for hosted environments, including both fast pseudo-random generation and cryptographically secure random generation.

## Usage

```astra
import std.random;
```

## Pseudo-Random Number Generation

### Random Generator

#### `new() -> Random`

Create a new random number generator seeded with current time.

**Returns:** New `Random` instance

#### `with_seed(seed: UInt64) -> Random`

Create a new random number generator with specific seed.

**Parameters:**
- `seed` - 64-bit seed value

**Returns:** New `Random` instance

**Example:**
```astra
rng = new();  // Seeded with current time
rng_seeded = with_seed(12345);  // Predictable sequence
```

### Basic Random Values

#### `next_uint64(rng: &mut Random) -> UInt64`

Generate a random 64-bit unsigned integer.

**Returns:** Random 64-bit value

#### `next_uint32(rng: &mut Random) -> UInt32`

Generate a random 32-bit unsigned integer.

**Returns:** Random 32-bit value

#### `next_int_range(rng: &mut Random, min: Int, max: Int) -> Int`

Generate a random signed integer in range [min, max].

**Parameters:**
- `min` - Minimum value (inclusive)
- `max` - Maximum value (inclusive)

**Returns:** Random integer in specified range

**Example:**
```astra
mut rng = new();

// Random integer between 1 and 100
dice_roll = next_int_range(rng, 1, 100);

// Random integer between -10 and 10
offset = next_int_range(rng, -10, 10);
```

#### `next_float(rng: &mut Random) -> Float`

Generate a random float in range [0.0, 1.0).

**Returns:** Random float between 0.0 (inclusive) and 1.0 (exclusive)

#### `next_float_range(rng: &mut Random, min: Float, max: Float) -> Float`

Generate a random float in range [min, max).

**Parameters:**
- `min` - Minimum value (inclusive)
- `max` - Maximum value (exclusive)

**Returns:** Random float in specified range

**Example:**
```astra
mut rng = new();

// Random float between 0.0 and 1.0
probability = next_float(rng);

// Random float between -5.0 and 5.0
coordinate = next_float_range(rng, -5.0, 5.0);
```

#### `next_bool(rng: &mut Random) -> Bool`

Generate a random boolean.

**Returns:** Random true or false value

**Example:**
```astra
mut rng = new();

if next_bool(rng) {
    print("Heads");
} else {
    print("Tails");
}
```

### Bytes and Data

#### `next_bytes(rng: &mut Random, length: Int) -> Vec<UInt8>`

Generate random bytes.

**Parameters:**
- `length` - Number of bytes to generate

**Returns:** Vector of random bytes

**Example:**
```astra
mut rng = new();

// Generate 16 random bytes
random_data = next_bytes(rng, 16);
```

### String Generation

#### `next_string(rng: &mut Random, length: Int, charset: String) -> String`

Generate a random string from given character set.

**Parameters:**
- `length` - Length of string to generate
- `charset` - Characters to choose from

**Returns:** Random string of specified length

#### `next_alphanumeric(rng: &mut Random, length: Int) -> String`

Generate a random alphanumeric string.

**Parameters:**
- `length` - Length of string to generate

**Returns:** Random alphanumeric string

**Example:**
```astra
mut rng = new();

// Generate 8-character random string
password = next_alphanumeric(rng, 8);

// Generate string from custom charset
symbols = "!@#$%^&*()";
symbol_string = next_string(rng, 4, symbols);
```

#### `next_hex_string(rng: &mut Random, length: Int) -> String`

Generate a random hexadecimal string.

**Parameters:**
- `length` - Length of hex string to generate

**Returns:** Random hex string

### Vector Operations

#### `shuffle_vec<T>(rng: &mut Random, vec: &mut Vec<T>)`

Shuffle a vector in place using Fisher-Yates algorithm.

**Example:**
```astra
mut rng = new();
mut numbers = vec_from([1, 2, 3, 4, 5, 6]);

shuffle_vec(rng, numbers);
// numbers is now randomly shuffled
```

#### `choose_vec<T>(rng: &mut Random, vec: Vec<T>) -> T?`

Choose a random element from a vector.

**Returns:** Random element, or `none` if vector is empty

**Example:**
```astra
mut rng = new();
options = vec_from(["apple", "banana", "cherry"]);

choice = choose_vec(rng, options);
if choice != none {
    print("Selected: " + (choice as String?));
}
```

## Cryptographically Secure Random

### Secure Bytes

#### `secure_bytes(length: Int) -> Vec<UInt8>?`

Generate cryptographically secure random bytes.

**Parameters:**
- `length` - Number of bytes to generate

**Returns:** Vector of secure random bytes, or `none` on error

**Example:**
```astra
// Generate 32 secure random bytes for encryption key
key = secure_bytes(32);
if key == none {
    print("Failed to generate secure random bytes");
}
```

### Secure Numbers

#### `secure_uint64() -> UInt64?`

Generate cryptographically secure 64-bit integer.

**Returns:** Secure random 64-bit value, or `none` on error

#### `secure_int_range(min: Int, max: Int) -> Int?`

Generate cryptographically secure integer in range.

**Parameters:**
- `min` - Minimum value (inclusive)
- `max` - Maximum value (inclusive)

**Returns:** Secure random integer, or `none` on error

**Example:**
```astra
// Generate secure random session ID
session_id = secure_int_range(1000000, 9999999);
```

#### `secure_float() -> Float?`

Generate cryptographically secure float in range [0.0, 1.0).

**Returns:** Secure random float, or `none` on error

### Secure Strings

#### `secure_string(length: Int, charset: String) -> String?`

Generate cryptographically secure random string.

**Parameters:**
- `length` - Length of string to generate
- `charset` - Characters to choose from

**Returns:** Secure random string, or `none` on error

#### `secure_alphanumeric(length: Int) -> String?`

Generate cryptographically secure alphanumeric string.

**Parameters:**
- `length` - Length of string to generate

**Returns:** Secure random alphanumeric string, or `none` on error

**Example:**
```astra
// Generate secure 16-character password
password = secure_alphanumeric(16);
if password != none {
    print("Generated secure password");
}
```

### UUID Generation

#### `uuid_v4() -> String?`

Generate a UUID v4 (random).

**Returns:** UUID string in format `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`, or `none` on error

**Example:**
```astra
id = uuid_v4();
if id != none {
    print("Generated UUID: " + (id as String?));
}
```

## Global Convenience Functions

For simple use cases, the module provides global functions that use an internal random generator:

### Pseudo-Random Convenience

#### `rand_int(min: Int, max: Int) -> Int`

Generate random integer using global RNG.

#### `rand_float(min: Float, max: Float) -> Float`

Generate random float using global RNG.

#### `rand_bool() -> Bool`

Generate random boolean using global RNG.

#### `rand_string(length: Int) -> String`

Generate random alphanumeric string using global RNG.

**Example:**
```astra
// Simple random number generation
dice = rand_int(1, 6);
temperature = rand_float(-10.0, 40.0);
is_ready = rand_bool();
token = rand_string(12);
```

### Secure Random Convenience

#### `rand_secure_int(min: Int, max: Int) -> Int?`

Generate secure random integer.

#### `rand_secure_float() -> Float?`

Generate secure random float.

#### `rand_secure_string(length: Int) -> String?`

Generate secure random alphanumeric string.

## Usage Examples

### Dice Rolling Game

```astra
import std.random;

fn roll_dice(sides Int) Int {
    return rand_int(1, sides);
}

fn play_game() {
    mut player_score = 0;
    mut computer_score = 0;
    mut rounds = 0;
    
    while rounds < 5 {
        player_roll = roll_dice(6);
        computer_roll = roll_dice(6);
        
        print("Round " + (rounds + 1) + ":");
        print("You rolled: " + player_roll);
        print("Computer rolled: " + computer_roll);
        
        if player_roll > computer_roll {
            player_score += 1;
            print("You win this round!");
        } else if computer_roll > player_roll {
            computer_score += 1;
            print("Computer wins this round!");
        } else {
            print("It's a tie!");
        }
        
        rounds += 1;
    }
    
    print("Final score - You: " + player_score + ", Computer: " + computer_score);
    
    if player_score > computer_score {
        print("🎉 You win the game!");
    } else if computer_score > player_score {
        print("😔 Computer wins the game!");
    } else {
        print("🤝 The game is a tie!");
    }
}
```

### Password Generator

```astra
import std.random;

fn generate_password(length Int, include_symbols Bool) String? {
    if length < 8 {
        return none;  // Minimum password length
    }
    
    charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    if include_symbols {
        charset += "!@#$%^&*()_+-=[]{}|;:,.<>?";
    }
    
    return secure_string(length, charset);
}

fn generate_secure_token() String? {
    return secure_alphanumeric(32);
}

// Usage
password = generate_password(16, true);
token = generate_secure_token();

if password != none {
    print("Generated password: " + (password as String?));
}

if token != none {
    print("Generated token: " + (token as String?));
}
```

### Random Data Sampling

```astra
import std.random;

fn random_sample[T](data Vec<T>, sample_size Int) Vec<T>? {
    n = vec_len(data);
    if sample_size > n || sample_size <= 0 {
        return none;
    }
    
    mut result = vec_new() as Vec<T>;
    mut indices = vec_new() as Vec<Int>;
    
    // Generate random indices
    mut i = 0;
    while i < sample_size {
        mut index = rand_int(0, n - 1);
        
        // Check for duplicates
        mut is_duplicate = false;
        mut j = 0;
        while j < vec_len(indices) {
            existing_opt = vec_get(indices, j);
            if existing_opt != none {
                existing = (existing_opt as Int?) ?? 0;
                if existing == index {
                    is_duplicate = true;
                    break;
                }
            }
            j += 1;
        }
        
        if !is_duplicate {
            vec_push(indices, index);
            i += 1;
        }
    }
    
    // Collect samples
    i = 0;
    while i < vec_len(indices) {
        index_opt = vec_get(indices, i);
        if index_opt != none {
            index = (index_opt as Int?) ?? 0;
            item_opt = vec_get(data, index);
            if item_opt != none {
                vec_push(result, (item_opt as T?) ?? vec_get_default());
            }
        }
        i += 1;
    }
    
    return result;
}

// Usage
population = vec_from([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
sample = random_sample(population, 3);
```

## Algorithm Details

### Pseudo-Random Algorithm

The module uses the **Xorshift64*** algorithm for pseudo-random number generation:

- **Fast:** Simple bit operations
- **Good quality:** Passes statistical tests
- **64-bit state:** Provides good period length
- **Deterministic:** Same seed produces same sequence

### Cryptographic Security

Cryptographically secure functions use the operating system's entropy sources:

- **Linux/macOS:** `/dev/urandom` or `getrandom()`
- **Windows:** `BCryptGenRandom` or `CryptGenRandom`
- **Fallback:** System-provided CSPRNG

## Performance Considerations

### Pseudo-Random vs Secure

| Operation | Pseudo-Random | Secure |
|-----------|---------------|--------|
| Speed | Very Fast | Slower |
| Quality | Good | Cryptographic |
| Predictability | Predictable (same seed) | Unpredictable |
| Use Case | Simulations, games | Security, cryptography |

### Recommendations

- **Use pseudo-random** for:
  - Games and simulations
  - Monte Carlo methods
  - Non-security applications
  - Performance-critical code

- **Use secure random** for:
  - Passwords and tokens
  - Encryption keys
  - Session IDs
  - Security-sensitive data

## Security Considerations

- **Never use pseudo-random** for security purposes
- **Always check return values** for secure functions
- **Use appropriate entropy sources** for your security needs
- **Consider key derivation** for cryptographic keys
- **Be aware of platform differences** in entropy quality

## Hosted Compatibility

❌ **Hosted-only** - Requires OS entropy sources and system random number generation.

## See Also

- [Crypto Module](crypto.md) - Cryptographic utilities
- [Time Module](time.md) - Time utilities for seeding
- [Math Module](math.md) - Mathematical utilities
