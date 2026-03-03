## Astra Stdlib Overview

This directory contains development copy of Astra standard library. In
installed builds, same modules are bundled under `astra/stdlib`.

Each module is either **freestanding-safe** (can be analyzed/used with
`--freestanding`) or **hosted-only** (relies on the runtime and host OS).

### Module index

| Module            | Description                                      | Freestanding? |
| -----------------| ------------------------------------------------ | ------------- |
| `core.astra`     | Core types (`Option`, `Result`, `Bytes`) and checked integer helpers. | ✅ |
| `math.astra`     | Small pure numeric helpers (`min_int`, `max_int`, `clamp_int`, `abs_int`). | ✅ |
| `vec.astra`      | Typed wrappers around `vec_*` container builtins for `Vec<T>`. | ✅ |
| `mem.astra`      | Simple helpers for filling/copying `Bytes` (`Vec<u8>`) using freestanding vector API. | ✅ |
| `encoding.astra` | UTF-8, ASCII encoding/decoding utilities and character manipulation. | ✅ |
| `hash.astra`     | SHA-256, MD5, HMAC hashing and simple hash functions. | ✅ |
| `algorithm.astra` | Sorting, searching, and data manipulation algorithms. | ✅ |
| `convert.astra`   | Safe type conversions between numeric types and strings. | ✅ |
| `collections.astra` | Hosted list/map helpers built on runtime list/map API. | ❌ |
| `io.astra`       | Hosted file I/O (`read`, `write`, `read_or`, etc.) and printing helpers (`print_int`, `print_bool`, `print_float`, `print_str`, `print_any`). | ❌ |
| `str.astra`      | Hosted string utilities (`length`, `is_empty`, `to_string_*`, `parse_int`). | ❌ |
| `net.astra`      | Hosted TCP helpers (`tcp_connect`, `tcp_send`, `tcp_send_line`, `tcp_recv`, `tcp_close`). | ❌ |
| `process.astra`  | Hosted process/environment helpers (`exit`, `env_or`, `cwd`, `run_ok`, `eprintln`). | ❌ |
| `crypto.astra`   | Hosted cryptographic helpers (`sha256`, `hmac_sha256`, `digest_pair`). | ❌ |
| `serde.astra`    | Hosted JSON helpers (`to_json`, `from_json`).    | ❌ |
| `time.astra`     | Hosted time helpers (`now_ms`, `monotonic_ms`, `sleep_ms`, `sleep_seconds`). | ❌ |
| `fs.astra`       | Hosted filesystem operations (directory traversal, path manipulation, metadata). | ❌ |
| `os.astra`       | Hosted OS utilities (environment, process info, system operations). | ❌ |
| `sync.astra`     | Hosted synchronization primitives (mutex, atomic operations, condition variables). | ❌ |
| `regex.astra`    | Basic regular expression matching and compilation. | ❌ |
| `random.astra`   | Hosted random number generation with various distributions. | ❌ |

Freestanding analysis is validated in `tests/test_stdlib_modules.py` and
runtime behavior is exercised throughout end-to-end and integration tests.
