# Modules

## Import Forms

- Preferred stdlib import: `import std.io;`
- Legacy stdlib form: `import stdlib::io;`
- File-path import: `import "relative/path";`

## Resolution Rules

- Stdlib imports resolve from stdlib root (`ASTRA_STDLIB_PATH`, repo `stdlib/`, or bundled module stdlib).
- Non-stdlib module imports resolve from nearest module root containing `Astra.toml`.
- If no module root exists, imports resolve relative to importing file.

Resolver implementation: `astra/module_resolver.py`.

## Current Implementation Status

- Import declarations are resolved and validated.
- Optional aliases are tracked for diagnostics/type context.
- Full symbol loading from imported modules is implemented with recursive loading of imported declarations/items.
- Most stdlib-facing callable APIs are currently available through builtin function names.
