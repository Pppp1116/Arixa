import pytest

from astra.gpu.runtime import AstraGpuRuntime, GpuError


def _noop_kernel(*_args):
    return None


def test_register_ir_rejects_duplicate_symbols_deterministically():
    rt = AstraGpuRuntime()
    payload = {
        "kernels": [
            {"name": "a", "symbol": "same", "params": [], "ret": "Void"},
            {"name": "b", "symbol": "same", "params": [], "ret": "Void"},
        ]
    }
    with pytest.raises(GpuError, match="duplicate gpu kernel metadata"):
        rt.register_ir(payload)


def test_launch_rejects_mismatched_gpu_buffer_sizes():
    rt = AstraGpuRuntime()
    rt.register_kernel(
        _noop_kernel,
        name="k",
        symbol="k",
        params=["GpuSlice<Float>", "GpuMutSlice<Float>"],
        ret="Void",
    )
    a = rt.copy([1.0, 2.0, 3.0])
    out = rt.alloc(2)
    with pytest.raises(GpuError, match="mismatched GPU buffer sizes"):
        rt.launch(_noop_kernel, 2, 64, a, out)


def test_launch_rejects_invalid_grid_and_block_size():
    rt = AstraGpuRuntime()
    rt.register_kernel(_noop_kernel, name="k", symbol="k", params=[], ret="Void")
    with pytest.raises(GpuError, match="grid_size > 0"):
        rt.launch(_noop_kernel, 0, 64)
    with pytest.raises(GpuError, match="block_size exceeds 1024"):
        rt.launch(_noop_kernel, 1, 2048)
