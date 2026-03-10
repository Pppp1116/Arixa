"""Runtime services for ASTRA host-side GPU programming APIs."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any

from astra.gpu.backend_cuda import CUDABackend
from astra.gpu.backend_stub import StubBackend


class GpuError(RuntimeError):
    """Raised when GPU runtime operations are invalid."""


@dataclass(frozen=True)
class _LaunchContext:
    global_id: int
    thread_id: int
    block_id: int
    block_dim: int
    grid_dim: int


class GpuSlice:
    """Immutable view over GPU-resident values."""

    def __init__(self, data: list[Any], *, owner: "GpuBuffer | None" = None):
        self._data = data
        self._owner = owner

    def len(self) -> int:
        return len(self._data)

    def __getitem__(self, index: int) -> Any:
        return self._data[int(index)]


class GpuMutSlice(GpuSlice):
    """Mutable view over GPU-resident values."""

    def __setitem__(self, index: int, value: Any) -> None:
        self._data[int(index)] = value


class GpuBuffer(GpuMutSlice):
    """Owning device buffer handle."""

    def to_slice(self) -> GpuSlice:
        return GpuSlice(self._data, owner=self)

    def to_mut_slice(self) -> GpuMutSlice:
        return GpuMutSlice(self._data, owner=self)

    def read(self) -> list[Any]:
        return list(self._data)


class AstraGpuRuntime:
    """Host runtime facade used by generated ASTRA Python code."""

    def __init__(self) -> None:
        self._cuda = CUDABackend()
        self._stub = StubBackend()
        self._tls = threading.local()
        self._kernel_meta: dict[Any, dict[str, Any]] = {}
        self._kernel_ir: dict[str, dict[str, Any]] = {}

    def _param_specs(self, meta: dict[str, Any]) -> list[dict[str, str]]:
        raw = meta.get("params", [])
        specs: list[dict[str, str]] = []
        if isinstance(raw, list):
            for idx, p in enumerate(raw):
                if isinstance(p, dict):
                    specs.append(
                        {
                            "name": str(p.get("name", f"arg{idx}")),
                            "type": str(p.get("type", "Any")),
                        }
                    )
                else:
                    specs.append({"name": f"arg{idx}", "type": str(p)})
        return specs

    def register_ir(self, ir_payload: dict[str, Any]) -> None:
        kernels = ir_payload.get("kernels")
        next_ir = dict(self._kernel_ir)
        if isinstance(kernels, list):
            keyed: list[tuple[str, dict[str, Any]]] = []
            for k in kernels:
                if not isinstance(k, dict):
                    continue
                symbol = str(k.get("symbol", ""))
                name = str(k.get("name", ""))
                key = symbol or name
                if not key:
                    continue
                keyed.append((key, k))
            for key, kernel in sorted(keyed, key=lambda item: item[0]):
                existing = next_ir.get(key)
                if existing is not None and existing is not kernel:
                    raise GpuError(f"duplicate gpu kernel metadata for symbol `{key}`")
                next_ir[key] = kernel
                kname = str(kernel.get("name", ""))
                if kname:
                    by_name = next_ir.get(kname)
                    if by_name is not None and by_name is not kernel:
                        raise GpuError(f"duplicate gpu kernel metadata for symbol `{kname}`")
                    next_ir[kname] = kernel
        self._kernel_ir = next_ir
        self._cuda.compile_program_ir(ir_payload)

    def register_kernel(
        self,
        fn,
        *,
        name: str,
        symbol: str,
        params: list[str],
        ret: str,
        cuda_source: str = "",
        cuda_name: str = "",
    ) -> None:
        self._kernel_meta[fn] = {
            "name": name,
            "symbol": symbol,
            "params": list(params),
            "ret": ret,
            "cuda_source": cuda_source,
            "cuda_name": cuda_name,
        }
        setattr(fn, "__astra_gpu_kernel__", True)
        setattr(fn, "__astra_gpu_name__", name)
        setattr(fn, "__astra_gpu_symbol__", symbol)
        setattr(fn, "__astra_gpu_params__", list(params))
        setattr(fn, "__astra_gpu_ret__", ret)
        setattr(fn, "__astra_gpu_cuda_source__", cuda_source)
        setattr(fn, "__astra_gpu_cuda_name__", cuda_name)

    def available(self) -> bool:
        return self._cuda.available()

    def device_count(self) -> int:
        return self._cuda.device_count()

    def device_name(self, index: int) -> str:
        if self._cuda.available():
            return self._cuda.device_name(index)
        if int(index) == 0:
            return self._stub.device_name(0)
        raise IndexError(f"device index out of range: {index}")

    def alloc(self, size: int) -> GpuBuffer:
        n = max(0, int(size))
        return GpuBuffer([0 for _ in range(n)])

    def copy(self, host_values: Any) -> GpuBuffer:
        if isinstance(host_values, GpuBuffer):
            return GpuBuffer(host_values.read())
        if isinstance(host_values, (GpuSlice, GpuMutSlice)):
            return GpuBuffer(list(host_values._data))
        if not isinstance(host_values, list):
            try:
                host_values = list(host_values)
            except Exception as err:
                raise GpuError("gpu.copy expects list-like input") from err
        return GpuBuffer(list(host_values))

    def read(self, memory: Any) -> list[Any]:
        if isinstance(memory, GpuBuffer):
            return memory.read()
        if isinstance(memory, (GpuSlice, GpuMutSlice)):
            return list(memory._data)
        raise GpuError("gpu.read expects GpuBuffer/GpuSlice/GpuMutSlice")

    def launch(self, kernel, grid_size: int, block_size: int, *args: Any) -> None:
        grid = int(grid_size)
        block = int(block_size)
        if grid <= 0:
            raise GpuError("gpu.launch requires grid_size > 0")
        if block <= 0:
            raise GpuError("gpu.launch requires block_size > 0")
        if block > 1024:
            raise GpuError("gpu.launch block_size exceeds 1024 threads per block")

        meta = self._kernel_meta.get(kernel)
        if meta is None and getattr(kernel, "__astra_gpu_kernel__", False):
            meta = {
                "name": getattr(kernel, "__astra_gpu_name__", getattr(kernel, "__name__", "kernel")),
                "symbol": getattr(kernel, "__astra_gpu_symbol__", getattr(kernel, "__name__", "kernel")),
                "params": [
                    {"name": f"arg{idx}", "type": str(pty)}
                    for idx, pty in enumerate(list(getattr(kernel, "__astra_gpu_params__", [])))
                ],
                "ret": getattr(kernel, "__astra_gpu_ret__", "Void"),
                "cuda_source": getattr(kernel, "__astra_gpu_cuda_source__", ""),
                "cuda_name": getattr(kernel, "__astra_gpu_cuda_name__", ""),
            }
        if meta is None:
            # Generated Python may launch the source kernel fn while metadata is
            # only present in registered IR. Resolve by symbol/name when possible.
            kernel_name = getattr(kernel, "__name__", "")
            ir_meta = self._kernel_ir.get(kernel_name)
            if ir_meta is None and kernel_name.startswith("__astra_cuda_kernel_"):
                ir_meta = self._kernel_ir.get(kernel_name[len("__astra_cuda_kernel_") :])
            if isinstance(ir_meta, dict):
                meta = {
                    "name": str(ir_meta.get("name", kernel_name or "kernel")),
                    "symbol": str(ir_meta.get("symbol", ir_meta.get("name", kernel_name or "kernel"))),
                    "params": list(ir_meta.get("params", [])),
                    "ret": str(ir_meta.get("ret", "Void")),
                    "cuda_source": "",
                    "cuda_name": "",
                }
        if meta is None:
            raise GpuError("gpu.launch expects a gpu fn kernel")
        if str(meta.get("ret", "Void")) != "Void":
            raise GpuError("gpu.launch kernel must return Void")
        expected_specs = self._param_specs(meta)
        expected_types = [s["type"] for s in expected_specs]
        if len(expected_types) != len(args):
            raise GpuError(f"gpu.launch kernel expects {len(expected_types)} args, got {len(args)}")
        prepared = [
            self._prepare_arg(spec["type"], arg, arg_name=spec["name"])
            for spec, arg in zip(expected_specs, args)
        ]
        gpu_lengths = [
            (spec["name"], val.len())
            for spec, val in zip(expected_specs, prepared)
            if isinstance(val, (GpuBuffer, GpuSlice, GpuMutSlice))
        ]
        if len(gpu_lengths) >= 2:
            base_name, base_len = gpu_lengths[0]
            for name, size in gpu_lengths[1:]:
                if size != base_len:
                    raise GpuError(
                        "gpu.launch detected mismatched GPU buffer sizes: "
                        f"{base_name} has {base_len} elements, {name} has {size}. "
                        "Consider allocating/copying buffers to the same length before launch."
                    )
        symbol = str(meta.get("symbol", meta.get("name", "kernel")))
        if self._cuda.launch(
            symbol,
            grid,
            block,
            prepared,
            expected_param_types=expected_types,
            meta=meta,
        ):
            return
        self._stub.launch(kernel, grid, block, prepared, self)

    def global_id(self) -> int:
        return self._require_ctx().global_id

    def thread_id(self) -> int:
        return self._require_ctx().thread_id

    def block_id(self) -> int:
        return self._require_ctx().block_id

    def block_dim(self) -> int:
        return self._require_ctx().block_dim

    def grid_dim(self) -> int:
        return self._require_ctx().grid_dim

    def barrier(self) -> None:
        # Stub backend executes serially; barrier is currently a no-op.
        _ = self._require_ctx()
        return None

    def _require_ctx(self) -> _LaunchContext:
        ctx = getattr(self._tls, "ctx", None)
        if ctx is None:
            raise GpuError("gpu thread-index builtin used outside gpu kernel launch")
        return ctx

    def _set_launch_context(self, *, global_id: int, thread_id: int, block_id: int, block_dim: int, grid_dim: int) -> None:
        self._tls.ctx = _LaunchContext(
            global_id=int(global_id),
            thread_id=int(thread_id),
            block_id=int(block_id),
            block_dim=int(block_dim),
            grid_dim=int(grid_dim),
        )

    def _clear_launch_context(self) -> None:
        if hasattr(self._tls, "ctx"):
            delattr(self._tls, "ctx")

    def _prepare_arg(self, expected_type: str, value: Any, *, arg_name: str = "arg") -> Any:
        exp = expected_type.replace(" ", "")
        if exp.startswith("GpuSlice<") and exp.endswith(">"):
            if isinstance(value, GpuBuffer):
                return value.to_slice()
            if isinstance(value, GpuMutSlice):
                return GpuSlice(value._data, owner=getattr(value, "_owner", None))
            if isinstance(value, GpuSlice):
                return value
            raise GpuError(
                f"kernel parameter `{arg_name}` expects {expected_type}, got {type(value).__name__}. "
                "Use gpu.copy(...) or gpu.alloc(...) to create device buffers."
            )
        if exp.startswith("GpuMutSlice<") and exp.endswith(">"):
            if isinstance(value, GpuBuffer):
                return value.to_mut_slice()
            if isinstance(value, GpuMutSlice):
                return value
            raise GpuError(
                f"kernel parameter `{arg_name}` expects {expected_type}, got {type(value).__name__}. "
                "Mutable GPU params require a GpuBuffer or GpuMutSlice."
            )
        if exp.startswith("GpuBuffer<") and exp.endswith(">"):
            if isinstance(value, GpuBuffer):
                return value
            raise GpuError(
                f"kernel parameter `{arg_name}` expects {expected_type}, got {type(value).__name__}."
            )
        return value


_RUNTIME_SINGLETON: AstraGpuRuntime | None = None


def get_runtime() -> AstraGpuRuntime:
    """Return the shared runtime instance used by generated programs."""

    global _RUNTIME_SINGLETON
    if _RUNTIME_SINGLETON is None:
        _RUNTIME_SINGLETON = AstraGpuRuntime()
    return _RUNTIME_SINGLETON
