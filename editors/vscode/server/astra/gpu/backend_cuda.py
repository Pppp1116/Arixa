"""Optional CUDA backend integration for ASTRA GPU kernels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


@dataclass
class CompiledCudaKernel:
    """Container for lowered CUDA source and per-kernel metadata."""

    name: str
    symbol: str
    source: str
    fn_name: str


class CUDABackend:
    """Best-effort CUDA backend.

    This backend is intentionally defensive: if CUDA runtime/tooling is not
    available, callers should transparently fall back to the stub backend.
    """

    def __init__(self) -> None:
        self._compiled: dict[str, CompiledCudaKernel] = {}
        self._jit_kernels: dict[str, Any] = {}
        self._cuda = None
        self._probe_error: str | None = None
        self._probe_cuda()

    def _probe_cuda(self) -> None:
        try:
            from numba import cuda  # type: ignore

            self._cuda = cuda
            _ = cuda.gpus  # Force runtime discovery.
        except Exception as err:  # pragma: no cover - hardware/env dependent
            self._cuda = None
            self._probe_error = str(err)

    def available(self) -> bool:
        if self._cuda is None:
            return False
        try:
            return len(list(self._cuda.gpus)) > 0
        except Exception:  # pragma: no cover - hardware/env dependent
            return False

    def device_count(self) -> int:
        if not self.available():
            return 0
        try:
            return len(list(self._cuda.gpus))
        except Exception:  # pragma: no cover - hardware/env dependent
            return 0

    def device_name(self, index: int) -> str:
        if not self.available():
            raise RuntimeError("CUDA is not available")
        devs = list(self._cuda.gpus)
        idx = int(index)
        if idx < 0 or idx >= len(devs):
            raise IndexError(f"CUDA device index out of range: {idx}")
        with devs[idx]:
            return str(self._cuda.get_current_device().name.decode("utf-8", errors="replace"))

    def compile_program_ir(self, ir_payload: dict[str, Any]) -> None:
        """Compile IR payload into backend-local CUDA source stubs."""

        kernels = ir_payload.get("kernels")
        if not isinstance(kernels, list):
            return
        for k in kernels:
            if not isinstance(k, dict):
                continue
            name = str(k.get("name", "kernel"))
            symbol = str(k.get("symbol", name))
            self._compiled[symbol] = CompiledCudaKernel(
                name=name,
                symbol=symbol,
                source=self._emit_cuda_stub(k),
                fn_name=f"__astra_cuda_stub_{_sanitize_symbol(symbol)}",
            )

    def _emit_cuda_stub(self, kernel: dict[str, Any]) -> str:
        params = kernel.get("params", [])
        psrc: list[str] = []
        for p in params:
            if not isinstance(p, dict):
                continue
            pname = str(p.get("name", "arg"))
            pty = str(p.get("type", "Any"))
            psrc.append(f"/* {pty} */ void* {pname}")
        ps = ", ".join(psrc) if psrc else "void"
        name = str(kernel.get("symbol", kernel.get("name", "kernel")))
        return (
            "// ASTRA CUDA stub (metadata-only)\n"
            "extern \"C\" __global__\n"
            f"void {name}({ps}) {{\n"
            "  // ASTRA MVP: runtime currently executes via CPU stub backend.\n"
            "  // This source is emitted for architecture validation and future NVRTC integration.\n"
            "}\n"
        )

    def launch(
        self,
        kernel_symbol: str,
        grid_size: int,
        block_size: int,
        args: list[Any],
        *,
        expected_param_types: list[str],
        meta: dict[str, Any],
    ) -> bool:
        """Attempt CUDA launch; returns False when runtime execution should fall back."""

        if not self.available():
            return False
        cuda_source = str(meta.get("cuda_source", "") or "")
        cuda_name = str(meta.get("cuda_name", "") or "")
        if not cuda_source or not cuda_name:
            return False
        try:
            kernel = self._ensure_compiled(kernel_symbol, cuda_source, cuda_name)
            launch_args, mutables = self._prepare_launch_args(args, expected_param_types)
            threads = max(1, int(block_size))
            total = max(0, int(grid_size))
            blocks = max(1, (total + threads - 1) // threads) if total > 0 else 1
            kernel[blocks, threads](*launch_args)
            self._cuda.synchronize()
            for dev_arr, host_ref in mutables:
                host_arr = dev_arr.copy_to_host()
                host_ref[:] = host_arr.tolist()
            return True
        except Exception:  # pragma: no cover - hardware/env dependent
            return False

    def _ensure_compiled(self, symbol: str, source: str, fn_name: str):
        compiled = self._jit_kernels.get(symbol)
        if compiled is not None:
            return compiled
        scope = {"cuda": self._cuda}
        exec(source, scope)
        pyfn = scope.get(fn_name)
        if pyfn is None:
            raise RuntimeError(f"missing generated CUDA function {fn_name}")
        jitted = self._cuda.jit(pyfn)
        self._jit_kernels[symbol] = jitted
        return jitted

    def _prepare_launch_args(
        self,
        args: list[Any],
        expected_param_types: list[str],
    ) -> tuple[list[Any], list[tuple[Any, list[Any]]]]:
        prepared: list[Any] = []
        mutable_refs: list[tuple[Any, list[Any]]] = []
        np = self._import_numpy()
        for arg, pty in zip(args, expected_param_types):
            p = pty.replace(" ", "")
            if p.startswith(("GpuSlice<", "GpuMutSlice<", "GpuBuffer<")) and p.endswith(">"):
                host_ref = getattr(arg, "_data", None)
                if not isinstance(host_ref, list):
                    raise TypeError(f"expected GPU memory argument for {pty}")
                inner = p[p.find("<") + 1 : -1]
                dtype = _numpy_dtype(inner)
                arr = np.array(host_ref, dtype=dtype)
                dev = self._cuda.to_device(arr)
                prepared.append(dev)
                if p.startswith(("GpuMutSlice<", "GpuBuffer<")):
                    mutable_refs.append((dev, host_ref))
                continue
            prepared.append(arg)
        return prepared, mutable_refs

    @staticmethod
    def _import_numpy():
        import numpy as np  # type: ignore

        return np


def _sanitize_symbol(symbol: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]", "_", symbol)


def _numpy_dtype(type_name: str):
    t = type_name.strip()
    np = CUDABackend._import_numpy()
    mapping = {
        "Bool": np.bool_,
        "Float": np.float64,
        "f64": np.float64,
        "f32": np.float32,
        "Int": np.int64,
        "isize": np.int64,
        "usize": np.uint64,
        "i8": np.int8,
        "i16": np.int16,
        "i32": np.int32,
        "i64": np.int64,
        "u8": np.uint8,
        "u16": np.uint16,
        "u32": np.uint32,
        "u64": np.uint64,
    }
    return mapping.get(t, np.float64)
