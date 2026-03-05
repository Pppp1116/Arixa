# Compiler Architecture

## Modules

- AST definitions: `astra/ast.py`
- Lexer: `astra/lexer.py`
- Parser: `astra/parser.py`
- Semantic/type checks: `astra/semantic.py`
- Compile-time executor: `astra/comptime.py`
- Lowering/optimization: `astra/for_lowering.py`, `astra/optimizer.py`
- Backends: `astra/codegen.py`, `astra/llvm_codegen.py`
- Build/check orchestration: `astra/build.py`, `astra/check.py`

## Stage Flow

```text
lex -> parse -> comptime -> semantic -> lowering -> optimization -> codegen
```

## Responsibilities

- Frontend ensures syntactic correctness and AST construction.
- Semantic phase enforces type, safety, ownership/borrow, and builtin rules.
- Lowering/optimization normalize AST and simplify code paths.
- Backend emits executable representations with hosted/freestanding constraints.
