# std.crypto

Source: `stdlib/crypto.astra`

Status: `experimental` (hosted runtime wrapper)

Functions:

- `sha256(s) -> String`
- `hmac_sha256(key, data) -> String`
- `digest_pair(a, b) -> String`
- `rand_bytes(len i32) -> Vec<u8> | CryptoError`

Types:

- `CryptoError { message String, code i32 }`

Backend support:

- Python backend: supported
- Native backend (LLVM + runtime): supported
- Freestanding mode: not supported

These wrappers use hosted runtime cryptographic helpers.

Current limits:

- No key/nonce typed wrappers
- No AEAD/KDF API in stdlib yet
- No constant-time guarantees documented at language level

Near-term direction:

- Add KDF and AEAD APIs on top of current RNG support
- Add misuse-resistant diagnostics around key/nonce handling
