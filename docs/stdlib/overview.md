# Standard Library Overview

Astra stdlib lives in `stdlib/` and is also bundled under `astra/stdlib/` for installed usage.

Module groups:

- Core types and algorithms: `core`, `algorithm`, `math`
- Data containers: `vec`, `collections`, `data`, `mem`
- Text and encoding: `str`, `encoding`, `c`
- Hosted utilities: `io`, `net`, `fs`, `process`, `env`, `time`, `crypto`, `serde`
- Concurrency/synchronization: `thread`, `sync`, `channel`, `atomic`
- System integration: `hardware`, `path`, `logging`, `random`, `geometry`

Import with `import std.<module>;`.

Current implementation note:

- stdlib source modules document stable API shapes.
- semantic/codegen paths currently expose most callable stdlib-facing APIs as builtins with matching names.
- module docs now include status tags (`stable` / `experimental`) and backend support notes.
