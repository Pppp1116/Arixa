# Code Generation

Astra supports two backend families:

- Python backend (`astra/codegen.py`)
- LLVM backend (`astra/llvm_codegen.py`)

Shared preconditions:

- parsed AST
- comptime-executed AST
- semantic-analyzed program
- lowered/optimized loops and statements

Build integration (`astra/build.py`) chooses target and writes output artifacts.
