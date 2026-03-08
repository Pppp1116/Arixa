import pytest

from astra.parser import parse
from astra.semantic import SemanticError, analyze


def test_gpu_kernel_must_return_void():
    src = "gpu fn bad(a GpuSlice<Int>) Int{ return 1; } fn main() Int{ return 0; }"
    with pytest.raises(SemanticError, match="gpu kernels must return Void"):
        analyze(parse(src))


def test_gpu_kernel_rejects_await_and_host_builtin():
    src = """
gpu fn bad(out GpuMutSlice<Int>) Void{
  x = await now_unix();
  print(x);
}
fn main() Int{ return 0; }
"""
    with pytest.raises(SemanticError, match="gpu kernels cannot be async|await is not supported in gpu kernels|builtin print is not available in gpu kernels"):
        analyze(parse(src))


def test_gpu_kernel_parameter_type_is_validated():
    bad = "gpu fn bad(xs Vec<Int>) Void{} fn main() Int{ return 0; }"
    with pytest.raises(SemanticError, match="gpu kernel parameter xs uses unsupported type"):
        analyze(parse(bad))


def test_gpu_kernel_rejects_host_function_calls():
    src = """
fn host_only(x Int) Int{ return x; }
gpu fn bad(out GpuMutSlice<Int>) Void{
  v = host_only(7);
  if 0 < out.len() { out[0] = v; }
}
fn main() Int{ return 0; }
"""
    with pytest.raises(SemanticError, match="gpu kernels cannot call host function host_only"):
        analyze(parse(src))


def test_gpu_safe_structs_are_allowed_in_kernel_signatures():
    src = """
struct Pair { x Float, y Float }
gpu fn scale(input GpuSlice<Pair>, out GpuMutSlice<Pair>) Void{
  i = gpu.global_id();
  if i < out.len() {
    out[i] = input[i];
  }
}
fn main() Int{ return 0; }
"""
    analyze(parse(src))
