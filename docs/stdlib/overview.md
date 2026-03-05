# Standard Library Overview

Astra stdlib lives in `stdlib/` and is also bundled under `astra/stdlib/` for installed usage.

Module groups:

- Core types and checked arithmetic: `core`
- Data containers: `vec`, `collections`, `mem`
- Hosted utilities: `io`, `net`, `process`, `time`, `crypto`, `serde`, `str`
- Math helpers: `math`

Import with `import std.<module>;`.

Current implementation note:

- stdlib source modules document stable API shapes.
- semantic/codegen paths currently expose most callable stdlib-facing APIs as builtins with matching names.
