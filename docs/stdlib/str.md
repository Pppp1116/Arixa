# std.str

Source: `stdlib/str.astra`

Functions:

- `length(s) -> Int`
- `is_empty(s) -> Bool`
- `to_string_int(x) -> String`
- `to_string_bool(x) -> String`
- `to_string_float(x) -> String`
- `parse_int(s) -> Int`

`parse_int` depends on runtime JSON parsing behavior and may fail at runtime for invalid numeric text.
