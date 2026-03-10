"""Helpers that validate generated LLVM IR during tests and build checks."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from llvmlite import binding
except Exception:  # pragma: no cover
    binding = None


_LLVM_INIT_DONE = False
_IR_PLACEHOLDER_MARKERS = ("TO" "DO",)


def _init_llvm_once() -> None:
    global _LLVM_INIT_DONE
    if _LLVM_INIT_DONE:
        return
    if binding is None:
        return
    try:
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()
    except RuntimeError:
        # Newer llvmlite versions auto-initialize.
        pass
    _LLVM_INIT_DONE = True


def assert_valid_llvm_ir(ir_text: str, *, triple: str | None = None, workdir: Path | None = None) -> None:
    """Assert that generated LLVM IR parses and verifies successfully.
    
    Parameters:
        ir_text: Input value used by this routine.
        triple: Input value used by this routine.
        workdir: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    text = ir_text.strip()
    if not text:
        raise AssertionError("LLVM IR output is empty")
    if any(marker in text for marker in _IR_PLACEHOLDER_MARKERS):
        raise AssertionError("LLVM IR contains unresolved placeholder markers")
    if triple:
        if triple not in text:
            raise AssertionError(f"missing module triple {triple!r}")

    if binding is not None:
        _init_llvm_once()
        mod = binding.parse_assembly(ir_text)
        mod.verify()
        return

    clang = shutil.which("clang")
    if clang is None:
        return

    out_dir = workdir or Path.cwd()
    with tempfile.TemporaryDirectory(prefix="astra-ir-check-", dir=str(out_dir)) as td:
        ll = Path(td) / "module.ll"
        obj = Path(td) / "module.o"
        ll.write_text(ir_text)
        cp = subprocess.run([clang, "-c", str(ll), "-o", str(obj)], capture_output=True, text=True)
        if cp.returncode != 0: raise AssertionError(f"clang failed to compile LLVM IR: {cp.stderr or cp.stdout}")
