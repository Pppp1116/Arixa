import pytest

from astra.parser import parse
from astra.semantic import SemanticError, analyze


def test_gpu_launch_typechecks_valid_kernel_invocation():
    src = """
gpu fn add(a GpuSlice<Float>, b GpuSlice<Float>, out GpuMutSlice<Float>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = a[i] + b[i]; }
}
fn main() Int{
  x: Vec<Float> = vec_from([1.0, 2.0]);
  y: Vec<Float> = vec_from([10.0, 20.0]);
  dx = gpu.copy(x);
  dy = gpu.copy(y);
  out: GpuBuffer<Float> = gpu.alloc(len(x));
  gpu.launch(add, len(x), 64, dx, dy, out);
  return 0;
}
"""
    analyze(parse(src))


def test_gpu_launch_rejects_non_kernel_function():
    src = """
fn host(x Int) Int{ return x; }
fn main() Int{
  gpu.launch(host, 1, 64, 1);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="gpu.launch expects a gpu fn kernel"):
        analyze(parse(src))


def test_gpu_launch_rejects_incompatible_argument_types():
    src = """
gpu fn add(a GpuSlice<Float>, b GpuSlice<Float>, out GpuMutSlice<Float>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = a[i] + b[i]; }
}
fn main() Int{
  x: Vec<Float> = vec_from([1.0, 2.0]);
  dx = gpu.copy(x);
  out: GpuBuffer<Float> = gpu.alloc(len(x));
  gpu.launch(add, len(x), 64, dx, 7, out);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="no matching gpu kernel overload for launch"):
        analyze(parse(src))


def test_gpu_kernel_cannot_be_called_directly_from_host():
    src = """
gpu fn k(out GpuMutSlice<Int>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = i; }
}
fn main() Int{
  out: GpuBuffer<Int> = gpu.alloc(1);
  k(out);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="cannot be called directly; use gpu.launch"):
        analyze(parse(src))
