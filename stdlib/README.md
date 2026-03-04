## Astra Stdlib Overview

This directory contains the development copy of the Astra standard library. In
installed builds the same modules are bundled under `astra/stdlib`.

Each module is either **freestanding-safe** (can be analyzed/used with
`--freestanding`) or **hosted-only** (relies on the runtime and host OS).

### Module index

| Module            | Description                                      | Freestanding? |
| -----------------| ------------------------------------------------ | ------------- |
| `core.astra`     | Core types (`Option`, `Result`, `Bytes`) and checked integer helpers. | ✅ |
| `math.astra`     | Small pure numeric helpers (`min_int`, `max_int`, `clamp_int`, `abs_int`). | ✅ |
| `vec.astra`      | Typed wrappers around `vec_*` container builtins for `Vec<T>`. | ✅ |
| `mem.astra`      | Simple helpers for filling/copying `Bytes` (`Vec<u8>`) using the freestanding vector API. | ✅ |
| `collections.astra` | Hosted list/map helpers built on the runtime list/map API. | ❌ |
| `io.astra`       | Hosted file I/O (`read`, `write`, `read_or`, etc.) and printing helpers (`print_int`, `print_bool`, `print_float`, `print_str`, `print_any`). | ❌ |
| `str.astra`      | Hosted string utilities (`length`, `is_empty`, `to_string_*`, `parse_int`). | ❌ |
| `net.astra`      | Hosted TCP helpers (`tcp_connect`, `tcp_send`, `tcp_send_line`, `tcp_recv`, `tcp_close`). | ❌ |
| `process.astra`  | Hosted process/environment helpers (`exit`, `env_or`, `cwd`, `run_ok`, `eprintln`). | ❌ |
| `crypto.astra`   | Hosted cryptographic helpers (`sha256`, `hmac_sha256`, `digest_pair`). | ❌ |
| `random.astra`   | Hosted cryptographic randomness (`secure_bytes`). | ❌ |
| `crypto/otp.astra` | Hosted one-time pad helpers (`OtpKey`, `OtpError`, `xor_bytes`, `encrypt`, `decrypt`, UTF-8 helpers). | ❌ |
| `serde.astra`    | Hosted JSON helpers (`to_json`, `from_json`).    | ❌ |
| `time.astra`     | Hosted time helpers (`now_ms`, `monotonic_ms`, `sleep_ms`, `sleep_seconds`). | ❌ |

Freestanding analysis is validated in `tests/test_stdlib_modules.py` and
runtime behavior is exercised throughout the end-to-end and integration tests.


Build note: ASTRA now performs reachability-based dead-code elimination before codegen, so only standard-library declarations that are actually reachable from your entry point are emitted into final build artifacts.
