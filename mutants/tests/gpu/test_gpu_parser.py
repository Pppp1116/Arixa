from astra.ast import FnDecl
from astra.parser import parse


def test_parse_gpu_fn_marks_kernel_decl():
    src = """
gpu fn add(a GpuSlice<Float>, b GpuSlice<Float>, out GpuMutSlice<Float>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = a[i] + b[i]; }
}
fn main() Int{ return 0; }
"""
    prog = parse(src)
    kernel = prog.items[0]
    host = prog.items[1]
    assert isinstance(kernel, FnDecl)
    assert isinstance(host, FnDecl)
    assert kernel.gpu_kernel
    assert not host.gpu_kernel


def test_parse_gpu_namespace_calls_in_host_and_kernel():
    src = """
gpu fn ids(out GpuMutSlice<Int>) Void{
  i = gpu.global_id();
  if i < out.len() { out[i] = i; }
}
fn main() Int{
  xs: GpuBuffer<Int> = gpu.alloc(4);
  gpu.launch(ids, 4, 64, xs);
  vals = gpu.read(xs);
  print(vals);
  return 0;
}
"""
    prog = parse(src)
    assert len(prog.items) == 2
