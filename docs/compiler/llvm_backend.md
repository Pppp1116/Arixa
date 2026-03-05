# LLVM Backend

Implementation: `astra/llvm_codegen.py`

Main API:

- `to_llvm_ir(prog, freestanding=..., overflow_mode=..., triple=..., profile=...)`

Behaviors:

- emits module/function IR through `llvmlite`
- validates/initializes LLVM binding setup
- supports runtime symbol declarations for hosted mode
- enforces runtime-free constraints in freestanding mode (via build checks)

Native build path:

- IR is linked by `clang` in `astra/build.py` when `--target native`.
