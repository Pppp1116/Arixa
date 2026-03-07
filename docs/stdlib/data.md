# Data Module

The `std.data` module provides data structure primitives for freestanding use. All functions in this module are pure and work in both hosted and freestanding modes.

## Usage

```astra
import std.data;
```

## Data Structures

### Stack

A simple stack implemented on top of `Vec<T>` with LIFO (Last In, First Out) semantics.

#### Type Definition

```astra
struct Stack<T> {
    data Vec<T>,
}
```

#### Functions

##### `stack_new() -> Stack<T>`

Create a new empty stack.

**Returns:** Empty stack of type `Stack<T>`

**Example:**
```astra
stack = stack_new();  // Creates: Stack<Int>
```

##### `stack_push(stack: Stack<T>, value: T)`

Push `value` onto `stack`.

**Example:**
```astra
mut stack = stack_new();
stack_push(stack, 42);
stack_push(stack, 17);
```

##### `stack_pop(stack: Stack<T>) -> T?`

Pop and return top value from `stack`.

**Returns:** Top value if stack is not empty, `none` otherwise

**Example:**
```astra
value = stack_pop(stack);  // Returns: 17
```

##### `stack_peek(stack: Stack<T>) -> T?`

Peek at top value without removing it.

**Returns:** Top value if stack is not empty, `none` otherwise

**Example:**
```astra
top = stack_peek(stack);  // Returns: 17 (stack unchanged)
```

##### `stack_is_empty(stack: Stack<T>) -> Bool`

Check if `stack` is empty.

**Returns:** `true` if empty, `false` otherwise

##### `stack_size(stack: Stack<T>) -> Int`

Get size of `stack`.

**Returns:** Number of elements in the stack

**Example:**
```astra
size = stack_size(stack);  // Returns: 2
empty = stack_is_empty(stack);  // Returns: false
```

### Queue

A simple queue implemented on top of `Vec<T>` with FIFO (First In, First Out) semantics.

#### Type Definition

```astra
struct Queue<T> {
    data Vec<T>,
    head Int,
}
```

#### Functions

##### `queue_new() -> Queue<T>`

Create a new empty queue.

**Example:**
```astra
queue = queue_new();  // Creates: Queue<String>
```

##### `queue_enqueue(queue: Queue<T>, value: T)`

Enqueue `value` at the back of `queue`.

**Example:**
```astra
mut queue = queue_new();
queue_enqueue(queue, "first");
queue_enqueue(queue, "second");
```

##### `queue_dequeue(queue: Queue<T>) -> T?`

Dequeue and return front value from `queue`.

**Returns:** Front value if queue is not empty, `none` otherwise

**Example:**
```astra
value = queue_dequeue(queue);  // Returns: "first"
```

##### `queue_peek(queue: Queue<T>) -> T?`

Peek at front value without removing it.

**Returns:** Front value if queue is not empty, `none` otherwise

##### `queue_is_empty(queue: Queue<T>) -> Bool`

Check if `queue` is empty.

##### `queue_size(queue: Queue<T>) -> Int`

Get size of `queue`.

**Example:**
```astra
size = queue_size(queue);  // Returns: 1
```

### Ring Buffer

A simple fixed-size ring buffer (circular buffer) for efficient FIFO operations.

#### Type Definition

```astra
struct RingBuffer<T> {
    data Vec<T>,
    head Int,
    tail Int,
    capacity Int,
}
```

#### Functions

##### `ring_buffer_new(capacity: Int) -> RingBuffer<T>`

Create a new ring buffer with `capacity`.

**Parameters:**
- `capacity` - Maximum number of elements

**Returns:** New ring buffer

**Example:**
```astra
buffer = ring_buffer_new(10);  // Creates buffer for 10 elements
```

##### `ring_buffer_push(buffer: RingBuffer<T>, value: T) -> Bool?`

Push `value` into ring buffer.

**Returns:** 
- `true` if push succeeded
- `none` if buffer is full

**Example:**
```astra
result = ring_buffer_push(buffer, 42);
if result == none {
    // Buffer full, handle overflow
}
```

##### `ring_buffer_pop(buffer: RingBuffer<T>) -> T?`

Pop value from ring buffer.

**Returns:** Popped value if buffer is not empty, `none` otherwise

**Example:**
```astra
value = ring_buffer_pop(buffer);
if value == none {
    // Buffer empty
}
```

## Usage Examples

### Stack Example

```astra
import std.data;

fn reverse_numbers(numbers Vec<Int>) Vec<Int> {
    mut stack = stack_new();
    mut result = vec_new() as Vec<Int>;
    
    // Push all numbers onto stack
    mut i = 0;
    while i < vec_len(numbers) {
        num_opt = vec_get(numbers, i);
        if num_opt != none {
            stack_push(stack, (num_opt as Int?) ?? 0);
        }
        i += 1;
    }
    
    // Pop to reverse order
    while !stack_is_empty(stack) {
        val_opt = stack_pop(stack);
        if val_opt != none {
            vec_push(result, (val_opt as Int?) ?? 0);
        }
    }
    
    return result;
}
```

### Queue Example

```astra
import std.data;

fn process_tasks(task_names Vec<String>) {
    mut queue = queue_new();
    
    // Enqueue all tasks
    mut i = 0;
    while i < vec_len(task_names) {
        task_opt = vec_get(task_names, i);
        if task_opt != none {
            queue_enqueue(queue, (task_opt as String?) ?? "");
        }
        i += 1;
    }
    
    // Process tasks in order
    while !queue_is_empty(queue) {
        task_opt = queue_dequeue(queue);
        if task_opt != none {
            task = (task_opt as String?) ?? "";
            print("Processing: " + task);
            // Process task...
        }
    }
}
```

## Performance Characteristics

| Structure | Push | Pop | Peek | Space |
|-----------|------|-----|------|-------|
| Stack | O(1) | O(1) | O(1) | O(n) |
| Queue | O(1) | O(1) | O(1) | O(n) |
| Ring Buffer | O(1) | O(1) | O(1) | O(capacity) |

## Limitations

- **Stack:** Uses simplified pop that doesn't shrink the underlying vector
- **Queue:** Head pointer only moves forward, doesn't reclaim used space
- **Ring Buffer:** Fixed capacity, requires knowing size in advance

## Freestanding Compatibility

✅ **Freestanding-safe** - All data structures are pure and don't require runtime support.

## See Also

- [Vector Module](vec.md) - Underlying vector operations
- [Algorithm Module](algorithm.md) - Algorithms for data structures
- [Collections Module](collections.md) - Higher-level collection utilities
