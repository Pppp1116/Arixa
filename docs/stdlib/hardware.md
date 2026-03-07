# Hardware Module

The `std.hardware` module provides low-level hardware interaction primitives for embedded and kernel development. All functions in this module are pure and work in both hosted and freestanding modes.

## Usage

```astra
import std.hardware;
```

## Memory Operations

### Memory Barriers

Memory barriers ensure proper ordering of memory operations in multi-threaded and low-level code.

#### Constants

```astra
const MEMORY_BARRIER_FULL = 0;
const MEMORY_BARRIER_READ = 1;
const MEMORY_BARRIER_WRITE = 2;
```

#### `memory_barrier(barrier_type: MemoryBarrier)`

Execute a memory barrier to prevent reordering of memory operations.

**Parameters:**
- `barrier_type` - Type of barrier (FULL, READ, or WRITE)

**Example:**
```astra
// Ensure all previous writes complete before next operation
memory_barrier(MEMORY_BARRIER_WRITE);

// Ensure all previous operations complete
memory_barrier(MEMORY_BARRIER_FULL);
```

### Atomic Operations

#### `atomic_compare_exchange_loop(ptr: &mut Int, expected: Int, desired: Int) -> (Int, Bool)`

Atomic compare-and-swap loop that retries until successful or value changes.

**Returns:** Tuple of (old_value, success_flag)

**Example:**
```astra
mut counter = 42;
(old_val, success) = atomic_compare_exchange_loop(counter, 42, 43);
if success {
    // Successfully updated from 42 to 43
}
```

#### `atomic_fetch_add_checked(ptr: &mut Int, delta: Int) -> Int?`

Atomic fetch-add with overflow checking.

**Returns:** Previous value, or `none` on overflow

**Example:**
```astra
mut value = maxVal(Int) - 1;
result = atomic_fetch_add_checked(value, 2);
if result == none {
    // Overflow would occur
}
```

## Synchronization Primitives

### Spin Waiting

#### `spin_wait(condition: fn() Bool, timeout: Int) -> Bool`

Spin-wait until `condition` becomes true or `timeout` cycles pass.

**Parameters:**
- `condition` - Function that returns boolean condition
- `timeout` - Maximum number of cycles to wait

**Returns:** `true` if condition was met, `false` if timeout occurred

**Example:**
```astra
// Wait for register to be ready, max 1000 cycles
ready = spin_wait(fn() {
    return read_reg(status_addr) & READY_FLAG != 0;
}, 1000);
```

#### `cpu_pause()`

CPU pause instruction to yield in spin loops (reduces power consumption).

**Example:**
```astra
while !is_ready() {
    cpu_pause();  // Be polite to the CPU
}
```

## Timing Operations

### Cycle Counters

#### `read_cycle_counter() -> Int?`

Read CPU cycle counter if available.

**Returns:** Cycle count, or `none` if not supported

**Example:**
```astra
cycles = read_cycle_counter();
if cycles != none {
    start = cycles as Int;
    // Do work...
    end = read_cycle_counter() as Int;
    elapsed = end - start;
}
```

#### `read_timestamp() -> Int?`

Read timestamp counter in nanoseconds if available.

**Returns:** Timestamp in nanoseconds, or `none` if not supported

**Example:**
```astra
time = read_timestamp();
if time != none {
    nanos = time as Int;
    print("Current time: " + nanos + " ns");
}
```

## Bit Manipulation

Bit manipulation utilities for hardware register operations.

### Basic Bit Operations

#### `bit_set(value: Int, n: Int) -> Int`

Set bit `n` in `value`.

**Example:**
```astra
flags = bit_set(0b1000, 2);  // Sets bit 2: 0b1100
```

#### `bit_clear(value: Int, n: Int) -> Int`

Clear bit `n` in `value`.

**Example:**
```astra
flags = bit_clear(0b1100, 2);  // Clears bit 2: 0b1000
```

#### `bit_toggle(value: Int, n: Int) -> Int`

Toggle bit `n` in `value`.

**Example:**
```astra
flags = bit_toggle(0b1000, 2);  // Toggles bit 2: 0b1100
```

