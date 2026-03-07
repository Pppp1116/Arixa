# Algorithm Module

The `std.algorithm` module provides pure algorithms for freestanding use. All functions in this module are pure and work in both hosted and freestanding modes.

## Usage

```astra
import std.algorithm;
```

## Functions

### Search Operations

#### `binary_search_int(data: Vec<Int>, target: Int) -> Int?`

Performs binary search for `target` in sorted integer `data`.

**Returns:** Index of `target` if found, `none` otherwise.

**Complexity:** O(log n)

**Example:**
```astra
sorted_data = vec_from([1, 3, 5, 7, 9, 11]);
index = binary_search_int(sorted_data, 7);  // Returns: 3
not_found = binary_search_int(sorted_data, 4);  // Returns: none
```

#### `linear_search_int(data: Vec<Int>, target: Int) -> Int?`

Performs linear search for `target` in integer `data`.

**Returns:** Index of `target` if found, `none` otherwise.

**Complexity:** O(n)

**Example:**
```astra
data = vec_from([5, 2, 8, 1, 9]);
index = linear_search_int(data, 8);  // Returns: 2
not_found = linear_search_int(data, 7);  // Returns: none
```

### Aggregate Operations

#### `find_min_int(data: Vec<Int>) -> Int?`

Find minimum value in integer `data`.

**Returns:** Minimum value if `data` is not empty, `none` otherwise.

**Example:**
```astra
data = vec_from([5, 2, 8, 1, 9]);
min_val = find_min_int(data);  // Returns: 1
empty = vec_new() as Vec<Int>;
none_result = find_min_int(empty);  // Returns: none
```

#### `find_max_int(data: Vec<Int>) -> Int?`

Find maximum value in integer `data`.

**Returns:** Maximum value if `data` is not empty, `none` otherwise.

**Example:**
```astra
data = vec_from([5, 2, 8, 1, 9]);
max_val = find_max_int(data);  // Returns: 9
```

### Query Operations

#### `contains_int(data: Vec<Int>, target: Int) -> Bool`

Check if integer `data` contains `target`.

**Returns:** `true` if `target` is found, `false` otherwise.

**Example:**
```astra
data = vec_from([5, 2, 8, 1, 9]);
has_eight = contains_int(data, 8);  // Returns: true
has_seven = contains_int(data, 7);  // Returns: false
```

#### `count_int(data: Vec<Int>, target: Int) -> Int`

Count occurrences of `target` in integer `data`.

**Returns:** Number of times `target` appears in `data`.

**Example:**
```astra
data = vec_from([5, 2, 8, 2, 9, 2]);
count = count_int(data, 2);  // Returns: 3
```

## Performance Considerations

- **Binary search** requires the input data to be sorted
- **Linear search** works on unsorted data but is slower for large datasets
- All functions use safe vector operations with proper bounds checking
- Functions return `none` for edge cases (empty data, not found) rather than panicking

## Freestanding Compatibility

✅ **Freestanding-safe** - All functions are pure and don't require runtime support.

## See Also

- [Vector Module](vec.md) - Basic vector operations
- [Math Module](math.md) - Mathematical utilities
- [Data Module](data.md) - Data structure primitives
