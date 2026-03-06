# Feature Status Matrix

This document tracks ASTRA implementation status against a minimally complete systems-language baseline.

Status labels:

- `stable`: implemented and broadly verified in tests
- `partial`: implemented but limited in depth or backend parity
- `experimental`: available but semantics/tooling are still evolving
- `planned`: not yet implemented

## Language and Compiler

| Area | Status | Current State | Next Concrete Step | Acceptance Criteria |
| --- | --- | --- | --- | --- |
| Syntax and parsing | stable | Core syntax, async/await keywords, unsafe, generics, match are parsed. | Keep grammar docs synced with parser changes. | Parser + formatter + syntax docs updated in same PR. |
| Semantic typing | partial | Strong baseline checks and integer strictness exist, including `trait` declarations, `impl Trait for Type` markers, and `where`-bounded call resolution for generic impl functions. | Add trait method requirements and coherence diagnostics for conflicting trait impls. | New constrained-generic tests pass; invalid impl overlap rejected. |
| Generics | partial | Parametric + impl specialization exists with `where` trait bounds for overload resolution and return-type substitution from inferred type vars. | Expand to full coherence rules and richer trait-driven method resolution. | Coherence and method resolution tests pass. |
| Pattern matching | partial | Wildcard + Bool + enum-variant exhaustiveness checks are implemented with `|` alternatives and `if` guards (without deep ADT destructuring). | Implement ADT destructuring and deeper nested-pattern coverage checker. | Exhaustiveness/redundancy suite for enums and nested patterns passes. |
| Ownership/borrow safety | partial | Move checks + borrow state + basic lifetime-like return rule implemented. | Extend region/lifetime reasoning and diagnostics. | Borrow/lifetime regression suite covers escapes and aliasing edge cases. |
| Error handling ergonomics | partial | `Option`/`Result` enums exist; `?` supports `Option<T>` and `Result<T, E>` in semantic analysis plus Python and LLVM/native lowering. | Add richer `Result` ergonomics (`map`, `and_then`, pattern destructuring) and diagnostics polish. | `?` behavior is parity-tested for `Option`/`Result` across Python and native backends. |
| Compile-time evaluation | experimental | `comptime` infra exists and is tested for basic cases. | Expand deterministic CTFE boundaries + diagnostics. | CTFE failure diagnostics include stable spans and notes. |

## Runtime and Backends

| Area | Status | Current State | Next Concrete Step | Acceptance Criteria |
| --- | --- | --- | --- | --- |
| Python backend | partial | Broad hosted feature support; fast dev loop backend. | Keep behavior aligned with documented semantics. | Golden semantic behavior stays consistent across releases. |
| LLVM IR backend | partial | Extensive IR lowering and validation pipeline. | Continue parity hardening for hosted runtime APIs. | Backend parity tests cover builtins used by stdlib wrappers. |
| Native runtime helpers | partial | Runtime includes memory, file/process/time helpers and TCP on POSIX. | Implement platform shims for non-POSIX networking. | Native network tests pass on Linux/macOS and have explicit Windows status. |
| Async/concurrency runtime | partial | Native `spawn/join` uses real OS threads for Int worker signatures; `await_result` remains lightweight without a full async scheduler contract. | Finalize scheduler/runtime contract for async beyond thread spawn/join. | Async/threading docs and stress tests cover the finalized model. |
| Cross-platform target matrix | partial | LLVM target triple support exists, runtime is mostly POSIX-oriented. | Define tier targets + CI matrix. | CI executes core suite on declared tier-1 targets. |

## Tooling and Ecosystem

| Area | Status | Current State | Next Concrete Step | Acceptance Criteria |
| --- | --- | --- | --- | --- |
| CLI/build/check/test/fmt | stable | Core commands exist and are exercised by tests. | Improve UX consistency and error messages. | Tooling snapshots stay stable across fixtures. |
| LSP/IDE | partial | Hover/definition/rename/format/code actions exist. | Add deeper quick-fix coverage and diagnostic actions. | LSP integration tests cover multi-file quick fixes. |
| Package manager (`astpm`) | partial | Add/remove/list/search/update/publish/lock/verify available with semver-aware transitive lock solving, source/checksum metadata, and registry cache fallback for offline use. | Improve conflict diagnostics for complex transitive constraints and workspace-scale dependency ergonomics. | Lockfile includes deterministic transitive graph, and `astpm verify` validates cached package integrity. |
| Incremental builds/cache | partial | Hash-based build caching exists; native sanitizer toggles are integrated into build cache keys and CLI flags. | Add finer-grained invalidation and module-level cache keys. | Incremental rebuild tests verify minimal recompilation. |
| Self-hosting | planned | Placeholder command/file-copy behavior only. | Replace with staged real self-host toolchain path. | `astra selfhost` builds compiler artifact end-to-end. |

## Standard Library

| Area | Status | Current State | Next Concrete Step | Acceptance Criteria |
| --- | --- | --- | --- | --- |
| `std.core` / checked numerics | stable | `Option`/`Result` and checked int helpers exist. | Add ergonomic sugar support (`?`) from language side. | Core error-handling examples compile and pass. |
| Collections | experimental | Dynamic list/map wrappers over runtime `Any`. | Add typed containers + iterator abstractions. | Typed container API has unit + semantic tests. |
| Concurrency helpers | partial | `std.thread` spawn/join and `std.atomic` are runtime-backed (OS threads + seq-cst atomics); `std.sync`/`std.channel` are still cooperative wrappers. | Replace cooperative sync/channel wrappers with runtime-backed primitives. | Thread/atomic behavior and sync/channel semantics are parity-tested with stress coverage. |
| Networking | experimental | TCP helper wrappers implemented for hosted backends with cross-backend parity coverage for connect/send/recv/close success + failure paths. | Add richer socket/error model and non-blocking options. | TCP tests include connect/send/recv/close success + failures. |
| Serde | experimental | JSON serialize/deserialize wrappers for dynamic values. | Add typed decode and derive hooks. | Typed serde roundtrip tests and diagnostics pass. |
| Crypto | experimental | SHA-256 and HMAC-SHA256 wrappers. | Add RNG/KDF/AEAD APIs with safer typed contracts. | Crypto API tests include misuse-resistant paths. |
| Math | stable | Pure integer helper functions. | Expand float/trig utilities as separate stable module. | Math docs + tests for new APIs pass in hosted/freestanding modes. |

## Execution Order

1. Backend/runtime parity and status documentation truth.
2. Trait-constrained generics and pattern-match exhaustiveness.
3. Error ergonomics (`?`) and package resolver lock integrity.
4. Concurrency/async model finalization and stdlib deepening.
5. Cross-platform CI tiers and self-hosting milestone.
