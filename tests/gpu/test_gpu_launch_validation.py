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
    with pytest.raises(SemanticError, match="expected device memory"):
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


def test_gpu_launch_rejects_invalid_launch_dimensions():
    src = """
gpu fn k(out GpuMutSlice<Int>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = i; }
}
fn main() Int{
  out: GpuBuffer<Int> = gpu.alloc(4);
  gpu.launch(k, 0, 64, out);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="grid_size must be > 0"):
        analyze(parse(src))


def test_gpu_launch_error_mentions_host_device_misuse():
    src = """
gpu fn add(a GpuSlice<Float>, out GpuMutSlice<Float>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = a[i]; }
}
fn main() Int{
  x: Vec<Float> = vec_from([1.0, 2.0]);
  out: GpuBuffer<Float> = gpu.alloc(len(x));
  gpu.launch(add, len(x), 64, x, out);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="expected device memory"):
        analyze(parse(src))


def test_gpu_launch_validates_constexpr_dimensions_at_compile_time():
    src = """
const GRID = 32 * 8;
gpu fn k(out GpuMutSlice<Int>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = i; }
}
fn main() Int{
  out: GpuBuffer<Int> = gpu.alloc(8);
  gpu.launch(k, GRID, 64, out);
  return 0;
}
"""
    analyze(parse(src))


def test_gpu_launch_rejects_constexpr_invalid_block_size():
    src = """
const BAD_BLOCK = 2048;
gpu fn k(out GpuMutSlice<Int>) Void{ }
fn main() Int{
  out: GpuBuffer<Int> = gpu.alloc(1);
  gpu.launch(k, 1, BAD_BLOCK, out);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="block_size exceeds CUDA limit 1024"):
        analyze(parse(src))


def test_gpu_launch_rejects_constexpr_thread_count_overflow():
    src = """
const G = 4611686018427387904;
const B = 4;
gpu fn k(out GpuMutSlice<Int>) Void{ }
fn main() Int{
  out: GpuBuffer<Int> = gpu.alloc(1);
  gpu.launch(k, G, B, out);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="total thread count overflows Int"):
        analyze(parse(src))


def test_gpu_launch_static_length_mismatch_is_reported():
    src = """
gpu fn add(a GpuSlice<Float>, b GpuSlice<Float>, out GpuMutSlice<Float>) Void{ }
fn main() Int{
  gpu.launch(add, 4, 64, gpu.copy([1.0, 2.0]), gpu.copy([3.0]), gpu.copy([0.0, 0.0]));
  return 0;
}
"""
    with pytest.raises(SemanticError, match="static length mismatch"):
        analyze(parse(src))


def test_gpu_launch_reports_element_type_mismatch_with_expected_found():
    src = """
gpu fn k(out GpuMutSlice<Float>) Void{ }
fn main() Int{
  out_i = gpu.copy([1, 2, 3, 4]);
  gpu.launch(k, 4, 64, out_i);
  return 0;
}
"""
    with pytest.raises(SemanticError, match="element type mismatch: expected `Float` but got `Int`"):
        analyze(parse(src))
