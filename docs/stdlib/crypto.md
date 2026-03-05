# std.crypto

Source: `stdlib/crypto.astra`

Status: `experimental` (hosted runtime wrapper)

Functions:

- `sha256(s) -> String`
- `hmac_sha256(key, data) -> String`
- `digest_pair(a, b) -> String`

Backend support:

- Python backend: supported
- Native backend (LLVM + runtime): supported
- Freestanding mode: not supported

These wrappers use hosted runtime cryptographic helpers.

Current limits:

- No key/nonce typed wrappers
- No AEAD/KDF/RNG API in stdlib yet
- No constant-time guarantees documented at language level
