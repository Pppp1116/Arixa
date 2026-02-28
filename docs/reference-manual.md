# Astra Reference Manual

## CLI
- `astra build <in> -o <out> [--target py|x86_64] [--emit-ir out.json] [--strict] [--freestanding]`
- `astra check <in> [--freestanding]`
- `astra run <in>`
- `astra test [--kind unit|integration|e2e]`
- `astra selfhost`

## Tooling
- `astpm init/add/lock`
- `astfmt <file>`
- `astlint <file>`
- `astdoc <in> -o <out>`
- `astlsp`
- `astdbg <py script>`
- `astprof <py script>`

## Standard library modules
- collections, io, net, serde, process, time, crypto

## Language conveniences
- `defer <expr>;`
- null coalescing: `<a> ?? <b>`
- immutable bindings: `fixed name[: Type] = expr;`
- typed params/fields accept `name Type` and `name: Type` (canonical style is `name: Type`)
- specialization impls: `impl fn name(...) -> ... { ... }`
- compile-time execution: `comptime { ... }` (pure/deterministic subset)
