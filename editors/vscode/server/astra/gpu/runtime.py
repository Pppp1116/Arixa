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

    def register_ir(self, ir_payload: dict[str, Any]) -> None:
        kernels = ir_payload.get("kernels")
        if isinstance(kernels, list):
            for k in kernels:
                if not isinstance(k, dict):
                    continue
                symbol = str(k.get("symbol", k.get("name", "")))
                if symbol:
                    self._kernel_ir[symbol] = k
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
        meta = self._kernel_meta.get(kernel)
        if meta is None and getattr(kernel, "__astra_gpu_kernel__", False):
            meta = {
                "name": getattr(kernel, "__astra_gpu_name__", getattr(kernel, "__name__", "kernel")),
                "symbol": getattr(kernel, "__astra_gpu_symbol__", getattr(kernel, "__name__", "kernel")),
                "params": list(getattr(kernel, "__astra_gpu_params__", [])),
                "ret": getattr(kernel, "__astra_gpu_ret__", "Void"),
                "cuda_source": getattr(kernel, "__astra_gpu_cuda_source__", ""),
                "cuda_name": getattr(kernel, "__astra_gpu_cuda_name__", ""),
            }
        if meta is None:
            raise GpuError("gpu.launch expects a gpu fn kernel")
        if str(meta.get("ret", "Void")) != "Void":
            raise GpuError("gpu.launch kernel must return Void")
        expected = list(meta.get("params", []))
        if len(expected) != len(args):
            raise GpuError(f"gpu.launch kernel expects {len(expected)} args, got {len(args)}")
        prepared = [self._prepare_arg(typ, arg) for typ, arg in zip(expected, args)]
        symbol = str(meta.get("symbol", meta.get("name", "kernel")))
        if self._cuda.launch(
            symbol,
            int(grid_size),
            int(block_size),
            prepared,
            expected_param_types=expected,
            meta=meta,
        ):
            return
        self._stub.launch(kernel, int(grid_size), int(block_size), prepared, self)

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

    def _prepare_arg(self, expected_type: str, value: Any) -> Any:
        exp = expected_type.replace(" ", "")
        if exp.startswith("GpuSlice<") and exp.endswith(">"):
            if isinstance(value, GpuBuffer):
                return value.to_slice()
            if isinstance(value, GpuMutSlice):
                return GpuSlice(value._data, owner=getattr(value, "_owner", None))
            if isinstance(value, GpuSlice):
                return value
            raise GpuError(f"kernel parameter expects {expected_type}, got {type(value).__name__}")
        if exp.startswith("GpuMutSlice<") and exp.endswith(">"):
            if isinstance(value, GpuBuffer):
                return value.to_mut_slice()
            if isinstance(value, GpuMutSlice):
                return value
            raise GpuError(f"kernel parameter expects {expected_type}, got {type(value).__name__}")
        if exp.startswith("GpuBuffer<") and exp.endswith(">"):
            if isinstance(value, GpuBuffer):
                return value
            raise GpuError(f"kernel parameter expects {expected_type}, got {type(value).__name__}")
        return value


_RUNTIME_SINGLETON: AstraGpuRuntime | None = None


def get_runtime() -> AstraGpuRuntime:
    """Return the shared runtime instance used by generated programs."""

    global _RUNTIME_SINGLETON
    if _RUNTIME_SINGLETON is None:
        _RUNTIME_SINGLETON = AstraGpuRuntime()
    return _RUNTIME_SINGLETON
