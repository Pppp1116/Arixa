# std.serde

Source: `stdlib/serde.astra`

Status: `experimental` (hosted runtime wrapper)

Functions:

- `to_json<T>(v T) -> String`
- `from_json(s String) -> Any`
- `from_json_t<T>(s String) -> T | ParseError`

Types:

- `ParseError { message String, line i32 }`

Backend support:

- Python backend: supported
- Native backend (LLVM + runtime): supported
- Freestanding mode: not supported

Current scope:

- JSON encode/decode for hosted runtime values
- Typed decode surface via `from_json_t<T>`
- Build pipeline includes serde derive expansion hooks for annotated structs/enums

Current limits:

- Typed decode currently relies on cast-based conversion from dynamic payloads
- Derive expansion is early-stage and not a full schema-aware serializer contract
- No streaming parser/encoder
- No structured error location information

Near-term direction:

- Improve typed decode mismatch diagnostics and error fidelity
- Expand derive behavior coverage and interoperability guarantees
