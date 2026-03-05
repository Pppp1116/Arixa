# Roadmap

This roadmap reflects the current repository implementation and near-term direction.

## Current Baseline

- Working lexer/parser/semantic pipeline
- Python and LLVM backends
- Native linking via `clang`
- Hosted/freestanding compilation modes
- CLI + formatter + linter + docgen + LSP tooling

## In Progress

- Continued semantic diagnostics quality improvements
- Expanded language/server test matrix
- Better documentation and API annotation coverage

## Next Priorities

- Broader stdlib ergonomics and examples
- Incremental compiler performance improvements
- Stronger packaging/dependency workflow (`astpm`)
- Additional backend stabilization and freestanding validation

## Longer Term

- Improve self-hosting story (current `selfhost` command is intentionally unavailable)
- Deeper optimization/lowering passes
- Expanded IDE/editor integrations
