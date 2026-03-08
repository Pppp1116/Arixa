import pytest

from astra.parser import parse
from astra.semantic import SemanticError, analyze


def test_gpu_struct_with_unsupported_field_type_is_rejected():
    src = """
struct Bad { label String, value Int }
gpu fn k(x GpuSlice<Bad>, out GpuMutSlice<Bad>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = x[i]; }
}
fn main() Int{ return 0; }
"""
    with pytest.raises(SemanticError, match="gpu kernel parameter x uses unsupported type"):
        analyze(parse(src))


def test_gpu_kernel_local_unsupported_type_is_rejected():
    src = """
gpu fn bad(out GpuMutSlice<Int>) Void{
  xs: Vec<Int> = vec_new() as Vec<Int>;
  if 0 < out.len() { out[0] = vec_len(xs); }
}
fn main() Int{ return 0; }
"""
    with pytest.raises(SemanticError, match="gpu kernel local xs uses unsupported type"):
        analyze(parse(src))