#### `bit_is_set(value: Int, n: Int) -> Bool`

Check if bit `n` is set in `value`.

**Example:**
```astra
is_set = bit_is_set(0b1100, 2);  // Returns: true
```

### Bit Field Operations

#### `bit_extract(value: Int, hi: Int, lo: Int) -> Int`

Extract bits `hi:lo` from `value`.

**Parameters:**
- `hi` - High bit position (inclusive)
- `lo` - Low bit position (inclusive)

**Example:**
```astra
value = 0b12345678;
field = bit_extract(value, 15, 8);  // Extract bits 15-8
```

#### `bit_insert(value: Int, field: Int, hi: Int, lo: Int) -> Int`

Insert `field` into bits `hi:lo` of `value`.

**Example:**
```astra
value = bit_insert(0x12345678, 0xAB, 15, 8);  // Insert 0xAB into bits 15-8
```

## Memory-Mapped I/O

### Register Operations

#### `read_reg(addr: &Int) -> Int`

Read a memory-mapped register.

**Parameters:**
- `addr` - Address of register

**Example:**
```astra
status = read_reg(DEVICE_STATUS_ADDR);
```

#### `write_reg(addr: &mut Int, value: Int)`

Write to a memory-mapped register with memory barrier.

**Example:**
```astra
write_reg(CONTROL_ADDR, 0x1);
```

#### `modify_reg(addr: &mut Int, mask: Int, value: Int)`

Read-modify-write a register with memory barriers.

**Parameters:**
- `mask` - Bits to modify (1 = modify, 0 = preserve)
- `value` - New values for masked bits

**Example:**
```astra
// Set bits 0 and 2, clear bit 1
modify_reg(CONFIG_ADDR, 0b111, 0b101);
```

#### `wait_for_reg_field(addr: &Int, mask: Int, expected: Int, timeout: Int) -> Bool`

Wait for a register field to match `expected` with timeout.

**Example:**
```astra
// Wait for bit 0 to be set, max 1000 cycles
ready = wait_for_reg_field(STATUS_ADDR, 0b1, 0b1, 1000);
```

## Usage Examples

### Device Driver Pattern

```astra
import std.hardware;

// Device register addresses
const UART_STATUS = 0x1000;
const UART_DATA = 0x1004;
const UART_TX_READY = 0x1;
const UART_RX_READY = 0x2;

fn uart_write_byte(addr &Int, data Int) Bool {
    // Wait for TX ready
    ready = wait_for_reg_field(UART_STATUS, UART_TX_READY, UART_TX_READY, 10000);
    if !ready {
        return false;
    }
    
    // Write data
    write_reg(UART_DATA, data);
    return true;
}

fn uart_read_byte(addr &Int) Int? {
    // Check if RX ready
    status = read_reg(UART_STATUS);
    if !bit_is_set(status, 1) {
        return none;
    }
    
    // Read data
    return read_reg(UART_DATA);
}
```

### Atomic Counter

```astra
import std.hardware;

struct AtomicCounter {
    value Int,
}

fn atomic_increment(counter &mut AtomicCounter) Int? {
    return atomic_fetch_add_checked(counter.value, 1);
}

fn atomic_set_if_zero(counter &mut AtomicCounter, new_val Int) Bool {
    (old_val, success) = atomic_compare_exchange_loop(counter.value, 0, new_val);
    return success;
}
```

## Performance Considerations

- **Memory barriers** can be expensive, use only when necessary
- **Spin waiting** should have reasonable timeouts to avoid infinite loops
- **Bit operations** are compile-time constants and very fast
- **Register operations** map directly to memory access instructions

## Safety Notes

- Memory-mapped I/O requires proper hardware documentation
- Atomic operations require proper memory alignment
- Spin waits can cause deadlocks if conditions are never met
- Always validate register addresses and bit positions

## Freestanding Compatibility

✅ **Freestanding-safe** - All operations are pure and suitable for embedded/kernel use.

## See Also

- [Atomic Module](atomic.md) - Higher-level atomic operations
- [Math Module](math.md) - Bit manipulation helpers
- [C Module](c.md) - Low-level C interoperability
