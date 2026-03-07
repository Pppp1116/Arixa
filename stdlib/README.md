## Astra Stdlib Overview

This directory contains the development copy of the Astra standard library. In
installed builds the same modules are bundled under `astra/stdlib`.

Each module is either **freestanding-safe** (can be analyzed/used with
`--freestanding`) or **hosted-only** (relies on the runtime and host OS).

### Module index

| Module            | Description                                      | Freestanding? |
| -----------------| ------------------------------------------------ | ------------- |
| `algorithm.astra` | Pure algorithms (binary search, sorting, etc.) | ✅ |
| `atomic.astra`   | Compatibility atomic API (`AtomicInt`, load/store/fetch_add/cas). | ✅ |
| `c.astra`         | C language bindings and FFI utilities | ❌ |
| `channel.astra`  | Runtime-backed FIFO channel (`channel_new`, `channel_send`, `channel_recv`, `channel_close`). | ❌ |
| `collections.astra` | Hosted list/map helpers with typed wrappers (`List<T>`, `Map<K,V>`) and nullable getters. | ❌ |
| `core.astra`     | Core types (`Option`, `Result`, `Bytes`) and checked integer helpers. | ✅ |
| `crypto.astra`   | Hosted cryptographic helpers (`sha256`, `hmac_sha256`, `digest_pair`, `rand_bytes`). | ❌ |
| `data.astra`      | Data structure primitives (Stack, Queue, RingBuffer) | ✅ |
| `encoding.astra` | Text encoding utilities (UTF-8, Base64, hex, URL) | ✅ |
| `env.astra`       | Environment variable utilities (get, set, current directory) | ❌ |
| `fs.astra`        | File system utilities (create, read, write, metadata) | ❌ |
| `geometry.astra`  | 2D/3D vector and matrix operations for graphics/physics | ✅ |
| `hardware.astra`  | Low-level hardware interaction (memory barriers, bit manipulation) | ✅ |
| `io.astra`        | Hosted file I/O (`read`, `write`, `read_or`, etc.) and printing helpers (`print_int`, `print_bool`, `print_float`, `print_str`, `print_any`). | ❌ |
| `logging.astra`   | Structured logging with levels, formatting, and file output | ❌ |
| `math.astra`      | Small pure numeric helpers (`min_int`, `max_int`, `clamp_int`, `abs_int`). | ✅ |
| `mem.astra`       | Simple helpers for filling/copying `Bytes` (`Vec<u8>`) using the freestanding vector API. | ✅ |
| `net.astra`       | Hosted TCP helpers (`tcp_connect`, `tcp_send`, `tcp_send_line`, `tcp_recv`, `tcp_close`). | ❌ |
| `path.astra`      | Cross-platform path manipulation utilities | ✅ |
| `process.astra`   | Hosted process/environment helpers (`exit`, `env_or`, `cwd`, `run_ok`, `eprintln`). | ❌ |
| `random.astra`    | Random number generation (fast pseudo-random and cryptographically secure) | ❌ |
| `serde.astra`     | Hosted JSON helpers (`to_json<T>`, `from_json`, `from_json_t<T>`, `ParseError`).    | ❌ |
| `str.astra`       | Hosted string utilities (`length`, `is_empty`, `to_string_*`, `parse_int`). | ❌ |
| `sync.astra`      | Runtime-backed mutex wrappers (`mutex_new`, `mutex_lock`, `mutex_unlock`). | ❌ |
| `thread.astra`    | Hosted task wrappers (`spawn0`, `spawn1`, `join_task`, `join_timeout`, `yield_now`). | ❌ |
| `time.astra`      | Hosted time helpers (`now_ms`, `monotonic_ms`, `sleep_ms`, `sleep_seconds`). | ❌ |
| `vec.astra`       | Typed wrappers around `vec_*` container builtins for `Vec<T>`. | ✅ |

Freestanding analysis is validated in `tests/test_stdlib_modules.py` and
runtime behavior is exercised throughout the end-to-end and integration tests.
