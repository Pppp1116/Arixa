from pathlib import Path

from astra.build import build


def test_gpu_kernel_registers_cuda_bridge_metadata(tmp_path: Path):
    src = tmp_path / "cuda_bridge.astra"
    out = tmp_path / "cuda_bridge.py"
    src.write_text(
        """
gpu fn vec_add(a GpuSlice<Float>, b GpuSlice<Float>, out GpuMutSlice<Float>) Void{
  i = gpu.global_id();
  if i < out.len() {
    out[i] = a[i] + b[i];
  }
}
fn main() Int{
  x: Vec<Float> = vec_from([1.0, 2.0, 3.0, 4.0]);
  y: Vec<Float> = vec_from([10.0, 20.0, 30.0, 40.0]);
  dx = gpu.copy(x);
  dy = gpu.copy(y);
  dout: GpuBuffer<Float> = gpu.alloc(len(x));
  gpu.launch(vec_add, len(x), 64, dx, dy, dout);
  return 0;
}
"""
    )
    state = build(str(src), str(out), target="py")
    assert state in {"built", "cached"}
    py = out.read_text()
    assert "__astra_cuda_kernel_vec_add" in py
    assert "cuda_source='def __astra_cuda_kernel_vec_add" in py
    assert "cuda_name='__astra_cuda_kernel_vec_add'" in py
