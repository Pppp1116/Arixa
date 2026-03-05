# Semantic Analysis

Implementation: `astra/semantic.py`

Main entrypoint:

- `analyze(prog, filename=..., freestanding=..., require_entrypoint=...)`

Responsibilities:

- name resolution and symbol table checks
- type inference/validation
- borrow/move safety checks
- builtin validation and freestanding restrictions
- function/return/entrypoint validation

Error type:

- `SemanticError`
