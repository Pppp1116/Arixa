# Type System Internals

Type-related logic spans:

- `astra/semantic.py` (typing rules and coercions)
- `astra/int_types.py` (integer width/signedness parsing)
- `astra/layout.py` (size/alignment/layout calculations)

Key internal concepts:

- canonical type normalization (`Bytes` -> `Vec<u8>`, ref normalization)
- integer type compatibility checks
- option/result generic shape handling
- sized vs unsized value restrictions
- cast validity checks and explicit unsafe boundaries
